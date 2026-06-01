# Installation

The A2E SDK requires Python 3.10+ and a handful of lightweight dependencies — Pydantic v2 for schema validation, FastAPI+Uvicorn for the HTTP transport, and aiofiles for async file I/O. Choose your environment: pip for standard deployments, poetry or uv for locked dependency management, or conda for teams already using it.

## Requirements

- **Python 3.10+** (uses `match` statements, `type` union syntax)
- **pip** package manager

## Install from PyPI

```bash
pip install a2e
```

## Core Dependencies

The `a2e` package depends on:

| Package | Version | Purpose |
|---------|---------|---------|
| `pydantic` | 2.12.5 | Data validation, schemas, serialization |
| `fastmcp` | 3.2.0 | MCP server/client integration |
| `mcp` | 1.27.0 | Model Context Protocol types |
| `fastapi` | 0.135.3 | HTTP server framework |
| `uvicorn` | latest | ASGI server |
| `pyyaml` | latest | YAML config parsing |

## Optional Dependencies

```bash
# For SQLite persistence (included in stdlib)
pip install a2e              # SQLite support built-in

# For cookbook HTTP tools
pip install requests

# For LLM-powered agents
pip install anthropic         # Claude Sonnet (agent.py)
pip install openai            # OpenAI/OpenRouter (deep_agent.py)
pip install langchain-openai # LangChain integration (deep_agent.py)
```

## Install from Source

```bash
git clone https://github.com/cynepiaadmin/a2e.git
cd a2e
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

## Verify Installation

```bash
python -c "import a2e; print(a2e.__version__)"   # Should print version
python -c "from a2e.schema import A2EHostConfig; print('OK')"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: No module named 'a2e'` | Run `pip install -e .` from repo root |
| `pydantic.ValidationError` on import | Ensure pydantic v2: `pip install pydantic>=2.0` |
| Port 8765 already in use | Change `server.port` in your config YAML |
| `ImportError: fastmcp` | Run `pip install fastmcp mcp` |
