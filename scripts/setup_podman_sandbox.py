#!/usr/bin/env python3
"""
Install and configure Podman rootless for AION session sandbox (container mode).

Usage:
  ./scripts/setup-podman-sandbox.sh
  python scripts/setup_podman_sandbox.py [--dry-run] [--skip-install] [--skip-build] [-y]

See docs/deployment/podman-sandbox.md
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _warn(msg: str) -> None:
    print(f"WARN: {msg}", file=sys.stderr, flush=True)


def _fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def _run(
    cmd: List[str], *, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    _log(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def _has_cmd(name: str) -> bool:
    return shutil.which(name) is not None


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
    if pm == "apt":
        cmd = ["sudo", "apt-get", "update"]
        if dry_run:
            _log(f"[dry-run] {' '.join(cmd)}")
        else:
            _run(cmd)
        install = [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "podman",
            "slirp4netns",
            "fuse-overlayfs",
            "uidmap",
        ]
    elif pm in ("dnf", "yum"):
        install = [
            "sudo",
            pm,
            "install",
            "-y",
            "podman",
            "slirp4netns",
            "fuse-overlayfs",
        ]
    else:
        install = [
            "sudo",
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


def _podman_socket_path() -> Path:
    return Path(f"/run/user/{os.getuid()}/podman/podman.sock")


def _cleanup_bogus_socket(*, dry_run: bool) -> None:
    sock = _podman_socket_path()
    parent = sock.parent
    if sock.is_dir():
        _warn(
            f"{sock} è una directory (tipico se docker compose è partito prima del socket)."
        )
        if parent.is_dir() and os.geteuid() == 0:
            shutil.rmtree(sock)
        else:
            _log(f"Rimuovi manualmente: sudo rm -rf {sock}")
            if not dry_run:
                _run(["sudo", "rm", "-rf", str(sock)], check=False)
    elif parent.is_dir() and not os.access(parent, os.W_OK):
        _log(f"Correggo permessi su {parent} (owner root da mount Docker precedente).")
        if not dry_run:
            _run(
                ["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(parent)],
                check=False,
            )


def _enable_podman_socket(*, dry_run: bool) -> None:
    linger = ["loginctl", "enable-linger", os.environ.get("USER", "")]
    if dry_run:
        _log(f"[dry-run] {' '.join(linger)}")
    else:
        _run(linger, check=False)
    _cleanup_bogus_socket(dry_run=dry_run)
    unit = ["systemctl", "--user", "enable", "--now", "podman.socket"]
    if dry_run:
        _log(f"[dry-run] {' '.join(unit)}")
        return
    proc = subprocess.run(unit, text=True, capture_output=True)
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


def _build_env_values(repo: Path) -> Dict[str, str]:
    uid = str(os.getuid())
    gid = str(os.getgid())
    data_dir = (repo / "data").resolve()
    return {
        "AION_SANDBOX_BACKEND": "container",
        "AION_PODMAN_SOCKET_HOST": str(_podman_socket_path()),
        "AION_SANDBOX_HOST_DATA_DIR": str(data_dir),
        "AION_SANDBOX_HOST_UID": uid,
        "AION_SANDBOX_HOST_GID": gid,
        "AION_CONTAINER_RUNTIME": "podman",
        "AION_SANDBOX_CONTAINER_IMAGE": "aion/sandbox:latest",
        "AION_PODMAN_SOCKET": "/run/podman/podman.sock",
        "AION_SANDBOX_FAIL_CLOSED": "1",
        "AION_SANDBOX_MCP_JAIL": "1",
        "AION_SANDBOX_CONTAINER_SELINUX": _selinux_default(),
        "AION_SANDBOX_CONTAINER_MEMORY": "512m",
        "AION_SANDBOX_CONTAINER_CPUS": "1.0",
        "AION_SANDBOX_CONTAINER_PIDS_LIMIT": "256",
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


def _build_sandbox_image(repo: Path, *, dry_run: bool) -> None:
    if not _has_cmd("docker"):
        _warn("docker non trovato — salta build immagine sandbox.")
        return
    compose = ["docker", "compose", "--profile", "sandbox-build", "build", "sandbox"]
    if dry_run:
        _log(f"[dry-run] {' '.join(compose)}")
        _log("[dry-run] docker save aion/sandbox:latest | podman load")
        return
    _run(compose, cwd=str(repo))
    if not _has_cmd("podman"):
        return
    _log("Import immagine sandbox in Podman...")
    save = subprocess.Popen(
        ["docker", "save", "aion/sandbox:latest"],
        stdout=subprocess.PIPE,
    )
    assert save.stdout is not None
    load = subprocess.run(["podman", "load"], stdin=save.stdout, check=False)
    save.wait()
    if load.returncode != 0:
        _warn(
            "podman load fallito — prova: docker save aion/sandbox:latest | podman load"
        )
    else:
        _run(
            ["podman", "tag", "aion/sandbox:latest", "localhost/aion/sandbox:latest"],
            check=False,
        )


def _verify(*, dry_run: bool) -> None:
    if dry_run:
        return
    _run(["podman", "info"], capture=False)
    sock = _podman_socket_path()
    if not sock.is_socket():
        _fail(f"Verifica fallita: {sock} non è un socket")
    listed = subprocess.run(
        ["podman", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if (
        "aion/sandbox:latest" not in listed.stdout
        and "docker.io/aion/sandbox:latest" not in listed.stdout
    ):
        _warn(
            "Immagine aion/sandbox:latest non trovata in Podman — esegui build o podman load."
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

    _log("=== AION Podman sandbox setup ===")
    _log(f"Repo: {repo}")
    _log(f"User: {os.getuid()}:{os.getgid()}")

    if not args.skip_install:
        _log("\n[1/5] Installazione Podman...")
        _install_podman(dry_run=args.dry_run)
    else:
        _log("\n[1/5] Installazione Podman — skip")

    _log("\n[2/5] Socket Podman rootless...")
    if args.dry_run and not _has_cmd("podman"):
        _log("[dry-run] systemctl --user enable --now podman.socket")
    else:
        _enable_podman_socket(dry_run=args.dry_run)

    _log("\n[3/5] Directory sessioni host...")
    _prepare_sessions_dir(repo, dry_run=args.dry_run)

    _log("\n[4/5] Configurazione .env...")
    values = _build_env_values(repo)
    if not env_path.is_file():
        example = repo / ".env.example"
        if example.is_file() and not args.dry_run:
            shutil.copy(example, env_path)
            _log(f"Creato {env_path} da .env.example")
        elif not example.is_file() and not args.dry_run:
            env_path.write_text("", encoding="utf-8")
    _merge_env_file(env_path, values, dry_run=args.dry_run)

    if not args.skip_build:
        _log("\n[5/5] Build immagine sandbox...")
        _build_sandbox_image(repo, dry_run=args.dry_run)
    else:
        _log("\n[5/5] Build immagine sandbox — skip")

    _log("\nVerifica...")
    _verify(dry_run=args.dry_run)

    _log("\nOrdine di avvio consigliato:")
    _log("  1. systemctl --user start podman.socket")
    _log("  2. docker compose up -d")

    _maybe_restart_backend(repo, dry_run=args.dry_run, assume_yes=args.yes)
    _log("\nSetup completato.")


if __name__ == "__main__":
    main()
