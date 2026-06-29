"""
Helper condiviso per operazioni filesystem sessione: edit, grep, glob, chunk read.
Usato da mcp_servers/session_sandbox/server.py e dai test unitari.
Tutti i path operativi sono Path già risolti con safe_resolve() dal chiamante.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple


def _edit_max_bytes() -> int:
    return int(os.environ.get("AION_EDIT_MAX_FILE_BYTES", str(2 * 1024 * 1024)))


def _grep_max_file_bytes() -> int:
    return int(os.environ.get("AION_GREP_MAX_FILE_BYTES", str(500_000)))


def _grep_max_matches() -> int:
    return int(os.environ.get("AION_GREP_MAX_MATCHES", "200"))


def _glob_max_paths() -> int:
    return int(os.environ.get("AION_GLOB_MAX_PATHS", "500"))


def _chunk_max_lines() -> int:
    return int(os.environ.get("AION_CHUNK_MAX_LINES", "500"))


class EditError(Exception):
    """Errore strutturato per edit_file."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def edit_file(
    path: Path,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
) -> Tuple[int, str]:
    """Sostituisce old_string con new_string in path (atomico via temp file)."""
    if not path.is_file():
        raise EditError("not_found", f"File not found: {path.name}")

    stat = path.stat()
    if stat.st_size > _edit_max_bytes():
        raise EditError(
            "file_too_large",
            f"File too large to edit ({stat.st_size} bytes > {_edit_max_bytes()} max). "
            "Use sandbox_write_workspace_file to rewrite the entire file.",
        )

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise EditError("binary_file", f"Il file {path.name} is not valid UTF-8 text.")

    count = content.count(old_string)

    if count == 0:
        preview = content[:300].replace("\n", "↵")
        raise EditError(
            "zero_matches",
            f"old_string not found nel file {path.name}.\n"
            f"File preview (primi 300 chars): {preview!r}\n"
            "Hint: check whitespace, indentazione, encoding.",
        )

    if count > 1 and not replace_all:
        lines_with_match = [
            f"  riga {i + 1}: {line[:120]!r}"
            for i, line in enumerate(content.splitlines())
            if old_string in line
        ]
        hint = "\n".join(lines_with_match[:10])
        raise EditError(
            "multiple_matches",
            f"old_string found {count} times in {path.name}. "
            "Per sostituire tutte le occorrenze usa replace_all=True. "
            f"Matches at lines:\n{hint}",
        )

    new_content = content.replace(old_string, new_string, -1 if replace_all else 1)

    _archive_version(path)

    parent = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    replacements = count if replace_all else 1
    return replacements, (
        f"Edit completed: {replacements} replacement(s) in {path.name}. "
        f"Previous version archived in .versions/."
    )


def _archive_version(path: Path) -> None:
    try:
        versions_base = None
        for parent in path.parents:
            if parent.name == "workspace":
                versions_base = parent / ".versions"
                break
        if versions_base is None:
            return

        archive_dir = versions_base / path.name
        archive_dir.mkdir(parents=True, exist_ok=True)

        existing = list(archive_dir.glob(f"v*{path.suffix}"))
        nums = []
        for f in existing:
            m = re.match(r"v(\d+)", f.stem)
            if m:
                nums.append(int(m.group(1)))
        next_v = max(nums, default=0) + 1

        archive_path = archive_dir / f"v{next_v}{path.suffix}"
        shutil.copy2(str(path), str(archive_path))
    except Exception:
        pass


class GrepTruncated(Exception):
    """I risultati sono stati troncati a max_matches."""

    def __init__(self, results: List[dict], total_scanned: int):
        self.results = results
        self.total_scanned = total_scanned
        super().__init__(f"Risultati troncati a {len(results)} (scansionati {total_scanned} file)")


def _compile_with_timeout(pattern: str, timeout_sec: float):
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(re.compile, pattern)
        try:
            return fut.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            raise re.error(f"Pattern regex troppo complesso (timeout {timeout_sec}s): {pattern!r}")


