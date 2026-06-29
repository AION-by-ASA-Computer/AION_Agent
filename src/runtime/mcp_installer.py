import json
import shutil
import requests
import logging
import subprocess
import re
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger("aion.mcp_installer")


def market_safe_dir_name(item: Dict[str, Any]) -> str:
    """Nome directory/file sicuro per ``mcp_servers/<name>`` (niente slash o caratteri path)."""
    raw = (item.get("name") or "tool").strip().lower().replace(" ", "_")
    for ch in ("/", "\\", ":", "@", "<", ">", "|", "?", "*", '"'):
        raw = raw.replace(ch, "_")
    while "__" in raw:
        raw = raw.replace("__", "_")
    raw = raw.strip("_").strip() or "tool"
    return raw[:120]


_MAX_NPM_LOG_BYTES = 2_500_000
_RE_NPM_HTTP_CACHE_LINE = re.compile(r"^\d+\s+http\s+cache\s", re.I)
_RE_NPM_SILLY_FETCH_CACHE = re.compile(r"^\d+\s+silly fetch http cache\b", re.I)


def _repo_has_tsconfig(dest_dir: Path) -> bool:
    """True se esiste un tsconfig*.json fuori da node_modules."""
    for p in dest_dir.rglob("tsconfig*.json"):
        if "node_modules" in p.parts:
            continue
        return True
    return False


def _git_npm_build_preflight(dest_dir: Path) -> str | None:
    """
    Alcuni repo pubblicano su Git solo metadati / doc senza sorgenti TypeScript, ma lasciano
    ``prepare`` → ``npm run build`` → ``tsc``. Il clone fallisce con l'help di tsc (nessun progetto).

    Restituisce None se OK, altrimenti una stringa di warning (usata per triggerare fallback npx).
    """
    pkg_path = dest_dir / "package.json"
    if not pkg_path.is_file():
        return None
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    scripts = data.get("scripts") or {}
    combined = " ".join(
        str(v).lower()
        for k, v in scripts.items()
        if k in ("prepare", "prepublish", "prepack", "postinstall", "install", "build")
    )
    if "tsc" not in combined:
        return None
    if _repo_has_tsconfig(dest_dir):
        return None
    pkg_name = (data.get("name") or "questo pacchetto").strip()
    return f"Repo senza tsconfig — npm build fallirebbe. Pacchetto npm: {pkg_name}"


def _git_npm_package_name(dest_dir: Path) -> str | None:
    """Estrae il nome pacchetto npm da package.json per fallback npx."""
    pkg_path = dest_dir / "package.json"
    if not pkg_path.is_file():
        return None
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (data.get("name") or "").strip() or None


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    intervals = sorted(intervals)
    out = [intervals[0]]
    for a, b in intervals[1:]:
        la, lb = out[-1]
        if a <= lb + 1:
            out[-1] = (la, max(lb, b))
        else:
            out.append((a, b))
    return out


def _npm_log_meaningful_excerpt(log_path: Path, max_chars: int = 16000) -> str:
    """
    Estrae dal log npm le zone con errori/stack TypeScript, evitando solo la coda «http cache».
    """
    try:
        log_path.stat()
    except OSError as e:
        return f"(stat log: {e})"
    try:
        raw = log_path.read_bytes()
    except OSError as e:
        return f"(lettura log: {e})"
    if len(raw) > _MAX_NPM_LOG_BYTES:
        raw = raw[-_MAX_NPM_LOG_BYTES:]
    lines = raw.decode("utf-8", errors="replace").splitlines()
    n = len(lines)
    if n == 0:
        return "(log vuoto)"

    def interesting(i: int) -> bool:
        ln = lines[i]
        low = ln.lower()
        if "verbose stack" in low:
            return True
        if "err!" in low or "npm err" in low:
            return True
        if "error code" in low or "error path" in low or "error command" in low:
            return True
        if "elifecycle" in low:
            return True
        if "command failed" in low and "silly" not in low[:30].lower():
            return True
        if re.search(r"\bts[0-9]{4,5}\b", low):
            return True
        # tsc stampa l'help se invocato male: è il segnale utile
        if "common commands" in low and "tsc" in low:
            return True
        if "error ts" in low:
            return True
        if "node-gyp" in low or "node gyp" in low:
            return True
        return False

    hits = [i for i in range(n) if interesting(i)]
    window = 22
    if not hits:
        tail = "\n".join(lines[-min(80, n) :])
        return (
            f"(Nessun pattern errore npm/tsc trovato; ultime {min(80, n)} righe di {log_path})\n"
            + tail
        )[:max_chars]

    intervals = [(max(0, i - window), min(n, i + window + 1)) for i in hits[-25:]]
    merged = _merge_intervals(intervals)
    chunks: list[str] = []
    prev_end = -1
    for a, b in merged:
        if prev_end >= 0 and a > prev_end:
            chunks.append("\n…\n")
        seg = lines[a:b]
        filt = [
            ln
            for ln in seg
            if not (
                _RE_NPM_HTTP_CACHE_LINE.match(ln) or _RE_NPM_SILLY_FETCH_CACHE.match(ln)
            )
        ]
        chunks.append("\n".join(filt if filt else seg))
        prev_end = b
    body = "\n".join(chunks)
    header = f"--- Estratto log npm ({log_path.name}, {len(hits)} segnali) — path completo sotto ---\n{log_path}\n\n"
    out = header + body
    if len(out) > max_chars:
        out = "…(troncato dall'inizio)\n" + out[-max_chars + 24 :]
    return out


