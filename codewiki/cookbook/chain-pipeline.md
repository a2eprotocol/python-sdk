# Chain Pipeline Example

A complete example of building and running a multi-step chain pipeline.

## Data Processing Chain

```python
import logging
from a2e.schema import A2EHostConfig
from a2e.core.server.server import A2EServer
from a2e.core.client.client import A2EClient
from a2e.caps.chains.client import ChainsAPI

logger = logging.getLogger("chain-agent")

# Setup (direct mode for simplicity)
config = A2EHostConfig.from_yaml("config.yaml")
server = A2EServer(config)
transport = server.start()

client = A2EClient(transport, logger, agent_caps=["chains", "tools", "skills"])
client.connect()

chains = ChainsAPI(client)

# Define a data processing pipeline
nodes = [
    # Step 1: Read input file
    {
        "node_id": "read",
        "kind": "tool",
        "name": "read_file",
        "input": {"path": "/data/raw.json"},
        "next_node": "parse"
    },
    # Step 2: Parse and validate
    {
        "node_id": "parse",
        "kind": "skill",
        "name": "json-parser",
        "input_map": {"raw_data": "read.data"},
        "on_error": "abort",
        "next_node": "transform"
    },
    # Step 3: Transform (branch based on data type)
    {
        "node_id": "transform",
        "kind": "branch",
        "condition": "parse.data_type == 'numeric'",
        "true_node": "numeric_transform",
        "false_node": "text_transform"
    },
    # Branch A: Numeric processing
    {
        "node_id": "numeric_transform",
        "kind": "tool",
        "name": "compute_stats",
        "input_map": {"values": "parse.values"},
        "next_node": "write_output"
    },
    # Branch B: Text processing
    {
        "node_id": "text_transform",
        "kind": "skill",
        "name": "text-summarizer",
        "input_map": {"text": "parse.text"},
        "next_node": "write_output"
    },
    # Step 4: Write results
    {
        "node_id": "write_output",
        "kind": "tool",
        "name": "write_file",
        "input_map": {
            "content": "numeric_transform.stats OR text_transform.summary",
            "path": "'/data/output.json'"
        },
    }
]

# Run with streaming
def on_event(event):
    print(f"[{event.node_id}] {event.phase}: "
          f"{event.output if event.output else event.error or ''}")

result = chains.run(
    nodes=nodes,
    entry_node="read",
    initial_input={},
    streaming=True,
    on_event=on_event,
    timeout=120.0
)

print(f"Chain completed: success={result.success}")
print(f"Nodes run: {result.nodes_run} in {result.duration_ms}ms")
print(f"Final output: {result.final_output}")

client.disconnect()
```

## Map (Fan-Out) Pattern

Process multiple items in parallel:

```python
nodes = [
    # Read list of files
    {
        "node_id": "list_files",
        "kind": "tool",
        "name": "glob",
        "input": {"pattern": "/data/*.json"},
        "next_node": "process_each"
    },
    # Map: process each file
    {
        "node_id": "process_each",
        "kind": "map",
        "items_path": "list_files.files",  # JMESPath to array
        "map_node": "analyze_file",
        "next_node": "aggregate"
    },
    # Per-item processing
    {
        "node_id": "analyze_file",
        "kind": "skill",
        "name": "file-analyzer",
        "input_map": {"file_path": "_item.path"}
    },
    # Aggregate results
    {
        "node_id": "aggregate",
        "kind": "tool",
        "name": "merge_results",
        "input_map": {"results": "process_each"}
    }
]
```

## JMESPath Expressions

`input_map` values use JMESPath to reference outputs from prior nodes:

| Expression | Meaning |
|-----------|---------|
| `"read.data"` | Output of node "read", field "data" |
| `"parse.values"` | Nested field access |
| `"'/fixed/path'"` | Literal string (quoted) |
| `"numeric_transform.stats OR text_transform.summary"` | First non-null |
| `"_item.path"` | Current item in map iteration |