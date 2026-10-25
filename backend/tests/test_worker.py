import shutil
import sys
from pathlib import Path

import pytest

from app import worker


SAMPLE_ROOT = Path(__file__).resolve().parents[2] / "sample-repo"


def queue_run(client, fixture="success"):
    pipeline_id = client.get("/api/pipelines").json()[0]["id"]
    response = client.post(
        f"/api/pipelines/{pipeline_id}/runs",
        json={"fixture": fixture},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_worker_executes_allowlisted_jobs_sequentially_and_passes_run(
    client, monkeypatch
):
    run_id = queue_run(client)
    assert worker.claim() == run_id
    monkeypatch.setattr(worker, "ROOT", SAMPLE_ROOT)
    commands = []

    def successful_command(_run_id, command, _workspace, _timeout):
        commands.append(tuple(command))
        return worker.CommandResult(0, f"completed: {' '.join(command)}")

    monkeypatch.setattr(worker, "run_command", successful_command)
    worker.execute(run_id, "success")

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "passed"
    assert [job["status"] for job in run["jobs"]] == [
        "passed",
        "passed",
        "passed",
    ]
    assert all(job["logs"].startswith("completed:") for job in run["jobs"])
    assert commands == [
        worker.INSTALL,
        *worker.COMMANDS,
    ]


def test_failed_command_fails_run_and_skips_remaining_jobs(client, monkeypatch):
    run_id = queue_run(client)
    assert worker.claim() == run_id
    monkeypatch.setattr(worker, "ROOT", SAMPLE_ROOT)
    commands = []

    def fail_test(_run_id, command, _workspace, _timeout):
        commands.append(tuple(command))
        if tuple(command) == worker.COMMANDS[1]:
            return worker.CommandResult(1, "expected test failure")
        return worker.CommandResult(0, "passed")

    monkeypatch.setattr(worker, "run_command", fail_test)
    worker.execute(run_id, "success")

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert "test failed with exit code 1" in run["failure_reason"]
    assert [job["status"] for job in run["jobs"]] == [
        "passed",
        "failed",
        "skipped",
    ]
    assert run["jobs"][1]["logs"] == "expected test failure"
    assert commands == [worker.INSTALL, *worker.COMMANDS[:2]]


def test_worker_persists_cancellation_of_active_job(client, monkeypatch):
    run_id = queue_run(client)
    assert worker.claim() == run_id
    monkeypatch.setattr(worker, "ROOT", SAMPLE_ROOT)
    commands = []

    def cancel_lint(_run_id, command, _workspace, _timeout):
        commands.append(tuple(command))
        if tuple(command) == worker.COMMANDS[0]:
            raise InterruptedError("Cancelled by user")
        return worker.CommandResult(0, "dependencies ready")

    monkeypatch.setattr(worker, "run_command", cancel_lint)
    worker.execute(run_id, "success")

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["status"] == "cancelled"
    assert [job["status"] for job in run["jobs"]] == [
        "cancelled",
        "cancelled",
        "cancelled",
    ]
    assert commands == [worker.INSTALL, worker.COMMANDS[0]]


def test_run_command_captures_a_real_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "cancelled", lambda _run_id: False)
    monkeypatch.setattr(worker, "mutate", lambda _run_id, _callback: None)

    result = worker.run_command(
        "unused",
        (sys.executable, "-c", "print('subprocess output')"),
        tmp_path,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.output.strip() == "subprocess output"


def test_run_command_times_out_and_stops_process(monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "cancelled", lambda _run_id: False)
    monkeypatch.setattr(worker, "mutate", lambda _run_id, _callback: None)

    with pytest.raises(TimeoutError, match="exceeded") as error:
        worker.run_command(
            "unused",
            (
                sys.executable,
                "-c",
                "import time; print('before timeout', flush=True); time.sleep(10)",
            ),
            tmp_path,
            timeout=0.1,
        )
    assert "before timeout" in error.value.output


def test_run_command_stops_subprocess_when_cancelled(monkeypatch, tmp_path):
    calls = 0

    def cancellation_requested(_run_id):
        nonlocal calls
        calls += 1
        return calls > 1

    monkeypatch.setattr(worker, "cancelled", cancellation_requested)
    monkeypatch.setattr(worker, "mutate", lambda _run_id, _callback: None)

    with pytest.raises(worker.CommandCancelled, match="Cancelled by user") as error:
        worker.run_command(
            "unused",
            (
                sys.executable,
                "-c",
                "import time; print('before cancellation', flush=True); time.sleep(10)",
            ),
            tmp_path,
            timeout=5,
        )
    assert "before cancellation" in error.value.output


def test_run_command_stops_subprocess_when_database_poll_fails(
    monkeypatch, tmp_path
):
    processes = []
    real_popen = worker.subprocess.Popen

    def track_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        if sys.executable in str(args[0]):
            processes.append(process)
        return process

    def database_error(_run_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker.subprocess, "Popen", track_process)
    monkeypatch.setattr(worker, "cancelled", database_error)
    monkeypatch.setattr(worker, "mutate", lambda _run_id, _callback: None)

    with pytest.raises(RuntimeError, match="database unavailable"):
        worker.run_command(
            "unused",
            (sys.executable, "-c", "import time; time.sleep(10)"),
            tmp_path,
            timeout=5,
        )

    assert processes
    assert processes[0].poll() is not None


def test_failure_fixture_only_changes_the_temporary_copy(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(worker, "ROOT", SAMPLE_ROOT)

    worker.prepare(workspace, "failure")

    assert "toBe(5)" in (workspace / "src" / "math.test.ts").read_text()
    assert "toBe(4)" in (SAMPLE_ROOT / "src" / "math.test.ts").read_text()


def test_temporary_workspace_cleanup_retries_transient_file_locks(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real_rmtree = shutil.rmtree
    attempts = 0

    def transient_lock(path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporary antivirus lock")
        real_rmtree(path)

    monkeypatch.setattr(worker.shutil, "rmtree", transient_lock)
    worker.cleanup_workspace(workspace)

    assert attempts == 2
    assert not workspace.exists()
