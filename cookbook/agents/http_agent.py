from __future__ import annotations

import os
import time
import uuid
import asyncio
import logging

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from a2e.client import A2EClient

from a2e.caps.env.client import EnvAPI
from a2e.caps.memory.client import MemoryAPI
from a2e.caps.skills.client import SkillAPI
from a2e.caps.tools.client import ToolAPI
from a2e.caps.chains.client import ChainsAPI
from a2e.caps.learn.client import LearnAPI

from a2e.caps.learn import (
    FeedbackPolarity,
    FeedbackDimension,
    FeedbackSource,
)

from a2e.caps.base.protocol import (
    A2ECapability,
)

from a2e.core.transports import (
    build_transport,
    TransportConfig,
    HTTPTransportConfig,
)


# =========================================================
# Trajectory Models
# =========================================================

@dataclass
class TrajectoryStep:

    step_id: int

    prompt: str

    response: str

    action: dict

    observation: Any

    reward: float

    success: bool

    latency_ms: float


@dataclass
class EpisodeTrajectory:

    rollout_id: str

    episode_id: str

    agent_name: str

    goal: str

    steps: List[TrajectoryStep] = field(
        default_factory=list
    )

    total_reward: float = 0.0

    success: bool = False

    metadata: dict = field(
        default_factory=dict
    )


# =========================================================
# Runtime Client
# =========================================================

class EnvClient:

    def __init__(self, logger):

        transport_config = TransportConfig(**{
            "type": "http",

            "config": HTTPTransportConfig(**{
                "base_url": "http://localhost:8765",
                "stream": "/stream",
                "send": "/send",
            }),
        })

        self.transport = build_transport(
            transport_config,
            logger,
        )

        self.client = A2EClient(

            transport=self.transport,

            logger=logger,

            agent_id="thirdparty-http-agent",

            auth_token="",

            agent_caps=[
                A2ECapability.TOOLKITS,
                A2ECapability.ENV,
                A2ECapability.PROC,
            ],
        )

        self.env = EnvAPI(self.client)

        self.memory = MemoryAPI(self.client)

        self.learn = LearnAPI(self.client)

        self.tools = ToolAPI(self.client)

        self.skills = SkillAPI(self.client)

        self.chains = ChainsAPI(self.client)

    async def start(self):

        await asyncio.to_thread(
            self.client.connect
        )
        await asyncio.to_thread(
            self.memory.init
        )

    async def stop(self):

        await asyncio.to_thread(
            self.client.disconnect
        )


# =========================================================
# Third Party Agent Config
# =========================================================

