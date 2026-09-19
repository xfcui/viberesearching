import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".cursor/skills/_shared"
sys.path.insert(0, str(SHARED))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


runtime = load_module("research_runtime_test", SHARED / "research_runtime.py")
single_runner = load_module(
    "single_runner_test",
    ROOT / ".cursor/skills/research-single-topic/scripts/research_runner.py",
)
multi_runner = load_module(
    "multi_runner_test",
    ROOT / ".cursor/skills/research-multi-angle/scripts/research_runner.py",
)


class FakeDeepResearch:
    def __init__(self):
        self.created = []
        self.status_response = None

    def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(success=True, deepresearch_id="task-1")

    def wait(self, task_id, **kwargs):
        return SimpleNamespace(
            success=True,
            status="completed",
            output="# Report\n\nDone.",
            cost=0.1,
        )

    def status(self, task_id):
        return self.status_response


class FakeSingleClient:
    def __init__(self):
        self.deepresearch = FakeDeepResearch()


def test_shared_runtime_sync_and_async(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "get_search_config", lambda: None)
    client = FakeSingleClient()
    output = tmp_path / "sync.md"

    task_id = runtime.run_single_task(
        client=client,
        query="focused topic",
        output_path=output,
        work_dir=tmp_path,
        mode="fast",
        no_wait=False,
        max_cost=1.0,
    )
    assert task_id == "task-1"
    assert output.read_text(encoding="utf-8").startswith("# Report")

    async_output = tmp_path / "async.md"
    runtime.run_single_task(
        client=client,
        query="another topic",
        output_path=async_output,
        work_dir=tmp_path,
        mode="fast",
        no_wait=True,
        max_cost=1.0,
    )
    state = json.loads((tmp_path / "tmp_state.json").read_text(encoding="utf-8"))
    assert state[0]["task_id"] == "task-1"
    assert state[0]["output"] == str(async_output)

    client.deepresearch.status_response = SimpleNamespace(
        success=True,
        status="completed",
        output="# Async\n\nDone.",
        cost=0.1,
    )
    runtime.collect_single_task(
        client=client,
        task_id="task-1",
        output_path=async_output,
        work_dir=tmp_path,
    )
    assert async_output.read_text(encoding="utf-8").startswith("# Async")
    assert not (tmp_path / "tmp_state.json").exists()


class FakeBatch:
    def __init__(self, task):
        self.task = task
        self.created = []
        self.added = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(batch_id="retry-batch")

    def add_tasks(self, batch_id, queries):
        self.added.extend(queries)

    def wait_for_completion(self, batch_id, **kwargs):
        return SimpleNamespace(batch=SimpleNamespace(status="completed", cost=0.5))

    def status(self, batch_id):
        return SimpleNamespace(
            batch=SimpleNamespace(
                status="completed",
                cost=0.5,
                counts=SimpleNamespace(
                    completed=1,
                    total=1,
                    queued=0,
                    running=0,
                    failed=0,
                ),
            )
        )

    def list_tasks(self, batch_id, include_output=True, last_key=None):
        return SimpleNamespace(
            tasks=[self.task],
            pagination=SimpleNamespace(last_key=None),
        )


class FakeBatchClient:
    def __init__(self, task):
        self.batch = FakeBatch(task)


def manifest_fixture(path: Path):
    data = [
        {
            "task_id": "ok-task",
            "id": "Q01",
            "query": "successful query",
            "original_query": "successful query",
            "main_topic": "Parent Topic",
            "anchor": "Heading A",
            "track": "evidence",
            "search_config": {"category": "research"},
            "status": "completed",
            "filename": "research01_successful_query.md",
        },
        {
            "task_id": "failed-task",
            "id": "Q02",
            "query": "failed query (within the scope of Parent Topic)",
            "original_query": "failed query",
            "main_topic": "Parent Topic",
            "anchor": "Heading B",
            "track": "counterpoint",
            "ordinal": 2,
            "search_config": {"category": "research"},
            "status": "failed",
            "filename": "research02_failed_query.md",
        },
    ]
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def retry_task():
    return SimpleNamespace(
        task_id="retry-task",
        query="failed query (within the scope of Parent Topic)",
        status="completed",
        output="# Retried\n\nRecovered.",
        sources=[],
        cost=0.5,
        error=None,
    )


def retry_args(manifest: Path, output_dir: Path, no_wait: bool):
    return Namespace(
        manifest=str(manifest),
        output_dir=str(output_dir),
        mode="standard",
        no_wait=no_wait,
        max_cost=2.0,
        no_anchor=False,
        allow_drift=False,
    )


