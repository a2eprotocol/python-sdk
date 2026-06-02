"""
a2e/agent.py — A2E Learning Agent

Extends the SCP agent with:
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

import json
import os
import sys
import textwrap
import time
import uuid
from pydantic import BaseModel, Field
from typing import Any

from a2e.session_manager import (
    SubprocessTransport,
)
from a2e.caps.skills.client import (
    SkillCallResponse,
    SkillEvent,
    SkillDefinition
)
from a2e.caps.tools.client import ToolAPI
from a2e.caps.tools.protocol import (
    EventKind,
    ToolResult,
    ToolDefinition,
)
from a2e.caps.chains.protocol import (
    ChainResponse,
)

from a2e.client import (
    A2EClient,
)
from a2e.caps.memory.client import MemoryAPI
from a2e.caps.memory.protocol import (
    MemoryEntry, MemoryTier
)
from a2e.caps.learn.protocol import (
    FeedbackPolarity,
    Experience,
)

from a2e.caps.env.protocol import (
    EnvObservation
)

# ═════════════════════════════════════════════════════════════════════════════
# Progressive Disclosure (unchanged from SCP agent, extended)
# ═════════════════════════════════════════════════════════════════════════════

class Disclosure:
    SILENT = 0
    STATUS = 1
    DETAIL = 2
    DEBUG = 3

    def __init__(self, level: int = 1):
        self.level = level

    def _dim(self, s): return f"\033[2m{s}\033[0m"
    def _grn(self, s): return f"\033[32m{s}\033[0m"
    def _red(self, s): return f"\033[31m{s}\033[0m"
    def _cyn(self, s): return f"\033[36m{s}\033[0m"

    def status(self, msg: str):
        if self.level >= self.STATUS:
            print(self._dim(msg), flush=True)

    def detail(self, msg: str):
        if self.level >= self.DETAIL:
            print(f"  {msg}", flush=True)

    def debug(self, obj: Any):
        if self.level >= self.DEBUG:
            print(json.dumps(obj, indent=2, default=str), flush=True)

    def on_skill_start(self, names: list[str]):
        if names:
            self.status(f"🔧 Skills: {', '.join(names)}")

    def on_tool_start(self, names: list[str]):
        if names:
            self.status(f"⚙️  Tools: {', '.join(names)}")

    def on_skill_event(self, evt: SkillEvent):
        if self.level < self.DETAIL:
            return
        d = evt.data
        if evt.kind == EventKind.PROGRESS.value:
            print(f"  [{d.get('pct','?'):>3}%] {d.get('message','')}", flush=True)
        elif evt.kind == EventKind.STATUS.value:
            print(f"  → {d.get('message','')}", flush=True)

    def on_tool_event(self, evt):
        if self.level < self.DETAIL:
            return
        d = getattr(evt, "data", {})
        print(f"  ⚙ {d.get('message','')}", flush=True)

    def on_chain_event(self, evt):
        if self.level < self.DETAIL:
            return
        print(f"  🔗 [{evt.node_id}] {evt.phase}", flush=True)

    def on_skill_done(self, r: SkillCallResponse):
        icon = self._grn("✓") if r.success else self._red("✗")
        self.detail(
            f"{icon} {r.skill_name} v{r.skill_version} ({r.duration_ms}ms)"
        )
        if not r.success:
            self.detail(f"  error: {r.error}")
        self.debug(r.output)

    def on_tool_done(self, r: ToolResult):
        icon = self._grn("✓") if r.success else self._red("✗")
        self.detail(f"{icon} tool:{r.tool_name} ({r.duration_ms}ms)")
        if not r.success:
            self.detail(f"  error: {r.error}")
        self.debug(r.output)

    def on_learn(self, msg: str):
        if self.level >= self.DETAIL:
            print(self._cyn(f"  📚 {msg}"), flush=True)


# ═════════════════════════════════════════════════════════════════════════════
# Turn plan
# ═════════════════════════════════════════════════════════════════════════════

class SkillCall(BaseModel):
    skill_name: str
    input: dict[str, Any]
    reason: str = ""


class ToolCall(BaseModel):
    tool_name: str
    input: dict[str, Any]
    reason: str = ""


class TurnPlan(BaseModel):
    skill_calls: list[SkillCall] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    chain: dict | None = None   # {nodes, entry_node} if planning a chain
    direct_response: str | None = None
    reasoning: str = ""


# ═════════════════════════════════════════════════════════════════════════════
# Planners
# ═════════════════════════════════════════════════════════════════════════════

def _skill_menu(skills: list[SkillDefinition]) -> str:
    return "\n".join(
        f"  SKILL {s.name} v{s.version}: {s.description}"
        for s in skills
    ) or "  (none)"


def _tool_menu(tools: list[ToolDefinition]) -> str:
    return "\n".join(
        f"  TOOL  {t.name} [{t.kind}]: {t.description}"
        for t in tools
    ) or "  (none)"


def plan_heuristic(
    user_message: str,
    skills: list[SkillDefinition],
    tools: list[ToolDefinition],
) -> TurnPlan:
    """Tag-match heuristic planner (no LLM needed)."""
    msg_lower = user_message.lower()
    skill_calls, tool_calls = [], []

    for skill in skills:
        for tag in skill.tags:
            if tag in msg_lower or skill.name.replace("_", " ") in msg_lower:
                skill_calls.append(SkillCall(skill.name, {"text": user_message},
                                             reason=f"tag:{tag}"))
                break

    # Tool heuristics
    if any(
        k in msg_lower for k in (
            "run", "execute", "shell", "bash", "command", "$"
        )
    ):
        tool_calls.append(
            ToolCall(
                "shell_exec",
                {"cmd": user_message},
                reason="shell keyword"
            )
        )
    elif any(k in msg_lower for k in ("read file", "open file", "cat ")):
        pass  # let the LLM handle it
    elif any(k in msg_lower for k in ("http", "fetch", "download", "curl", "api")):
        tool_calls.append(
            ToolCall(
                "http_request",
                {"url": ""},
                reason="http keyword"
            )
        )

    return TurnPlan(
        skill_calls=skill_calls,
        tool_calls=tool_calls,
        reasoning="Heuristic"
    )


def plan_llm(
    user_message: str,
    history: list[dict],
    skills: list[SkillDefinition],
    tools: list[ToolDefinition],
    memories: list[MemoryEntry],
    env_snap: EnvObservation | None,
    llm_client: Any,
) -> TurnPlan:
    """LLM-based planner with full context."""
    mem_ctx = ""
    if memories:
        mem_ctx = "\n".join(
            f"  [{e.key}] {json.dumps(e.content, default=str)[:120]}"
            for e in memories[:5]
        )

    env_ctx = ""
    if env_snap:
        env_ctx = f"  cwd={env_snap.cwd}  free_mb={env_snap.disk_free_mb}"

    system = textwrap.dedent(f"""
        You are a planning agent.
        Given the conversation, memories, and environment,
        decide which skills and/or tools (if any) to invoke.

        Available skills:
        {_skill_menu(skills)}

        Available tools:
        {_tool_menu(tools)}

        Relevant memories:
        {mem_ctx or '  (none)'}

        Environment:
        {env_ctx or '  (unavailable)'}

        Reply with ONLY a JSON object:
        {{
          "reasoning": "<one sentence>",
          "skill_calls": [
            {{"skill_name": "<n>", "input": {{...}}, "reason": "<why>"}}
          ],
          "tool_calls": [
            {{"tool_name": "<n>", "input": {{...}}, "reason": "<why>"}}
          ],
          "direct_response": "<answer if no calls needed, else null>"
        }}
    """).strip()

    messages = history[-6:] + [{"role": "user", "content": user_message}]
    resp = llm_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=768,
        system=system,
        messages=messages,
    )
    raw = resp.content[0].text.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return TurnPlan(direct_response=raw, reasoning="LLM parse error")

    return TurnPlan(
        skill_calls=[SkillCall(**c) for c in data.get("skill_calls", [])],
        tool_calls=[ToolCall(**c) for c in data.get("tool_calls", [])],
        direct_response=data.get("direct_response"),
        reasoning=data.get("reasoning", ""),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Agent config
# ═════════════════════════════════════════════════════════════════════════════

class A2EAgentConfig(BaseModel):
    host_cmd: list[str]
    llm_client: Any | None = None
    disclosure: Disclosure = Field(default_factory=Disclosure)
    synthesise: bool = True
    max_history: int = 20
    
    # Memory settings
    use_memory: bool = True
    memory_recall_limit: int = 5
    
    # Learning
    use_learning: bool = True
    auto_adapt_every: int = 10   # adapt router every N turns
    
    # Environment
    observe_env: bool = True
    
    # Agent identity
    agent_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    correlation_prefix: str = Field(default_factory=lambda: uuid.uuid4().hex[:6])


# ═════════════════════════════════════════════════════════════════════════════
# A2E Agent
# ═════════════════════════════════════════════════════════════════════════════

class A2EAgent:
    """
    Full A2E-powered multi-turn agent.

    Per-turn flow:
      observe → recall → plan → execute → learn → synthesise → remember
    """

    def __init__(self, config: A2EAgentConfig):
        self.cfg = config
        self.history: list[dict] = []
        self._turn = 0

        transport = SubprocessTransport(config.host_cmd)
        self._client = A2EClient(transport, agent_id=config.agent_id)

        self._memory = MemoryAPI(self._client)
        self._tools_api = ToolAPI(self._client)

        self._skills: list[SkillDefinition] = []
        self._tools: list[ToolDefinition] = []
        self._env_snap: EnvObservation | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        d = self.cfg.disclosure
        d.status("🔌 Connecting to A2E host…")
        self._client.connect()

        self._memory.init()

        self._skills = self._client.discover()
        self._tools = self._tools_api.list()      # active (non-deferred) tools only

        d.status(f"📦 {len(self._skills)} skills")
        d.detail(f"📦 Skills: {[s.name for s in self._skills]}")

        # Progressive disclosure for tools:
        #   STATUS  → count only
        #   DETAIL  → names
        #   DEBUG   → full definitions (name, kind, description)
        d.status(f"⚙️  {len(self._tools)} tools loaded")
        if d.level >= Disclosure.DETAIL:
            d.detail(f"⚙️  Tools: {[t.name for t in self._tools]}")
        if d.level >= Disclosure.DEBUG:
            for t in self._tools:
                d.debug(f"  TOOL {t.name} [{getattr(t, 'kind', 'tool')}] — {t.description}")

        # Register env push callback
        if self.cfg.observe_env:
            self._client.env.on_push(self._on_env_push)
            self._env_snap = self._client.env.observe()

    def stop(self):
        self._client.disconnect()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    # ── Chat ──────────────────────────────────────────────────────────────

    def chat(self, user_message: str) -> str:
        self._turn += 1
        d = self.cfg.disclosure
        cid = f"{self.cfg.correlation_prefix}-t{self._turn}"
        t0 = time.monotonic()

        # 1. Recall memories
        memories: list[MemoryEntry] = []
        if self.cfg.use_memory:
            memories = self._memory.retrieve(
                query=user_message,
                limit=self.cfg.memory_recall_limit,
            )
            if memories:
                d.detail(f"🧠 Recalled {len(memories)} memories")

        # 2. Plan
        if self.cfg.llm_client:
            plan = plan_llm(
                user_message, self.history,
                self._skills, self._tools,
                memories, self._env_snap,
                self.cfg.llm_client,
            )
        else:
            plan = plan_heuristic(user_message, self._skills, self._tools)
        d.detail(f"📋 {plan.reasoning}")

        # 3. Execute skills (parallel)
        skill_results: list[SkillCallResponse] = []
        if plan.skill_calls:
            d.on_skill_start([c.skill_name for c in plan.skill_calls])
            calls_dicts = [
                {
                    "skill_name": c.skill_name,
                    "input": c.input,
                    "correlation_id": cid
                }
                for c in plan.skill_calls
            ]
            skill_results = self._client.call_parallel(
                calls_dicts, on_event=d.on_skill_event
            )
            for r in skill_results:
                d.on_skill_done(r)

        # 4. Execute tools (parallel)
        tool_results: list[ToolResult] = []
        if plan.tool_calls:
            d.on_tool_start([c.tool_name for c in plan.tool_calls])
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, len(plan.tool_calls))
            ) as ex:
                futures = [
                    ex.submit(
                        self._client.tools.call,
                        c.tool_name, c.input,
                        on_event=d.on_tool_event,
                        correlation_id=cid,
                    )
                    for c in plan.tool_calls
                ]
                tool_results = [
                    f.result()
                    for f in concurrent.futures.as_completed(futures)
                ]
            for r in tool_results:
                d.on_tool_done(r)

        # 5. Execute chain (if planned)
        chain_result: ChainResponse | None = None
        if plan.chain:
            d.status("🔗 Running chain…")
            chain_result = self._client.chains.run(
                nodes=plan.chain["nodes"],
                entry_node=plan.chain["entry_node"],
                initial_input=plan.chain.get("initial_input", {}),
                on_event=d.on_chain_event,
                correlation_id=cid,
            )

        # 6. Learn
        if self.cfg.use_learning:
            self._record_learning(plan, skill_results, tool_results, cid, t0)

        # 7. Synthesise
        response = self._synthesise(
            user_message, plan, skill_results, tool_results, chain_result
        )

        # 8. Update conversation history
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": response})
        self.history = self.history[-(self.cfg.max_history * 2):]

        # 9. Save to episodic memory
        if self.cfg.use_memory:
            self._memory.remember(
                key=f"turn:{cid}",
                value={"user": user_message, "response": response[:500],
                       "skills": [r.skill_name for r in skill_results],
                       "tools": [r.tool_name for r in tool_results]},
                tier=MemoryTier.EPISODIC.value,
                tags=["turn", "conversation"],
                ttl=0,
            )

        return response

    # ── Learning helper ───────────────────────────────────────────────────

    def _record_learning(
        self,
        plan: TurnPlan,
        skill_results: list[SkillCallResponse],
        tool_results: list[ToolResult],
        cid: str,
        t0: float,
    ):
        d = self.cfg.disclosure
        feedbacks = []

        for r in skill_results:
            polarity = (FeedbackPolarity.POSITIVE.value if r.success
                        else FeedbackPolarity.NEGATIVE.value)
            feedbacks.append({
                "polarity": polarity,
                "score": 1.0 if r.success else -0.5,
                "skill_name": r.skill_name,
                "correlation_id": cid,
                "source": "env",
            })

        for r in tool_results:
            polarity = (FeedbackPolarity.POSITIVE.value if r.success
                        else FeedbackPolarity.NEGATIVE.value)
            feedbacks.append({
                "polarity": polarity,
                "score": 1.0 if r.success else -0.5,
                "skill_name": r.tool_name,
                "correlation_id": cid,
                "source": "env",
            })

        if feedbacks:
            self._client.learn.feedback(
                polarity="neutral",  # batch call; individual feedbacks embedded
                score=0.0,
                correlation_id=cid,
            )

        # Store experience tuple
        exp = Experience(
            state={"turn": self._turn, "history_len": len(self.history)},
            action={
                "skills": [c.skill_name for c in plan.skill_calls],
                "tools": [c.tool_name for c in plan.tool_calls],
            },
            reward=sum(
                1.0 if r.success else -0.5
                for r in skill_results + tool_results
            ),
            next_state={"turn": self._turn + 1},
            done=False,
        )
        self._client.learn.experience([exp])

        # Periodically adapt routing
        if self._turn % self.cfg.auto_adapt_every == 0:
            records = self._client.learn.adapt()
            d.on_learn(f"Adapted routing ({len(records)} skills/tools tracked)")

    # ── Synthesise ────────────────────────────────────────────────────────

    def _synthesise(
        self,
        user_message: str,
        plan: TurnPlan,
        skill_results: list[SkillCallResponse],
        tool_results: list[ToolResult],
        chain_result: ChainResponse | None,
    ) -> str:
        all_results = skill_results + tool_results + (
            [chain_result] if chain_result else []
        )

        if not all_results and plan.direct_response:
            if self.cfg.llm_client and self.cfg.synthesise:
                return self._llm_answer(user_message)
            return plan.direct_response

        ctx_parts = []
        for r in skill_results:
            if r.success:
                ctx_parts.append(
                    f"[skill:{r.skill_name}]\n{json.dumps(r.output, indent=2)}"
                )
            else:
                ctx_parts.append(
                    f"[skill:{r.skill_name} ERROR {r.error_code}]: {r.error}"
                )

        for r in tool_results:
            if r.success:
                ctx_parts.append(
                    f"[tool:{r.tool_name}]\n{json.dumps(r.output, indent=2)}"
                )
            else:
                ctx_parts.append(
                    f"[tool:{r.tool_name} ERROR {r.error_code}]: {r.error}"
                )

        if chain_result:
            if chain_result.success:
                ctx_parts.append(
                    f"[chain]\n{json.dumps(chain_result.final_output, indent=2)}"
                )
            else:
                ctx_parts.append(f"[chain ERROR]: {chain_result.error}")

        ctx = "\n\n".join(ctx_parts)

        if self.cfg.llm_client and self.cfg.synthesise:
            return self._llm_answer(user_message, ctx)

        # Fallback: surface summary if available
        if len(skill_results) == 1 and skill_results[0].success:
            out = skill_results[0].output
            if isinstance(out, dict) and "summary" in out:
                parts = [f"Summary: {out['summary']}"]
                if out.get("key_points"):
                    parts.append("Key points: " + ", ".join(out["key_points"]))
                return "\n".join(parts)

        return ctx or "(no output)"

    def _llm_answer(self, user_message: str, context: str = "") -> str:
        system = (
            "You are a helpful assistant with access"
            "to skills, tools, and memory. "
            "Use the provided results to answer the user concisely."
        )
        content = (
            f"{context}\n\nUser: {user_message}"
            if context else user_message
        )
        messages = self.history[-8:] + [{"role": "user", "content": content}]
        resp = self.cfg.llm_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return resp.content[0].text

    # ── Env push callback ─────────────────────────────────────────────────

    def _on_env_push(self, push):
        self.cfg.disclosure.detail(f"🌍 env push: {push.reason}")
        if push.delta.get("proc_exit"):
            pe = push.delta["proc_exit"]
            self.cfg.disclosure.detail(
                f"   proc {pe['proc_id']} exited (rc={pe.get('exit_code')})"
            )

    # ── REPL ──────────────────────────────────────────────────────────────

    def run_loop(self):
        print("A2E Agent ready.  Commands: quit | debug | skills | tools | search | "
              "memory | stats | env\n")
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue

            match user_input:
                case "quit":
                    break
                case "debug":
                    self.cfg.disclosure.level = (
                        Disclosure.STATUS
                        if self.cfg.disclosure.level >= Disclosure.DEBUG
                        else Disclosure.DEBUG
                    )
                    print(f"[disclosure → {self.cfg.disclosure.level}]")
                case "skills":
                    for s in self._skills:
                        print(f"  SKILL {s.name} v{s.version} — {s.description}")
                case "tools":
                    for t in self._tools:
                        print(f"  TOOL  {t.name} [{getattr(t, 'kind', 'tool')}] — {t.description}")
                case "search":
                    q = input("  search query: ").strip()
                    if not q:
                        print("  (no query)")
                    else:
                        results = self._tools_api.list(query=q, include_deferred=True)
                        if results:
                            for t in results:
                                print(f"  TOOL  {t.name} [{getattr(t, 'kind', 'tool')}] — {t.description}")
                        else:
                            print(f"  (no tools matching '{q}')")
                case "memory":
                    entries = self._memory.retrieve(limit=10)
                    for e in entries:
                        print(f"  [{e.tier}] {e.key}: {str(e.content)[:80]}")
                case "stats":
                    skills, tools = self._client.learn.stats()
                    for r in skills + tools:
                        print(f"  {r.skill_name}: calls={r.calls_total} "
                              f"score={r.avg_score:.2f}")
                case "env":
                    snap = self._client.env.observe()
                    print(f"  cwd={snap.cwd}  disk_free={snap.disk_free_mb}MB "
                          f"procs={len(snap.running_procs)}")
                case _:
                    response = self.chat(user_input)
                    print(f"\nAgent: {response}\n")


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    import logging
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    p = argparse.ArgumentParser()
    p.add_argument("--skills-root", default="./skills")
    p.add_argument("--pool-size", type=int, default=4)
    p.add_argument("--disclosure", type=int, default=2, choices=[0, 1, 2, 3])
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--episodic-db", default=None)
    p.add_argument("--semantic-db", default=None)
    p.add_argument("--learn-strategy", default="ucb1")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--no-learning", action="store_true")
    args = p.parse_args()

    host_cmd = [
        sys.executable, "-m", "a2e.host",
        "--skills-root", args.skills_root,
        "--pool-size", str(args.pool_size),
        "--learn-strategy", args.learn_strategy,
        *(["--episodic-db", args.episodic_db] if args.episodic_db else []),
        *(["--semantic-db", args.semantic_db] if args.semantic_db else []),
    ]

    llm_client = None
    if not args.no_llm:
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                llm_client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            pass

    config = A2EAgentConfig(
        host_cmd=host_cmd,
        llm_client=llm_client,
        disclosure=Disclosure(level=args.disclosure),
        synthesise=bool(llm_client),
        use_memory=not args.no_memory,
        use_learning=not args.no_learning,
    )

    with A2EAgent(config) as agent:
        agent.run_loop()


if __name__ == "__main__":
    main()
