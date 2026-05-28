# Chains

```text
a2e/caps/chains/protocol.py — MessageType, ChainNode, ChainRequest
a2e/caps/chains/plugin.py   — ChainPlugin (concrete DAG executor)
a2e/caps/chains/client.py   — ChainsAPI
```

## Overview

Chains enable **DAG (Directed Acyclic Graph) pipeline execution** — multi-step compositions of tools, skills, and processes with branching, parallel fan-out, and error handling.

## Protocol Messages (3 types)

| Type String | Model | Direction |
|-------------|-------|-----------|
| `chain/req` | `ChainRequest` | Agent → Host |
| `chain/resp` | `ChainResponse` | Host → Agent |
| `chain/event` | `ChainEvent` | Host → Agent (streaming) |

### ChainNode

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | `str` | Unique node identifier |
| `kind` | `str` | `skill`, `tool`, `branch`, or `map` |
| `name` | `str` | Skill/tool/proc name to invoke |
| `input` | `dict` | Static input |
| `input_map` | `dict` | JMESPath expressions to resolve from prior outputs |
| `condition` | `str` | Boolean expression for branch nodes |
| `true_node` | `str` | Next node if condition is true |
| `false_node` | `str` | Next node if condition is false |
| `items_path` | `str` | JMESPath to array for map fan-out |
| `map_node` | `str` | Node to run for each item |
| `next_node` | `str` | Default next node |
| `on_error` | `str` | `abort`, `skip`, or a node_id to jump to |
| `deps` | `list[str]` | Dependency node IDs |

### ChainRequest

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Session identifier |
| `chain_id` | `str` | Chain identifier |
| `nodes` | `list[ChainNode]` | All nodes in the DAG |
| `entry_node` | `str` | Starting node ID |
| `initial_input` | `dict` | Input to the chain |
| `correlation_id` | `str` | Correlation ID |
| `streaming` | `bool` | Enable streaming events |
| `timeout` | `float` | Total chain timeout |

### ChainEvent (extends A2EEvent)

| Field | Type | Description |
|-------|------|-------------|
| `node_id` | `str` | Which node |
| `phase` | `str` | `start`, `done`, `skip`, or `error` |
| `output` | `dict` | Node output (on `done`) |
| `error` | `str` | Error message (on `error`) |

### ChainResponse

| Field | Type | Description |
|-------|------|-------------|
| `chain_id` | `str` | Chain identifier |
| `success` | `bool` | All nodes succeeded |
| `outputs` | `dict` | `node_id → output` mapping |
| `final_output` | `dict` | Output of terminal nodes |
| `duration_ms` | `int` | Total execution time |
| `nodes_run` | `int` | Number of nodes executed |
| `error` | `str` | Error if chain failed |

## ChainPlugin (Concrete DAG Executor)

Unlike most plugins, `ChainPlugin` is a **concrete implementation** with a full DAG scheduler:

```python
class ChainPlugin(A2EPlugin):
    name = "chain"
    priority = 10

    def _run_chain(self, req):
        # 1. Build node lookup dict
        # 2. Track completed/running/failed sets
        # 3. Scheduler loop:
        #    a. Find runnable nodes (dependencies met)
        #    b. Spawn threads for each
        #    c. Join all
        #    d. Repeat until no more runnable or all done

    def can_run(self, node):
        # Check if all dependency nodes are completed

    def resolve_input(self, node):
        # Merge static input with dependency outputs via JMESPath

    def run_node(self, node):
        # Dispatch by node.kind:
        #   "tool"  -> _run_tool(name, inp)  via host.tool_registry
        #   "skill" -> _run_skill(name, inp)  via SkillPlugin
        #   "proc"  -> _run_proc(name, inp)   via ProcPlugin
```

**Terminal nodes** are identified as nodes that no other node depends on. Their output becomes `final_output`.

## ChainsAPI (Client)

```python
from a2e.caps.chains.client import ChainsAPI

chains = ChainsAPI(client)

# Define a chain
nodes = [
    {"node_id": "read", "kind": "tool", "name": "read_file",
     "input": {"path": "/data/input.txt"}, "next_node": "analyze"},
    {"node_id": "analyze", "kind": "skill", "name": "analysis",
     "input_map": {"data": "read.data"}, "next_node": "write"},
    {"node_id": "write", "kind": "tool", "name": "write_file",
     "input_map": {"content": "analyze.data", "path": "'/data/output.txt'"}},
]

result = chains.run(
    nodes=nodes,
    entry_node="read",
    initial_input={},
    streaming=True,
    on_event=lambda e: print(f"Node {e.node_id}: {e.phase}"),
    timeout=60.0
)

print(f"Success: {result.success}, Output: {result.final_output}")
print(f"Nodes run: {result.nodes_run} in {result.duration_ms}ms")
```

### ChainResult (Client-Side)

The client wraps the response in a `ChainResult` model that also collects streaming `events` for full observability.
