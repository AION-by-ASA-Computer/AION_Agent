"""
Import server MCP da JSON in stile Claude Desktop / Cursor in `mcp_registry.local.yaml`.

Esempi:
  python -m src.mcp_import --input ~/Library/Application\\ Support/Claude/claude_desktop_config.json
  python -m src.mcp_import --input mcp.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

from src.mcp_registry_io import dump_registry_json, flatten_registry_document


def _extract_mcp_servers(root: Any) -> Dict[str, Any]:
    return flatten_registry_document(root)


def _normalize_server(entry: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "command" in entry:
        out["command"] = entry["command"]
    if "args" in entry and isinstance(entry["args"], list):
        out["args"] = list(entry["args"])
    if "env" in entry and isinstance(entry["env"], dict):
        out["env"] = dict(entry["env"])
    if "type" in entry:
        out["type"] = entry["type"]
    if "url" in entry:
        out["url"] = entry["url"]
    if "description" in entry:
        out["description"] = entry["description"]
    if "transport" in entry:
        out["transport"] = entry["transport"]
    return out


def parse_claude_json(data: Any) -> Dict[str, Any]:
    servers = _extract_mcp_servers(data)
    return {
        name: _normalize_server(s) for name, s in servers.items() if isinstance(s, dict)
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Import MCP servers into local registry YAML"
    )
    p.add_argument(
        "--input",
        "-i",
        required=True,
        help="File JSON (Claude Desktop, Cursor, o oggetto con mcpServers)",
    )
    p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Destinazione (default: config/mcp_registry.local.yaml)",
    )
    p.add_argument(
        "--format",
        choices=("yaml", "json"),
        default=None,
        help="yaml (flat) o json (mcpServers, standard Claude/Cursor). Default: da estensione -o",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="Non unire con il file locale esistente: scrive solo i server importati (+ eventuale _removed vuoto)",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Stampa YAML su stdout, non scrive file"
    )
    args = p.parse_args(argv)

    path = Path(args.input).expanduser()
    if not path.is_file():
        print(f"File non trovato: {path}", file=sys.stderr)
        return 1

    raw_text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"JSON non valido: {e}", file=sys.stderr)
        return 1

    imported = parse_claude_json(data)
    if not imported:
        print("Nessun blocco mcpServers / servers trovato.", file=sys.stderr)
        return 1

    root = Path(__file__).resolve().parents[1]
    out_path = (
        Path(args.output).expanduser()
        if args.output
        else root / "config" / "mcp_registry.local.yaml"
    )
    out_fmt = args.format or ("json" if out_path.suffix.lower() == ".json" else "yaml")

    existing_flat: Dict[str, Any] = {}
    if not args.replace and out_path.is_file():
        if out_path.suffix.lower() == ".json":
            existing_flat = flatten_registry_document(
                json.loads(out_path.read_text(encoding="utf-8"))
            )
        else:
            existing_flat = flatten_registry_document(
                yaml.safe_load(out_path.read_text(encoding="utf-8")) or {}
            )

    if args.replace:
        merged = dict(imported)
    else:
        merged = dict(existing_flat)
        merged.update(imported)
        if "_removed" in existing_flat:
            merged["_removed"] = existing_flat["_removed"]

    if args.dry_run:
        if out_fmt == "json":
            sys.stdout.write(dump_registry_json(merged))
        else:
            yaml.safe_dump(
                merged,
                sys.stdout,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_fmt == "json":
        out_path.write_text(dump_registry_json(merged), encoding="utf-8")
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                merged, f, default_flow_style=False, allow_unicode=True, sort_keys=False
            )

    print(f"Scritto {out_path} ({len(imported)} server importati, format={out_fmt}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
