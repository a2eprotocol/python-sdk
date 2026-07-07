# A2E Launch Video — Storyboard & Plan

## Reference: Bloom YC Launch Video
- Duration: ~41 seconds
- Format: Product demo screencast (subtle purple/dark theme)
- Structure: Hook → 3-step how-it-works → Built for agents → CTA
- Publishing: Y Combinator Launches + X/Twitter (@ycombinator)
- Metrics: 483 likes, 44 reposts, 64 replies (as of day 1)

## A2E Video Strategy
- Duration: ~40 seconds (match the YC format)
- Format: Terminal screencast + animated text overlays (dark theme)
- Audience: Developers building AI agents
- Tone: Clear, technical, confident

## Color Palette (Dark tech theme)
```
BG         = "#0D1117"  (GitHub dark)
TERMINAL   = "#1C2128"  (terminal background)
GREEN      = "#3FB950"  (success/output)
BLUE       = "#58A6FF"  (primary brand)
PURPLE     = "#BC8CFF"  (accent: protocol layer)
ORANGE     = "#D29922"  (accent: runtime layer)
WHITE      = "#E6EDF3"  (primary text)
GRAY       = "#8B949E"  (secondary text)
```

## Scene Breakdown

### Scene 1: Title / Hook (0:00 - 0:06)
**Visual:** Terminal window, cursor blinking. Text types out:
```
$ what is A2E?
Agent-to-Environment Protocol
The open protocol for agent-environment interaction
```
**Animation:** Typewriter effect, 1.5s per line.
**Voiceover/Text subtitle:** "A2E is the open protocol for agent-environment interaction."

---

### Scene 2: The Problem (0:06 - 0:13)
**Visual:** Split screen
- Left: Terminal shows frameworks creating tools/memory each time
- Right: Animated icons for LangChain, CrewAI, AutoGPT each building their own tool system
**Text overlay:** "Every agent framework reinvents the same primitives"
**Animation:** Each framework icon appears with a Build/Reinvent label.
**Voiceover/Text subtitle:** "Every agent framework reinvents tools, memory, processes — from scratch."

---

### Scene 3: The Solution - 10 Capabilities (0:13 - 0:21)
**Visual:** 10 small boxes arranged in 2 rows of 5, appearing one by one:
```
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│  tools │ │ memory │ │  env   │ │  proc  │ │ learn  │
├────────┤ ├────────┤ ├────────┤ ├────────┤ ├────────┤
│ skills ││toolkits││ chains ││  mcp   ││subagents│
└────────┘ └────────┘ └────────┘ └────────┘ └────────┘
```
**Animation:** Boxes fill in left-to-right, top-to-bottom with a pivot animation.
**Text overlay at bottom:** "tools · memory · env · proc · learn · skills · toolkits · chains · mcp · subagents"
**Voiceover/Text subtitle:** "Ten capability namespaces. One protocol."

---

### Scene 4: Terminal Demo — How It Works (0:21 - 0:30)
**Visual:** Terminal window with code typing out:
```bash
# Install
$ pip install a2e

# Start a server (4 lines)
$ cat config.yaml
host_id: "a2e-demo"
server:
  host: "0.0.0.0"
  port: 8765

$ python -m a2e.server config.yaml
```
Then client connecting:
```bash
$ python
>>> from a2e import A2EClient
>>> client = A2EClient(...)
>>> client.call("tools", {"name": "read_file", "params": {"path": "/etc/hostname"}})
{"result": "a2e-host"}
```
**Animation:** Terminal output rendered with green text on dark background.
**Voiceover/Text subtitle:** "Install, configure, connect. Five lines to a running environment."

---

### Scene 5: MCP Bridge (0:30 - 0:34)
**Visual:** Two nodes connected:
```
[MCP Servers] ←→ [A2E MCPPlugin] ←→ [A2E Client/Agent]
```
**Text:** "Native MCP bridge — use any MCP server as an A2E tool"
**Animation:** Data flows from MCP server through A2E to agent.
**Voiceover/Text subtitle:** "Native MCP bridge. Every MCP server becomes an A2E tool."

---

### Scene 6: Call to Action (0:34 - 0:40)
**Visual:** Clean centered text:
```
A2E Protocol
━━━━━━━━━━━━━━━━━━━━
Open source · MIT License

pip install a2e
github.com/a2eprotocol/python-sdk
```
**Animation:** Text fades in with slight upward drift.
**Voiceover/Text subtitle:** "A2E — open source, MIT. Install it and build."

---

## Total: ~40 seconds

## Production Approach

We'll use Manim CE to create this as an animated video. The terminal scenes will use Manim's Code/CairoText for monospace rendering.

### Script file: `a2e_launch_video.py`
### Render: `manim -qh a2e_launch_video.py Scene1_Title Scene2_Problem ...`
### Stitch: ffmpeg concat