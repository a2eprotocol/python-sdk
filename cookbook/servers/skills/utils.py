import os
import yaml
from typing import Tuple


def parse_skill_md(file_path: str) -> Tuple[dict, str]:
    """
    Parses markdown with YAML frontmatter.
    Returns: (frontmatter_dict, body_text)
    """
    with open(file_path, "r") as f:
        content = f.read()

    if not content.startswith("---"):
        raise ValueError(f"{file_path} missing frontmatter")

    parts = content.split("---", 2)
    frontmatter = yaml.safe_load(parts[1])
    body = parts[2].strip()

    return frontmatter, body
