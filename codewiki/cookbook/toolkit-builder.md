# Toolkit Builder Plugin & Client Example

## Overview

Toolkits are **bundled collections of tools** with shared configuration and schemas. While tools are individual stateless operations, toolkits group related tools together and provide a configuration interface (e.g., credentials, API keys, root directories). This cookbook covers:

1. **Plugin side**: Writing a custom `ToolkitPlugin` that registers a toolkit with its tool manifest and configuration schema
2. **Client side**: Listing toolkits, configuring them, and using their tools

## Plugin Side: Database Toolkit Plugin

Below is a complete toolkit plugin that provides a PostgreSQL database toolkit with connection configuration and bundled query tools:

```python
import json
import psycopg2
import psycopg2.extras

from a2e.caps.toolkits.plugin import ToolkitPlugin
from a2e.caps.toolkits.protocol import (
    ToolkitDefinition,
    ToolkitListResponse,
    ToolkitConfigureResponse,
)
from a2e.caps.tools.protocol import (
    ToolDefinition, ToolParameter,
    ToolListResponse, ToolCallResponse,
    ToolResult,
)

class DatabaseToolkitPlugin(ToolkitPlugin):
    """PostgreSQL database toolkit — handles config + discovery only."""

    name = "db_toolkit"

    def __init__(self, host_instance, config):
        super().__init__(host_instance, config)
        self._connections = {}
        self._configured = {}
        self._db_config = {}

        # Define the toolkit
        self._toolkits = {
            "postgres": ToolkitDefinition(
                name="postgres",
                alias="pg",
                description="PostgreSQL database toolkit — query, insert, update, and schema inspection",
                category="database",
                tags=["database", "sql", "postgres", "persistence"],
                icon_svg=None,
                schema={
                    "type": "object",
                    "properties": {
                        "host": {
                            "type": "string",
                            "description": "PostgreSQL server hostname",
                            "default": "localhost",
                        },
                        "port": {
                            "type": "integer",
                            "description": "PostgreSQL server port",
                            "default": 5432,
                        },
                        "database": {
                            "type": "string",
                            "description": "Database name",
                        },
                        "username": {
                            "type": "string",
                            "description": "Database username",
                        },
                        "password": {
                            "type": "string",
                            "description": "Database password",
                        },
                        "ssl_mode": {
                            "type": "string",
                            "description": "SSL mode: disable, require, verify-ca, verify-full",
                            "enum": ["disable", "require", "verify-ca", "verify-full"],
                            "default": "require",
                        },
                        "max_rows": {
                            "type": "integer",
                            "description": "Maximum rows returned per query",
                            "default": 1000,
                        },
                    },
                    "required": ["host", "database", "username", "password"],
                },
                tools=[
                    "db_query",
                    "db_execute",
                    "db_list_tables",
                    "db_describe_table",
                ],
                configured=False,
                version="1.0.0",
            ),
        }

        # Define the tools inside this toolkit
        self._tool_defs = [
            ToolDefinition(
                name="db_query",
                description="Execute a SELECT query and return results as JSON",
                input_parameters=[
                    ToolParameter(name="sql", type="string", description="SQL SELECT query", required=True),
                    ToolParameter(name="params", type="array", description="Query parameters for parameterized queries", required=False),
                ],
                output_parameters=[
                    ToolParameter(name="rows", type="array", description="Query result rows"),
                    ToolParameter(name="row_count", type="integer", description="Number of rows returned"),
                ],
                streaming=False,
                idempotent=True,
                tags=["database", "sql", "read"],
                version="1.0.0",
                toolkit="postgres",
            ),
            ToolDefinition(
                name="db_execute",
                description="Execute an INSERT/UPDATE/DELETE and return affected row count",
                input_parameters=[
                    ToolParameter(name="sql", type="string", description="SQL statement (INSERT/UPDATE/DELETE)", required=True),
                    ToolParameter(name="params", type="array", description="Query parameters", required=False),
                ],
                output_parameters=[
                    ToolParameter(name="affected", type="integer", description="Number of affected rows"),
                ],
                streaming=False,
                idempotent=False,
                tags=["database", "sql", "write"],
                version="1.0.0",
                toolkit="postgres",
            ),
            ToolDefinition(
                name="db_list_tables",
                description="List all tables in the connected database",
                input_parameters=[],
                output_parameters=[
                    ToolParameter(name="tables", type="array", description="List of table names"),
                ],
                streaming=False,
                idempotent=True,
                tags=["database", "schema", "read"],
                version="1.0.0",
                toolkit="postgres",
            ),
            ToolDefinition(
                name="db_describe_table",
                description="Get column definitions for a specific table",
                input_parameters=[
                    ToolParameter(name="table_name", type="string", description="Table to describe", required=True),
                ],
                output_parameters=[
                    ToolParameter(name="columns", type="array", description="Column definitions"),
                ],
                streaming=False,
                idempotent=True,
                tags=["database", "schema", "read"],
                version="1.0.0",
                toolkit="postgres",
            ),
        ]

    # --- ToolkitPlugin abstract hooks ---
    # (supported_messages() and handle() are provided by the base class)

    def _list_toolkits(self, msg) -> ToolkitListResponse:
        """Return toolkit definitions with current configured status."""
        toolkits = []
        for name, tk in self._toolkits.items():
            # Clone with updated configured status
            updated = tk.model_copy(update={
                "configured": self._configured.get(name, False),
            })
            toolkits.append(updated)
        return ToolkitListResponse(toolkits=toolkits)

    def _configure_toolkit(self, msg) -> ToolkitConfigureResponse:
        """Validate config against schema and establish DB connection."""
        toolkit_name = msg.toolkit_name
        config = msg.config

        if toolkit_name not in self._toolkits:
            return ToolkitConfigureResponse(
                toolkit_name=toolkit_name,
                status="error",
                message=f"Unknown toolkit: {toolkit_name}",
            )

        # Validate required fields from schema
        schema = self._toolkits[toolkit_name].schema
        required = schema.get("required", [])
        missing = [f for f in required if f not in config or not config[f]]
        if missing:
            return ToolkitConfigureResponse(
                toolkit_name=toolkit_name,
                status="error",
                message=f"Missing required fields: {', '.join(missing)}",
            )

        # Validate enum fields
        properties = schema.get("properties", {})
        for field, value in config.items():
            prop = properties.get(field, {})
            if "enum" in prop and value not in prop["enum"]:
                return ToolkitConfigureResponse(
                    toolkit_name=toolkit_name,
                    status="error",
                    message=f"Invalid value for '{field}': {value}. Allowed: {prop['enum']}",
                )

        # Try to connect
        try:
            conn = psycopg2.connect(
                host=config["host"],
                port=config.get("port", 5432),
                dbname=config["database"],
                user=config["username"],
                password=config["password"],
                sslmode=config.get("ssl_mode", "require"),
            )
            conn.autocommit = True

            # Store connection
            self._connections[msg.session_id] = conn
            self._configured[toolkit_name] = True

            # Save config for tool execution (minus password)
            self._db_config = {
                k: v for k, v in config.items()
                if k != "password"
            }
            self._max_rows = config.get("max_rows", 1000)

            return ToolkitConfigureResponse(
                toolkit_name=toolkit_name,
                status="ok",
                message="Database toolkit configured and connected successfully",
            )

        except psycopg2.Error as exc:
            return ToolkitConfigureResponse(
                toolkit_name=toolkit_name,
                status="error",
                message=f"Connection failed: {exc}",
            )

    # --- Lifecycle ---

    def teardown(self):
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

    # --- State persistence ---

    def save_state(self, store, key, session_id):
        # Save configuration (not password), not live connections
        if hasattr(self, "_db_config"):
            store.save(f"{self.name}:{key}", {
                "config": self._db_config,
                "configured": self._configured,
            })

    def restore_state(self, store, key, session_id):
        state = store.load(f"{self.name}:{key}")
        if state:
            self._configured = state.get("configured", {})

    def clear_state(self, store, key, session_id):
        self.teardown()
        self._configured = {}
        store.clear(f"{self.name}:{key}")
```

