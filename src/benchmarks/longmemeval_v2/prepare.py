from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..paths import benchmark_data_dir
from .denoise import collect_boilerplate, denoise_tree, filter_boilerplate

HF_REPO = "xiaowu0162/longmemeval-v2"
HF_BASE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main"

REQUIRED_FILES = [
    "questions.jsonl",
    "trajectories.jsonl",
    "haystacks/lme_v2_small.json",
]


def dataset_root() -> Path:
    tier = os.getenv("AION_LME_V2_TIER", "small").strip().lower()
    return benchmark_data_dir() / "datasets" / "longmemeval-v2" / tier


def manifest_path() -> Path:
    return benchmark_data_dir() / "manifests" / "longmemeval_v2_small.json"


def is_dataset_ready() -> bool:
    root = dataset_root()
    for rel in REQUIRED_FILES:
        if not (root / rel).is_file():
            return False
    return manifest_path().is_file()


def dataset_status() -> Dict[str, Any]:
    root = dataset_root()
    ready = is_dataset_ready()
    question_count = None
    trajectory_count = None
    if ready:
        manifest = json.loads(manifest_path().read_text(encoding="utf-8"))
        question_count = manifest.get("question_count")
        trajectory_count = manifest.get("trajectory_count")
    return {
        "ready": ready,
        "tier": os.getenv("AION_LME_V2_TIER", "small"),
        "manifest_path": str(manifest_path()) if ready else None,
        "question_count": question_count,
        "trajectory_count": trajectory_count,
        "root": str(root),
        "message": "Dataset ready"
        if ready
        else "Run prepare to download LME-V2-Small files",
    }


def _download_file(url: str, dest: Path) -> None:
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=600.0) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def prepare_dataset(*, fixture: Optional[Path] = None) -> Dict[str, Any]:
    """Download LME-V2-Small core files or copy from fixture (tests)."""
    root = dataset_root()
    root.mkdir(parents=True, exist_ok=True)

    if fixture and fixture.is_dir():
        import shutil

        for rel in REQUIRED_FILES:
            src = fixture / rel
            if src.is_file():
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
    else:
        for rel in REQUIRED_FILES:
            url = f"{HF_BASE}/{rel}"
            _download_file(url, root / rel)

    questions = load_questions(root)
    trajectories = load_trajectories(root)
    haystack = load_haystack_small(root)

    manifest = {
        "benchmark": "longmemeval_v2_small",
        "tier": "small",
        "hf_repo": HF_REPO,
        "question_count": len(questions),
        "trajectory_count": len(trajectories),
        "haystack_question_count": len(haystack) if isinstance(haystack, dict) else 0,
        "haystack_trajectory_ids": len(collect_haystack_trajectory_ids(haystack)),
        "text_only": os.getenv("AION_LME_V2_TEXT_ONLY", "1") == "1",
    }
    manifest_path().parent.mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {**dataset_status(), "message": "Dataset prepared successfully"}


