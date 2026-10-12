#!/usr/bin/env python3
"""
Install and configure Podman rootless for AION session sandbox (container mode).

Usage:
  ./scripts/setup-podman-sandbox.sh
  python scripts/setup_podman_sandbox.py [--dry-run] [--skip-install] [--skip-build] [-y]

GHCR installs (scripts/install.sh) call it with a pre-built image and no host checkout:
  python3 scripts/setup_podman_sandbox.py --image ghcr.io/...:<ver> --no-host-src --no-restart

Podman is always configured for the invoking user (``SUDO_USER`` under sudo, never
root) and run with that user's primary group: a shell where ``newgrp docker`` is
active would otherwise make ``newuidmap`` refuse the rootless user namespace.

See docs/deployment/podman-sandbox.md
"""

from __future__ import annotations

import argparse
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]

ENV_BLOCK_HEADER = (
    "# --- Podman session sandbox (auto: scripts/setup-podman-sandbox.sh) ---"
)

ENV_KEYS: Tuple[str, ...] = (
    "AION_SANDBOX_BACKEND",
    "AION_PODMAN_SOCKET_HOST",
    "AION_SANDBOX_HOST_DATA_DIR",
    "AION_SANDBOX_HOST_UID",
    "AION_SANDBOX_HOST_GID",
    "AION_CONTAINER_RUNTIME",
    "AION_SANDBOX_CONTAINER_IMAGE",
    "AION_PODMAN_SOCKET",
    "AION_SANDBOX_FAIL_CLOSED",
    "AION_SANDBOX_MCP_JAIL",
    "AION_SANDBOX_CONTAINER_SELINUX",
    "AION_SANDBOX_CONTAINER_MEMORY",
    "AION_SANDBOX_CONTAINER_CPUS",
    "AION_SANDBOX_CONTAINER_PIDS_LIMIT",
    "AION_SANDBOX_MOUNT_HOST_SRC",
    "AION_SANDBOX_CONTAINER_USERNS",
)

DEFAULT_IMAGE = "aion/sandbox:latest"
SUBID_RANGE = "100000:65536"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr, flush=True)


def _fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def _run(
    cmd: List[str],
    *,
    check: bool = True,
    capture: bool = False,
    cwd: Optional[str | Path] = None,
) -> subprocess.CompletedProcess:
    _log(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
        cwd=str(cwd) if cwd is not None else None,
    )


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _sudo() -> List[str]:
    return [] if os.geteuid() == 0 else ["sudo"]


class TargetUser(NamedTuple):
    name: str
    uid: int
    gid: int

    @property
    def runtime_dir(self) -> Path:
        return Path(f"/run/user/{self.uid}")


def _target_user() -> TargetUser:
    """User that owns the rootless Podman: the sudo caller, not root."""
    name = os.environ.get("SUDO_USER") if os.geteuid() == 0 else None
    entry = pwd.getpwnam(name) if name else pwd.getpwuid(os.getuid())
    return TargetUser(entry.pw_name, entry.pw_uid, entry.pw_gid)


def _as_target(cmd: List[str]) -> List[str]:
    """
    Wrap ``cmd`` to run as the target user with its primary group and the
    systemd user-session env (``systemctl --user`` needs XDG_RUNTIME_DIR/DBUS).
    """
    user = _target_user()
    env = [
        "env",
        f"XDG_RUNTIME_DIR={user.runtime_dir}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path={user.runtime_dir}/bus",
    ]
    if os.getuid() == user.uid and os.getgid() == user.gid:
        return env + cmd
    if os.geteuid() == 0 and _has_cmd("runuser"):
        return ["runuser", "-u", user.name, "--"] + env + cmd
    return ["sudo", "-u", user.name, "-g", f"#{user.gid}"] + env + cmd