### Register in Config

```yaml
plugins:
  - name: db_toolkit
    type: toolkits
    cls: my_package.db_toolkit.DatabaseToolkitPlugin
    metadata:
      enabled: true
      priority: 5

  - name: db_tools
    type: tools
    cls: my_package.db_toolkit.DatabaseToolsPlugin
    metadata:
      enabled: true
      priority: 5
```

## Client Side: Toolkit Discovery and Usage

```python
import logging
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.toolkits.client import ToolkitAPI
from a2e.caps.tools.client import ToolAPI

logger = logging.getLogger("toolkit-agent")

config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["toolkits", "tools"])
client.connect()

toolkits = ToolkitAPI(client)
tools = ToolAPI(client)

# ============================================================
# 1. List available toolkits
# ============================================================

kit_list = toolkits.list()
for kit in kit_list:
    status = "configured" if kit.configured else "not configured"
    print(f"  {kit.name} (v{kit.version}) [{status}]: {kit.description}")
    print(f"    Category: {kit.category}, Tags: {kit.tags}")
    print(f"    Tools: {kit.tools}")
    print(f"    Schema: {json.dumps(kit.schema, indent=2)}")

# Find a specific toolkit by name
pg = toolkits.get("postgres")
if pg:
    print(f"Found: {pg.name} — {pg.description}")
    print(f"Required config fields: {pg.schema.get('required', [])}")

# ============================================================
# 2. Configure a toolkit
# ============================================================

# Full configuration with all required fields
resp = toolkits.configure("postgres", {
    "host": "db.example.com",
    "port": 5432,
    "database": "analytics",
    "username": "agent_user",
    "password": "secret123",
    "ssl_mode": "require",
    "max_rows": 500,
})

print(f"Configure status: {resp.status}")
if resp.status == "ok":
    print(f"Message: {resp.message}")
else:
    print(f"Error: {resp.message}")
    # Example error: "Missing required fields: username, password"

# ============================================================
# 3. Idempotent configuration
# ============================================================

# ensure() only configures if not already configured — safe to call repeatedly
resp = toolkits.ensure("postgres", {
    "host": "db.example.com",
    "database": "analytics",
    "username": "agent_user",
    "password": "secret123",
})
# First call: configures and connects
# Second call: skips (already configured)

# ============================================================
# 4. Use toolkit tools after configuration
# ============================================================

# Once configured, the toolkit's tools appear in tool/list
tool_list = tools.list()
pg_tools = [t for t in tool_list if t.toolkit == "postgres"]
print(f"PostgreSQL tools: {[t.name for t in pg_tools]}")

# List tables
result = tools.call("db_list_tables", {})
if result.success:
    for table in result.data["tables"]:
        print(f"  Table: {table}")

# Describe a table
result = tools.call("db_describe_table", {"table_name": "users"})
if result.success:
    for col in result.data["columns"]:
        print(f"  {col['column_name']}: {col['data_type']} "
              f"({'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'})")

# Run a query
result = tools.call("db_query", {
    "sql": "SELECT id, name, email FROM users WHERE active = %s LIMIT 10",
    "params": [True],
})
if result.success:
    print(f"Rows: {result.data['row_count']}")
    for row in result.data["rows"]:
        print(f"  {row['id']}: {row['name']} <{row['email']}>")

# Execute a mutation
result = tools.call("db_execute", {
    "sql": "UPDATE users SET last_login = NOW() WHERE id = %s",
    "params": [42],
})
if result.success:
    print(f"Affected rows: {result.data['affected']}")

# ============================================================
# 5. Error handling
# ============================================================

# Configure with invalid credentials
resp = toolkits.configure("postgres", {
    "host": "db.example.com",
    "database": "analytics",
    "username": "wrong_user",
    "password": "wrong_pass",
})
# resp.status == "error", resp.message contains connection error

# Try to use tools without configuring
# (Requires a fresh session where toolkit is not configured)
result = tools.call("db_query", {"sql": "SELECT 1"})
# result.success == False, result.error == "Database not configured"

# Query with invalid SQL
result = tools.call("db_query", {"sql": "SELECTT * FROM users"})
# result.success == False, result.error contains syntax error

# ============================================================
# 6. Schema-driven client-side validation
# ============================================================

# Use toolkit.schema to validate config before sending
pg = toolkits.get("postgres")
required_fields = pg.schema.get("required", [])
properties = pg.schema.get("properties", {})

config_candidate = {
    "host": "db.example.com",
    "database": "analytics",
    # Oops, forgot username and password
}

# Client-side validation
missing = [f for f in required_fields if f not in config_candidate]
if missing:
    print(f"Cannot configure: missing {missing}")
    # Don't send the request — fix config first

# Validate enum fields
for field, value in config_candidate.items():
    prop = properties.get(field, {})
    if "enum" in prop and value not in prop["enum"]:
        print(f"Invalid '{field}': {value}. Allowed: {prop['enum']}")

# ============================================================
# 7. Filtering toolkits by tags and category
# ============================================================

# List all database toolkits
db_kits = toolkits.list(filter_tags=["database"])
for kit in db_kits:
    print(f"Database toolkit: {kit.name}")

client.disconnect()
```