def test_sync_retry_merges_once_and_preserves_metadata(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    original = manifest_fixture(manifest_path)
    client = FakeBatchClient(retry_task())
    monkeypatch.setattr(multi_runner, "get_valyu_client", lambda: client)
    monkeypatch.setattr(multi_runner, "get_search_config", lambda: None)

    writes = []
    real_write = multi_runner.atomic_write_json

    def recording_write(path, data):
        if Path(path) == manifest_path:
            writes.append(data)
        return real_write(path, data)

    monkeypatch.setattr(multi_runner, "atomic_write_json", recording_write)
    multi_runner.handle_retry(retry_args(manifest_path, tmp_path, False))

    merged = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(writes) == 1
    assert merged[0] == original[0]
    assert merged[1]["task_id"] == "retry-task"
    assert merged[1]["retry_of_task_id"] == "failed-task"
    assert merged[1]["filename"] == "research02_failed_query.md"
    assert merged[1]["track"] == "counterpoint"
    assert merged[1]["original_query"] == "failed query"
    assert client.batch.created[0]["search"] == {"category": "research"}


def test_async_retry_status_merges_original_manifest(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    original = manifest_fixture(manifest_path)
    client = FakeBatchClient(retry_task())
    monkeypatch.setattr(multi_runner, "get_valyu_client", lambda: client)
    monkeypatch.setattr(multi_runner, "get_search_config", lambda: None)

    multi_runner.handle_retry(retry_args(manifest_path, tmp_path, True))
    state = json.loads((tmp_path / "tmp_state.json").read_text(encoding="utf-8"))
    assert state[0]["retry_manifest_path"] == str(manifest_path.resolve())
    assert state[0]["scope"]["entries"][0]["track"] == "counterpoint"

    multi_runner.handle_status(
        Namespace(batch_id="retry-batch", output_dir=str(tmp_path))
    )
    merged = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert merged[0] == original[0]
    assert merged[1]["task_id"] == "retry-task"
    assert merged[1]["anchor"] == "Heading B"
    assert not (tmp_path / "tmp_state.json").exists()


def test_batch_result_preserves_enrichment_metadata(tmp_path):
    task = SimpleNamespace(
        task_id="task-e1",
        query="evidence query (within the scope of Actual Subject)",
        status="completed",
        output="# Evidence\n\nFinding.",
        sources=[],
        cost=0.1,
        error=None,
    )
    client = FakeBatchClient(task)
    scope = {
        "main_topic": "Actual Subject",
        "entries": [
            {
                "submitted": task.query,
                "original_query": "evidence query",
                "id": "E01",
                "anchor": "Claim 1",
                "track": "evidence",
                "main_topic": "Actual Subject",
                "ordinal": 1,
                "filename": "research01_evidence_query.md",
            }
        ],
    }
    manifest, succeeded = multi_runner.save_batch_results(
        client,
        "batch-1",
        tmp_path,
        scope,
        write_manifest=False,
    )
    assert succeeded
    assert manifest[0]["id"] == "E01"
    assert manifest[0]["track"] == "evidence"
    assert manifest[0]["anchor"] == "Claim 1"
    assert manifest[0]["original_query"] == "evidence query"


def test_hitl_honors_prewritten_valid_response(tmp_path):
    response = tmp_path / "tmp_checkpoint_response.json"
    response.write_text('{"approved": true}', encoding="utf-8")
    callback = single_runner.make_hitl_handler(tmp_path)
    result = callback(SimpleNamespace(interaction_id="i1", type="plan", data={}))
    assert result == {"approved": True}
    assert not response.exists()
    assert not (tmp_path / "tmp_checkpoint.json").exists()


def test_hitl_invalid_response_stays_paused_until_corrected(tmp_path, monkeypatch):
    response = tmp_path / "tmp_checkpoint_response.json"
    response.write_text("{invalid", encoding="utf-8")
    sleeps = []

    def correct_on_sleep(seconds):
        sleeps.append(seconds)
        response.write_text('{"approved": false}', encoding="utf-8")

    monkeypatch.setattr(single_runner.time, "sleep", correct_on_sleep)
    callback = single_runner.make_hitl_handler(tmp_path)
    result = callback(SimpleNamespace(interaction_id="i2", type="source", data={}))
    assert sleeps
    assert result == {"approved": False}


def test_merge_retry_uses_task_identity_before_duplicate_query():
    original = [
        {"task_id": "a", "id": None, "query": "duplicate", "status": "completed"},
        {"task_id": "b", "id": None, "query": "duplicate", "status": "failed"},
    ]
    retry = [
        {
            "task_id": "c",
            "retry_of_task_id": "b",
            "query": "duplicate",
            "status": "completed",
        }
    ]
    merged = multi_runner.merge_retry_results(original, retry)
    assert merged[0]["task_id"] == "a"
    assert merged[1]["task_id"] == "c"


@pytest.mark.parametrize(
    ("script", "command"),
    [
        (
            ROOT / ".cursor/skills/research-single-topic/scripts/research_runner.py",
            ["run", "--help"],
        ),
        (
            ROOT / ".cursor/skills/research-multi-angle/scripts/research_runner.py",
            ["task-status", "--help"],
        ),
        (
            ROOT / ".cursor/skills/research-multi-angle/scripts/research_runner.py",
            ["retry", "--help"],
        ),
        (
            ROOT / ".cursor/skills/research-verify/scripts/verify_references.py",
            ["verify", "--help"],
        ),
    ],
)
def test_cli_parsers_load(script, command):
    result = subprocess.run(
        [sys.executable, str(script), *command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