def _npm_diagnostic_tail(stderr_stdout: str) -> str:
    """Aggiunge un estratto significativo dal file di log npm citato in stderr/stdout."""
    combined = (stderr_stdout or "").strip()
    if not combined:
        return ""
    m = re.search(r"A complete log of this run can be found in:\s*(/\S+)", combined)
    if not m:
        m = re.search(r"(/[^\s]+\.npm[^\s]*/_logs/[^\s]+\.log)", combined)
    if not m:
        return ""
    log_path = m.group(1).strip()
    p = Path(log_path)
    if not p.is_file():
        return f"\n\n(Log npm indicato ma non trovato: {log_path})"
    try:
        excerpt = _npm_log_meaningful_excerpt(p)
        return f"\n\n{excerpt}"
    except Exception as ex:
        return f"\n\n(Impossibile analizzare log npm {log_path}: {ex})"


class MCPInstaller:
    def __init__(self, bin_dir: str = "bin"):
        self.bin_dir = Path(bin_dir)
        self.bin_dir.mkdir(parents=True, exist_ok=True)

    def get_platform_key(self) -> str:
        import platform

        system = platform.system().lower()
        arch = platform.machine().lower()
        if arch == "x86_64":
            arch = "amd64"
        elif arch == "aarch64":
            arch = "arm64"
        return f"{system}/{arch}"

    async def install_from_market(self, item: Dict[str, Any]) -> tuple[bool, str]:
        """
        Install marketplace artifact. Returns (success, message).
        On failure, ``message`` is user-facing (also logged).
        """
        install_type = item.get("install_type")
        if install_type == "remote":
            return True, ""
        if install_type == "binary":
            return await self._install_binary(item)
        if install_type == "npx":
            return await self._install_npx(item)
        if install_type == "git":
            ok, msg = await self._install_git(item)
            if not ok and msg and str(msg).startswith("__NPX_FALLBACK__:"):
                pkg_name = str(msg).split(":", 1)[1]
                item["install_type"] = "npx"
                item["npx_args"] = ["-y", pkg_name]
                logger.info("Retry install as npx: %s", pkg_name)
                return await self._install_npx(item)
            return ok, msg
        if install_type == "stdio":
            msg = (
                "Questo pacchetto è di tipo «stdio» (nessun installer automatico): "
                "aggiungilo manualmente in config/mcp_registry.local.yaml usando la documentazione "
                "del server (npm/npx, Docker, ecc.). Il marketplace non espone ancora il comando esatto."
            )
            logger.warning("market install: stdio-only item %r", item.get("id"))
            return False, msg
        msg = f"Tipo di installazione non supportato: {install_type!r}"
        logger.error(msg)
        return False, msg

    async def _install_git(self, item: Dict[str, Any]) -> tuple[bool, str]:
        url = item.get("url")
        if not url:
            msg = "URL mancante per installazione git"
            logger.error(msg)
            return False, msg

        name = market_safe_dir_name(item)
        dest_dir = Path("mcp_servers") / name
        cloned_here = False

        if dest_dir.exists():
            logger.warning("Directory %s already exists. Skipping clone.", dest_dir)
        else:
            logger.info("Cloning MCP server from %s to %s", url, dest_dir)
            try:
                proc = subprocess.run(
                    ["git", "clone", "--depth", "1", url, str(dest_dir)],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except FileNotFoundError:
                msg = (
                    "git non trovato nel PATH del backend. "
                    "In Docker: ricostruisci l'immagine backend (include git nel Dockerfile). "
                    "In locale: installa git."
                )
                logger.error(msg)
                return False, msg
            except subprocess.TimeoutExpired:
                msg = "git clone: timeout (300s)"
                logger.error(msg)
                return False, msg
            if proc.returncode != 0:
                err = (
                    proc.stderr or proc.stdout or ""
                ).strip() or f"exit {proc.returncode}"
                msg = f"git clone fallito: {err[:1500]}"
                logger.error(msg)
                return False, msg
            cloned_here = True

        try:
            if (dest_dir / "package.json").exists():
                pre = _git_npm_build_preflight(dest_dir)
                if pre:
                    # Repo senza tsconfig: non possiamo buildare. Prova a usare
                    # il pacchetto npm già pubblicato invece del git clone.
                    pkg_name = _git_npm_package_name(dest_dir)
                    logger.warning(
                        "git npm preflight: %s → fallback npx %s", pre, pkg_name
                    )
                    if cloned_here:
                        shutil.rmtree(dest_dir, ignore_errors=True)
                    if pkg_name:
                        return False, f"__NPX_FALLBACK__:{pkg_name}"
                    return False, pre
                logger.info("Node.js project detected. Running npm install...")
                try:
                    npm = subprocess.run(
                        ["npm", "install"],
                        cwd=str(dest_dir),
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                except subprocess.TimeoutExpired:
                    msg = "npm install: timeout (600s)"
                    logger.error(msg)
                    if cloned_here:
                        shutil.rmtree(dest_dir, ignore_errors=True)
                    return False, msg
                if npm.returncode != 0:
                    blob = "\n".join(x for x in (npm.stderr, npm.stdout) if x)
                    tail = blob.strip()
                    msg = f"npm install fallito (exit {npm.returncode}): {tail[:2000]}"
                    msg += _npm_diagnostic_tail(blob)
                    logger.error(msg)
                    if cloned_here:
                        try:
                            shutil.rmtree(dest_dir, ignore_errors=True)
                        except Exception:
                            pass
                    else:
                        msg += (
                            f" — Cartella già presente: {dest_dir}. "
                            "Eliminala o correggi l'ambiente (Node/npm) e riprova «Install»."
                        )
                    return False, msg
            elif (dest_dir / "requirements.txt").exists():
                logger.info(
                    "Python project detected. Preparing setup (clone only; nessun pip automatico)."
                )

            return True, ""
        except Exception as e:
            msg = f"post-clone setup: {e}"
            logger.error(msg, exc_info=True)
            if cloned_here:
                shutil.rmtree(dest_dir, ignore_errors=True)
            return False, msg

    async def _install_binary(self, item: Dict[str, Any]) -> tuple[bool, str]:
        urls = item.get("binary_urls", {})
        platform = self.get_platform_key()
        url = urls.get(platform)

        if not url:
            msg = f"Nessun binario per la piattaforma {platform!r} (chiavi disponibili: {list(urls.keys())})"
            logger.error(msg)
            return False, msg

        name = market_safe_dir_name(item)
        dest_path = self.bin_dir / name

        logger.info("Downloading binary from %s to %s", url, dest_path)
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(response.raw, f)

            # Make executable
            dest_path.chmod(0o755)
            logger.info("Successfully installed binary: %s", name)
            return True, ""
        except Exception as e:
            msg = f"Download binario fallito: {e}"
            logger.error(msg, exc_info=True)
            return False, msg

    async def _install_npx(self, item: Dict[str, Any]) -> tuple[bool, str]:
        # For NPX, we just verify node is present
        try:
            proc = subprocess.run(
                ["node", "--version"], capture_output=True, text=True, check=True
            )
            logger.info("Node.js detected (%s), npx ready.", proc.stdout.strip())
            return True, ""
        except Exception as e:
            msg = "Node.js non trovato nel PATH: impossibile usare installazioni npx."
            logger.error("%s (%s)", msg, e)
            return False, msg


mcp_installer = MCPInstaller()
