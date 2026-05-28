from __future__ import annotations
import os
import time
import pdb
import asyncio
import time
import uuid

from dataclasses import dataclass, field
from typing import Any, Dict, List

from deepagents import create_deep_agent

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

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
# Trajectory Types
# =========================================================

@dataclass
class TrajectoryStep:

    step_id: int

    thought: str

    action_type: str
    action_name: str
    action_input: dict

    observation: Any

    reward: float
    success: bool

    latency_ms: float


@dataclass
class EpisodeTrajectory:

    rollout_id: str

    episode_id: str

    env_name: str

    goal: str

    initial_obs: dict

    steps: List[TrajectoryStep] = field(
        default_factory=list
    )

    total_reward: float = 0.0

    done: bool = False

    truncated: bool = False

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

            agent_id="deepagent-react",

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
# DeepAgent Runtime
# =========================================================

class A2EDeepAgent:

    def __init__(
        self,
        rt_client,
        model="inclusionai/ring-2.6-1t:free",
    ):

        self.rt_client = rt_client

        self.history = []

        self.rollout_id = ""

        self.lc_tools = []

        self._build_tools()

        self.model = ChatOpenAI(
            model=model,
            temperature=0,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )

        self.agent = create_deep_agent(
            model=self.model,
            tools=self.lc_tools,
        )

    # =====================================================
    # Tool Adapters
    # =====================================================

    def _build_tools(self):

        # -------------------------------------------------
        # Runtime Tools
        # -------------------------------------------------

        for t in self.rt_client.tools.list():

            def make_tool(
                tool_name,
                tool_description,
            ):

                @tool
                async def runtime_tool(
                    **kwargs,
                ):
                    """
                    A2E Runtime Tool
                    """

                    result = (
                        await asyncio.to_thread(
                            self.rt_client.tools.call,
                            tool_name,
                            kwargs,
                        )
                    )

                    return str(result.output)

                runtime_tool.name = tool_name

                runtime_tool.description = (
                    tool_description
                )

                return runtime_tool

            self.lc_tools.append(
                make_tool(
                    t.name,
                    t.description,
                )
            )

        # -------------------------------------------------
        # Runtime Skills
        # -------------------------------------------------
        """ 
        for s in self.rt_client.skills.list():

            def make_skill(
                skill_name,
                skill_description,
            ):

                @tool
                async def runtime_skill(
                    **kwargs,
                ):
                    # A2E Runtime Skill

                    result = (
                        await asyncio.to_thread(
                            self.rt_client.skills.call,
                            skill_name,
                            kwargs,
                        )
                    )

                    return str(result.output)

                runtime_skill.name = skill_name

                runtime_skill.description = (
                    skill_description
                )

                return runtime_skill

            self.lc_tools.append(
                make_skill(
                    s.name,
                    s.description,
                )
            )
        """
    # =====================================================
    # Main Run Loop
    # =====================================================

    async def run(
        self,
        goal: str,
        env_name: str = "counter_env",
        max_steps: int = 20,
    ) -> EpisodeTrajectory:

        # =================================================
        # Reset Environment
        # =================================================

        reset_resp = (
            await asyncio.to_thread(
                self.rt_client.env.reset,
                env_name=env_name,
            )
        )

        obs = reset_resp.obs

        episode_id = obs.episode_id

        self.rollout_id = (
            f"rollout_{uuid.uuid4().hex[:8]}"
        )

        done = obs.done

        truncated = obs.truncated

        trajectory = EpisodeTrajectory(

            rollout_id=self.rollout_id,

            episode_id=episode_id,

            env_name=env_name,

            goal=goal,

            initial_obs=obs.model_dump(),
        )

        step_idx = 0

        # =================================================
        # Main Agent Loop
        # =================================================

        while (
            not self.rt_client.env.is_done(
                done,
                truncated,
            )
            and step_idx < max_steps
        ):

            # =============================================
            # Observation
            # =============================================

            observation = {
                "env": obs.model_dump(),
                "history": self.history[-10:],
            }

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
You are an A2E DeepAgent.

Goal:
{goal}

Environment:
{observation}

Relevant Memories:
{memory_context}

You may:
- use tools
- use skills
- reason step by step

If the environment requires an action,
return a FINAL_ACTION block.

Example:

