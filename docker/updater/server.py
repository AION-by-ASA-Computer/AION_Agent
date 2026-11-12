"""aion-updater sidecar: HTTP API that applies AION upgrades from the admin-ui.

Role in the system
------------------
The backend cannot upgrade the stack it runs in: it has no Docker socket, its
``.env`` is mounted read-only and restarting the stack would kill the process
doing the upgrade. This sidecar (service ``updater`` in
``docker-compose.ghcr.yml``) has ``/var/run/docker.sock`` and the install
directory mounted at the *same path as on the host*, and simply runs the
existing ``install.sh upgrade`` flow (hop chain, backups, ``upgrade_runner.py``
per hop, health checks), so the upgrade logic lives in one place only.

Who calls it
------------
Only the backend (``src/api/admin_update.py``) over the internal ``aion_net``
network; no port is published. Every endpoint except ``/healthz`` requires
``Authorization: Bearer $AION_UPDATER_TOKEN`` (shared secret in ``.env``).

Endpoints
---------
``GET  /healthz``  liveness, no auth.
``GET  /plan``     ``install.sh upgrade --plan`` output (current/target/chain),
                   cached for a few minutes (``?refresh=1`` bypasses the cache).
``GET  /status``   ``data/updater/status.json`` + tail of the current run's log.
``POST /upgrade``  starts ``install.sh upgrade --yes --progress-file ...`` in the
                   background; 409 if an upgrade is already running/locked, 404
                   if there is nothing to apply.

State lives on disk (``<install_dir>/data/updater/``) because the backend,
admin-ui and Caddy restart at every hop: the admin-ui polls ``/status`` and the
file survives page reloads. The sidecar itself is excluded from per-hop
restarts and recreated at the very end (see ``_schedule_updater_recreate`` in
``scripts/install.sh``). Docs: ``docs/deployment/self-update.md``.

Only the Python standard library is used: the image is ``docker:cli`` + python3.
"""

from __future__ import annotations

import hmac
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

# How long a computed plan is reused: computing it hits the GitHub API, and the
# admin-ui banner asks for it on every page load.
PLAN_CACHE_TTL_SEC = 300
# Hard cap for `install.sh upgrade --plan` (GitHub API call with retries).
PLAN_TIMEOUT_SEC = 120
# Log lines returned by /status (enough for the admin-ui's collapsible log).
LOG_TAIL_LINES = 200
# Bytes read from the end of the log to build the tail (avoids reading huge logs).
LOG_TAIL_BYTES = 128 * 1024
# Old run logs kept in data/updater/logs/ (one file per upgrade run).
MAX_LOG_FILES = 20
# A lock written by another host/PID namespace counts as active for this long;
# must match AION_UPGRADE_STALE_LOCK_SEC in scripts/install.sh (_lock_acquire).
STALE_LOCK_SEC = int(os.environ.get("AION_UPGRADE_STALE_LOCK_SEC", "7200"))
# Request bodies are tiny JSON objects; anything bigger is rejected.
MAX_BODY_BYTES = 4096


class UpdaterError(Exception):
    """Error mapped to an HTTP response by the request handler.

    ``status`` is the HTTP status code, ``code`` a stable machine-readable
    identifier (used by the backend/admin-ui), ``detail`` a human message.
    """

    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.status = status
        self.code = code
        self.detail = detail


