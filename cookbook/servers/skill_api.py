from a2e.caps.skills.client import SkillAPI

def run_skill(client):
    # ─────────────────────────────────────────────
    # List available tools
    # ─────────────────────────────────────────────
    skill = SkillAPI(client)
    skills = skill.discover()

    skill.call(
        skill_id="example-analysis",
        arguments={"args": "AI agents in enterprises"}
    )
