import os
import time
import yaml
import json
import glob
import traceback
from typing import Dict, Any, List

from a2e.caps.skills import (
    SkillDefinition,
    SkillResult,
    SkillPlugin
)


class FilesystemSkillPlugin(SkillPlugin):
    """
    Loads skills from filesystem (skill.md files).

    Structure:
        skills/
            example-analysis/
                skill.md
            code-review/
                skill.md
    """

    def __init__(self, host_instance, config):
        super().__init__(host_instance, config)

        self.skills_path = config.get("skills_path", "./skills_folder")
        self._skills_cache: Dict[str, Dict] = {}

    # ─────────────────────────────────────────────
    # DISCOVERY
    # ─────────────────────────────────────────────
    def _list_skills(self) -> List[SkillDefinition]:
        skills: List[SkillDefinition] = []

        pattern = os.path.join(self.skills_path, "*", "skill.md")
        files = glob.glob(pattern)

        for filepath in files:
            try:
                skill = self._load_skill(filepath)
                skills.append(skill)
            except Exception as e:
                self.logger.warning(f"[skill] failed to load {filepath}: {e}")

        return skills

    def _load_skill(self, filepath: str) -> SkillDefinition:
        """
        Parse skill.md → SkillDefinition
        """
        with open(filepath, "r") as f:
            content = f.read()

        # Split frontmatter
        if content.startswith("---"):
            _, frontmatter, body = content.split("---", 2)
            meta = yaml.safe_load(frontmatter)
        else:
            meta = {}
            body = content

        name = meta.get("name") or os.path.basename(os.path.dirname(filepath))

        # Cache full skill for execution
        self._skills_cache[name] = {
            "meta": meta,
            "body": body,
            "path": filepath,
        }

        return SkillDefinition(
            name=name,
            version=meta.get("version", "1.0.0"),
            description=meta.get("description", ""),
            triggers=meta.get("triggers", []),
            tools=meta.get("tools", []),  # just names here
            toolkits=[],
            status="Published",

            input_schema={
                "type": "object",
                "properties": {
                    "args": {"type": "string"}
                }
            },
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "findings": {"type": "array"},
                    "recommendations": {"type": "array"},
                }
            },

            instructions=body,
            when_to_use=meta.get("description", ""),
            argument_hint="args: string",
            source="filesystem",

            category=meta.get("category"),
            tags=meta.get("tags", []),
            icon=meta.get("icon"),
        )

    # ─────────────────────────────────────────────
    # EXECUTION
    # ─────────────────────────────────────────────
    def _execute_skill(
        self,
        name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> SkillResult:
        """
        Stream-aware filesystem skill execution runtime.

        Execution model:
            skill.started
                -> tool.*
                -> llm.*
                -> skill.completed

        Designed for:
            - SSE streaming
            - replayable execution traces
            - observability
            - harness supervision
            - future RL trajectories
        """

        start = time.time()

        emit_event = context.get("emit_event")

        # ─────────────────────────────────────────────
        # Event helper
        # ─────────────────────────────────────────────
        def emit(kind: str, data: Dict[str, Any]):
            if emit_event:
                emit_event(
                    kind=kind,
                    data={
                        "skill": name,
                        "ts": time.time(),
                        **data,
                    },
                )

        # ─────────────────────────────────────────────
        # Resolve skill
        # ─────────────────────────────────────────────
        skill = self._skills_cache.get(name)

        if not skill:
            emit(
                "skill.failed",
                {
                    "error": f"Skill not found: {name}",
                    "error_code": "unknown_skill",
                },
            )

            return SkillResult(
                success=False,
                skill_id=name,
                error=f"Skill not found: {name}",
                error_code="unknown_skill",
                duration_ms=0,
            )

        meta = skill["meta"]
        instructions = skill["body"]

        emit(
            "skill.started",
            {
                "arguments": arguments,
                "tools": meta.get("tools", []),
            },
        )

        try:
            # ─────────────────────────────────────────
            # Build prompt
            # ─────────────────────────────────────────
            emit("skill.preparing", {})

            args = arguments.get("args", "")

            prompt = instructions.replace(
                "{args}",
                str(args),
            )

            emit(
                "skill.prompt.ready",
                {
                    "prompt_preview": prompt[:500],
                },
            )

            # ─────────────────────────────────────────
            # Tool execution
            # ─────────────────────────────────────────
            tool_outputs = {}
            """
            for tool_name in meta.get("tools", []):

                emit(
                    "tool.started",
                    {
                        "tool": tool_name,
                    },
                )

                tool_start = time.time()

                try:
                    result = execute_tool(
                        name=tool_name,
                        params=arguments,
                        config=context.get("config", {}),
                    )

                    tool_outputs[tool_name] = result

                    emit(
                        "tool.completed",
                        {
                            "tool": tool_name,
                            "duration_ms": int(
                                (time.time() - tool_start) * 1000
                            ),
                            "output_preview": str(result)[:1000],
                        },
                    )

                except Exception as e:
                    tool_outputs[tool_name] = {
                        "error": str(e)
                    }

                    emit(
                        "tool.failed",
                        {
                            "tool": tool_name,
                            "error": str(e),
                            "traceback": traceback.format_exc(),
                        },
                    )
            """
            # ─────────────────────────────────────────
            # LLM execution
            # ─────────────────────────────────────────
            llm = context.get("llm")

            if llm:

                emit(
                    "llm.started",
                    {
                        "provider": getattr(
                            llm,
                            "provider",
                            "unknown",
                        ),
                    },
                )

                final_prompt = (
                    prompt
                    + "\n\nTool Outputs:\n"
                    + json.dumps(
                        tool_outputs,
                        indent=2,
                        default=str,
                    )
                )

                streaming = context.get("streaming", False)

                # ─────────────────────────────────────
                # Streaming path
                # ─────────────────────────────────────
                if streaming and hasattr(llm, "stream"):

                    chunks = []

                    for chunk in llm.stream(final_prompt):

                        chunks.append(chunk)

                        emit(
                            "llm.token",
                            {
                                "token": chunk,
                            },
                        )

                    llm_response = "".join(chunks)

                # ─────────────────────────────────────
                # Non-streaming path
                # ─────────────────────────────────────
                else:
                    llm_response = llm.generate(final_prompt)

                emit(
                    "llm.completed",
                    {
                        "response_preview": llm_response[:1000],
                    },
                )

                data = {
                    "response": llm_response,
                    "tools": tool_outputs,
                }

            # ─────────────────────────────────────────
            # No LLM fallback
            # ─────────────────────────────────────────
            else:

                emit(
                    "llm.skipped",
                    {
                        "reason": "no_llm_available",
                    },
                )

                data = {
                    "prompt": prompt,
                    "tools": tool_outputs,
                }

            # ─────────────────────────────────────────
            # Complete
            # ─────────────────────────────────────────
            duration = int((time.time() - start) * 1000)

            emit(
                "skill.completed",
                {
                    "duration_ms": duration,
                },
            )

            return SkillResult(
                success=True,
                skill_id=name,
                data=data,
                summary="Skill executed successfully",
                duration_ms=duration,
            )

        except Exception as e:
            duration = int((time.time() - start) * 1000)

            emit(
                "skill.failed",
                {
                    "error": str(e),
                    "duration_ms": duration,
                    "traceback": traceback.format_exc(),
                },
            )

            return SkillResult(
                success=False,
                skill_id=name,
                error=str(e),
                error_code="execution_error",
                duration_ms=duration,
            )
