from a2e.caps.memory.client import MemoryAPI


def run_mem(client):
    memory = MemoryAPI(client)

    # ---------------------------------------------------------------
    # 1. INIT — establish a memory session and get back a memory_id
    # ---------------------------------------------------------------
    resp = memory.init(
        namespace="cookbook-demo",
        scope={"agent": "analytics-01", "env": "dev"},
        metadata={"source": "mem_api_example"},
    )
    print(f"Memory session initialized: memory_id={memory.memory_id}")

    # ---------------------------------------------------------------
    # 2. STORE — batch write entries across tiers
    # ---------------------------------------------------------------
    stored, errors = memory.store([
        {
            "key": {"user_id": "foo", "index": "1"},
            "content": {"text": "user prefers python"},
            "tags": ["preference"],
            "tier": "semantic",
        },
        {
            "key": {"user_id": "bar", "index": "1"},
            "content": {"step": "opened file"},
            "tags": ["trace"],
            "tier": "episodic",
        },
        {
            "key": {"user_id": "bar", "index": "1"},
            "content": {"current_file": "/tmp/test.py"},
            "tier": "working",
        },
    ])
    print(f"Stored: {len(stored)} entries, Errors: {len(errors)}")

    # ---------------------------------------------------------------
    # 3. RETRIEVE — tag-based search across tiers
    # ---------------------------------------------------------------
    entries = memory.retrieve(
        tags=["preference"],
        tier="semantic",
        limit=5,
    )

    for e in entries:
        print(e.content)

    # ---------------------------------------------------------------
    # 4. RETRIEVE — all working memory
    # ---------------------------------------------------------------
    working = memory.retrieve(tier="working")
    print(f"Working memory count: {len(working)}")

    # ---------------------------------------------------------------
    # 5. FORGET — bulk delete by tag + tier
    # ---------------------------------------------------------------
    deleted = memory.forget(tags=["trace"], tier="episodic")
    print(f"Deleted {deleted} trace entries")