## Schema Design Patterns

The `schema` field on `ToolkitDefinition` is a standard JSON Schema object. Common patterns:

### Simple key-value config

```python
schema = {
    "type": "object",
    "properties": {
        "api_key": {"type": "string", "description": "API key"},
        "base_url": {"type": "string", "description": "API base URL", "default": "https://api.example.com"},
    },
    "required": ["api_key"],
}
```

### Enum-based configuration

```python
schema = {
    "type": "object",
    "properties": {
        "region": {
            "type": "string",
            "description": "Cloud region",
            "enum": ["us-east-1", "eu-west-1", "ap-south-1"],
        },
        "tier": {
            "type": "string",
            "description": "Service tier",
            "enum": ["free", "pro", "enterprise"],
            "default": "free",
        },
    },
    "required": ["region"],
}
```

### Nested configuration

```python
schema = {
    "type": "object",
    "properties": {
        "connection": {
            "type": "object",
            "description": "Connection settings",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "default": 443},
            },
            "required": ["host"],
        },
        "auth": {
            "type": "object",
            "description": "Authentication settings",
            "properties": {
                "type": {"type": "string", "enum": ["api_key", "oauth", "basic"]},
                "token": {"type": "string"},
            },
            "required": ["type", "token"],
        },
    },
    "required": ["connection", "auth"],
}
```