def _utc_now() -> str:
    """ISO-8601 UTC timestamp, same format as ``_progress`` in install.sh."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically (temp file + rename).

    install.sh rewrites the same file at every phase and the HTTP handlers read
    it concurrently, so a reader must never see a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".status.")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any] | None:
    """Return the parsed JSON object at ``path``, or None if missing/invalid."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _tail_lines(path: Path, max_lines: int = LOG_TAIL_LINES) -> list[str]:
    """Return the last ``max_lines`` lines of a text file (empty if missing)."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - LOG_TAIL_BYTES))
            chunk = fh.read()
    except OSError:
        return []
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if size > LOG_TAIL_BYTES and lines:
        lines = lines[1:]  # first line is probably cut in the middle
    return lines[-max_lines:]


def _last_error_line(lines: list[str]) -> str | None:
    """Human-readable failure reason: the last ``[error]`` line printed by install.sh."""
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("[error]"):
            return stripped[len("[error]"):].strip() or stripped
    return None


def _pid_alive(pid: int) -> bool:
    """True if ``pid`` exists in this PID namespace (signal 0 probe)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Updater:
    """Runs and tracks ``install.sh upgrade`` for one installation directory.

    Thread-safe: HTTP requests are served by a ThreadingHTTPServer, so every
    state transition (start, finish) happens under ``self._lock``.

    ``runner`` (tests only) replaces ``subprocess.run`` for the plan command;
    ``popen`` replaces ``subprocess.Popen`` for the upgrade process.
    """

    def __init__(
        self,
        install_dir: Path,
        script: Path,
        *,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.install_dir = install_dir
        self.script = script
        self.state_dir = install_dir / "data" / "updater"
        self.status_path = self.state_dir / "status.json"
        self.logs_dir = self.state_dir / "logs"
        self.lock_path = install_dir / "data" / ".upgrade.lock"
        self._runner = runner
        self._popen = popen
        self._clock = clock
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._plan_cache: tuple[float, dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Environment / boot
    # ------------------------------------------------------------------
    def child_env(self) -> dict[str, str]:
        """Environment for install.sh.

        - ``AION_VERSION`` is removed: install.sh would read it as the target
          version, while the sidecar always upgrades to the latest release (or
          to the local hop in hybrid mode). The current version is read from
          ``.env`` by install.sh itself.
        - ``AION_UPDATER_MODE=1`` makes install.sh skip the ``updater`` service
          on per-hop restarts and schedule its recreation at the end.
        """
        env = dict(os.environ)
        env.pop("AION_VERSION", None)
        env.pop("AION_PROGRESS_FILE", None)
        env["AION_UPDATER_MODE"] = "1"
        return env

    def recover_after_restart(self) -> None:
        """Mark a run left "running" by a previous sidecar process as failed.

        The upgrade process lives inside this container: if the container
        restarted (crash, manual ``docker compose down``), that process is gone
        and the status would stay "running" forever. The stale lock with our
        fixed hostname is cleaned by install.sh's ``_lock_acquire`` on retry.
        """
        status = _read_json(self.status_path)
        if status and status.get("state") == "running":
            status.update(
                state="failed",
                error="Updater restarted while the upgrade was running; retry to resume.",
                updated_at=_utc_now(),
                finished_at=_utc_now(),
            )
            _atomic_write_json(self.status_path, status)

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------
    def plan(self, refresh: bool = False) -> dict[str, Any]:
        """Return the hop plan computed by ``install.sh upgrade --plan``.

        Cached for PLAN_CACHE_TTL_SEC; ``refresh=True`` forces a recomputation
        (used right before starting an upgrade). Raises UpdaterError(502) when
        the plan cannot be computed (e.g. GitHub unreachable).
        """
        now = self._clock()
        if not refresh and self._plan_cache and now - self._plan_cache[0] < PLAN_CACHE_TTL_SEC:
            return self._plan_cache[1]
        try:
            proc = self._runner(
                ["bash", str(self.script), "upgrade", "--plan"],
                cwd=str(self.install_dir),
                env=self.child_env(),
                capture_output=True,
                text=True,
                timeout=PLAN_TIMEOUT_SEC,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise UpdaterError(502, "plan_failed", "Timed out computing the upgrade plan.") from exc
        stdout_lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
        if proc.returncode != 0 or not stdout_lines:
            detail = _last_error_line((proc.stderr or "").splitlines()) or "install.sh --plan failed."
            raise UpdaterError(502, "plan_failed", detail)
        try:
            plan = json.loads(stdout_lines[-1])
        except ValueError as exc:
            raise UpdaterError(502, "plan_failed", "Invalid plan output from install.sh.") from exc
        self._plan_cache = (now, plan)
        return plan

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        """True while the upgrade process started by this sidecar is alive."""
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict[str, Any]:
        """Current upgrade status for the admin-ui.

        ``state`` is ``idle`` (never run), ``running``, ``succeeded`` or
        ``failed``; the rest of the keys are written by install.sh's
        ``_progress`` (current, target, chain, hop_index, completed, phase...).
        """
        data = _read_json(self.status_path) or {"state": "idle"}
        log_file = data.get("log_file")
        log_tail = _tail_lines(Path(log_file)) if log_file else []
        if data.get("state") == "failed" and not data.get("error"):
            data["error"] = _last_error_line(log_tail) or "Upgrade failed (see log)."
        data["running"] = self.is_running()
        data["log_tail"] = log_tail
        data["supported"] = True
        return data

    def _lock_held_elsewhere(self) -> bool:
        """True if data/.upgrade.lock belongs to a live upgrade (e.g. run from the host).

        Mirrors install.sh's ``_lock_acquire``: a lock from another hostname is
        active until it is STALE_LOCK_SEC old; one from this container is active
        only if its PID is still alive here.
        """
        lock = _read_json(self.lock_path)
        if lock is None:
            return False
        if lock.get("hostname") not in (None, "-", socket.gethostname()):
            started = int(lock.get("started_at") or 0)
            return self._clock() - started < STALE_LOCK_SEC
        return _pid_alive(int(lock.get("pid") or 0))

    # ------------------------------------------------------------------
    # Start / finish
    # ------------------------------------------------------------------
    def start(self, requested_by: str | None = None) -> dict[str, Any]:
        """Start the upgrade in the background and return the initial status.

        Side effects: writes status.json and a new log file under
        data/updater/, spawns ``install.sh upgrade`` and a reaper thread.
        Raises UpdaterError 409 (already running / locked), 404 (no update).
        """
        with self._lock:
            if self.is_running():
                raise UpdaterError(409, "upgrade_running", "An upgrade is already running.")
            if self._lock_held_elsewhere():
                raise UpdaterError(409, "upgrade_locked", "Another upgrade holds data/.upgrade.lock.")
            # Fresh plan: the cached one may predate a release or a manual upgrade.
            plan = self.plan(refresh=True)
            if not plan.get("chain"):
                raise UpdaterError(404, "no_update", "Already on the latest version.")

            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self._prune_logs()
            log_path = self.logs_dir / time.strftime("upgrade-%Y%m%d-%H%M%S.log", time.gmtime())
            # Initial status, written before the process starts: install.sh's
            # `_progress reset=1` keeps log_file/requested_by/started_at.
            status = {
                "state": "running",
                "phase": "starting",
                "current": plan.get("current"),
                "target": plan.get("target"),
                "chain": plan.get("chain", []),
                "mode": plan.get("mode"),
                "hop_index": 0,
                "completed": [],
                "log_file": str(log_path),
                "requested_by": requested_by,
                "started_at": _utc_now(),
                "updated_at": _utc_now(),
            }
            _atomic_write_json(self.status_path, status)

            log_fh = log_path.open("ab")
            try:
                self._proc = self._popen(
                    [
                        "bash", str(self.script), "upgrade", "--yes",
                        "--progress-file", str(self.status_path),
                    ],
                    cwd=str(self.install_dir),
                    env=self.child_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                log_fh.close()
                status.update(state="failed", error=f"Cannot start install.sh: {exc}",
                              finished_at=_utc_now())
                _atomic_write_json(self.status_path, status)
                raise UpdaterError(500, "spawn_failed", str(exc)) from exc
            log_fh.close()  # the child keeps its own copy of the descriptor
            self._plan_cache = None
            proc = self._proc
            threading.Thread(target=self._reap, args=(proc,), daemon=True).start()
        return self.status()

    def _reap(self, proc: subprocess.Popen) -> None:
        """Wait for the upgrade process and fix up the final status.

        install.sh marks "failed" from its EXIT trap, but it cannot do so when
        killed by a signal (OOM, SIGKILL): in that case the status would stay
        "running", so it is closed here with the exit code.
        """
        code = proc.wait()
        with self._lock:
            status = _read_json(self.status_path) or {}
            if status.get("state") == "running":
                if code == 0:
                    status.update(state="succeeded", phase="done")
                else:
                    tail = _tail_lines(Path(status.get("log_file", "")))
                    status.update(
                        state="failed",
                        exit_code=code,
                        error=_last_error_line(tail) or f"install.sh exited with code {code}.",
                    )
                status.update(updated_at=_utc_now(), finished_at=_utc_now())
                _atomic_write_json(self.status_path, status)
            self._plan_cache = None

    def _prune_logs(self) -> None:
        """Keep only the newest MAX_LOG_FILES - 1 logs (a new one is about to be created)."""
        logs = sorted(self.logs_dir.glob("upgrade-*.log"))
        for old in logs[: max(0, len(logs) - (MAX_LOG_FILES - 1))]:
            try:
                old.unlink()
            except OSError:
                pass


def make_handler(updater: Updater, token: str) -> type[BaseHTTPRequestHandler]:
    """Build the request handler class bound to ``updater`` and the shared token."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "aion-updater/1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
            # Access log to stderr without the Authorization header (never logged).
            sys.stderr.write(f"[updater] {self.address_string()} {fmt % args}\n")

        # -- helpers -----------------------------------------------------
        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            # No token configured = refuse everything: the Docker socket is
            # root-equivalent on the host, an open endpoint is never acceptable.
            if not token:
                self._send(503, {"error": "updater_token_missing"})
                return False
            header = self.headers.get("Authorization", "")
            supplied = header[7:] if header.startswith("Bearer ") else ""
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                self._send(401, {"error": "unauthorized"})
                return False
            return True

        def _json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                raise UpdaterError(413, "body_too_large")
            if length == 0:
                return {}
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError as exc:
                raise UpdaterError(400, "invalid_json") from exc
            return data if isinstance(data, dict) else {}

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            if method == "GET" and url.path == "/healthz":
                self._send(200, {"ok": True})
                return
            if not self._authorized():
                return
            try:
                if method == "GET" and url.path == "/plan":
                    refresh = parse_qs(url.query).get("refresh", ["0"])[0] == "1"
                    self._send(200, updater.plan(refresh=refresh))
                elif method == "GET" and url.path == "/status":
                    self._send(200, updater.status())
                elif method == "POST" and url.path == "/upgrade":
                    body = self._json_body()
                    requested_by = body.get("requested_by")
                    self._send(202, updater.start(str(requested_by) if requested_by else None))
                else:
                    self._send(404, {"error": "not_found"})
            except UpdaterError as exc:
                self._send(exc.status, {"error": exc.code, "detail": exc.detail})
            except Exception as exc:  # pragma: no cover - last-resort guard
                sys.stderr.write(f"[updater] unexpected error: {exc!r}\n")
                self._send(500, {"error": "internal_error"})

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802 (http.server naming)
            self._dispatch("POST")

    return Handler


def main() -> None:
    """Entry point: configure from the environment and serve until SIGTERM."""
    install_dir = Path(os.environ.get("AION_HOST_INSTALL_DIR") or os.getcwd())
    script = Path(os.environ.get("AION_UPDATER_INSTALL_SCRIPT", "/opt/aion-updater/install.sh"))
    port = int(os.environ.get("AION_UPDATER_PORT", "8090"))
    token = os.environ.get("AION_UPDATER_TOKEN", "")

    if not (install_dir / ".env").is_file():
        sys.stderr.write(f"[updater] warning: no .env in {install_dir} (AION_HOST_INSTALL_DIR?)\n")
    if not token:
        sys.stderr.write("[updater] warning: AION_UPDATER_TOKEN is empty, every request is refused\n")

    updater = Updater(install_dir, script)
    updater.recover_after_restart()
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(updater, token))
    server.daemon_threads = True

    # `docker stop` sends SIGTERM: shut the server down cleanly.
    def _stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _stop)
    sys.stderr.write(f"[updater] listening on :{port}, install dir {install_dir}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
