import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .db import Session
from .models import Run

logger = logging.getLogger(__name__)
WORKER = socket.gethostname()
ROOT = Path(os.getenv("SAMPLE_ROOT", Path(__file__).resolve().parents[2] / "sample-repo"))
INSTALL = ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund")
COMMANDS = (
    ("npm", "run", "lint"),
    ("npm", "run", "test", "--", "--run"),
    ("npm", "run", "build"),
)
MAX_LOG = 100_000
INSTALL_TIMEOUT = 180
JOB_TIMEOUT = 90


class CommandResult(NamedTuple):
    returncode: int
    output: str


class CommandTimedOut(TimeoutError):
    def __init__(self, message, output):
        super().__init__(message)
        self.output = output


class CommandCancelled(InterruptedError):
    def __init__(self, message, output):
        super().__init__(message)
        self.output = output


def now():
    return datetime.now(timezone.utc)


def elapsed_ms(started_at, finished_at):
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return int((finished_at - started_at).total_seconds() * 1000)


def claim():
    with Session.begin() as db:
        run = db.scalar(
            select(Run)
            .where(Run.status == "queued")
            .order_by(Run.triggered_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        run.status = "running"
        run.started_at = now()
        run.worker_id = WORKER
        run.heartbeat_at = now()
        return run.id


def mutate(run_id, callback):
    with Session.begin() as db:
        run = db.scalar(
            select(Run)
            .options(selectinload(Run.jobs))
            .where(Run.id == run_id)
            .with_for_update()
        )
        if run is not None:
            return callback(run)
    return None


def cancelled(run_id):
    with Session() as db:
        run = db.get(Run, run_id)
        return run is None or run.cancel_requested_at is not None


def prepare(destination, fixture):
    if fixture not in ("success", "failure"):
        raise ValueError("Unknown fixture")
    if not (ROOT / "package.json").is_file():
        raise FileNotFoundError(f"Sample repository not found at {ROOT}")
    shutil.copytree(
        ROOT,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("node_modules", ".git", ".venv"),
    )
    if fixture == "failure":
        test_file = Path(destination) / "src" / "math.test.ts"
        if not test_file.is_file():
            raise FileNotFoundError("Failure fixture test file is missing")
        test_file.write_text(
            'import { expect, test } from "vitest"; import { add } from "./math"; '
            'test("failure demo", () => { expect(add(2,2)).toBe(5); });\n',
            encoding="utf-8",
        )


def child_environment(workspace):
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    home = Path(workspace) / ".ci-home"
    home.mkdir(exist_ok=True)
    user_config = home / ".npmrc"
    user_config.write_text("", encoding="utf-8")
    cache = Path.home() / ".cache" / "minici-npm"
    cache.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "CI": "true",
            "HOME": str(home),
            "NPM_CONFIG_USERCONFIG": str(user_config),
            "NPM_CONFIG_CACHE": str(cache),
            "NPM_CONFIG_REGISTRY": "https://registry.npmjs.org/",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
        }
    )
    if os.name == "nt":
        env["USERPROFILE"] = str(home)
    return env


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def read_output(log_path):
    return log_path.read_bytes()[-MAX_LOG:].decode("utf-8", "replace")


def cleanup_workspace(path):
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == 4:
                logger.exception("Unable to remove temporary workspace %s", path)
            else:
                time.sleep(0.2)


def run_command(run_id, command, workspace, timeout):
    log_path = Path(workspace) / ".ci-output.log"
    launch_command = list(command)
    popen_options = {
        "cwd": workspace,
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": subprocess.STDOUT,
        "env": child_environment(workspace),
        "shell": False,
    }
    if os.name == "nt":
        launch_command = subprocess.list2cmdline(launch_command)
        popen_options["shell"] = True
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True

    try:
        with log_path.open("wb") as output:
            popen_options["stdout"] = output
            process = subprocess.Popen(launch_command, **popen_options)
            try:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if cancelled(run_id):
                        stop_process(process)
                        raise CommandCancelled(
                            "Cancelled by user", read_output(log_path)
                        )
                    if time.monotonic() >= deadline:
                        stop_process(process)
                        raise CommandTimedOut(
                            f"Command exceeded {timeout} seconds",
                            read_output(log_path),
                        )
                    mutate(run_id, lambda run: setattr(run, "heartbeat_at", now()))
                    time.sleep(0.5)
                returncode = process.wait()
            except BaseException:
                if process.poll() is None:
                    stop_process(process)
                raise
    except FileNotFoundError as error:
        return CommandResult(127, f"Command could not be started: {error}")

    return CommandResult(returncode, read_output(log_path))


