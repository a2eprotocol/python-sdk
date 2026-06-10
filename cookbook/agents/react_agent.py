"""
a2e/react.py — A2E React Agent

Extends the A2E agent with:
  • Tool calls alongside skill calls in every turn
  • Working + episodic memory automatically populated from conversation
  • Experience replay: (state, action, reward, next_state) stored per turn
  • Adaptive skill/tool routing via the learning subsystem
  • Environment observation injected into the planner context
  • Long-running process support via the procs API
  • Multi-step chains for complex reasoning pipelines

Turn loop
─────────
  1. Observe environment snapshot (optional, async)
  2. Recall relevant memories
  3. Plan (LLM or heuristic) → list of SkillCalls + ToolCalls + optional Chain
  4. Execute (parallel where possible)
  5. Store experiences + emit feedback to learning subsystem
  6. Synthesise → respond
  7. Save turn memory + update episodic store
"""

from __future__ import annotations

import pdb
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from a2e import A2EClient
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
    Feedback
)
from a2e.core.transports import (
    build_transport,
    TransportConfig,
    HTTPTransportConfig
)
from a2e.caps.base.protocol import (
    A2ECapability,
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
    episode_id: str

    env_name: str
    goal: str

    initial_obs: dict

    steps: List[TrajectoryStep] = field(default_factory=list)

    total_reward: float = 0.0

    done: bool = False
    truncated: bool = False


# =========================================================
# Runtime
# =========================================================

class EnvClient:
    def __init__(self, logger):
        transport_config = TransportConfig(**{
            "type": "http",
            "config": HTTPTransportConfig(**{
                "base_url": "http://localhost:8765",
                "stream": "/stream",
                "send": "/send"
            })
        })

        self.transport = build_transport(transport_config, logger)
        self.client = A2EClient(
            transport=self.transport,
            logger=logger,
            agent_id="react-agent",
            auth_token="",  # dev mode
            agent_caps=[
                A2ECapability.TOOLKITS,
                A2ECapability.ENV,
                A2ECapability.PROC
            ],
        )

        self.env = EnvAPI(self.client)
        self.memory = MemoryAPI(self.client)
        self.learn = LearnAPI(self.client)
        self.tools = ToolAPI(self.client)
        self.skills = SkillAPI(self.client)
        self.chains = ChainsAPI(self.client) 

    async def start(self):
        await asyncio.to_thread(self.client.connect)
        await asyncio.to_thread(self.memory.init)

    async def stop(self):
        await asyncio.to_thread(self.client.disconnect)


# =========================================================
# ReAct + RLM Agent
# =========================================================

class A2EReActAgent:
    def __init__(self, rt_client, llm=None):
        self.rt_client = rt_client
        self.llm = llm
        self.history = []

    # -----------------------------------------------------
    # Main RL / ReAct Loop
    # -----------------------------------------------------

    async def run(
        self,
        goal: str,
        env_name: str = "counter_env",
        max_steps: int = 20,
    ) -> EpisodeTrajectory:

        # =================================================
        # Reset Environment
        # =================================================

        reset_resp = await asyncio.to_thread(
            self.rt_client.env.reset,
            env_name=env_name,
        )

        obs = reset_resp.obs

        # episode owned by env
        episode_id = obs.episode_id

        done = obs.done
        truncated = obs.truncated

        trajectory = EpisodeTrajectory(
            episode_id=episode_id,
            env_name=env_name,
            goal=goal,
            initial_obs=obs.model_dump(),
        )

        step_idx = 0

        # =================================================
        # Main Loop
        # =================================================

        while (
            not self.rt_client.env.is_done(done, truncated)
            and step_idx < max_steps
        ):

            # =============================================
            # Observe
            # =============================================
            observation = {
                "env": obs.model_dump(),
                "history": self.history[-10:],
            }

            # =============================================
            # Recall Memories
            # =============================================
            memories = await asyncio.to_thread(
                self.rt_client.memory.retrieve,
                query=goal,
                limit=5,
            )

            # =============================================
            # Build Working Context
            # =============================================

            context = {
                "goal": goal,
                "observation": observation,
                "memories": [
                    str(m.content)
                    for m in memories
                ],
                "available_tools": [
                    t.name
                    for t in self.rt_client.tools.list()
                ],
            }

            # =============================================
            # Reason / Plan
            # =============================================

            thought = await self.reason(context)

            action = thought["action"]

            action_type = action["type"]
            action_name = action["name"]
            action_input = action["input"]

            t0 = time.monotonic()

            success = True

            try:

                # =========================================
                # TOOL ACTION
                # =========================================
                print(f"action type is `{action_type}`")
                if action_type == "tool":
                    result = await asyncio.to_thread(
                        self.rt_client.tools.call,
                        action_name,
                        action_input,
                    )

                    observation_result = result.output

                    success = result.success

                # =========================================
                # SKILL ACTION
                # =========================================

                elif action_type == "skill":
                    result = await asyncio.to_thread(
                        self.rt_client.skills.call,
                        action_name,
                        action_input,
                    )

                    observation_result = result.output

                    success = result.success

                # =========================================
                # CHAIN ACTION
                # =========================================

                elif action_type == "chain":

                    result = await asyncio.to_thread(
                        self.rt_client.chains.run,
                        nodes=action_input["nodes"],
                        entry_node=action_input["entry_node"],
                        initial_input=action_input.get(
                            "initial_input",
                            {},
                        ),
                    )

                    observation_result = result.output

                    success = result.success

                # =========================================
                # ENV ACTION
                # =========================================

                elif action_type == "env":

                    step_resp = await asyncio.to_thread(
                        self.rt_client.env.step,
                        episode_id,
                        action_input,
                    )

                    obs = step_resp.obs

                    done = step_resp.done
                    truncated = step_resp.truncated

                    observation_result = obs.model_dump()

                else:
                    raise RuntimeError(
                        f"Unknown action type: {action_type}"
                    )

            except Exception as e:

                success = False
                observation_result = str(e)

            latency_ms = (
                time.monotonic() - t0
            ) * 1000

            # =============================================
            # Reward Model
            # =============================================
            reward = await self.compute_reward(
                goal=goal,
                thought=thought,
                observation=observation_result,
                success=success,
            )

            # =============================================
            # Record Trajectory
            # =============================================

            traj_step = TrajectoryStep(
                step_id=step_idx,

                thought=thought["reasoning"],

                action_type=action_type,
                action_name=action_name,
                action_input=action_input,

                observation=observation_result,

                reward=reward,
                success=success,

                latency_ms=latency_ms,
            )

            trajectory.steps.append(traj_step)

            trajectory.total_reward += reward

            trajectory.done = done
            trajectory.truncated = truncated

            # =============================================
            # Learn Feedback
            # =============================================
            await asyncio.to_thread(
                self.rt_client.learn.feedback,

                # -------------------------------------------------
                # Core Signal
                # -------------------------------------------------

                polarity=(
                    FeedbackPolarity.POSITIVE
                    if reward > 0
                    else FeedbackPolarity.NEGATIVE
                ),

                score=float(reward),

                dimension=(
                    FeedbackDimension.CORRECTNESS
                    if success
                    else FeedbackDimension.PLAN_QUALITY
                ),

                confidence=1.0,

                # -------------------------------------------------
                # Rated Turn
                # -------------------------------------------------

                prompt=goal,

                response=str(observation_result),

                model="a2e-react-agent",

                environment={
                    "env_name": env_name,
                    "episode_id": episode_id,
                    "step_id": step_idx,
                },

                version="react-agent-v1",

                # -------------------------------------------------
                # Correlation
                # -------------------------------------------------

                correlation_id=episode_id,

                session_id=episode_id,

                # -------------------------------------------------
                # Human / Harness Context
                # -------------------------------------------------

                comment=thought["reasoning"],

                correction=(
                    ""
                    if success
                    else "Planner should select a safer "
                         "or more relevant action."
                ),

                # -------------------------------------------------
                # Provenance
                # -------------------------------------------------

                source=FeedbackSource.ENV,

                annotator_id="a2e-runtime",

                # -------------------------------------------------
                # Runtime
                # -------------------------------------------------

                timeout=10,
            )

            # =============================================
            # Store Episodic Memory
            # =============================================
            await asyncio.to_thread(
                self.rt_client.memory.remember,
                key={"episode_id": episode_id, "step_idx": step_idx},
                value={
                    "goal": goal,
                    "thought": thought,
                    "action": action,
                    "reward": reward,
                    "success": success,
                },
                tier="episodic",
                tags=[
                    "trajectory",
                    "react",
                    "rlm",
                ],
                ttl=0,
            )

            # =============================================
            # Adapt Policy / Routing
            # =============================================
            if step_idx > 0 and step_idx % 5 == 0:

                await asyncio.to_thread(
                    self.rt_client.learn.adapt
                )

            # =============================================
            # Update Local History
            # =============================================

            self.history.append({
                "role": "assistant",
                "thought": thought["reasoning"],
                "action": action,
                "reward": reward,
            })

            step_idx += 1

        # =================================================
        # Final Experience Upload
        # =================================================

        experience = {
            "episode_id": episode_id,
            "goal": goal,
            "reward": trajectory.total_reward,
            "steps": len(trajectory.steps),
            "success": trajectory.done,
            "truncated": trajectory.truncated,
        }

        await asyncio.to_thread(
            self.rt_client.learn.experience,
            [experience],
        )

        # =================================================
        # Optional Env Review
        # =================================================

        try:

            review = await asyncio.to_thread(
                self.rt_client.env.review,
                episode_id,
                {
                    "goal": goal,
                    "reward": trajectory.total_reward,
                    "steps": len(trajectory.steps),
                },
            )

            trajectory.review = review.model_dump()

        except Exception:
            pass

        return trajectory

    # -----------------------------------------------------
    # Planner / ReAct Policy
    # -----------------------------------------------------

    async def reason(self, context: dict):

        """
        Replace with:
          - planner LLM
          - verifier
          - routing model
          - critique model
          - harness guidance
        """

        env_obs = context["observation"]["env"]

        counter = env_obs.get("state", {}).get("counter", 0)

        if counter >= 5:

            return {
                "reasoning": (
                    "Counter reached target value."
                ),
                "done": True,
                "action": {
                    "type": "env",
                    "name": "finish",
                    "input": {},
                },
            }

        return {
            "reasoning": (
                "Need to increment counter."
            ),
            "done": False,
            "action": {
                "type": "env",
                "name": "increment_counter",
                "input": {
                    "type": "inc",
                },
            },
        }

    # -----------------------------------------------------
    # Reward Model
    # -----------------------------------------------------

    async def compute_reward(
        self,
        goal: str,
        thought: dict,
        observation: Any,
        success: bool,
    ) -> float:

        if not success:
            return -1.0

        reward = 0.1

        obs_str = str(observation).lower()

        if "error" not in obs_str:
            reward += 0.5

        if thought.get("done"):
            reward += 5.0

        return reward


# =========================================================
# Example Usage
# =========================================================

async def main():

    import logging

    rt_client = EnvClient(
        logger=logging.getLogger("a2e"),
    )

    await rt_client.start()
    
    agent = A2EReActAgent(rt_client)

    trajectory = await agent.run(
        goal="Increase counter to 5",
        env_name="counter_env",
    )

    print("\n=== TRAJECTORY ===\n")

    print(
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
