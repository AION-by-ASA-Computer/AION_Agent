"""
Zero-Clone GitHub MCP repository analyzer powered by Gitingest & LLM Structured Extraction.
Fetches repository digests via Gitingest (with raw.githubusercontent.com fallback) and uses LLM
Structured Output to extract runtime runner, command arguments, and required env vars.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import requests

logger = logging.getLogger("aion.marketplaces.github_raw")


class McpEnvVarSpec(BaseModel):
    key: str = Field(
        ..., description="Nome della variabile d'ambiente (es. GITHUB_TOKEN, API_KEY)"
    )
    description: str = Field(
        default="", description="Descrizione e scopo della variabile"
    )
    is_secret: bool = Field(
        default=False, description="True se è una credenziale, token, secret o password"
    )
    required: bool = Field(
        default=True,
        description="True se il server non può avviarsi senza questa variabile",
    )
    default: str = Field(
        default="", description="Valore di default suggerito se applicabile"
    )


class McpCliArgSpec(BaseModel):
    """Specifica un argomento CLI posizionale che richiede input dall'utente."""

    name: str = Field(
        ...,
        description="Nome descrittivo dell'argomento (es. 'allowed_directory', 'db_connection_string')",
    )
    description: str = Field(
        default="", description="Descrizione e scopo dell'argomento"
    )
    required: bool = Field(
        default=True,
        description="True se il server non può avviarsi senza questo argomento",
    )
    default: str = Field(
        default="", description="Valore di default suggerito se applicabile"
    )
    placeholder: str = Field(
        default="",
        description="Placeholder suggerito (es. '/path/to/dir', 'postgresql://...')",
    )


class McpServerAnalysisResult(BaseModel):
    package_url: str = Field(
        ...,
        description="Identificatore o nome pacchetto (es. @modelcontextprotocol/server-postgres o repo/pkg)",
    )
    runner: str = Field(..., description="Runner di esecuzione: 'npx' oppure 'uvx'")
    description: str = Field(default="", description="Breve descrizione del tool")
    required_envs: List[McpEnvVarSpec] = Field(
        default_factory=list, description="Lista delle variabili d'ambiente necessarie"
    )
    cli_args: List[McpCliArgSpec] = Field(
        default_factory=list,
        description="Argomenti CLI posizionali configurabili dall'utente (es. directory consentite, percorsi)",
    )
    command_args: Optional[List[str]] = Field(
        default=None,
        description="Argomenti completi del comando template (es. ['-y', 'exa-mcp-server']). Se None, il backend decide.",
    )


def parse_github_url_details(url: str) -> Optional[Dict[str, str]]:
    """Estrae owner, repo, subpath e branch da URL GitHub (inclusi monorepo /tree/branch/subpath)."""
    u = (url or "").strip()
    if not u:
        return None
    if u.lower().startswith("github:"):
        u = u.split(":", 1)[1].strip()

    # Pattern: https://github.com/owner/repo/tree/branch/sub/path
    m_tree = re.search(
        r"github\.com/([^/]+)/([^/?#]+)/tree/([^/?#]+)(?:/(.*))?", u, re.I
    )
    if m_tree:
        owner = m_tree.group(1)
        repo = m_tree.group(2).removesuffix(".git")
        branch = m_tree.group(3)
        subpath = (m_tree.group(4) or "").strip("/").split("?")[0].split("#")[0]
        return {"owner": owner, "repo": repo, "branch": branch, "subpath": subpath}

    # Pattern standard: https://github.com/owner/repo
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", u, re.I)
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2).removesuffix(".git"),
            "branch": "",
            "subpath": "",
        }

    parts = u.strip("/").split("/")
    if len(parts) >= 2 and not u.startswith("http"):
        return {
            "owner": parts[0],
            "repo": parts[1].removesuffix(".git"),
            "branch": "",
            "subpath": "/".join(parts[2:]) if len(parts) > 2 else "",
        }
    return None


def parse_github_owner_repo(url: str) -> Optional[tuple[str, str]]:
    """Compatibilità retroattiva: estrae (owner, repo)."""
    details = parse_github_url_details(url)
    if details:
        return details["owner"], details["repo"]
    return None