def start_job(run, index):
    job = run.jobs[index]
    job.status = "running"
    job.started_at = now()


def end_job(run, index, status, code, logs):
    job = run.jobs[index]
    job.status = status
    job.exit_code = code
    job.logs = logs[-MAX_LOG:]
    job.finished_at = now()
    job.duration_ms = elapsed_ms(job.started_at, job.finished_at)


def finish(run_id, status, reason):
    def update(run):
        run.status = status
        run.finished_at = now()
        run.failure_reason = reason
        for job in run.jobs:
            if job.status == "pending":
                job.status = "cancelled" if status == "cancelled" else "skipped"
            elif job.status == "running":
                job.status = "cancelled" if status == "cancelled" else "failed"
                job.logs = (job.logs + "\n" + (reason or "Worker stopped."))[-MAX_LOG:]
                job.finished_at = now()
                job.duration_ms = elapsed_ms(job.started_at, job.finished_at)

    mutate(run_id, update)


def execute(run_id, fixture):
    temp = Path(tempfile.mkdtemp(prefix="minici-"))
    try:
        workspace = temp / "workspace"
        prepare(workspace, fixture)
        try:
            install = run_command(run_id, INSTALL, workspace, INSTALL_TIMEOUT)
        except InterruptedError as error:
            detail = getattr(error, "output", "")
            finish(
                run_id,
                "cancelled",
                str(error) + (f": {detail[-2_000:].strip()}" if detail else ""),
            )
            return
        except TimeoutError as error:
            detail = getattr(error, "output", "")
            finish(
                run_id,
                "failed",
                str(error) + (f": {detail[-2_000:].strip()}" if detail else ""),
            )
            return
        if install.returncode != 0:
            detail = install.output[-2_000:].strip()
            finish(
                run_id,
                "failed",
                "Dependency installation failed"
                + (f": {detail}" if detail else f" (exit code {install.returncode})"),
            )
            return

        for index, command in enumerate(COMMANDS):
            if cancelled(run_id):
                finish(run_id, "cancelled", "Cancelled by user")
                return
            mutate(run_id, lambda run: start_job(run, index))
            try:
                result = run_command(run_id, command, workspace, JOB_TIMEOUT)
            except InterruptedError as error:
                logs = getattr(error, "output", "") or str(error)
                mutate(
                    run_id,
                    lambda run: end_job(run, index, "cancelled", None, logs),
                )
                finish(run_id, "cancelled", "Cancelled by user")
                return
            except TimeoutError as error:
                logs = getattr(error, "output", "") or str(error)
                mutate(
                    run_id,
                    lambda run: end_job(run, index, "timed_out", None, logs),
                )
                finish(run_id, "failed", str(error))
                return

            status = "passed" if result.returncode == 0 else "failed"
            mutate(
                run_id,
                lambda run: end_job(
                    run, index, status, result.returncode, result.output
                ),
            )
            if result.returncode != 0:
                finish(
                    run_id,
                    "failed",
                    f"{command[2]} failed with exit code {result.returncode}",
                )
                return
        finish(run_id, "passed", None)
    finally:
        cleanup_workspace(temp)


def recover():
    def update(run):
        run.status = "failed"
        run.failure_reason = "Worker restarted during execution"
        run.finished_at = now()
        for job in run.jobs:
            if job.status == "running":
                job.status = "failed"
                job.logs = (job.logs + "\nWorker restarted during execution")[-MAX_LOG:]
                job.finished_at = now()
                job.duration_ms = elapsed_ms(job.started_at, job.finished_at)
            elif job.status == "pending":
                job.status = "skipped"

    with Session() as db:
        run_ids = db.scalars(select(Run.id).where(Run.status == "running")).all()
    for run_id in run_ids:
        mutate(run_id, update)


def main():
    recover()
    while True:
        try:
            run_id = claim()
        except Exception:
            logger.exception("Unable to claim a queued pipeline run")
            time.sleep(5)
            continue
        if run_id is None:
            time.sleep(1)
            continue
        try:
            with Session() as db:
                run = db.get(Run, run_id)
                fixture = run.fixture if run is not None else None
            if fixture is None:
                continue
            execute(run_id, fixture)
        except Exception as error:
            logger.exception("Pipeline run %s failed", run_id)
            finish(
                run_id,
                "failed",
                f"Execution error: {type(error).__name__}: {str(error)[:300]}",
            )


if __name__ == "__main__":
    main()
