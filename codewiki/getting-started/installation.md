# Installation

The A2E SDK requires Python 3.10+ and a handful of lightweight dependencies — Pydantic v2 for schema validation, FastAPI+Uvicorn for the HTTP transport. This page covers both pip and uv workflows.

## Requirements

- **Python 3.10+** (uses `match` statements, `type` union syntax)
- **pip** or **[uv](https://docs.astral.sh/uv/)** package manager

## Install from PyPI

### With pip
```bash
pip install a2e
```

### With uv
```bash
uv pip install a2e
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

### With pip
```bash
git clone https://github.com/a2eprotocol/python-sdk.git
cd python-sdk
pip install -e .
```

For development:

```bash
pip install -e ".[dev]"
```

### With uv (recommended for development)

```bash
git clone https://github.com/a2eprotocol/python-sdk.git
cd python-sdk
uv sync
```

`uv sync` reads `pyproject.toml` directly and creates a virtual environment with the exact dependency versions. It is the fastest way to get a reproducible development environment.

For development extras:

```bash
uv sync --dev
```

### Lockfile

When using uv, a `uv.lock` file can be generated for deterministic installs:

```bash
uv lock
```

This produces a cross-platform lockfile that pins every transitive dependency. Commit it to version control for reproducible builds.


## Verify Installation

```bash
python -c "import a2e; print(a2e.__version__)"   # Should print version
python -c "from a2e.schema import A2EHostConfig; print('OK')"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: No module named 'a2e'` | Run `pip install -e .` or `uv sync` from repo root |
| `pydantic.ValidationError` on import | Ensure pydantic v2: `pip install pydantic>=2.0` |
| Port 8765 already in use | Change `server.port` in your config YAML |
| `ImportError: fastmcp` | Run `pip install fastmcp mcp` |
