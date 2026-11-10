"""Tests for the aion-updater sidecar (``docker/updater/server.py``).

The module is stdlib-only and lives outside ``src/``, so it is loaded by path.
``install.sh`` is never executed: the plan command (``runner``) and the upgrade
process (``popen``) are replaced by fakes, and the HTTP layer is exercised on a
real ``ThreadingHTTPServer`` bound to an ephemeral port.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

import pytest

_SERVER_PATH = Path(__file__).resolve().parents[2] / "docker" / "updater" / "server.py"
_spec = importlib.util.spec_from_file_location("aion_updater_server", _SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(server)

PLAN = {
    "current": "1.6.2",
    "target": "1.7.0",
    "chain": ["1.6.3", "1.7.0"],
    "mode": "github",
    "update_available": True,
}


class FakeRunner:
    """Stand-in for subprocess.run of `install.sh upgrade --plan`."""

    def __init__(
        self, plan: Dict[str, Any] | None = None, returncode: int = 0, stderr: str = ""
    ):
        self.plan = PLAN if plan is None else plan
        self.returncode = returncode
        self.stderr = stderr
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, args, **kwargs):
        self.calls.append({"args": args, **kwargs})
        stdout = (
            "noise\n" + json.dumps(self.plan) + "\n" if self.returncode == 0 else ""
        )
        return subprocess.CompletedProcess(
            args, self.returncode, stdout=stdout, stderr=self.stderr
        )


class FakeProc:
    """Stand-in for the upgrade Popen: runs until ``finish(code)`` is called."""

    def __init__(self):
        self.code: int | None = None
        self._done = threading.Event()

    def poll(self):
        return self.code

    def wait(self):
        self._done.wait(5)
        return self.code

    def finish(self, code: int) -> None:
        self.code = code
        self._done.set()


class FakePopen:
    """Records spawn arguments and hands out FakeProc instances."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.procs: List[FakeProc] = []

    def __call__(self, args, **kwargs):
        self.calls.append({"args": args, **kwargs})
        proc = FakeProc()
        self.procs.append(proc)
        return proc