def _run_as_target(
    cmd: List[str], *, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    _log(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        _as_target(cmd), check=check, text=True, capture_output=capture, cwd="/"
    )


def _detect_pkg_manager() -> Optional[str]:
    if _has_cmd("apt-get"):
        return "apt"
    if _has_cmd("dnf"):
        return "dnf"
    if _has_cmd("yum"):
        return "yum"
    if _has_cmd("pacman"):
        return "pacman"
    return None


def _install_podman(*, dry_run: bool) -> None:
    if _has_cmd("podman"):
        _log("Podman già installato.")
        return
    pm = _detect_pkg_manager()
    if pm is None:
        _fail(
            "Package manager non supportato. Installa podman manualmente e rilancia con --skip-install."
        )
    sudo = _sudo()
    if pm == "apt":
        cmd = sudo + ["apt-get", "update"]
        if dry_run:
            _log(f"[dry-run] {' '.join(cmd)}")
        else:
            _run(cmd)
        install = sudo + [
            "env",
            "DEBIAN_FRONTEND=noninteractive",
            "apt-get",
            "install",
            "-y",
            "podman",
            "slirp4netns",
            "fuse-overlayfs",
            "uidmap",
            # bus systemd utente: senza, 'systemctl --user' non funziona via linger
            "dbus-user-session",
        ]
    elif pm in ("dnf", "yum"):
        install = sudo + [
            pm,
            "install",
            "-y",
            "podman",
            "slirp4netns",
            "fuse-overlayfs",
        ]
    else:
        install = sudo + [
            "pacman",
            "-S",
            "--noconfirm",
            "podman",
            "slirp4netns",
            "fuse-overlayfs",
        ]
    if dry_run:
        _log(f"[dry-run] {' '.join(install)}")
        return
    _run(install)


def _ensure_subids(*, dry_run: bool) -> bool:
    """Append ``user:100000:65536`` to /etc/subuid|subgid if missing. Returns True if changed."""
    user = _target_user()
    changed = False
    for path in (Path("/etc/subuid"), Path("/etc/subgid")):
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        if re.search(rf"^{re.escape(user.name)}:", text, re.MULTILINE):
            continue
        line = f"{user.name}:{SUBID_RANGE}"
        if dry_run:
            _log(f"[dry-run] echo {line} >> {path}")
            continue
        subprocess.run(
            _sudo() + ["tee", "-a", str(path)],
            input=line + "\n",
            text=True,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        _log(f"Aggiunta mappatura {line} in {path}")
        changed = True
    return changed


def _podman_socket_path() -> Path:
    return _target_user().runtime_dir / "podman" / "podman.sock"


def _cleanup_bogus_socket(*, dry_run: bool) -> None:
    sock = _podman_socket_path()
    parent = sock.parent
    user = _target_user()
    if sock.is_dir():
        _warn(
            f"{sock} è una directory (tipico se docker compose è partito prima del socket)."
        )
        if dry_run:
            _log(f"[dry-run] sudo rm -rf {sock}")
        else:
            _run(_sudo() + ["rm", "-rf", str(sock)], check=False)
    if parent.is_dir() and parent.stat().st_uid != user.uid:
        _log(f"Correggo permessi su {parent} (owner root da mount Docker precedente).")
        if not dry_run:
            _run(
                _sudo() + ["chown", "-R", f"{user.uid}:{user.gid}", str(parent)],
                check=False,
            )


def _wait_user_bus(timeout: float = 10.0) -> bool:
    bus = _target_user().runtime_dir / "bus"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if bus.is_socket():
            return True
        time.sleep(0.5)
    return bus.is_socket()


def _enable_podman_socket(*, dry_run: bool, subids_changed: bool) -> None:
    user = _target_user()
    linger = _sudo() + ["loginctl", "enable-linger", user.name]
    if dry_run:
        _log(f"[dry-run] {' '.join(linger)}")
    else:
        _run(linger)
        if not _wait_user_bus():
            _fail(
                f"Bus systemd utente non disponibile in {user.runtime_dir}/bus "
                "(Debian/Ubuntu: installa dbus-user-session)."
            )
    _cleanup_bogus_socket(dry_run=dry_run)
    if dry_run:
        _log("[dry-run] systemctl --user enable --now podman.socket")
        return
    if subids_changed:
        _run_as_target(["podman", "system", "migrate"], check=False, capture=True)
    _run_as_target(["systemctl", "--user", "daemon-reload"], check=False)
    proc = _run_as_target(
        ["systemctl", "--user", "enable", "--now", "podman.socket"],
        check=False,
        capture=True,
    )
    if proc.returncode != 0:
        _warn(proc.stderr.strip() or proc.stdout.strip())
        _fail(
            "podman.socket non avviato. Se vedi 'Address already in use', ferma il backend "
            "(docker compose stop backend) e rimuovi la directory spuria con: "
            f"sudo rm -rf {_podman_socket_path()}"
        )
    sock = _podman_socket_path()
    if not sock.is_socket():
        _fail(f"Socket Podman non valido: {sock} (atteso file socket)")


def _selinux_default() -> str:
    if Path("/sys/fs/selinux").exists():
        return "1"
    return "0"


def _build_env_values(
    repo: Path,
    *,
    image: str = DEFAULT_IMAGE,
    host_src: bool = True,
    userns: str = "keep-id",
) -> Dict[str, str]:
    user = _target_user()
    data_dir = (repo / "data").resolve()
    return {
        "AION_SANDBOX_BACKEND": "container",
        "AION_PODMAN_SOCKET_HOST": str(_podman_socket_path()),
        "AION_SANDBOX_HOST_DATA_DIR": str(data_dir),
        "AION_SANDBOX_HOST_UID": str(user.uid),
        "AION_SANDBOX_HOST_GID": str(user.gid),
        "AION_CONTAINER_RUNTIME": "podman",
        "AION_SANDBOX_CONTAINER_IMAGE": image,
        "AION_PODMAN_SOCKET": "/run/podman/podman.sock",
        "AION_SANDBOX_FAIL_CLOSED": "1",
        "AION_SANDBOX_MCP_JAIL": "1",
        "AION_SANDBOX_CONTAINER_SELINUX": _selinux_default(),
        "AION_SANDBOX_CONTAINER_MEMORY": "512m",
        "AION_SANDBOX_CONTAINER_CPUS": "1.0",
        "AION_SANDBOX_CONTAINER_PIDS_LIMIT": "256",
        # GHCR: nessun checkout sull'host, src/ è già nell'immagine sandbox
        # (un bind-mount di <repo>/src inesistente fa fallire 'podman run').
        "AION_SANDBOX_MOUNT_HOST_SRC": "1" if host_src else "0",
        "AION_SANDBOX_CONTAINER_USERNS": userns,
    }


def _merge_env_file(env_path: Path, values: Dict[str, str], *, dry_run: bool) -> None:
    lines: List[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    block_start = None
    block_end = None
    for i, line in enumerate(lines):
        if line.strip() == ENV_BLOCK_HEADER:
            block_start = i
            break
    if block_start is not None:
        block_end = block_start + 1
        while block_end < len(lines):
            stripped = lines[block_end].strip()
            if stripped.startswith("# ---") and stripped != ENV_BLOCK_HEADER:
                break
            if stripped and not stripped.startswith("#") and "=" not in stripped:
                break
            if (
                stripped
                and not stripped.startswith("#")
                and "=" in stripped
                and stripped.split("=", 1)[0].strip() not in ENV_KEYS
                and block_end > block_start + len(ENV_KEYS)
            ):
                break
            block_end += 1
        # Trim until next blank after our keys or next section
        while block_end < len(lines) and lines[block_end].strip().startswith("#"):
            if lines[block_end].strip().startswith("# ---"):
                break
            block_end += 1

    new_block = [ENV_BLOCK_HEADER]
    for key in ENV_KEYS:
        new_block.append(f"{key}={values[key]}")
    new_block.append("")

    if block_start is not None and block_end is not None:
        updated = lines[:block_start] + new_block + lines[block_end:]
    else:
        updated = lines
        if updated and updated[-1].strip():
            updated.append("")
        updated.extend(new_block)

    # Remove duplicate keys outside the managed block (last wins in parsers — keep block authoritative)
    seen = set(ENV_KEYS)
    filtered: List[str] = []
    in_block = False
    for line in updated:
        if line.strip() == ENV_BLOCK_HEADER:
            in_block = True
            filtered.append(line)
            continue
        if in_block:
            filtered.append(line)
            if not line.strip():
                in_block = False
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line.strip())
        if m and m.group(1) in seen:
            continue
        filtered.append(line)

    content = "\n".join(filtered).rstrip() + "\n"
    if dry_run:
        _log("[dry-run] .env aggiornato:")
        for line in new_block:
            _log(f"  {line}")
        return
    env_path.write_text(content, encoding="utf-8")
    _log(f"Aggiornato {env_path}")


def _prepare_sessions_dir(repo: Path, *, dry_run: bool) -> None:
    sessions = repo / "data" / "sessions"
    if dry_run:
        _log(f"[dry-run] mkdir -p {sessions}")
        return
    sessions.mkdir(parents=True, exist_ok=True)
    os.chmod(sessions, 0o775)
    if os.geteuid() == 0:
        user = _target_user()
        os.chown(sessions, user.uid, user.gid)


def _podman_load_from_docker(image: str) -> bool:
    save = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
    assert save.stdout is not None
    load = subprocess.run(_as_target(["podman", "load"]), stdin=save.stdout, check=False)
    save.wait()
    return load.returncode == 0 and save.returncode == 0


def _build_sandbox_image(repo: Path, *, dry_run: bool) -> None:
    if not _has_cmd("docker"):
        _warn("docker non trovato — salta build immagine sandbox.")
        return
    compose = ["docker", "compose", "--profile", "sandbox-build", "build", "sandbox"]
    if dry_run:
        _log(f"[dry-run] {' '.join(compose)}")
        _log(f"[dry-run] docker save {DEFAULT_IMAGE} | podman load")
        return
    _run(compose, cwd=str(repo))
    if not _has_cmd("podman"):
        return
    _log("Import immagine sandbox in Podman...")
    if not _podman_load_from_docker(DEFAULT_IMAGE):
        _warn(
            f"podman load fallito — prova: docker save {DEFAULT_IMAGE} | podman load"
        )
    else:
        _run_as_target(
            ["podman", "tag", DEFAULT_IMAGE, f"localhost/{DEFAULT_IMAGE}"],
            check=False,
        )


def _pull_sandbox_image(image: str, *, dry_run: bool) -> None:
    """Pull a pre-built image (GHCR) into the target user's Podman store."""
    if dry_run:
        _log(f"[dry-run] podman pull {image}")
        return
    if _run_as_target(["podman", "pull", image], check=False).returncode == 0:
        return
    _warn("podman pull fallito, provo docker pull + podman load...")
    if (
        _has_cmd("docker")
        and _run(["docker", "pull", image], check=False).returncode == 0
        and _podman_load_from_docker(image)
    ):
        return
    _fail(f"Immagine sandbox {image} non disponibile in Podman.")


def _probe_userns_mode(image: str, *, dry_run: bool) -> str:
    """
    Start the sandbox image through the Podman socket, as the backend does.
    Prefer ``--userns=keep-id``; fall back to ``host-root`` (container root =
    host user in rootless Podman) where keep-id cannot mount the rootfs.
    """
    if dry_run or not _has_cmd("podman"):
        return "keep-id"
    exists = _run_as_target(
        ["podman", "image", "exists", image], check=False, capture=True
    )
    if exists.returncode != 0:
        _warn(f"Immagine {image} assente — verifica userns saltata (keep-id).")
        return "keep-id"
    user = _target_user()
    base = [
        "podman",
        "--url",
        f"unix://{_podman_socket_path()}",
        "run",
        "--rm",
        "--entrypoint",
        "true",
    ]
    keep_id = _run_as_target(
        base + ["--userns=keep-id", "--user", f"{user.uid}:{user.gid}", image],
        check=False,
        capture=True,
    )
    if keep_id.returncode == 0:
        return "keep-id"
    _warn(keep_id.stderr.strip())
    host_root = _run_as_target(
        base + ["--user", "0:0", image], check=False, capture=True
    )
    if host_root.returncode == 0:
        _log("--userns=keep-id non supportato su questo host: uso host-root.")
        return "host-root"
    _warn(host_root.stderr.strip())
    _fail(f"Il container sandbox {image} non parte tramite il socket Podman.")
    return "keep-id"  # unreachable


def _verify(*, image: str, dry_run: bool) -> None:
    if dry_run:
        return
    info = _run_as_target(["podman", "info"], check=False, capture=True)
    if info.returncode != 0:
        _warn(info.stderr.strip())
        _fail(
            f"'podman info' fallito per l'utente {_target_user().name}. Se vedi "
            "'OCI permission denied' dopo un tentativo fallito, lo storage è "
            "inizializzato a metà: rm -rf ~/.local/share/containers e rilancia."
        )
    sock = _podman_socket_path()
    if not sock.is_socket():
        _fail(f"Verifica fallita: {sock} non è un socket")
    exists = _run_as_target(
        ["podman", "image", "exists", image], check=False, capture=True
    )
    if exists.returncode != 0:
        _warn(
            f"Immagine {image} non trovata in Podman — esegui build o podman load."
        )


def _maybe_restart_backend(repo: Path, *, dry_run: bool, assume_yes: bool) -> None:
    if not _has_cmd("docker"):
        return
    ps = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--services"],
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=False,
    )
    if "backend" not in (ps.stdout or ""):
        _log("Backend non in esecuzione — avvia con: docker compose up -d")
        return
    if dry_run:
        _log("[dry-run] docker compose up -d --build backend")
        return
    if not assume_yes:
        try:
            answer = (
                input("Ricostruire e riavviare il backend ora? [y/N] ").strip().lower()
            )
        except EOFError:
            answer = "n"
        if answer not in ("y", "yes", "s", "si"):
            _log(
                "Salta restart. Esegui manualmente: docker compose up -d --build backend"
            )
            return
    _run(["docker", "compose", "up", "-d", "--build", "backend"], cwd=str(repo))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Setup Podman rootless per session sandbox AION"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra azioni senza modificare il sistema",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Salta installazione pacchetti Podman",
    )
    parser.add_argument(
        "--skip-build", action="store_true", help="Salta build/import immagine sandbox"
    )
    parser.add_argument(
        "--image",
        help="Immagine sandbox pre-built (es. GHCR) da scaricare con podman pull "
        "invece di costruirla; scritta in AION_SANDBOX_CONTAINER_IMAGE",
    )
    parser.add_argument(
        "--no-host-src",
        action="store_true",
        help="Nessun checkout sull'host (install GHCR): AION_SANDBOX_MOUNT_HOST_SRC=0",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Non riavviare il backend (lo stack viene avviato dal chiamante)",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Non chiedere conferma per restart backend",
    )
    args = parser.parse_args()

    if sys.platform == "darwin":
        _fail(
            "macOS: usa AION_SANDBOX_BACKEND=subprocess (Podman socket non supportato in dev)."
        )
    if not sys.platform.startswith("linux"):
        _fail(f"SO non supportato: {sys.platform}")

    repo = _REPO_ROOT
    env_path = repo / ".env"
    image = args.image or DEFAULT_IMAGE
    user = _target_user()

    _log("=== AION Podman sandbox setup ===")
    _log(f"Repo: {repo}")
    _log(f"User: {user.name} ({user.uid}:{user.gid})")

    if not args.skip_install:
        _log("\n[1/5] Installazione Podman...")
        _install_podman(dry_run=args.dry_run)
    else:
        _log("\n[1/5] Installazione Podman — skip")

    _log("\n[2/5] Socket Podman rootless...")
    if args.dry_run and not _has_cmd("podman"):
        _log("[dry-run] systemctl --user enable --now podman.socket")
    else:
        subids_changed = _ensure_subids(dry_run=args.dry_run)
        _enable_podman_socket(dry_run=args.dry_run, subids_changed=subids_changed)

    _log("\n[3/5] Directory sessioni host...")
    _prepare_sessions_dir(repo, dry_run=args.dry_run)

    if args.image:
        _log("\n[4/5] Pull immagine sandbox...")
        _pull_sandbox_image(image, dry_run=args.dry_run)
    elif not args.skip_build:
        _log("\n[4/5] Build immagine sandbox...")
        _build_sandbox_image(repo, dry_run=args.dry_run)
    else:
        _log("\n[4/5] Build immagine sandbox — skip")

    _log("\n[5/5] Configurazione .env...")
    userns = _probe_userns_mode(image, dry_run=args.dry_run)
    values = _build_env_values(
        repo, image=image, host_src=not args.no_host_src, userns=userns
    )
    if not env_path.is_file():
        example = repo / ".env.example"
        if example.is_file() and not args.dry_run:
            shutil.copy(example, env_path)
            _log(f"Creato {env_path} da .env.example")
        elif not example.is_file() and not args.dry_run:
            env_path.write_text("", encoding="utf-8")
    _merge_env_file(env_path, values, dry_run=args.dry_run)

    _log("\nVerifica...")
    _verify(image=image, dry_run=args.dry_run)

    if not args.no_restart:
        _log("\nOrdine di avvio consigliato:")
        _log("  1. systemctl --user start podman.socket")
        _log("  2. docker compose up -d")
        _maybe_restart_backend(repo, dry_run=args.dry_run, assume_yes=args.yes)
    _log("\nSetup completato.")


if __name__ == "__main__":
    main()