FINAL_ACTION:
{{
  "type": "env",
  "input": {{
      "type": "inc"
  }}
}}
"""

            t0 = time.monotonic()

            success = True

            try:
                # =========================================
                # Run DeepAgent
                # =========================================

                result = (
                    await self.agent.ainvoke({
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt,
                            }
                        ]
                    })
                )

                output = str(result)

                # =========================================
                # Parse Env Action
                # =========================================

                action = await self.extract_action(
                    output
                )

                action_type = action["type"]

                observation_result = output

                # =========================================
                # ENV ACTION
                # =========================================

                if action_type == "env":

                    step_resp = (
                        await asyncio.to_thread(
                            self.rt_client.env.step,
                            episode_id,
                            action["input"],
                        )
                    )

                    obs = step_resp.obs

                    done = step_resp.done

                    truncated = (
                        step_resp.truncated
                    )

                    observation_result = (
                        obs.model_dump()
                    )

            except Exception as e:

                success = False

                output = str(e)

                observation_result = str(e)

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
                output=output,
                observation=observation_result,
                success=success,
            )

            # =============================================
            # Record Step
            # =============================================

            traj_step = TrajectoryStep(

                step_id=step_idx,

                thought=output,

                action_type=action["type"],

                action_name=action.get(
                    "name",
                    action["type"],
                ),

                action_input=action["input"],

                observation=observation_result,

                reward=reward,

                success=success,

                latency_ms=latency_ms,
            )

            trajectory.steps.append(
                traj_step
            )

            trajectory.total_reward += (
                reward
            )

            trajectory.done = done

            trajectory.truncated = truncated

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

                prompt=goal,

                response=output,

                model="a2e-deepagent",

                environment={
                    "env_name": env_name,
                    "episode_id": episode_id,
                    "step_id": step_idx,
                    "rollout_id": (
                        self.rollout_id
                    ),
                },

                version="deepagent-v1",

                correlation_id=episode_id,

                session_id=episode_id,

                comment=output,

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
                    "goal": goal,
                    "output": output,
                    "reward": reward,
                },
                tier="episodic",
                tags=[
                    "deepagent",
                    "trajectory",
                    "rollout",
                ],
                ttl=0,
            )

            # =============================================
            # Periodic Adaptation
            # =============================================

            if (
                step_idx > 0
                and step_idx % 5 == 0
            ):

                await asyncio.to_thread(
                    self.rt_client.learn.adapt
                )

            # =============================================
            # Update History
            # =============================================

            self.history.append({
                "role": "assistant",
                "content": output,
                "reward": reward,
            })

            step_idx += 1

        # =================================================
        # Upload Rollout Experience
        # =================================================

        rollout = {

            "rollout_id": self.rollout_id,

            "episode_id": episode_id,

            "goal": goal,

            "reward": trajectory.total_reward,

            "steps": len(
                trajectory.steps
            ),

            "success": trajectory.done,

            "truncated": (
                trajectory.truncated
            ),

            "trajectory": [
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
    # Parse Final Action
    # =====================================================

    async def extract_action(
        self,
        text: str,
    ):

        import re
        import json

        m = re.search(
            r"FINAL_ACTION:\s*(\{.*\})",
            text,
            re.DOTALL,
        )

        if not m:

            return {
                "type": "env",
                "name": "noop",
                "input": {},
            }

        try:
            return json.loads(
                m.group(1)
            )

        except Exception:

            return {
                "type": "env",
                "name": "noop",
                "input": {},
            }

    # =====================================================
    # Reward Model
    # =====================================================

    async def compute_reward(
        self,
        goal: str,
        output: str,
        observation: Any,
        success: bool,
    ) -> float:

        if not success:
            return -1.0

        reward = 0.1

        obs_str = str(observation).lower()

        if "error" not in obs_str:
            reward += 0.5

        if "counter" in obs_str:
            reward += 0.25

        if "target value" in output.lower():
            reward += 5.0

        return reward


# =========================================================
# Main
# =========================================================

async def main():

    import logging

    logging.basicConfig(level=logging.INFO)

    rt_client = EnvClient(
        logger=logging.getLogger(
            "a2e"
        )
    )

    await rt_client.start()

    agent = A2EDeepAgent(rt_client)

    trajectory = await agent.run(
        goal="Increase counter to 5",
        env_name="counter_env",
    )

    print("\n=== TRAJECTORY ===\n")

    print(
        f"rollout={trajectory.rollout_id} "
        f"episode={trajectory.episode_id} "
        f"reward={trajectory.total_reward}"
    )

    for step in trajectory.steps:

        print(
            f"[{step.step_id}] "
            f"{step.action_name} "
            f"reward={step.reward:.2f} "
            f"success={step.success}"
        )

    await rt_client.stop()


if __name__ == "__main__":

    asyncio.run(main())
