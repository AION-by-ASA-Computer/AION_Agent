#!/usr/bin/env python3
"""
scripts/upgrade_runner.py — Entrypoint del container migrazione GHCR.

Questo script vive DENTRO l'immagine Docker (ghcr.io/.../aion-backend).
Viene eseguito da install.sh tramite un container usa e getta con i volumi
dell'host montati in lettura/scrittura:

    docker run --rm \\
        -v "$PWD/.env:/app/.env:rw" \\
        -v "$PWD/config:/app/config:rw" \\
        -v "$PWD/mcp_servers:/app/mcp_servers:rw" \\
        -v "$PWD/data:/app/data:rw" \\
        --entrypoint python3 \\
        ghcr.io/aion-by-asa-computer/aion-backend:<next_version> \\
        scripts/upgrade_runner.py --from <prev_version> --to <next_version>

Vantaggi rispetto all'approccio "scarica script da GitHub ed eseguilo sull'host":
  - Ha accesso all'intero stack Python di AION (SQLAlchemy, FastAPI, ecc.)
  - Ha accesso a config_std/ e mcp_servers_std/ della NUOVA versione (dentro l'immagine)
  - Non dipende da connessione GitHub raw durante la migrazione
  - È determinista: la versione dello script è quella tagghata nell'immagine stessa

Flusso:
  1. Sincronizza config_std/ → /app/config/ (merge non-distruttivo)
  2. Sincronizza mcp_servers_std/ → /app/mcp_servers/ (merge non-distruttivo)
  3. Esegue scripts/upgrades/<to_version>.py se presente (con UpgradeContext)
  4. Aggiorna AION_VERSION=<to_version> in /app/.env
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path

# ROOT è /app dentro il container
ROOT = Path(__file__).resolve().parent.parent

# Aggiunge scripts/ al path per importare upgrade_lib
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Sync non-distruttivo: src_dir/ → dst_dir/
# ---------------------------------------------------------------------------


def _sync_dir(src: Path, dst: Path, label: str) -> None:
    """Copia da src/ a dst/ solo i file ASSENTI in dst/.

    Non sovrascrive mai file già presenti — le personalizzazioni dell'utente
    (profili, config locali, MCP custom) sono sempre preservate.

    Per le sottodirectory ricorre in modo analogo.
    """
    if not src.is_dir():
        print(f"[runner] {label}: sorgente assente ({src}) — skip.")
        return

    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0

    for src_item in src.rglob("*"):
        rel = src_item.relative_to(src)
        dst_item = dst / rel

        if src_item.is_dir():
            dst_item.mkdir(parents=True, exist_ok=True)
            continue

        if dst_item.exists():
            skipped += 1
            continue

        dst_item.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_item, dst_item)
        print(f"[runner] {label}: + {rel}")
        copied += 1

    print(f"[runner] {label}: {copied} file copiati, {skipped} già presenti (preservati).")


# ---------------------------------------------------------------------------
# Esecuzione script per-versione
# ---------------------------------------------------------------------------


def _run_version_script(to_version: str, dry_run: bool) -> None:
    """Esegue scripts/upgrades/<to_version>.py se presente nell'immagine.

    In dry-run non modifica nulla, ma simula il percorso di discovery.
    """
    script_path = ROOT / "scripts" / "upgrades" / f"{to_version}.py"

    if not script_path.exists():
        print(f"[runner] Nessuno script per-versione per {to_version} — no-op.")
        return

    print(f"[runner] Eseguo script per-versione: {script_path.name}")

    from upgrade_lib import UpgradeContext  # importato dall'immagine

    ctx = UpgradeContext(
        env_path=ROOT / ".env",
        config_dir=ROOT / "config",
        install_dir=ROOT,
    )

    if dry_run:
        print(f"[runner] --dry-run: script {script_path.name} individuato ma NON eseguito.")
        return

    spec = importlib.util.spec_from_file_location("_upgrade_version", script_path)
    if spec is None or spec.loader is None:
        print(f"[runner] WARN: impossibile caricare {script_path.name} — skip.", file=sys.stderr)
        return

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    if not hasattr(mod, "upgrade"):
        print(f"[runner] WARN: {script_path.name} non espone upgrade(ctx) — skip.", file=sys.stderr)
        return

    mod.upgrade(ctx)
    print(f"[runner] Script per-versione {to_version} completato.")


# ---------------------------------------------------------------------------
# Aggiorna AION_VERSION nel .env
# ---------------------------------------------------------------------------


def _update_aion_version(to_version: str, dry_run: bool) -> None:
    """Aggiorna AION_VERSION=<to_version> nel .env montato.

    Usa rewrite_env_key da upgrade_lib (già nell'immagine).
    """
    from upgrade_lib import rewrite_env_key

    env_path = ROOT / ".env"
    if not env_path.is_file():
        print(f"[runner] WARN: {env_path} non trovato — AION_VERSION non aggiornata.", file=sys.stderr)
        return

    if dry_run:
        print(f"[runner] --dry-run: AION_VERSION={to_version} (non scritto).")
        return

    ok = rewrite_env_key(env_path, "AION_VERSION", to_version)
    if ok:
        print(f"[runner] AION_VERSION={to_version} scritto in {env_path}.")
    else:
        print(f"[runner] ERRORE: impossibile aggiornare AION_VERSION in {env_path}.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Upgrade runner GHCR — eseguito come container usa e getta."
    )
    ap.add_argument("--from", dest="from_version", required=True, help="Versione di partenza (es. 1.5.1)")
    ap.add_argument("--to", dest="to_version", required=True, help="Versione di arrivo (es. 1.6.0)")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simula la migrazione senza modificare file",
    )
    args = ap.parse_args()

    dry_tag = " [DRY-RUN]" if args.dry_run else ""
    print(f"[runner] Migrazione{dry_tag}: {args.from_version} → {args.to_version}")
    print(f"[runner] ROOT container: {ROOT}")

    # 1. Sync config_std/ → config/
    print("\n[runner] === Step 1: sync config_std/ ===")
    _sync_dir(
        src=ROOT / "config_std",
        dst=ROOT / "config",
        label="config_std → config",
    )

    # 2. Sync mcp_servers_std/ → mcp_servers/
    print("\n[runner] === Step 2: sync mcp_servers_std/ ===")
    _sync_dir(
        src=ROOT / "mcp_servers_std",
        dst=ROOT / "mcp_servers",
        label="mcp_servers_std → mcp_servers",
    )

    # 3. Script per-versione
    print("\n[runner] === Step 3: script per-versione ===")
    _run_version_script(args.to_version, args.dry_run)

    # 4. Aggiorna AION_VERSION nel .env
    print("\n[runner] === Step 4: aggiorna AION_VERSION ===")
    _update_aion_version(args.to_version, args.dry_run)

    print(f"\n[runner] Migrazione{dry_tag} {args.from_version} → {args.to_version} COMPLETATA.")


if __name__ == "__main__":
    main()