## Relationship to Other Capabilities

```
ToolkitPlugin                    ToolPlugin
     |                               |
     v                               v
ToolkitDefinition               ToolDefinition
  - name: "postgres"              - name: "db_query"
  - tools: ["db_query", ...]      - toolkit: "postgres"
  - schema: { JSON Schema }      - input_parameters: [...]
                                   - output_parameters: [...]
                                          |
                                          v
                                    ToolkitAPI (client)     ToolAPI (client)
                                     - list()                - list()
                                     - configure()            - call()
                                     - ensure()               - call()
                                     - get()
```

- **Toolkits → Tools**: Once a toolkit is configured, its tools appear in `tool/list/resp` with the `toolkit` field set.
- **MCP**: MCP server tools are registered as plain tools (not toolkits), since MCP manages its own configuration.
- **Skills**: Skills may reference toolkits in their `toolkits` field to declare dependencies.
- **Memory**: Toolkit configuration can be persisted via `save_state` / `restore_state`.

## Key Patterns

| Pattern | When to Use |
|---------|-------------|
| `toolkits.list()` | Discover available toolkits |
| `toolkits.get(name)` | Look up a specific toolkit |
| `toolkits.configure(name, config)` | Initialize a toolkit with credentials |
| `toolkits.ensure(name, config)` | Idempotent configure (skip if already done) |
| `tools.call(toolkit_tool, args)` | Use toolkit tools after configuration |
| Validate config against `schema` | Client-side validation before sending |

## Tips

- **Validate config early**: Use `schema.required` and `schema.properties.enum` on the client side to catch errors before network round-trips.
- **Mark configured = False on startup**: The plugin should report `configured=False` until `toolkit/configure/req` succeeds.
- **Don't store passwords in state**: `save_state` should persist config minus secrets; re-authenticate on `restore_state`.
- **Use ensure() for idempotent setup**: Prevents duplicate configuration calls in agent loops.
- **Set max_rows / rate limits**: Prevent runaway queries from exhausting resources.
- **Schema drives UI**: The JSON Schema in `ToolkitDefinition.schema` is designed for client-side form generation — use `description`, `default`, and `enum` to provide rich metadata.