def fetch_raw_github_file(
    owner: str,
    repo: str,
    filename: str,
    *,
    subpath: str = "",
    branch_hint: str = "",
) -> Optional[str]:
    """Scarica il contenuto testuale di un file da raw.githubusercontent.com provando subpath e branch."""
    headers = {"User-Agent": "AION-Agent/1.0"}
    token = (os.getenv("AION_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    branches = [branch_hint] if branch_hint else []
    for b in ("main", "master"):
        if b not in branches:
            branches.append(b)

    paths_to_try = []
    if subpath:
        paths_to_try.append(f"{subpath.strip('/')}/{filename}")
    else:
        paths_to_try.append(filename)

    for branch in branches:
        for p in paths_to_try:
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{p}"
            try:
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception as ex:
                logger.debug("Fetch raw %s on branch %s failed: %s", p, branch, ex)
    return None


def fetch_gitingest_repo_context(
    owner: str,
    repo: str,
    *,
    subpath: str = "",
    branch_hint: str = "",
) -> Optional[Dict[str, str]]:
    """
    Interroga l'API di Gitingest (https://gitingest.com/api/...) per ottenere il digest
    del repository GitHub filtrando i file prioritari per MCP.
    """
    url = f"https://gitingest.com/api/{owner}/{repo}"
    if branch_hint and subpath:
        url = f"https://gitingest.com/api/{owner}/{repo}/tree/{branch_hint}/{subpath.strip('/')}"
    elif subpath:
        url = f"https://gitingest.com/api/{owner}/{repo}?pattern={subpath.strip('/')}/*"

    headers = {"User-Agent": "AION-Agent/1.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("content", "")
            if content:
                all_files: Dict[str, str] = {}
                current_fn = None
                current_lines = []
                for line in content.splitlines():
                    if line.startswith("FILE: "):
                        if current_fn:
                            all_files[current_fn] = "\n".join(current_lines)
                        current_fn = line.replace("FILE: ", "").strip()
                        current_lines = []
                    else:
                        current_lines.append(line)
                if current_fn:
                    all_files[current_fn] = "\n".join(current_lines)

                # Filtra selettivamente solo i file chiave per MCP per evitare rumore e sovraccarico
                priority_exts = (
                    "readme.md",
                    "package.json",
                    "pyproject.toml",
                    "setup.py",
                    ".env",
                    ".env.example",
                    ".env.sample",
                    ".env.template",
                    "smithery.yaml",
                    "server.json",
                    "glama.json",
                    "mcp.json",
                    "src/index.ts",
                    "src/server.ts",
                    "src/main.ts",
                    "src/stdio.ts",
                    "index.ts",
                    "server.ts",
                    "main.py",
                    "server.py",
                )
                filtered_dict: Dict[str, str] = {}
                for fn, body in all_files.items():
                    fn_lower = fn.lower()
                    if any(
                        fn_lower == p or fn_lower.endswith("/" + p) or p in fn_lower
                        for p in priority_exts
                    ):
                        if not any(
                            noise in fn_lower
                            for noise in (
                                "test",
                                "dist/",
                                "node_modules/",
                                "coverage",
                                ".lock",
                            )
                        ):
                            filtered_dict[fn] = body[:15000]

                if filtered_dict:
                    logger.info(
                        "Gitingest: estratti %d file chiave su %d totali per %s/%s",
                        len(filtered_dict),
                        len(all_files),
                        owner,
                        repo,
                    )
                    return filtered_dict
    except Exception as ex:
        logger.warning(
            "Chiamata Gitingest per %s/%s non riuscita (%s), fallback su raw GitHub",
            owner,
            repo,
            ex,
        )
    return None


def fetch_github_manifests(
    owner: str,
    repo: str,
    *,
    subpath: str = "",
    branch_hint: str = "",
) -> Dict[str, str]:
    """Recupera i file manifest e documentazione chiave (Gitingest primario con fallback a raw GitHub)."""
    # 1. Prova prima via Gitingest
    gitingest_files = fetch_gitingest_repo_context(
        owner, repo, subpath=subpath, branch_hint=branch_hint
    )
    if gitingest_files:
        return gitingest_files

    # 2. Fallback diretto raw GitHub
    targets = [
        "package.json",
        "pyproject.toml",
        "setup.py",
        ".env.example",
        ".env.template",
        ".env.sample",
        ".env",
        "README.md",
        "src/config/schema.ts",
        "src/config/loader.ts",
        "src/config.ts",
        "src/env.ts",
        "src/stdio.ts",
        "src/index.ts",
        "src/server.ts",
        "src/main.ts",
        "src/main.py",
        "index.ts",
        "server.py",
        "smithery.yaml",
        "server.json",
        "glama.json",
        "mcp.json",
        "plugin.json",
    ]
    manifests: Dict[str, str] = {}
    for filename in targets:
        content = fetch_raw_github_file(
            owner, repo, filename, subpath=subpath, branch_hint=branch_hint
        )
        if content:
            manifests[filename] = content[:15000]
    return manifests


def _is_valid_env_key(key: str) -> bool:
    if not key or not key[0].isalpha():
        return False
    k_upper = key.upper()
    invalid_prefixes = (
        "YOUR_",
        "MY_",
        "THE_",
        "SOME_",
        "ANOTHER_",
        "EXAMPLE_",
        "DUMMY_",
        "TEST_",
        "PLACEHOLDER_",
        "DEFAULT_",
        "NODE_",
        "AGNOST_",
        "NPM_",
        "CI_",
    )
    if any(k_upper.startswith(p) for p in invalid_prefixes):
        return False
    invalid_exact = {
        "YOUR_API_KEY",
        "YOUR_TOKEN",
        "MY_API_KEY",
        "ACCESS_TOKEN_HERE",
        "API_KEY_HERE",
        "TRUE",
        "FALSE",
        "STRING",
        "BOOLEAN",
        "NUMBER",
        "CONFIG",
        "README",
        "LICENSE",
        "UTF8",
        "PORT",
        "HOST",
        "VERSION",
        "PATH",
        "NODE_ENV",
        "HOME",
        "USER",
        "PWD",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "TMP",
        "TEMP",
        "PYTHONPATH",
        "HOSTNAME",
        "SHLVL",
        "EDITOR",
        "LOG_LEVEL",
        "DEBUG",
    }
    if k_upper in invalid_exact:
        return False
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_]{1,50}$", key))


def _extract_json_dict_from_llm_text(text: str) -> Optional[Dict[str, Any]]:
    """Estrae in modo resiliente un dizionario JSON dal testo dell'LLM."""
    if not text:
        return None

    # 1. Prova estrazione da blocco markdown ```json ... ``` o ``` ... ```
    m_code = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    candidates = []
    if m_code:
        candidates.append(m_code.group(1).strip())

    # 2. Prova estrazione con bilanciamento parentesi graffe
    start = text.find("{")
    if start != -1:
        depth = 0
        end = start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if depth == 0 and end > start:
            candidates.append(text[start : end + 1].strip())

    candidates.append(text.strip())

    for c in candidates:
        if not c or "{" not in c or "}" not in c:
            continue
        try:
            parsed = json.loads(c)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            # Pulisci trailing commas comuni in output LLM: ,} o ,]
            cleaned = re.sub(r",\s*([\}\]])", r"\1", c)
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

    return None


async def analyze_github_mcp_repo(github_url: str) -> McpServerAnalysisResult:
    """
    Analizza un repository GitHub MCP senza clonare su disco (supporta monorepo e subfolder).
    Utilizza Gitingest + LLM Structured Extraction con fallback euristico robusto.
    """
    details = parse_github_url_details(github_url)
    if not details:
        raise ValueError(f"URL GitHub non valido: '{github_url}'")
    owner = details["owner"]
    repo = details["repo"]
    subpath = details["subpath"]
    branch = details["branch"]

    manifests = fetch_github_manifests(owner, repo, subpath=subpath, branch_hint=branch)
    if not manifests:
        logger.warning(
            "Nessun file o manifest trovato per %s/%s (subpath: %s)",
            owner,
            repo,
            subpath,
        )

    # Heuristics pre-determinazione runner
    has_package_json = any(k.endswith("package.json") for k in manifests)
    has_python = any(
        k.endswith("pyproject.toml") or k.endswith("setup.py") or k.endswith(".py")
        for k in manifests
    )

    default_pkg = subpath.split("/")[-1] if subpath else repo
    pkg_name = f"{owner}/{default_pkg}"
    runner = "npx"

    # Ricerca pacchetto npm o python in manifests
    for fn, content in manifests.items():
        if fn.endswith("package.json"):
            try:
                pj = json.loads(content)
                if pj.get("name") and pj.get("name") != "@modelcontextprotocol/servers":
                    pkg_name = pj["name"]
                    runner = "npx"
                    break
            except Exception:
                pass
        elif fn.endswith("pyproject.toml"):
            runner = "uvx"
            pkg_name = (
                f"mcp-server-{default_pkg}"
                if not default_pkg.startswith("mcp-server-")
                else default_pkg
            )
            m_name = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            if m_name:
                pkg_name = m_name.group(1).strip()

    # Eseguiamo arricchimento con LLM Structured Output
    try:
        from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
        from src.runtime.llm_adapter import resolve_llm_credentials
        from haystack.dataclasses import ChatMessage
        from haystack.utils import Secret

        endpoint, model_name, api_key = resolve_llm_credentials()
        secret_key = Secret.from_token(api_key) if api_key else None
        generator = LiteLLMChatGeneratorWrapper(
            model=model_name,
            api_base_url=endpoint,
            api_key=secret_key,
            generation_kwargs={"temperature": 0.1, "max_tokens": 4000},
        )

        # Seleziona i file prioritari estratti da Gitingest o raw
        priority_files: Dict[str, str] = {}
        for fn, content in manifests.items():
            fn_lower = fn.lower()
            if fn_lower == "readme.md" or fn_lower.endswith("/readme.md"):
                priority_files[fn] = content[:15000]
            elif any(
                k in fn_lower
                for k in (
                    "package.json",
                    "pyproject.toml",
                    "smithery.yaml",
                    "server.json",
                    "glama.json",
                    ".env",
                )
            ):
                priority_files[fn] = content[:4000]
            elif any(
                fn_lower.endswith(k)
                for k in (
                    "src/server.ts",
                    "src/main.ts",
                    "src/index.ts",
                    "main.py",
                    "server.py",
                    "src/stdio.ts",
                )
            ):
                priority_files[fn] = content[:3000]

        # Se nessun file prioritario specifico, prendi i primi 5
        if not priority_files:
            for fn, content in list(manifests.items())[:6]:
                priority_files[fn] = content[:3000]

        prompt_context = "\n\n".join(
            f"=== FILE: {fn} ===\n{content}" for fn, content in priority_files.items()
        )

        prompt = (
            "Sei un assistente AI specializzato in Model Context Protocol (MCP).\n"
            f"Analizza i file del repository GitHub {owner}/{repo} estratti tramite Gitingest.\n"
            "Devi identificare la configurazione completa per registrare ed eseguire questo server MCP:\n"
            f"1. package_url: nome del pacchetto npm (es. {pkg_name}) o pacchetto Python uvx.\n"
            f"2. runner: 'npx' (Node/JS/TS) oppure 'uvx' (Python).\n"
            "3. command_args: argomenti CLI template per avviare il server MCP in modalità stdio. Usa placeholder come '/path/to/dir' o '<CONNECTION_URL>' per gli argomenti che l'utente deve configurare.\n"
            "4. description: breve spiegazione di 1 frase in italiano sul funzionamento del tool.\n"
            "5. required_envs: lista di TUTTE le variabili d'ambiente (es. tabelle di configurazione, file .env, codice sorgente). Per ogni variabile: key (stringa esatta), description, is_secret (true per password/token/key/secret), required, default (stringa o '').\n"
            "6. cli_args: lista degli argomenti CLI POSIZIONALI che l'utente DEVE configurare (es. directory consentite per filesystem, URL di connessione come argomento posizionale). NON includere flag come '-y' o il nome del pacchetto. Solo argomenti che variano per ogni installazione.\n"
            "   Per ogni cli_arg: name (nome descrittivo breve), description (spiegazione), required (bool), default (valore default o ''), placeholder (esempio concreto come '/data/files' o 'postgresql://user:pass@host/db').\n\n"
            "IMPORTANTE: Se il server MCP richiede directory consentite o percorsi come argomenti posizionali (come server-filesystem), includili in cli_args, NON in required_envs.\n"
            "IMPORTANTE: Se il server non richiede nessuna variabile d'ambiente né argomenti CLI posizionali specifici, lascia entrambe le liste vuote.\n\n"
            "Rispondi ESCLUSIVAMENTE con un JSON compatto nel seguente formato senza testo aggiuntivo:\n"
            "{\n"
            f'  "package_url": "{pkg_name}",\n'
            f'  "runner": "{runner}",\n'
            f'  "command_args": ["-y", "{pkg_name}"],\n'
            '  "description": "Descrizione del server MCP",\n'
            '  "required_envs": [\n'
            '    {"key": "NOME_VARIABILE", "description": "Descrizione", "is_secret": true, "required": true, "default": ""}\n'
            "  ],\n"
            '  "cli_args": [\n'
            '    {"name": "allowed_directory", "description": "Directory consentita per l\'accesso", "required": true, "default": "", "placeholder": "/path/to/dir"}\n'
            "  ]\n"
            "}\n\n"
            f"{prompt_context}"
        )

        resp = generator.run(messages=[ChatMessage.from_user(prompt)])
        replies = resp.get("replies") or []
        if replies:
            reply_obj = replies[0]
            if hasattr(reply_obj, "text") and reply_obj.text:
                reply_text = reply_obj.text
            elif hasattr(reply_obj, "_content") and reply_obj._content:
                reply_text = "".join(
                    getattr(c, "text", str(c)) for c in reply_obj._content
                )
            elif isinstance(reply_obj, dict):
                reply_text = str(
                    reply_obj.get("text") or reply_obj.get("content") or ""
                )
            else:
                reply_text = str(reply_obj)
            reply_text = str(reply_text).strip()
            logger.debug(
                "LLM raw reply (%d chars): %.300s", len(reply_text), reply_text
            )

            data = _extract_json_dict_from_llm_text(reply_text)
            if data:
                # Normalizza runner
                llm_runner = str(data.get("runner") or "").strip().lower()
                if llm_runner in (
                    "node",
                    "nodejs",
                    "npm",
                    "npx",
                    "typescript",
                    "javascript",
                ):
                    llm_runner = "npx"
                elif llm_runner in ("python", "py", "uvx", "pip"):
                    llm_runner = "uvx"
                else:
                    llm_runner = "uvx" if has_python else "npx"
                data["runner"] = llm_runner

                # Normalizza package_url
                llm_pkg = str(data.get("package_url") or "").strip()
                if not llm_pkg or llm_pkg.startswith("http"):
                    llm_pkg = pkg_name
                data["package_url"] = llm_pkg

                # Normalizza required_envs
                raw_envs = data.get("required_envs")
                norm_envs: List[McpEnvVarSpec] = []
                seen_keys: set[str] = set()

                if isinstance(raw_envs, list):
                    for item in raw_envs:
                        if isinstance(item, str):
                            k_str = item.strip()
                            if _is_valid_env_key(k_str) and k_str not in seen_keys:
                                is_sec = any(
                                    x in k_str.lower()
                                    for x in (
                                        "key",
                                        "token",
                                        "secret",
                                        "password",
                                        "auth",
                                        "pwd",
                                    )
                                )
                                norm_envs.append(
                                    McpEnvVarSpec(
                                        key=k_str,
                                        description=f"Variabile {k_str}",
                                        is_secret=is_sec,
                                        required=True,
                                        default="",
                                    )
                                )
                                seen_keys.add(k_str)
                        elif isinstance(item, dict) and item.get("key"):
                            k_str = str(item["key"]).strip()
                            if _is_valid_env_key(k_str) and k_str not in seen_keys:
                                is_sec = bool(item.get("is_secret")) or any(
                                    x in k_str.lower()
                                    for x in (
                                        "key",
                                        "token",
                                        "secret",
                                        "password",
                                        "auth",
                                        "pwd",
                                    )
                                )
                                norm_envs.append(
                                    McpEnvVarSpec(
                                        key=k_str,
                                        description=str(
                                            item.get("description")
                                            or f"Variabile {k_str}"
                                        ),
                                        is_secret=is_sec,
                                        required=bool(item.get("required", True)),
                                        default=str(item.get("default") or ""),
                                    )
                                )
                                seen_keys.add(k_str)

                data["required_envs"] = [e.model_dump() for e in norm_envs]

                # Normalizza cli_args
                raw_cli_args = data.get("cli_args")
                norm_cli_args: List[McpCliArgSpec] = []
                if isinstance(raw_cli_args, list):
                    for item in raw_cli_args:
                        if isinstance(item, dict) and item.get("name"):
                            try:
                                norm_cli_args.append(
                                    McpCliArgSpec(
                                        name=str(item.get("name", "")).strip(),
                                        description=str(item.get("description") or ""),
                                        required=bool(item.get("required", True)),
                                        default=str(item.get("default") or ""),
                                        placeholder=str(item.get("placeholder") or ""),
                                    )
                                )
                            except Exception:
                                pass
                data["cli_args"] = [a.model_dump() for a in norm_cli_args]

                # Arricchisci il risultato LLM con command_args ottimali
                result = McpServerAnalysisResult(**data)
                if not result.command_args:
                    if result.runner == "uvx":
                        result.command_args = [result.package_url]
                    else:
                        result.command_args = ["-y", result.package_url]
                return result
    except Exception as ex:
        logger.warning(
            "Analisi LLM GitHub Gitingest fallita per %s/%s (%s), fallback a parser manifesto/sorgente.",
            owner,
            repo,
            ex,
        )

    # Fallback deterministico basato su manifest, .env e codice sorgente (quando LLM non è disponibile)
    envs: List[McpEnvVarSpec] = []
    existing_keys: set[str] = set()

    # 1. File .env.example / .env.sample / .env
    for env_k in (".env.example", ".env.sample", ".env.template", ".env"):
        for m_fn, m_content in manifests.items():
            if m_fn.endswith(env_k):
                for line in m_content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if _is_valid_env_key(k) and k not in existing_keys:
                        is_secret = any(
                            x in k.lower()
                            for x in (
                                "key",
                                "token",
                                "secret",
                                "password",
                                "auth",
                                "pwd",
                            )
                        )
                        envs.append(
                            McpEnvVarSpec(
                                key=k,
                                description=f"Variabile {k} per {repo}",
                                is_secret=is_secret,
                                required=True,
                                default=v.strip().strip('"').strip("'")
                                if not is_secret
                                else "",
                            )
                        )
                        existing_keys.add(k)

    # 3. Scansione del codice sorgente per variabili effettive (process.env.VAR e os.getenv)
    all_combined_text = "\n\n".join(manifests.values())
    found_code_matches = set(
        re.findall(r"\bprocess\.env\.([A-Za-z][A-Za-z0-9_]+)\b", all_combined_text)
    )
    found_code_matches.update(
        re.findall(
            r"\bos\.(?:getenv|environ(?:\[|\.get\())\s*\(?[\"']([A-Za-z][A-Za-z0-9_]+)[\"']",
            all_combined_text,
        )
    )

    # 4. Scansione pattern di variabili maiuscole nel README.md (es. MCP_EMAIL_HOST, API_KEY, etc.)
    readme_text = ""
    for m_fn, m_content in manifests.items():
        if "readme" in m_fn.lower():
            readme_text += "\n" + m_content
    readme_env_matches = set(
        re.findall(
            r"\b(MCP_[A-Z0-9_]{2,40}|[A-Z0-9_]{3,35}_(?:KEY|TOKEN|SECRET|PASSWORD|HOST|PORT|URL|USER|ACCOUNT|DATABASE|API|AUTH|ADDRESS|PASS|PWD))\b",
            readme_text,
        )
    )
    found_code_matches.update(readme_env_matches)

    for k in sorted(found_code_matches):
        if _is_valid_env_key(k) and k not in existing_keys:
            is_secret = any(
                x in k.lower()
                for x in ("key", "token", "secret", "password", "auth", "pwd")
            )
            is_port_or_flag = any(
                x in k.lower()
                for x in ("port", "ssl", "tls", "pool", "limit", "verify", "debug")
            )
            envs.append(
                McpEnvVarSpec(
                    key=k,
                    description=f"Variabile {k} per {repo}",
                    is_secret=is_secret,
                    required=not is_port_or_flag,
                    default="",
                )
            )
            existing_keys.add(k)

    # Costruisci command_args ottimali
    if runner == "uvx":
        command_args = [pkg_name]
    else:
        command_args = ["-y", pkg_name]

    return McpServerAnalysisResult(
        package_url=pkg_name,
        runner=runner,
        description=f"Server MCP {owner}/{repo}",
        required_envs=envs,
        command_args=command_args,
    )
