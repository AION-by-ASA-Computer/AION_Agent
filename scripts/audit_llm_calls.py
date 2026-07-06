#!/usr/bin/env python3
"""Inspect persisted vLLM/LiteLLM call payloads (AION_LLM_CALL_AUDIT=1)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# Allow `python scripts/audit_llm_calls.py` from repo root.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.runtime.llm_call_audit import audit_root_dir  # noqa: E402


def _load_index() -> List[Dict[str, Any]]:
    idx = audit_root_dir() / "index.jsonl"
    if not idx.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with idx.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _load_call(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_list(args: argparse.Namespace) -> int:
    rows = _load_index()
    if args.session:
        rows = [r for r in rows if r.get("session_id") == args.session]
    if not rows:
        print(f"No audit entries under {audit_root_dir()}")
        print("Enable logging: AION_LLM_CALL_AUDIT=1 and restart the backend.")
        return 1
    tail = rows[-args.limit :]
    for r in tail:
        tools = ",".join(r.get("tool_call_names") or []) or "-"
        err = f" ERROR={r.get('error')}" if r.get("error") else ""
        print(
            f"step={r.get('step'):>4}  session={str(r.get('session_id', ''))[:36]}  "
            f"msgs={r.get('message_count')}  tools_out={tools}  "
            f"{r.get('duration_ms')}ms  {r.get('path')}{err}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    root = audit_root_dir()
    path: Optional[Path] = None
    if args.file:
        path = Path(args.file)
        if not path.is_absolute():
            path = root / path
    elif args.session and args.step:
        matches = sorted((root / args.session).glob(f"step_{args.step:04d}_*.json"))
        if not matches:
            print(f"No call for session={args.session} step={args.step}")
            return 1
        path = matches[-1]
    else:
        rows = _load_index()
        if args.session:
            rows = [r for r in rows if r.get("session_id") == args.session]
        if not rows:
            print("No calls found.")
            return 1
        rel = rows[-1].get("path")
        path = root / str(rel)

    data = _load_call(path)
    if args.raw:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"=== {path} ===")
    print(f"step={data.get('step')} session={data.get('session_id')} profile={data.get('profile_name')}")
    req = data.get("request") or {}
    print(f"model={req.get('model')} base={req.get('api_base_url')}")
    print(f"messages={req.get('message_count')} tools={len(req.get('tools') or [])}")
    if req.get("system_prompt"):
        print(f"system_prompt_chars={len(req['system_prompt'])}")
    print("\n--- generation_kwargs ---")
    print(json.dumps(req.get("generation_kwargs") or {}, indent=2))
    print("\n--- messages (last 6) ---")
    for row in (req.get("messages") or [])[-6:]:
        preview = str(row.get("content") or "").replace("\n", " ")[:160]
        tcs = row.get("tool_calls") or []
        tc_names = ",".join(tc.get("tool_name") or "?" for tc in tcs)
        extra = f" tool_calls=[{tc_names}]" if tcs else ""
        print(f"  [{row.get('index')}] {row.get('role')}: {preview}{extra}")
    print("\n--- response replies ---")
    for i, rep in enumerate((data.get("response") or {}).get("replies") or []):
        preview = str(rep.get("content") or "").replace("\n", " ")[:200]
        tcs = rep.get("tool_calls") or []
        tc_names = ",".join(tc.get("tool_name") or "?" for tc in tcs)
        print(f"  reply[{i}] tools=[{tc_names}] text={preview}")
    err = (data.get("response") or {}).get("error")
    if err:
        print(f"\nERROR: {err}")
    return 0


def _tool_signature(tc: Dict[str, Any]) -> str:
    name = tc.get("tool_name") or "?"
    args = tc.get("arguments")
    if isinstance(args, dict):
        arg_s = json.dumps(args, sort_keys=True, default=str)
    else:
        arg_s = str(args or "")
    return f"{name}({arg_s})"


def cmd_analyze(args: argparse.Namespace) -> int:
    rows = _load_index()
    if args.session:
        rows = [r for r in rows if r.get("session_id") == args.session]
    if not rows:
        print("No audit data.")
        return 1

    by_session: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_session[str(r.get("session_id") or "unknown")].append(r)

    for sid, sess_rows in by_session.items():
        print(f"\n=== session {sid} ({len(sess_rows)} LLM calls) ===")
        prev_sigs: List[str] = []
        dup_runs: Counter[str] = Counter()
        for r in sess_rows:
            sigs = [_tool_signature({"tool_name": n, "arguments": {}}) for n in (r.get("tool_call_names") or [])]
            for sig in sigs:
                if prev_sigs and prev_sigs[-1] == sig:
                    dup_runs[sig] += 1
                prev_sigs.append(sig)
            print(
                f"  step {r.get('step'):>3} msgs={r.get('message_count')} "
                f"out={','.join(r.get('tool_call_names') or []) or '-'} "
                f"{r.get('duration_ms')}ms"
            )
        if dup_runs:
            print("  Possible repeat loops (same tool back-to-back across steps):")
            for sig, n in dup_runs.most_common(10):
                print(f"    {n}x  {sig}")
        else:
            print("  No obvious back-to-back duplicate tool pattern in index.")

    return 0


def cmd_latest(args: argparse.Namespace) -> int:
    args.step = None
    args.file = None
    return cmd_show(args)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect AION LLM call audit files (enable with AION_LLM_CALL_AUDIT=1)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List calls from index.jsonl")
    p_list.add_argument("--session", help="Filter by session_id")
    p_list.add_argument("--limit", type=int, default=30)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show one call payload")
    p_show.add_argument("--session", help="Session id")
    p_show.add_argument("--step", type=int, help="Step number (1-based)")
    p_show.add_argument("--file", help="Relative or absolute path to JSON file")
    p_show.add_argument("--raw", action="store_true", help="Print full JSON")
    p_show.set_defaults(func=cmd_show)

    p_latest = sub.add_parser("latest", help="Show the most recent call")
    p_latest.add_argument("--session", help="Filter by session_id")
    p_latest.add_argument("--raw", action="store_true")
    p_latest.set_defaults(func=cmd_latest)

    p_analyze = sub.add_parser("analyze", help="Summarize loops / duplicate tools")
    p_analyze.add_argument("--session", help="Filter by session_id")
    p_analyze.set_defaults(func=cmd_analyze)

    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