@dataclass
class ThirdPartyAgentConfig:

    name: str

    endpoint: str

    api_key: str = ""

    model: str = ""

    timeout: int = 120

    headers: Dict[str, str] = field(
        default_factory=dict
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# =========================================================
# Third Party HTTP Agent
# =========================================================

class ThirdPartyHttpAgent:

    """
    Generic external HTTP-based agent runtime.

    Examples:
      - OpenAI Responses API
      - Claude API
      - OpenRouter
      - DeepSeek
      - Internal Agents
      - Hosted LangGraph runtimes
      - MCP Gateways
      - Custom planners
    """

    def __init__(
        self,
        rt_client: EnvClient,
        config: ThirdPartyAgentConfig,
    ):

        self.rt_client = rt_client

        self.cfg = config

        self.rollout_id = ""

        self.history = []

    # =====================================================
    # Main Run Loop
    # =====================================================

    async def run(
        self,
        goal: str,
        max_steps: int = 10,
    ) -> EpisodeTrajectory:

        rollout_id = (
            f"rollout_{uuid.uuid4().hex[:8]}"
        )

        episode_id = (
            f"episode_{uuid.uuid4().hex[:8]}"
        )

        self.rollout_id = rollout_id

        trajectory = EpisodeTrajectory(

            rollout_id=rollout_id,

            episode_id=episode_id,

            agent_name=self.cfg.name,

            goal=goal,
        )

        for step_idx in range(max_steps):

            # =============================================
            # Recall Memory
            # =============================================

            memories = (
                await asyncio.to_thread(
                    self.rt_client.memory.retrieve,
                    query=goal,
                    limit=5,
                )
            )

            memory_context = "\n".join([
                str(m.content)
                for m in memories
            ])

            # =============================================
            # Build Prompt
            # =============================================

            prompt = f"""
Goal:
{goal}

Relevant Memory:
{memory_context}

History:
{self.history[-5:]}

You are operating inside A2E.

Respond with:
- reasoning
- action
- result

Return JSON:

{{
  "reasoning": "...",
  "action": {{
      "type": "tool|skill|finish",
      "name": "...",
      "input": {{}}
  }},
  "done": false
}}
"""

            t0 = time.monotonic()

            success = True

            try:

                # =========================================
                # Call External Agent
                # =========================================

                response = (
                    await self.call_agent(
                        prompt
                    )
                )

                reasoning = response.get(
                    "reasoning",
                    "",
                )

                action = response.get(
                    "action",
                    {},
                )

                done = response.get(
                    "done",
                    False,
                )

                action_type = action.get(
                    "type",
                    "finish",
                )

                observation = None

                # =========================================
                # Tool Action
                # =========================================

                if action_type == "tool":

                    result = (
                        await asyncio.to_thread(
                            self.rt_client.tools.call,
                            action["name"],
                            action.get(
                                "input",
                                {},
                            ),
                        )
                    )

                    observation = result.output

                    success = result.success

                # =========================================
                # Skill Action
                # =========================================

                elif action_type == "skill":

                    result = (
                        await asyncio.to_thread(
                            self.rt_client.skills.call,
                            action["name"],
                            action.get(
                                "input",
                                {},
                            ),
                        )
                    )

                    observation = result.output

                    success = result.success

                # =========================================
                # Finish
                # =========================================

                else:

                    observation = {
                        "status": "finished"
                    }

                    trajectory.success = True

                    done = True

            except Exception as e:

                success = False

                done = False

                reasoning = str(e)

                observation = str(e)

                action = {
                    "type": "error",
                    "name": "exception",
                    "input": {},
                }

            latency_ms = (
                time.monotonic() - t0
            ) * 1000

            # =============================================
            # Reward
            # =============================================

            reward = await self.compute_reward(
                goal=goal,
                success=success,
                observation=observation,
            )

            trajectory.total_reward += (
                reward
            )

            # =============================================
            # Record Step
            # =============================================

            traj_step = TrajectoryStep(

                step_id=step_idx,

                prompt=prompt,

                response=reasoning,

                action=action,

                observation=observation,

                reward=reward,

                success=success,

                latency_ms=latency_ms,
            )

            trajectory.steps.append(
                traj_step
            )

            # =============================================
            # Feedback
            # =============================================

            await asyncio.to_thread(

                self.rt_client.learn.feedback,

                polarity=(
                    FeedbackPolarity.POSITIVE
                    if reward > 0
                    else FeedbackPolarity.NEGATIVE
                ),

                score=float(reward),

                dimension=(
                    FeedbackDimension.CORRECTNESS
                ),

                confidence=1.0,

                prompt=prompt,

                response=str(reasoning),

                model=self.cfg.model,

                environment={
                    "rollout_id": rollout_id,
                    "episode_id": episode_id,
                    "step_id": step_idx,
                },

                version="http-agent-v1",

                correlation_id=rollout_id,

                session_id=episode_id,

                comment=str(observation),

                source=FeedbackSource.ENV,

                annotator_id="a2e-runtime",
            )

            # =============================================
            # Episodic Memory
            # =============================================

            await asyncio.to_thread(

                self.rt_client.memory.remember,

                key={"episode_id": episode_id, "step_idx": step_idx},

                value={

                    "prompt": prompt,

                    "response": reasoning,

                    "action": action,

                    "observation": observation,

                    "reward": reward,
                },

                tier="episodic",

                tags=[
                    "thirdparty-agent",
                    "rollout",
                ],

                ttl=0,
            )

            # =============================================
            # Local History
            # =============================================

            self.history.append({

                "reasoning": reasoning,

                "action": action,

                "reward": reward,
            })

            # =============================================
            # Adapt
            # =============================================

            if (
                step_idx > 0
                and step_idx % 5 == 0
            ):

                await asyncio.to_thread(
                    self.rt_client.learn.adapt
                )

            if done:
                break

        # =================================================
        # Upload Rollout
        # =================================================

        rollout = {

            "rollout_id": rollout_id,

            "episode_id": episode_id,

            "goal": goal,

            "reward": trajectory.total_reward,

            "success": trajectory.success,

            "steps": [
                s.__dict__
                for s in trajectory.steps
            ],
        }

        await asyncio.to_thread(
            self.rt_client.learn.experience,
            [rollout],
        )

        return trajectory

    # =====================================================
    # HTTP Agent Call
    # =====================================================

    async def call_agent(
        self,
        prompt: str,
    ) -> dict:

        headers = {
            "Content-Type": "application/json",
            **self.cfg.headers,
        }

        if self.cfg.api_key:
            headers["Authorization"] = (
                f"Bearer {self.cfg.api_key}"
            )

        payload = {

            "model": self.cfg.model,

            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],

            "temperature": 0,
        }

        async with httpx.AsyncClient() as client:

            resp = await client.post(

                self.cfg.endpoint,

                headers=headers,

                json=payload,

                timeout=self.cfg.timeout,
            )

            resp.raise_for_status()

            data = resp.json()

        # =================================================
        # OpenAI/OpenRouter Compatible
        # =================================================

        if "choices" in data:

            content = (
                data["choices"][0]
                ["message"]["content"]
            )

            import json

            return json.loads(content)

        # =================================================
        # Generic JSON API
        # =================================================

        return data

    # =====================================================
    # Reward
    # =====================================================

    async def compute_reward(
        self,
        goal: str,
        success: bool,
        observation: Any,
    ) -> float:

        if not success:
            return -1.0

        reward = 0.25

        obs = str(observation).lower()

        if "error" not in obs:
            reward += 0.5

        return reward



