"""Regression tests for the env DATA PLANE (env/data/{reset,add,get}).

The data plane is ORTHOGONAL to the episode lifecycle: reset_data restores the
data root to pristine, add_data stages task data, get_data reads results back,
and none of them disturb (or are disturbed by) env/reset.

Payloads carry METADATA ONLY — bytes never cross the protocol, which is what
makes multi-GB corpora viable.
"""
import json
import os
import shutil
import tempfile
import hashlib

import pytest

from a2e.caps.env.plugin import EnvPlugin
from a2e.caps.env.protocol import (
    DEFAULT_DATA_ROOT,
    EnvDataAddRequest,
    EnvDataGetRequest,
    EnvDataPart,
    EnvDataResetRequest,
    EnvObservation,
    EnvState,
)
from a2e.caps.base.protocol import A2EError


class DataEnv(EnvPlugin):
    """Env with a real filesystem data plane and a pristine baseline."""

    name = "env"
    type = "env"

    def __init__(self, host_instance=None, config=None):
        super().__init__(host_instance, config or {})
        self.baseline = (config or {}).get("baseline", [])
        self.seen_roots = []

    # episode hooks
    def on_reset(self, seed=None, options=None):
        return EnvState(count=0, step_num=0, seed=seed or 0)

    def on_step(self, episode_id, action):
        ep = self._require_episode()
        prev = ep.state.model_dump()
        n = int(prev.get("count", 0)) + 1
        return EnvObservation(
            episode_id=episode_id, step_num=n,
            state=EnvState(count=n, step_num=n), reward=0.0, done=n >= 3,
        )

    # data plane
    def _root(self, data_root):
        r = data_root or DEFAULT_DATA_ROOT
        os.makedirs(r, exist_ok=True)
        self.seen_roots.append(r)
        return r

    def on_data_reset(self, scope="all", data_root=DEFAULT_DATA_ROOT):
        r = self._root(data_root)
        if os.path.isdir(r):
            shutil.rmtree(r)
        os.makedirs(r, exist_ok=True)
        restored = 0
        for src, name in self.baseline:
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(r, name))
                restored += 1
        return {"restored": restored, "data_root": r, "detail": "pristine"}

    def on_data_add(self, parts, data_root=DEFAULT_DATA_ROOT):
        r = self._root(data_root)
        added, errors, staged = 0, [], []
        for p in parts:
            src, dest = p.get("src", ""), p.get("dest", "")
            target = os.path.join(r, dest or os.path.basename(src))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(src, target)
                digest = hashlib.sha256(open(target, "rb").read()).hexdigest()
                want = (p.get("checksum") or "").replace("sha256:", "")
                if want and digest != want:
                    os.remove(target)
                    errors.append(f"checksum mismatch: {dest}")
                    continue
                added += 1
                staged.append({"uri": p.get("uri", ""), "dest": dest,
                               "size_bytes": os.path.getsize(target)})
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"{dest}: {exc}")
        return {"added": added, "errors": errors, "staged": staged, "data_root": r}

    def on_data_get(self, query="", include_content=False, max_bytes=1_048_576,
                    data_root=DEFAULT_DATA_ROOT):
        r = data_root or DEFAULT_DATA_ROOT
        items = []
        if not os.path.isdir(r):
            return items
        for dirpath, _, files in os.walk(r):
            for fn in files:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, r)
                if query and query not in rel:
                    continue
                size = os.path.getsize(full)
                item = {"uri": rel, "dest": rel, "size_bytes": size}
                if include_content and size <= max_bytes:
                    item["content"] = open(full).read()
                items.append(item)
        return items