@pytest.fixture
def install_dir(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    return tmp_path


def make_updater(install_dir: Path, runner=None, popen=None, clock=time.time):
    return server.Updater(
        install_dir,
        Path("/opt/aion-updater/install.sh"),
        runner=runner or FakeRunner(),
        popen=popen or FakePopen(),
        clock=clock,
    )


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached")


# ---------------------------------------------------------------------------
# Updater (no HTTP)
# ---------------------------------------------------------------------------


def test_child_env_drops_version_and_sets_updater_mode(install_dir, monkeypatch):
    """install.sh must not see AION_VERSION (it would pin the target) and runs in updater mode."""
    monkeypatch.setenv("AION_VERSION", "1.6.2")
    monkeypatch.setenv("AION_PROGRESS_FILE", "/x")
    env = make_updater(install_dir).child_env()
    assert "AION_VERSION" not in env
    assert "AION_PROGRESS_FILE" not in env
    assert env["AION_UPDATER_MODE"] == "1"


def test_plan_parses_last_line_and_caches(install_dir):
    """Plan = last stdout line; reused within the TTL; refresh forces a new run."""
    now = [1000.0]
    runner = FakeRunner()
    up = make_updater(install_dir, runner=runner, clock=lambda: now[0])
    assert up.plan() == PLAN
    assert runner.calls[0]["args"][-2:] == ["upgrade", "--plan"]
    up.plan()
    assert len(runner.calls) == 1  # cached
    up.plan(refresh=True)
    assert len(runner.calls) == 2
    now[0] += server.PLAN_CACHE_TTL_SEC + 1
    up.plan()
    assert len(runner.calls) == 3  # expired


def test_plan_failure_reports_error_line(install_dir):
    """A failing `--plan` becomes 502 plan_failed with install.sh's [error] message."""
    runner = FakeRunner(returncode=1, stderr="info\n[error] GitHub API unreachable\n")
    with pytest.raises(server.UpdaterError) as exc:
        make_updater(install_dir, runner=runner).plan()
    assert exc.value.status == 502
    assert exc.value.code == "plan_failed"
    assert exc.value.detail == "GitHub API unreachable"


def test_start_spawns_install_sh_and_writes_status(install_dir):
    """Start writes a running status + log file and spawns `upgrade --yes --progress-file`."""
    popen = FakePopen()
    up = make_updater(install_dir, popen=popen)
    status = up.start("alice")
    assert status["state"] == "running"
    assert status["running"] is True
    assert status["chain"] == ["1.6.3", "1.7.0"]
    assert status["requested_by"] == "alice"
    call = popen.calls[0]
    assert call["args"][2:] == [
        "upgrade",
        "--yes",
        "--progress-file",
        str(up.status_path),
    ]
    assert call["cwd"] == str(install_dir)
    assert call["start_new_session"] is True
    assert Path(status["log_file"]).parent == up.logs_dir
    assert json.loads(up.status_path.read_text())["state"] == "running"
    popen.procs[0].finish(0)


def test_double_start_is_409(install_dir):
    """A second start while the process is alive is refused with upgrade_running."""
    popen = FakePopen()
    up = make_updater(install_dir, popen=popen)
    up.start()
    with pytest.raises(server.UpdaterError) as exc:
        up.start()
    assert (exc.value.status, exc.value.code) == (409, "upgrade_running")
    assert len(popen.calls) == 1
    popen.procs[0].finish(0)


def test_start_without_chain_is_404(install_dir):
    """Already on the latest version: 404 no_update and nothing spawned."""
    popen = FakePopen()
    up = make_updater(
        install_dir, runner=FakeRunner(plan={**PLAN, "chain": []}), popen=popen
    )
    with pytest.raises(server.UpdaterError) as exc:
        up.start()
    assert (exc.value.status, exc.value.code) == (404, "no_update")
    assert popen.calls == []


def test_lock_from_other_host_blocks_until_stale(install_dir):
    """A lock written by another host (e.g. manual run) blocks until it is stale."""
    now = 10_000.0
    lock = install_dir / "data" / ".upgrade.lock"
    lock.write_text(
        json.dumps({"pid": 1, "hostname": "some-host", "started_at": int(now) - 60})
    )
    popen = FakePopen()
    up = make_updater(install_dir, popen=popen, clock=lambda: now)
    with pytest.raises(server.UpdaterError) as exc:
        up.start()
    assert exc.value.code == "upgrade_locked"

    lock.write_text(
        json.dumps(
            {
                "pid": 1,
                "hostname": "some-host",
                "started_at": int(now) - server.STALE_LOCK_SEC - 1,
            }
        )
    )
    up.start()
    assert len(popen.calls) == 1
    popen.procs[0].finish(0)


def test_lock_from_this_host_with_dead_pid_is_ignored(install_dir):
    """A lock left by this container whose PID is gone does not block a retry."""
    lock = install_dir / "data" / ".upgrade.lock"
    lock.write_text(
        json.dumps(
            {
                "pid": 999_999_999,
                "hostname": socket.gethostname(),
                "started_at": int(time.time()),
            }
        )
    )
    popen = FakePopen()
    make_updater(install_dir, popen=popen).start()
    assert len(popen.calls) == 1
    popen.procs[0].finish(0)


def test_reaper_closes_status_when_killed(install_dir):
    """If install.sh dies without writing a final state, the reaper marks it failed."""
    popen = FakePopen()
    up = make_updater(install_dir, popen=popen)
    status = up.start()
    Path(status["log_file"]).write_text("[hop] 1.6.3\n[error] docker pull failed\n")
    popen.procs[0].finish(137)
    _wait_until(lambda: json.loads(up.status_path.read_text())["state"] == "failed")
    final = json.loads(up.status_path.read_text())
    assert final["exit_code"] == 137
    assert final["error"] == "docker pull failed"
    assert up.is_running() is False


def test_reaper_marks_success_on_exit_zero(install_dir):
    """Exit code 0 with a status still 'running' is closed as succeeded."""
    popen = FakePopen()
    up = make_updater(install_dir, popen=popen)
    up.start()
    popen.procs[0].finish(0)
    _wait_until(lambda: json.loads(up.status_path.read_text())["state"] == "succeeded")
    assert json.loads(up.status_path.read_text())["phase"] == "done"


def test_status_idle_and_failed_error_from_log(install_dir):
    """No status file → idle; failed status without error takes the log's [error] line."""
    up = make_updater(install_dir)
    assert up.status()["state"] == "idle"
    assert up.status()["supported"] is True

    log = install_dir / "run.log"
    log.write_text("line 1\n[error] migration 1.7.0 failed\n")
    up.status_path.parent.mkdir(parents=True, exist_ok=True)
    up.status_path.write_text(json.dumps({"state": "failed", "log_file": str(log)}))
    status = up.status()
    assert status["error"] == "migration 1.7.0 failed"
    assert status["log_tail"] == ["line 1", "[error] migration 1.7.0 failed"]


def test_recover_after_restart_fails_leftover_run(install_dir):
    """A 'running' status left by a previous sidecar process is turned into failed."""
    up = make_updater(install_dir)
    up.status_path.parent.mkdir(parents=True, exist_ok=True)
    up.status_path.write_text(json.dumps({"state": "running", "phase": "pull"}))
    up.recover_after_restart()
    status = json.loads(up.status_path.read_text())
    assert status["state"] == "failed"
    assert "retry" in status["error"]


def test_prune_logs_keeps_newest(install_dir):
    """Only the newest MAX_LOG_FILES - 1 logs survive before a new run."""
    up = make_updater(install_dir)
    up.logs_dir.mkdir(parents=True)
    for i in range(server.MAX_LOG_FILES + 3):
        (up.logs_dir / f"upgrade-20260101-{i:06d}.log").write_text("x")
    up._prune_logs()
    remaining = sorted(p.name for p in up.logs_dir.glob("upgrade-*.log"))
    assert len(remaining) == server.MAX_LOG_FILES - 1
    assert remaining[-1] == f"upgrade-20260101-{server.MAX_LOG_FILES + 2:06d}.log"


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


@pytest.fixture
def http_server(install_dir):
    """Serve a fake-backed Updater on an ephemeral port; yields (base_url, updater, popen, set_token)."""
    popen = FakePopen()
    up = make_updater(install_dir, popen=popen)
    servers = []

    def start(token: str):
        httpd = server.ThreadingHTTPServer(
            ("127.0.0.1", 0), server.make_handler(up, token)
        )
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start, up, popen
    for proc in popen.procs:
        proc.finish(0)
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def _request(
    url: str, method: str = "GET", token: str | None = None, body: dict | None = None
):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_http_healthz_needs_no_token(http_server):
    """/healthz is the only unauthenticated endpoint (container healthcheck)."""
    start, _, _ = http_server
    base = start("tok")
    assert _request(f"{base}/healthz") == (200, {"ok": True})


def test_http_rejects_wrong_or_missing_token(http_server):
    """Every other endpoint needs the exact Bearer token."""
    start, _, popen = http_server
    base = start("tok")
    assert _request(f"{base}/status")[0] == 401
    assert _request(f"{base}/status", token="nope")[0] == 401
    assert _request(f"{base}/upgrade", method="POST", token="nope", body={})[0] == 401
    assert popen.calls == []


def test_http_refuses_everything_without_configured_token(http_server):
    """An empty AION_UPDATER_TOKEN must never open the Docker-socket-backed API."""
    start, _, _ = http_server
    base = start("")
    status, body = _request(f"{base}/status", token="")
    assert status == 503
    assert body["error"] == "updater_token_missing"


def test_http_upgrade_flow(http_server):
    """POST /upgrade → 202 with requested_by; a second POST → 409; /status shows the run."""
    start, _, popen = http_server
    base = start("tok")
    status, body = _request(
        f"{base}/upgrade", method="POST", token="tok", body={"requested_by": "alice"}
    )
    assert status == 202
    assert body["requested_by"] == "alice"
    status, body = _request(f"{base}/upgrade", method="POST", token="tok", body={})
    assert (status, body["error"]) == (409, "upgrade_running")
    status, body = _request(f"{base}/status", token="tok")
    assert status == 200 and body["state"] == "running" and body["running"] is True
    assert len(popen.calls) == 1


def test_http_plan_refresh_flag(http_server):
    """GET /plan?refresh=1 bypasses the cache."""
    start, up, _ = http_server
    base = start("tok")
    runner = up._runner
    _request(f"{base}/plan", token="tok")
    _request(f"{base}/plan", token="tok")
    assert len(runner.calls) == 1
    status, body = _request(f"{base}/plan?refresh=1", token="tok")
    assert status == 200 and body == PLAN
    assert len(runner.calls) == 2
