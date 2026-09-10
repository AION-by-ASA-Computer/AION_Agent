#!/usr/bin/env python3
"""
scripts/upgrade_lib.py — Primitivi condivisi per l'upgrade GHCR.

Espone le funzioni di manipolazione del .env già presenti (privatamente)
in upgrade_core.py, con API pubblica (senza underscore), più la classe
UpgradeContext usata dai file per-versione in scripts/upgrades/<version>.py.

Contratto:
    from scripts.upgrade_lib import UpgradeContext
    def upgrade(ctx: UpgradeContext) -> None:
        ctx.ensure_env_key("AION_NEW_FLAG", "0")
        ctx.rename_env_key("AION_OLD_NAME", "AION_NEW_NAME")
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# .env parser / writer
# ---------------------------------------------------------------------------


def parse_env_simple(path: Path) -> list[tuple[str, str, str]]:
    """Parser minimale: ritorna lista di (key, value, original_line).

    Preserva ordine, commenti e righe vuote.
    Per righe non-KEY=VAL ritorna ('', '', original_line).
    """
    out: list[tuple[str, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for raw in text.splitlines():
        s = raw.lstrip()
        if not s or s.startswith("#"):
            out.append(("", "", raw))
            continue
        if "=" not in raw:
            out.append(("", "", raw))
            continue
        key, _, val = raw.partition("=")
        out.append((key.strip(), val.strip(), raw))
    return out


def rewrite_env_key(path: Path, key: str, value: str) -> bool:
    """Sostituisce KEY=... con KEY=value (prima occorrenza); aggiunge se assente.

    Returns True se l'operazione è riuscita.
    """
    if not path.is_file():
        return False
    entries = parse_env_simple(path)
    out_lines: list[str] = []
    seen: set[str] = set()
    found = False
    for k, _, raw in entries:
        if not k:
            out_lines.append(raw)
            continue
        if k in seen:
            continue
        seen.add(k)
        if k == key:
            out_lines.append(f"{key}={value}")
            found = True
        else:
            out_lines.append(raw)
    if not found:
        out_lines.append(f"{key}={value}")
    try:
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def remove_env_key(path: Path, key: str) -> bool:
    """Rimuove KEY=... dal .env (chiavi deprecate).

    Returns True se l'operazione è riuscita (anche se la chiave era assente).
    """
    if not path.is_file():
        return False
    entries = parse_env_simple(path)
    out_lines: list[str] = []
    seen: set[str] = set()
    removed = False
    for k, _, raw in entries:
        if not k:
            out_lines.append(raw)
            continue
        if k in seen:
            continue
        seen.add(k)
        if k == key:
            removed = True
            continue
        out_lines.append(raw)
    if not removed:
        return True  # già assente — no-op, non è un errore
    try:
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def ensure_env_key(path: Path, key: str, default: str) -> bool:
    """Aggiunge KEY=default solo se la chiave è assente nel .env.

    Non sovrascrive mai un valore esistente (idempotente).
    Returns True se l'operazione è riuscita.
    """
    entries = parse_env_simple(path)
    for k, _, _ in entries:
        if k == key:
            return True  # già presente
    return rewrite_env_key(path, key, default)


def rename_env_key(path: Path, old: str, new: str) -> bool:
    """Rinomina OLD_KEY in NEW_KEY preservando il valore.

    Se OLD_KEY è assente, è un no-op.
    Se NEW_KEY esiste già, non sovrascrive (rimuove solo OLD_KEY).
    Returns True se l'operazione è riuscita.
    """
    entries = parse_env_simple(path)
    old_value: str | None = None
    new_exists = False
    for k, v, _ in entries:
        if k == old:
            old_value = v
        if k == new:
            new_exists = True
    if old_value is None:
        return True  # OLD_KEY assente — no-op
    if new_exists:
        # NEW_KEY già esiste: rimuovi solo il vecchio
        return remove_env_key(path, old)
    # Aggiungi NEW_KEY con il valore di OLD_KEY, poi rimuovi OLD_KEY
    ok = rewrite_env_key(path, new, old_value)
    if ok:
        ok = remove_env_key(path, old)
    return ok


# ---------------------------------------------------------------------------
# UpgradeContext — interfaccia per i file scripts/upgrades/<version>.py
# ---------------------------------------------------------------------------


@dataclass
class UpgradeContext:
    """Contesto passato alla funzione upgrade() nei file per-versione.

    Esempio d'uso in scripts/upgrades/1.6.0.py:

        def upgrade(ctx: UpgradeContext) -> None:
            ctx.ensure_env_key("AION_NEW_FEATURE_FLAG", "0")
            ctx.rename_env_key("AION_OLD_NAME", "AION_NEW_NAME")
    """

    env_path: Path
    config_dir: Path
    install_dir: Path

    def ensure_env_key(self, key: str, default: str) -> bool:
        """Aggiunge KEY=default solo se assente (idempotente)."""
        ok = ensure_env_key(self.env_path, key, default)
        if ok:
            print(f"[upgrade_lib] ensure_env_key: {key} OK")
        else:
            print(f"[upgrade_lib] ensure_env_key: {key} FAILED", file=sys.stderr)
        return ok

    def rewrite_env_key(self, key: str, value: str) -> bool:
        """Imposta KEY=value sovrascrivendo se presente."""
        ok = rewrite_env_key(self.env_path, key, value)
        if ok:
            print(f"[upgrade_lib] rewrite_env_key: {key} OK")
        else:
            print(f"[upgrade_lib] rewrite_env_key: {key} FAILED", file=sys.stderr)
        return ok

    def rename_env_key(self, old: str, new: str) -> bool:
        """Rinomina OLD→NEW preservando il valore (no-op se assente)."""
        ok = rename_env_key(self.env_path, old, new)
        if ok:
            print(f"[upgrade_lib] rename_env_key: {old} → {new} OK")
        else:
            print(f"[upgrade_lib] rename_env_key: {old} → {new} FAILED", file=sys.stderr)
        return ok

    def remove_env_key(self, key: str) -> bool:
        """Rimuove KEY dal .env (no-op se assente)."""
        ok = remove_env_key(self.env_path, key)
        if ok:
            print(f"[upgrade_lib] remove_env_key: {key} OK")
        else:
            print(f"[upgrade_lib] remove_env_key: {key} FAILED", file=sys.stderr)
        return ok


# ---------------------------------------------------------------------------
# Lock manager (richiamato da install.sh via `python3 scripts/upgrade_lib.py`)
# ---------------------------------------------------------------------------


class LockManager:
    """Gestione del file di lock per evitare run concorrenti di upgrade.

    Formato JSON: {"pid": int, "hostname": str, "started_at": int (epoch)}
    Il lock è considerato stale se il processo non esiste più E
    l'età supera stale_sec (default 7200s = 2h).
    """

    def __init__(self, lock_path: Path, stale_sec: int = 7200, yes: bool = False):
        self.lock_path = lock_path
        self.stale_sec = stale_sec
        self.yes = yes

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def acquire(self) -> None:
        """Acquisisce il lock. Lancia SystemExit se il lock è attivo."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                data = json.loads(self.lock_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            pid = int(data.get("pid", 0) or 0)
            started = int(data.get("started_at", 0) or 0)
            age = max(0, int(time.time()) - started) if started else self.stale_sec + 1
            stale = (not self._pid_alive(pid)) and age >= self.stale_sec
            if stale and not self.yes and sys.stdin.isatty():
                ans = (
                    input(f"Stale lock rilevato ({self.lock_path}). Recuperare? [y/N] ")
                    .strip()
                    .lower()
                )
                if ans not in ("y", "yes"):
                    raise SystemExit(2)
            elif not stale:
                raise SystemExit(
                    f"[upgrade_lib] Lock attivo: {self.lock_path}\n"
                    f"  PID={pid}, hostname={data.get('hostname')}, "
                    f"avviato {age}s fa.\n"
                    "  Attendere il termine del processo o rimuovere manualmente il lock."
                )
            self.lock_path.unlink(missing_ok=True)

        payload = {
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "started_at": int(time.time()),
        }
        self.lock_path.write_text(json.dumps(payload), encoding="utf-8")

    def release(self) -> None:
        """Rilascia il lock."""
        self.lock_path.unlink(missing_ok=True)

    def __enter__(self) -> "LockManager":
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