@pytest.fixture
def root():
    d = tempfile.mkdtemp(prefix="a2e-data-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def stage():
    d = tempfile.mkdtemp(prefix="a2e-stage-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def env(stage, root):
    base = os.path.join(stage, "baseline.txt")
    with open(base, "w") as fh:
        fh.write("PRISTINE-BASELINE\n")
    return DataEnv(None, {"baseline": [[base, "baseline.txt"]]})


def _src(stage, name, body):
    p = os.path.join(stage, name)
    with open(p, "w") as fh:
        fh.write(body)
    return p, hashlib.sha256(body.encode()).hexdigest()


# ── default hooks must not break existing subclasses ──────────────────────

def test_default_data_hooks_are_safe_noops():
    """A subclass that overrides only on_reset/on_step still works."""
    from a2e.caps.env.protocol import EnvResetRequest

    class Minimal(EnvPlugin):
        name = "env"
        type = "env"

        def on_reset(self, seed=None, options=None):
            return EnvState(count=0)

        def on_step(self, episode_id, action):  # pragma: no cover - unused
            raise NotImplementedError

    m = Minimal(None, {})
    assert m.on_data_reset()["restored"] == 0
    assert m.on_data_add([{"src": "x"}])["added"] == 0
    assert m.on_data_get() == []
    # env/reset still works without opting into the data plane
    assert m.reset(seed=1).episode_id


# ── reset_data: restore to PRISTINE (not purge-to-empty) ───────────────────

def test_data_reset_restores_pristine_not_empty(env, stage, root):
    env.handle(EnvDataResetRequest(data_root=root))          # establish pristine
    src, _ = _src(stage, "junk.txt", "task-A leftovers\n")
    env.on_data_add([{"src": src, "dest": "junk.txt"}], data_root=root)
    assert sorted(i["uri"] for i in env.on_data_get(data_root=root)) == \
        ["baseline.txt", "junk.txt"]

    resp = env.handle(EnvDataResetRequest(data_root=root))
    assert resp.ok is True
    assert resp.restored == 1
    # pristine means the baseline came back, and task-A's leftovers are gone
    assert sorted(i["uri"] for i in env.on_data_get(data_root=root)) == ["baseline.txt"]


def test_data_reset_does_not_disturb_the_episode(env, root):
    obs = env.reset(seed=7)
    env.handle(EnvDataResetRequest(data_root=root))
    assert env._episode is not None
    assert env._episode.id == obs.episode_id


# ── add_data: stage task data, verify checksums ───────────────────────────

def test_data_add_stages_and_echoes(env, stage, root):
    env.handle(EnvDataResetRequest(data_root=root))          # establish pristine
    src, digest = _src(stage, "orders.csv", "id,amount\n1,A\n")
    resp = env.handle(EnvDataAddRequest(
        parts=[EnvDataPart(src=src, dest="orders", uri="orders",
                           checksum=f"sha256:{digest}")],
        data_root=root))
    assert resp.ok and resp.added == 1 and not resp.errors
    assert resp.staged[0]["dest"] == "orders"
    assert [i["uri"] for i in env.on_data_get(data_root=root)] == ["baseline.txt", "orders"]


def test_data_add_rejects_checksum_mismatch_and_removes_the_file(env, stage, root):
    src, _ = _src(stage, "corrupt.csv", "tampered\n")
    resp = env.handle(EnvDataAddRequest(
        parts=[EnvDataPart(src=src, dest="corrupt.csv",
                           checksum="sha256:" + "0" * 64)],
        data_root=root))
    assert resp.ok is False
    assert resp.added == 0
    assert any("checksum mismatch" in e for e in resp.errors)
    assert "corrupt.csv" not in [i["uri"] for i in env.on_data_get(data_root=root)]


def test_data_add_partial_failure_is_per_part_not_fatal(env, stage, root):
    good, digest = _src(stage, "ok.txt", "fine\n")
    resp = env.handle(EnvDataAddRequest(parts=[
        EnvDataPart(src=good, dest="ok.txt", checksum=f"sha256:{digest}"),
        EnvDataPart(src=os.path.join(stage, "does-not-exist"), dest="missing.txt"),
    ], data_root=root))
    assert resp.added == 1
    assert len(resp.errors) == 1


def test_data_add_carries_no_bytes_on_the_wire(env, stage, root):
    """The payload is metadata only — the multi-GB guarantee."""
    src, _ = _src(stage, "big.bin", "x" * 4096)
    req = EnvDataAddRequest(parts=[EnvDataPart(src=src, dest="big.bin")])
    wire = req.model_dump_json()
    assert len(wire) < 1024          # metadata only
    assert "x" * 100 not in wire      # no file content


# ── get_data: read results back out ──────────────────────────────────────

def test_data_get_lists_metadata_without_content_by_default(env, stage, root):
    env.handle(EnvDataResetRequest(data_root=root))          # establish pristine
    src, _ = _src(stage, "out.txt", "agent output\n")
    env.on_data_add([{"src": src, "dest": "out.txt"}], data_root=root)
    resp = env.handle(EnvDataGetRequest(data_root=root))
    assert resp.ok and {i["uri"] for i in resp.items} == {"baseline.txt", "out.txt"}
    assert all("content" not in i for i in resp.items)


def test_data_get_inlines_small_content_when_asked(env, stage, root):
    src, _ = _src(stage, "small.txt", "tiny\n")
    env.on_data_add([{"src": src, "dest": "small.txt"}], data_root=root)
    resp = env.handle(EnvDataGetRequest(data_root=root, include_content=True,
                                        max_bytes=4096))
    got = {i["uri"]: i.get("content") for i in resp.items}
    assert got["small.txt"] == "tiny\n"


def test_data_get_query_filters(env, stage, root):
    src, _ = _src(stage, "report.md", "# report\n")
    env.on_data_add([{"src": src, "dest": "report.md"}], data_root=root)
    resp = env.handle(EnvDataGetRequest(data_root=root, query="report"))
    assert [i["uri"] for i in resp.items] == ["report.md"]


# ── per-task cycle, the flow this API exists for ─────────────────────────

def test_two_tasks_on_one_base_env_do_not_share_data(env, stage, root):
    """data_reset between tasks restores pristine; task B never sees task A."""
    seen = {}
    for task in ("task-A", "task-B"):
        env.handle(EnvDataResetRequest(data_root=root))
        src, digest = _src(stage, f"{task}.csv", f"id\n{task}\n")
        env.handle(EnvDataAddRequest(
            parts=[EnvDataPart(src=src, dest=f"{task}.csv",
                               checksum=f"sha256:{digest}")], data_root=root))
        env.reset(seed=1)                      # episode; must not touch data
        seen[task] = sorted(i["uri"] for i in env.on_data_get(data_root=root))

    assert seen["task-A"] == ["baseline.txt", "task-A.csv"]
    assert seen["task-B"] == ["baseline.txt", "task-B.csv"]
    assert "task-A.csv" not in seen["task-B"]


# ── protocol hygiene ─────────────────────────────────────────────────────

def test_every_data_response_carries_req_id():
    """G3/G4: without req_id the client RPC can never resolve."""
    from a2e.caps.env.protocol import (
        EnvDataAddResponse, EnvDataGetResponse, EnvDataResetResponse,
    )
    for model in (EnvDataResetResponse, EnvDataAddResponse, EnvDataGetResponse):
        assert "req_id" in model.model_fields
        assert model().req_id == ""


def test_data_messages_are_registered_in_env_type_map():
    """G4: both request AND response types must decode on the client."""
    from a2e.caps.env.protocol import ENV_TYPE_MAP
    wires = {getattr(k, "value", k) for k in ENV_TYPE_MAP}
    for w in ("env/data/reset/req", "env/data/reset/resp",
              "env/data/add/req", "env/data/add/resp",
              "env/data/get/req", "env/data/get/resp"):
        assert w in wires, w


def test_data_reset_returns_a_response_not_none(env, root):
    """Regression: a `finally: return` on a never-assigned response yields
    None -> the executor sends nothing -> client-side silent RPC hang."""
    resp = env.handle(EnvDataResetRequest(data_root=root))
    assert resp is not None
    assert not isinstance(resp, A2EError)


def test_data_hooks_returning_a_dict_of_pydantics_still_serialize(env, stage, root):
    """G3: responses carrying live models are re-validated on serialization."""
    src, _ = _src(stage, "m.txt", "x\n")
    env.on_data_add = lambda parts, data_root=None: {
        "added": 1, "errors": [], "data_root": data_root,
        "staged": [{"uri": "m.txt", "dest": "m.txt", "meta": EnvDataPart(src="s")}],
    }
    resp = env.handle(EnvDataAddRequest(
        parts=[EnvDataPart(src=src, dest="m.txt")], data_root=root))
    json.loads(resp.model_dump_json())          # must not raise
    assert resp.added == 1
