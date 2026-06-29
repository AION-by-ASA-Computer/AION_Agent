"""Generazione skill in data/skills/generated (Hermes FASE B) — versione essenziale."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

from ..memory.llm_extract import complete_json_async
from ..skill_registry import skill_registry
from .dedup import find_similar_skill

logger = logging.getLogger("aion.learning.distiller")

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


class SkillDistiller:
    def __init__(self) -> None:
        self.min_tools = int(os.getenv("AION_SKILL_DISTILL_MIN_TOOLS", "5"))
        self.max_per_day = int(os.getenv("AION_SKILL_DISTILL_MAX_PER_DAY", "20"))
        self.dedup_threshold = float(os.getenv("AION_SKILL_DISTILL_DEDUP_THRESHOLD", "0.88"))
        self.out_dir = Path(
            os.getenv("AION_SKILL_GENERATED_DIR", "data/skills/generated")
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = Path("data/logs/skill_audit.jsonl")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _rate_limit_hit(self) -> bool:
        today = date.today().isoformat()
        if not self.audit_path.exists():
            return False
        count = 0
        with open(self.audit_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("op") == "create" and rec.get("date") == today:
                        count += 1
                except Exception:
                    continue
        return count >= self.max_per_day

    def _format_tool_calls_log(self, tool_calls: List[Dict[str, Any]]) -> str:
        try:
            max_chars = int(os.getenv("AION_SKILL_DISTILL_TOOL_LOG_MAX_CHARS", "8000"))
        except ValueError:
            max_chars = 8000
        lines: List[str] = []
        for evt in tool_calls or []:
            et = str(evt.get("type") or "")
            if et not in ("tool_start", "tool_end", "tool_error"):
                continue
            name = str(evt.get("name") or evt.get("tool") or "?")
            if et == "tool_start":
                args = evt.get("arguments") or evt.get("input") or {}
                try:
                    arg_str = json.dumps(args, ensure_ascii=False)[:200]
                except Exception:
                    arg_str = str(args)[:200]
                lines.append(f"START {name} args={arg_str}")
            elif et == "tool_end":
                out = str(evt.get("output") or "")[:300]
                lines.append(f"END {name} ok output={out}")
            else:
                err = str(evt.get("error") or "")[:300]
                lines.append(f"ERROR {name} {err}")
        return "\n".join(lines)[:max_chars]

    def _audit(self, op: str, payload: Dict[str, Any]) -> None:
        rec = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "date": date.today().isoformat(),
            "op": op,
            **payload,
        }
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    async def maybe_distill(
        self,
        session_id: str,
        profile_name: str,
        user_input: str,
        assistant_output: str,
        tool_calls: List[Dict[str, Any]],
    ) -> Optional[str]:
        if os.getenv("AION_SKILL_DISTILL_ENABLED", "0").lower() not in ("1", "true", "yes"):
            return None
        if len(tool_calls) < self.min_tools:
            return None
        if self._rate_limit_hit():
            logger.info("distill skipped: rate limit")
            return None

        system = (
            "Sei un distillatore di skill. Rispondi SOLO con JSON: "
            '{"should_create": bool, "reason": "...", "slug": "kebab-case", '
            '"description": "...", "tags": [], "procedure": ["step1"]}'
        )
        tools_section = self._format_tool_calls_log(tool_calls)
        user_prompt = (
            f"USER:\n{user_input[:2000]}\n\nASSISTANT:\n{assistant_output[:3000]}"
        )
        if tools_section:
            user_prompt += f"\n\nTOOLS:\n{tools_section}"
        try:
            data = await complete_json_async(system, user_prompt)
        except Exception as e:
            logger.warning("distill LLM failed: %s", e)
            return None
        if not isinstance(data, dict) or not data.get("should_create"):
            return None
        desc = (data.get("description") or "").strip()
        if not desc:
            return None
        similar = find_similar_skill(desc, threshold=self.dedup_threshold)
        if similar:
            logger.info("distill: similar skill %s", similar[0])
            self._audit("dedup_skip", {"existing": similar[0], "score": similar[1]})
            return None

        slug = _SLUG_RE.sub("", (data.get("slug") or "skill").lower().strip())[:60] or "skill"
        path = self.out_dir / f"{slug}.md"
        if path.exists():
            slug = f"{slug}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            path = self.out_dir / f"{slug}.md"

        body = "\n".join(
            f"{i}. {s}" for i, s in enumerate(data.get("procedure") or ["Vedi descrizione"], 1)
        )
        post = frontmatter.Post(
            content=f"# {data.get('slug', slug)}\n\n{body}",
            **{
                "name": slug,
                "description": desc,
                "tags": data.get("tags") or [],
                "status": "draft",
                "source": "generated",
                "version": 1,
            },
        )
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        skill_registry.reload()
        self._audit("create", {"slug": slug, "session_id": session_id, "profile": profile_name})
        logger.info("distilled skill %s", slug)
        return slug


skill_distiller = SkillDistiller()
