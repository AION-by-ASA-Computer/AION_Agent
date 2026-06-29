#!/usr/bin/env python3
"""Aggiunge frontmatter minimo alle skill .md senza YAML."""
from pathlib import Path

import frontmatter

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "config" / "skills"

DEFAULTS = {
    "core_protocol": {
        "description": "Regole d'oro AION: no allucinazioni, filtri, procedura memoria",
        "tags": ["core", "protocol"],
    },
    "promql_library": {
        "description": "Sintassi PromQL e libreria query comuni",
        "tags": ["prometheus", "promql"],
    },
    "infra_audit": {
        "description": "Audit infrastrutturale: incrocio documenti e metriche",
        "tags": ["audit", "infrastructure"],
    },
    "mempalace_protocol": {
        "description": "Protocollo MemPalace / memoria a lungo termine",
        "tags": ["memory", "ltm"],
    },
    "datasource_memory_protocol": {
        "description": "SQL QueryMemory + MemPalace navigation per datasource relazionali",
        "tags": ["memory", "sql", "mempalace", "navigation", "datasource"],
    },
    "llm_wiki": {
        "description": "Manutenzione LLM Wiki ad alta densità",
        "tags": ["wiki", "documentation"],
    },
    "ltm_extraction": {
        "description": "Schema estrazione LTM JSON (server-side)",
        "tags": ["memory", "internal"],
    },
}


def main() -> None:
    for md in sorted(SKILLS.glob("*.md")):
        post = frontmatter.loads(md.read_text(encoding="utf-8"))
        if post.metadata.get("name"):
            print("skip", md.name)
            continue
        stem = md.stem
        d = DEFAULTS.get(stem, {})
        post.metadata["name"] = stem
        post.metadata["description"] = d.get("description", stem.replace("_", " ").title())
        post.metadata["tags"] = d.get("tags", [])
        post.metadata["status"] = "verified"
        post.metadata["source"] = "curated"
        post.metadata["version"] = 1
        md.write_text(frontmatter.dumps(post), encoding="utf-8")
        print("migrated", md.name)


if __name__ == "__main__":
    main()