# ---------------------------------------------------------------------------
# CLI helper — usato da install.sh via `python3 scripts/upgrade_lib.py <cmd>`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="upgrade_lib CLI helper per install.sh")
    sub = ap.add_subparsers(dest="cmd")

    lock_p = sub.add_parser("lock-acquire", help="Acquisisce il lock di upgrade")
    lock_p.add_argument("--lock-file", type=Path, required=True)
    lock_p.add_argument("--stale-sec", type=int, default=7200)
    lock_p.add_argument("--yes", action="store_true")

    rel_p = sub.add_parser("lock-release", help="Rilascia il lock di upgrade")
    rel_p.add_argument("--lock-file", type=Path, required=True)

    ek_p = sub.add_parser("ensure-key", help="Aggiunge KEY=DEFAULT se assente")
    ek_p.add_argument("--env-file", type=Path, required=True)
    ek_p.add_argument("--key", required=True)
    ek_p.add_argument("--default", required=True, dest="default_val")

    rk_p = sub.add_parser("rewrite-key", help="Imposta KEY=VALUE (sovrascrive)")
    rk_p.add_argument("--env-file", type=Path, required=True)
    rk_p.add_argument("--key", required=True)
    rk_p.add_argument("--value", required=True)

    rnk_p = sub.add_parser("rename-key", help="Rinomina OLD→NEW nel .env")
    rnk_p.add_argument("--env-file", type=Path, required=True)
    rnk_p.add_argument("--old", required=True)
    rnk_p.add_argument("--new", required=True)

    args = ap.parse_args()

    if args.cmd == "lock-acquire":
        lm = LockManager(args.lock_file, args.stale_sec, args.yes)
        lm.acquire()
        print(f"[upgrade_lib] Lock acquisito: {args.lock_file}")

    elif args.cmd == "lock-release":
        lm = LockManager(args.lock_file)
        lm.release()
        print(f"[upgrade_lib] Lock rilasciato: {args.lock_file}")

    elif args.cmd == "ensure-key":
        ok = ensure_env_key(args.env_file, args.key, args.default_val)
        sys.exit(0 if ok else 1)

    elif args.cmd == "rewrite-key":
        ok = rewrite_env_key(args.env_file, args.key, args.value)
        sys.exit(0 if ok else 1)

    elif args.cmd == "rename-key":
        ok = rename_env_key(args.env_file, args.old, args.new)
        sys.exit(0 if ok else 1)

    else:
        ap.print_help()
        sys.exit(1)
