from a2e.caps.skills.client import SkillAPI
from a2e.caps.skills.protocol import SkillEvent


def on_skill_event(evt: SkillEvent):
    """Receive streaming events during skill execution."""
    print(f"  [skill.event] kind={evt.kind} | data={evt.data}")


def run_skill(client):
    skill = SkillAPI(client)
    skills = skill.discover()

    # --- Call skill without streaming ---
    result = skill.call(
        name="example-analysis",
        arguments={"args": "AI agents in enterprises"},
        streaming=False,
    )
    print("Result:", result)

    # --- Call skill with streaming events ---
    print("\n--- Streaming skill call ---")
    result = skill.call(
        name="example-analysis",
        arguments={"args": "AI agents in enterprises"},
        streaming=True,
        on_event=on_skill_event,
    )
    print("Final result:", result)