def load_questions(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = root or dataset_root()
    path = root / "questions.jsonl"
    return _read_jsonl(path)


def load_trajectories(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    root = root or dataset_root()
    path = root / "trajectories.jsonl"
    return _read_jsonl(path)


def load_trajectories_by_ids(
    trajectory_ids: List[str],
    root: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Stream trajectories.jsonl and load only requested IDs (memory-safe)."""
    needed = {str(t) for t in trajectory_ids if t}
    if not needed:
        return {}
    root = root or dataset_root()
    path = root / "trajectories.jsonl"
    found: Dict[str, Dict[str, Any]] = {}
    if not path.is_file():
        return found
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if len(found) >= len(needed):
                break
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            tid = str(row.get("trajectory_id") or row.get("id") or "")
            if tid in needed:
                found[tid] = row
    return found


def load_haystack_small(root: Optional[Path] = None) -> Dict[str, Any]:
    root = root or dataset_root()
    path = root / "haystacks" / "lme_v2_small.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def collect_haystack_trajectory_ids(
    haystack: Dict[str, Any],
    *,
    question_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """Resolve trajectory IDs from LME-V2 haystack (question_id -> [traj_ids])."""
    ids: List[str] = []
    if question_id and question_id in haystack:
        raw = haystack[question_id]
        if isinstance(raw, list):
            ids = [str(x) for x in raw]
    elif isinstance(haystack.get("trajectory_ids"), list):
        ids = [str(x) for x in haystack["trajectory_ids"]]
    elif isinstance(haystack.get("ids"), list):
        ids = [str(x) for x in haystack["ids"]]
    else:
        seen: set[str] = set()
        for value in haystack.values():
            if not isinstance(value, list):
                continue
            for tid in value:
                s = str(tid)
                if s not in seen:
                    seen.add(s)
                    ids.append(s)
    if limit is not None:
        ids = ids[: int(limit)]
    return ids


# Set once per ingest run (see ingest_haystack).
_RUN_BOILERPLATE: set[str] = set()


def set_run_boilerplate(lines: set[str] | frozenset[str]) -> None:
    global _RUN_BOILERPLATE
    _RUN_BOILERPLATE = set(lines)


def clear_run_boilerplate() -> None:
    global _RUN_BOILERPLATE
    _RUN_BOILERPLATE = set()


def collect_trajectory_boilerplate(trajs: Dict[str, Dict[str, Any]]) -> set[str]:
    """Two-pass boilerplate detection across all trajectory states."""
    state_lines: list[list[str]] = []
    for traj in trajs.values():
        for state in traj.get("states") or []:
            if not isinstance(state, dict):
                continue
            tree = state.get("accessibility_tree") or state.get("observation")
            if isinstance(tree, str) and tree.strip():
                state_lines.append(denoise_tree(tree))
    return collect_boilerplate(state_lines)


def _env_limit(name: str, default: int) -> int | None:
    """Return None when env is 0 (unlimited)."""
    raw = os.getenv(name, str(default)).strip()
    try:
        val = int(raw)
    except ValueError:
        val = default
    return None if val == 0 else val


_MENUITEM_LABEL_RE = re.compile(r"menuitem\s+'([^']{2,120})'", re.IGNORECASE)
_OPTION_LABEL_RE = re.compile(
    r"(?:radio|option|checkbox|combobox)\s+'([^']{2,120})'",
    re.IGNORECASE,
)
_UI_LABEL_RE = re.compile(
    r"(?:StaticText|link|button|heading|ListMarker)\s+'([^']{2,120})'",
    re.IGNORECASE,
)
_PRICE_LABEL_RE = re.compile(r"\$|\[add\s|\[subtract\s", re.IGNORECASE)
_NAV_CHROME_PREFIXES = (
    "skip to",
    "open accessibility",
    "my servicenow",
    "scope selectors",
    "sidebar discussions",
    "show help",
    "show notifications",
    "create favorite for",
    "no exact match",
    "more menus",
    "choose search context",
)


def _is_nav_chrome(label: str) -> bool:
    low = label.lower().strip()
    return any(low.startswith(p) for p in _NAV_CHROME_PREFIXES)


def _stable_deprioritize_chrome(labels: List[str]) -> List[str]:
    """Move nav chrome to the end without reordering answer-bearing labels."""
    primary = [label for label in labels if not _is_nav_chrome(label)]
    chrome = [label for label in labels if _is_nav_chrome(label)]
    return primary + chrome


def _extract_label_groups(
    tree: str, *, limit: Optional[int] = None
) -> tuple[List[str], List[str]]:
    """Return (picker_labels, static_labels) preserving discovery order."""
    if not tree:
        return [], []
    if limit is None:
        limit = int(os.getenv("AION_LME_V2_UI_LABEL_LIMIT", "80"))
    seen: set[str] = set()
    picker: List[str] = []
    static: List[str] = []

    for pattern in (_MENUITEM_LABEL_RE, _OPTION_LABEL_RE):
        for match in pattern.finditer(tree):
            label = match.group(1).strip()
            if len(label) < 2 or label in seen:
                continue
            seen.add(label)
            picker.append(label)

    for match in _UI_LABEL_RE.finditer(tree):
        if len(picker) + len(static) >= limit:
            break
        label = match.group(1).strip()
        if len(label) < 2 or label in seen:
            continue
        seen.add(label)
        static.append(label)
    return picker, static


def _extract_ui_labels(tree: str, *, limit: Optional[int] = None) -> List[str]:
    """Flat label list: picker/options first, then static with chrome at the end."""
    picker, static = _extract_label_groups(tree, limit=limit)
    return picker + _stable_deprioritize_chrome(static)


def _note_safe_chunk(text: str, *, max_chars: Optional[int] = None) -> str:
    """Fit content within Mnemos CONTENT_MAX_CHARS (default 500)."""
    if max_chars is None:
        max_chars = int(os.getenv("AION_LME_V2_NOTE_MAX_CHARS", "480"))
    body = (text or "").strip().replace("\n", " ")
    if len(body) <= max_chars:
        return body
    return body[: max_chars - 3] + "..."


def _ui_label_chunks(picker: List[str], static: List[str]) -> List[str]:
    """Build compact ingest chunks; high-signal labels get their own prefix."""
    chunks: List[str] = []
    if picker:
        chunks.append(_note_safe_chunk("menu_options: " + "; ".join(picker)))

    price_labels: List[str] = []
    seen_prices: set[str] = set()
    for label in picker + static:
        if not _PRICE_LABEL_RE.search(label):
            continue
        if label in seen_prices:
            continue
        seen_prices.add(label)
        price_labels.append(label)
    if price_labels:
        chunks.append(_note_safe_chunk("catalog_options: " + "; ".join(price_labels)))

    ordered = picker + _stable_deprioritize_chrome(static)
    if ordered:
        chunks.append(_note_safe_chunk("ui_labels: " + "; ".join(ordered)))
    return chunks


def _chunk_lines(prefix: str, lines: List[str], *, max_chars: int) -> List[str]:
    """Pack lines into notes without splitting mid-line."""
    if not lines:
        return []
    chunks: List[str] = []
    current: List[str] = []
    base = prefix.strip()
    base_len = len(base) + 3  # " | "

    def flush() -> None:
        if not current:
            return
        body = base + " | " + " ".join(current)
        chunks.append(_note_safe_chunk(body, max_chars=max_chars))

    for line in lines:
        line = line.strip()
        if not line:
            continue
        add = len(line) + (1 if current else 0)
        if current and base_len + sum(len(x) for x in current) + add > max_chars:
            flush()
            current = [line]
        else:
            current.append(line)
    flush()
    return chunks


def trajectory_text_chunks(
    traj: Dict[str, Any],
    max_chunk: int = 480,
    *,
    max_states: int | None = None,
    max_tree_chars: int | None = None,
    max_chunks: int | None = None,
) -> List[str]:
    """Extract textual observations from a trajectory record (full retention mode)."""
    note_max = int(os.getenv("AION_LME_V2_NOTE_MAX_CHARS", "480"))
    if max_chunk <= 0:
        max_chunk = note_max
    if max_states is None:
        max_states = _env_limit("AION_LME_V2_MAX_STATES_PER_TRAJ", 0)
    if max_tree_chars is None:
        max_tree_chars = _env_limit("AION_LME_V2_MAX_TREE_CHARS", 0)
    if max_chunks is None:
        max_chunks = _env_limit("AION_LME_V2_MAX_CHUNKS_PER_TRAJ", 0)

    traj_id = str(traj.get("trajectory_id") or traj.get("id") or "unknown")
    chunks: List[str] = []

    header_parts: List[str] = []
    for key in ("goal", "outcome", "start_url", "summary", "task"):
        val = traj.get(key)
        if isinstance(val, str) and val.strip():
            header_parts.append(f"{key}: {val.strip()}")
    if header_parts:
        chunks.append(
            _note_safe_chunk(
                f"traj={traj_id} header | " + " | ".join(header_parts),
                max_chars=note_max,
            )
        )

    states = traj.get("states") or []
    if not isinstance(states, list):
        states = []

    state_indices = (
        list(range(len(states)))
        if max_states is None
        else _sample_state_indices(len(states), max_states)
    )

    for i in state_indices:
        state = states[i]
        if not isinstance(state, dict):
            continue
        step_n = state.get("step", state.get("state_index", i))
        prefix = f"traj={traj_id} step={step_n}"

        step_meta: List[str] = []
        for key in ("url", "action", "thought"):
            val = state.get(key)
            if isinstance(val, str) and val.strip():
                step_meta.append(f"{key}: {val.strip()}")
        if step_meta:
            chunks.append(
                _note_safe_chunk(
                    prefix + " | " + " | ".join(step_meta), max_chars=note_max
                )
            )

        tree = state.get("accessibility_tree") or state.get("observation")
        if isinstance(tree, str) and tree.strip():
            lines = denoise_tree(tree)
            lines = filter_boilerplate(lines, _RUN_BOILERPLATE)
            if max_tree_chars is not None and max_tree_chars > 0:
                trimmed: List[str] = []
                total = 0
                for ln in lines:
                    if total + len(ln) > max_tree_chars:
                        break
                    trimmed.append(ln)
                    total += len(ln)
                lines = trimmed

            picker, static = _extract_label_groups("\n".join(lines))
            if picker or static:
                chunks.extend(_ui_label_chunks(picker, static))

            chunks.extend(_chunk_lines(prefix + " tree", lines, max_chars=note_max))

    steps = traj.get("steps") or traj.get("trajectory") or []
    if isinstance(steps, dict):
        steps = steps.get("steps") or list(steps.values())
    for step in steps:
        if not isinstance(step, dict):
            if isinstance(step, str) and step.strip():
                chunks.append(
                    _note_safe_chunk(
                        f"traj={traj_id} | {step.strip()}", max_chars=note_max
                    )
                )
            continue
        for key in ("observation", "text", "content", "page_text", "action_result"):
            val = step.get(key)
            if isinstance(val, str) and val.strip():
                chunks.extend(
                    _chunk_lines(
                        f"traj={traj_id} {key}",
                        [val.strip()],
                        max_chars=note_max,
                    )
                )

    deduped: List[str] = []
    seen: set[str] = set()
    for c in chunks:
        c = _note_safe_chunk(c.strip(), max_chars=note_max)
        if len(c) < 3 or c in seen:
            continue
        seen.add(c)
        deduped.append(c)
        if max_chunks is not None and len(deduped) >= max_chunks:
            break
    return deduped


def _sample_state_indices(total: int, max_states: int) -> List[int]:
    if total <= 0 or max_states <= 0:
        return []
    if total <= max_states:
        return list(range(total))
    picks = {0, total - 1, total // 2}
    step = max(1, total // max(1, max_states - 1))
    for i in range(0, total, step):
        picks.add(i)
    return sorted(picks)[:max_states]


def _split_text(text: str, max_chunk: int) -> List[str]:
    if len(text) <= max_chunk:
        return [text]
    out: List[str] = []
    start = 0
    while start < len(text):
        out.append(text[start : start + max_chunk])
        start += max_chunk
    return out


def normalize_ability(raw: Any) -> str:
    s = str(raw or "unknown").strip().lower()
    mapping = {
        "static_state_recall": "static",
        "static": "static",
        "dynamic_state_tracking": "dynamic",
        "dynamic": "dynamic",
        "workflow_knowledge": "workflow",
        "workflow": "workflow",
        "environment_gotchas": "gotchas",
        "gotchas": "gotchas",
        "premise_awareness": "premise",
        "premise": "premise",
    }
    return mapping.get(s, s)