async def main():

    # ==========================================
    # Connect A2E Runtime
    # ==========================================

    rt_client = EnvClient(
        logger=logging.getLogger("a2e")
    )

    await rt_client.start()

    # ==========================================
    # Configure Third Party Agent
    # ==========================================

    cfg = ThirdPartyAgentConfig(

        name="openrouter-react-agent",

        endpoint=(
            "https://openrouter.ai/api/v1/"
        ),

        api_key=os.environ[
            "OPENROUTER_API_KEY"
        ],

        model=(
            "anthropic/claude-3.7-sonnet"
        ),

        headers={

            # optional but recommended
            "HTTP-Referer": (
                "https://github.com/your-org/a2e"
            ),

            "X-Title": "A2E Runtime",
        },
    )

    # ==========================================
    # Create Agent
    # ==========================================

    agent = ThirdPartyHttpAgent(
        rt_client=rt_client,
        config=cfg,
    )

    # ==========================================
    # Run Agent
    # ==========================================

    trajectory = await agent.run(

        goal=(
            "Increase counter to 5 "
            "using the environment."
        ),

        max_steps=10,
    )

    # ==========================================
    # Print Results
    # ==========================================

    print("\n=== TRAJECTORY ===\n")

    print(
        f"rollout={trajectory.rollout_id}"
    )

    print(
        f"episode={trajectory.episode_id}"
    )

    print(
        f"reward={trajectory.total_reward}"
    )

    print(
        f"success={trajectory.success}"
    )

    print("\n=== STEPS ===\n")

    for step in trajectory.steps:

        print(
            f"[{step.step_id}] "
            f"reward={step.reward:.2f} "
            f"success={step.success}"
        )

        print(
            f"action={step.action}"
        )

        print(
            f"response={step.response}"
        )

        print(
            f"observation={step.observation}"
        )

        print("-" * 80)

    # ==========================================
    # Disconnect Runtime
    # ==========================================

    await rt_client.stop()


if __name__ == "__main__":
    asyncio.run(main())
