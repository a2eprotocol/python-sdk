---
name: example-analysis
version: "1.0.0"
description: "Analyze a topic and produce structured insights"
user-invocable: true

triggers:
  - "/example-analysis"
  - "analyze"
  - "give insights"

tools:
  - Read
  - Glob
  - Grep

category: analysis

tags:
  - analysis
  - insights
  - reporting

when_to_use: >
  Use this skill when the user asks for structured analysis,
  breakdown, or insights on a topic.

argument_hint: >
  Provide a clear topic or subject to analyze (e.g., "AI in healthcare",
  "startup growth strategies").

inputs:
  topic:
    type: string
    required: true
    description: Topic to analyze

outputs:
  summary:
    type: string
  key_findings:
    type: array
    items: string
  recommendations:
    type: array
    items: string

max_turns: 5
timeout_seconds: 60
---

# Example Analysis Skill

You are a helpful analyst. The user has asked you to analyze a topic and provide structured insights.

## Your task

Analyze the following topic and provide structured findings:

**Topic:** {topic}

## Instructions

- Think clearly and structure your response
- Use tools if needed (search, read, grep relevant data)
- Focus on clarity and actionable insights
- Avoid vague or generic statements

## Output format

1. **Summary** — 2–3 sentence overview  
2. **Key findings** — bulleted list  
3. **Recommendations** — actionable next steps