def _match_with_timeout(compiled_re, line: str, timeout_sec: float) -> bool:
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(compiled_re.search, line)
        try:
            return bool(fut.result(timeout=timeout_sec))
        except concurrent.futures.TimeoutError:
            return False


def grep_content(
    session_root: Path,
    search_root: Path,
    pattern: str,
    *,
    fixed_string: bool = False,
    glob_filter: str = "*",
    max_matches: Optional[int] = None,
    max_file_bytes: Optional[int] = None,
    recursive: bool = True,
) -> List[dict]:
    if not pattern:
        raise ValueError("pattern cannot be empty")

    max_m = max_matches if max_matches is not None else _grep_max_matches()
    max_fb = max_file_bytes if max_file_bytes is not None else _grep_max_file_bytes()

    if fixed_string:
        compiled = re.compile(re.escape(pattern))
    else:
        compiled = _compile_with_timeout(pattern, timeout_sec=2.0)

    results: List[dict] = []
    total_scanned = 0

    iterator = search_root.rglob(glob_filter) if recursive else search_root.glob(glob_filter)

    for path in iterator:
        if not path.is_file():
            continue
        if ".versions" in path.parts:
            continue
        try:
            if path.stat().st_size > max_fb:
                continue
        except OSError:
            continue
        total_scanned += 1

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        try:
            rel_file = str(path.relative_to(session_root)).replace("\\", "/")
        except ValueError:
            rel_file = path.name

        for i, line in enumerate(text.splitlines(), start=1):
            if _match_with_timeout(compiled, line, timeout_sec=0.5):
                results.append(
                    {
                        "file": rel_file,
                        "line": i,
                        "content": line[:500],
                    }
                )
                if len(results) >= max_m:
                    raise GrepTruncated(results, total_scanned)

    return results


def fnmatch_glob(
    session_root: Path,
    search_root: Path,
    pattern: str,
    *,
    max_paths: Optional[int] = None,
    recursive: bool = True,
) -> List[str]:
    if not pattern:
        raise ValueError("pattern cannot be empty")

    max_p = max_paths if max_paths is not None else _glob_max_paths()
    results: List[str] = []

    if "**" in pattern or "/" in pattern:
        iterator = sorted(search_root.glob(pattern))
    elif recursive:
        iterator = sorted(search_root.rglob(pattern))
    else:
        iterator = sorted(search_root.glob(pattern))

    for path in iterator:
        if not path.is_file():
            continue
        if ".versions" in path.parts:
            continue
        try:
            rel = str(path.relative_to(session_root)).replace("\\", "/")
        except ValueError:
            continue
        results.append(rel)
        if len(results) >= max_p:
            results.append(f"[TRUNCATED: più di {max_p} results]")
            break

    return sorted(results)


def read_file_chunk(
    path: Path,
    *,
    offset_lines: int = 0,
    max_lines: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path.name}")

    try:
        with open(path, "rb") as f:
            sample = f.read(512)
        if b"\x00" in sample:
            raise ValueError(f"Il file {path.name} sembra binario, non leggibile come testo.")
    except OSError as e:
        raise ValueError(f"Impossibile leggere {path.name}: {e}") from e

    max_l = max_lines if max_lines is not None else _chunk_max_lines()
    mb = max_bytes

    try:
        all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        raise ValueError(f"Read error {path.name}: {e}") from e

    total = len(all_lines)
    start = max(0, offset_lines)

    if start >= total:
        return {
            "content": "",
            "start_line": start,
            "end_line": start,
            "total_lines": total,
            "truncated": False,
            "note": f"offset_lines={start} supera la lunghezza del file ({total} righe)",
        }

    chunk_lines = all_lines[start : start + max_l]
    content = "\n".join(chunk_lines)

    truncated = False
    if mb is not None and len(content.encode("utf-8")) > mb:
        encoded = content.encode("utf-8")[:mb]
        content = encoded.decode("utf-8", errors="replace")
        truncated = True
    elif (start + max_l) < total:
        truncated = True

    return {
        "content": content,
        "start_line": start + 1,
        "end_line": start + len(chunk_lines),
        "total_lines": total,
        "truncated": truncated,
    }
