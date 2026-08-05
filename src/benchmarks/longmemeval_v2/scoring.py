"""Official LongMemEval-V2 scoring: honours the per-question `eval_function` spec.

Each dataset row ships a spec such as
``norm_phrase_set_match|lower=true|normalize_hyphen=true|strip_punct=true|separators=,;|require_non_empty=true``.
The families in lme_v2_small are:

- ``norm_phrase_set_match`` / ``norm_phrase_set_match_ordered`` — normalised phrase comparison
- ``mc_choice_match`` / ``mc_choice_set_match`` — multiple-choice letters
- ``llm_abstention_checker`` — the question carries a false premise; the model must reject it
- ``llm_gotchas_checker`` — free-form advice, graded for semantic equivalence
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Dict, List, Tuple

from src.memory.llm_extract import complete_text_async_detailed

_BOXED_RE = re.compile(r"\\boxed\{([^{}]*)\}")
_DASH_RE = re.compile(r"[\u2010-\u2015\u2212]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_SINGLE_LETTER_RE = re.compile(r"^[A-H]$", re.IGNORECASE)
_LETTER_TOKEN_RE = re.compile(r"\b([A-H])\b")
_ANSWER_LETTER_RE = re.compile(
    r"(?:answer|option|choice)\b(?:\s+(?:is|are))?\W{0,4}\b([A-H])\b",
    re.IGNORECASE,
)

LLM_JUDGE_FAMILIES = ("llm_abstention_checker", "llm_gotchas_checker")

DEFAULT_SEPARATORS = ",;"


def parse_eval_function(spec: Any) -> Tuple[str, Dict[str, str]]:
    """Split ``family|k=v|k=v`` into its family name and options."""
    text = str(spec or "").strip()
    if not text:
        return "", {}
    parts = [p for p in text.split("|") if p.strip()]
    family = parts[0].strip() if parts else ""
    opts: Dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        opts[key.strip()] = value.strip()
    return family, opts


def _flag(opts: Dict[str, str], key: str, default: bool = False) -> bool:
    raw = opts.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_phrase(
    text: str,
    *,
    lower: bool = True,
    normalize_hyphen: bool = True,
    strip_punct: bool = True,
) -> str:
    out = unicodedata.normalize("NFKC", str(text or ""))
    if normalize_hyphen:
        out = _DASH_RE.sub("-", out).replace("-", " ")
    if strip_punct:
        out = _PUNCT_RE.sub(" ", out)
    out = _WS_RE.sub(" ", out).strip()
    return out.lower() if lower else out


def split_phrases(text: str, separators: str, **norm: bool) -> List[str]:
    seps = separators or DEFAULT_SEPARATORS
    pattern = "[" + re.escape(seps) + "]"
    phrases = []
    for raw in re.split(pattern, str(text or "")):
        phrase = normalize_phrase(raw, **norm)
        if phrase:
            phrases.append(phrase)
    return phrases


def extract_choice_letters(text: str) -> List[str]:
    """Pull multiple-choice letters out of a model answer."""
    raw = str(text or "").strip()
    if not raw:
        return []

    boxed = _BOXED_RE.findall(raw)
    candidate = boxed[-1].strip() if boxed else raw

    if _SINGLE_LETTER_RE.match(candidate):
        return [candidate.upper()]

    tokens = [t.strip() for t in re.split(r"[,;/\s]+", candidate) if t.strip()]
    letters = [t.upper() for t in tokens if _SINGLE_LETTER_RE.match(t)]
    if letters and len(letters) == len(tokens):
        return letters

    hinted = _ANSWER_LETTER_RE.search(raw)
    if hinted:
        return [hinted.group(1).upper()]

    # A bare "A" inside prose is usually the article, not a choice.
    if letters and len(candidate) <= 20:
        return letters

    for line in reversed([ln.strip() for ln in raw.splitlines() if ln.strip()]):
        stripped = line.rstrip(".)").strip()
        if _SINGLE_LETTER_RE.match(stripped):
            return [stripped.upper()]
    return []


def unbox(text: str) -> str:
    """Return the last ``\\boxed{...}`` payload, or the text itself."""
    boxed = _BOXED_RE.findall(str(text or ""))
    return boxed[-1].strip() if boxed else str(text or "").strip()


def _looks_like_non_answer(text: str) -> bool:
    low = normalize_phrase(text)
    return not low or low.startswith("unknown")


def _judge_enabled() -> bool:
    return os.getenv("AION_LME_V2_LLM_JUDGE", "1") == "1"


def _abstention_judge_prompt() -> str:
    return (
        "You grade answers to benchmark questions whose premise is FALSE. "
        "The REFERENCE states the true situation and corrects that false premise. "
        "Decide whether the CANDIDATE makes the same correction. "
        "Reply CORRECT only if the candidate explicitly conveys that the premise "
        "does not hold (e.g. the item, field, or step asked about does not exist), "
        "in substance matching the reference. "
        "A candidate that merely says it does not know, lacks evidence, or answers "
        "UNKNOWN is INCORRECT: it failed to identify the false premise. "
        "A candidate that answers the question as if the premise were true is INCORRECT. "
        "Reply with exactly one word: CORRECT or INCORRECT."
    )


def _gotchas_judge_prompt() -> str:
    return (
        "You grade answers to benchmark questions about environment pitfalls and "
        "recommended workarounds. Decide whether the CANDIDATE conveys the same "
        "essential guidance as the REFERENCE. Wording, ordering, and extra detail "
        "do not matter; missing or contradicting the key recommendation does. "
        "A candidate that says it does not know or answers UNKNOWN is INCORRECT. "
        "Reply with exactly one word: CORRECT or INCORRECT."
    )


async def _llm_judge(
    *,
    family: str,
    question: str,
    expected: str,
    actual: str,
) -> Dict[str, Any]:
    system = (
        _abstention_judge_prompt()
        if family == "llm_abstention_checker"
        else _gotchas_judge_prompt()
    )
    user = (
        f"QUESTION:\n{question.strip()[:4000]}\n\n"
        f"REFERENCE:\n{expected.strip()[:2000]}\n\n"
        f"CANDIDATE:\n{actual.strip()[:2000]}\n\n"
        "Verdict (CORRECT or INCORRECT):"
    )
    detail = await complete_text_async_detailed(
        system,
        user,
        max_tokens=int(os.getenv("AION_LME_V2_JUDGE_MAX_TOKENS", "16")),
        timeout=float(os.getenv("AION_LME_V2_JUDGE_TIMEOUT", "60")),
        disable_reasoning=True,
    )
    verdict_raw = str(detail.get("raw_text") or detail.get("text") or "")
    verdict = normalize_phrase(verdict_raw)
    if verdict.startswith("correct"):
        return {
            "score": 1.0,
            "reason": "llm_judge_correct",
            "verdict": verdict_raw.strip(),
        }
    if verdict.startswith("incorrect"):
        return {
            "score": 0.0,
            "reason": "llm_judge_incorrect",
            "verdict": verdict_raw.strip(),
        }
    return {
        "score": 0.0,
        "reason": "llm_judge_unparsable",
        "verdict": verdict_raw.strip(),
    }


async def score_case(
    *,
    question: str,
    expected: str,
    actual: str,
    eval_function: Any,
    raw_actual: str = "",
) -> Dict[str, Any]:
    """Score one case with the dataset's own eval_function semantics."""
    family, opts = parse_eval_function(eval_function)
    prediction = (actual or "").strip()
    reference = (expected or "").strip()
    detail: Dict[str, Any] = {"eval_function": family or "unspecified"}

    if not reference:
        return {**detail, "score": 0.0, "reason": "missing_reference"}
    if _flag(opts, "require_non_empty", True) and not prediction:
        return {**detail, "score": 0.0, "reason": "empty_prediction"}

    if family in LLM_JUDGE_FAMILIES:
        if not _judge_enabled():
            return {**detail, "score": 0.0, "reason": "llm_judge_disabled"}
        try:
            verdict = await _llm_judge(
                family=family,
                question=question,
                expected=reference,
                actual=raw_actual.strip() or prediction,
            )
        except Exception as exc:  # judge outage must not abort the run
            return {
                **detail,
                "score": 0.0,
                "reason": "llm_judge_error",
                "error": str(exc),
            }
        return {**detail, **verdict}

    if family in {"mc_choice_match", "mc_choice_set_match"}:
        gold = extract_choice_letters(reference)
        if not gold:
            # A few rows reuse the mc scorer for true/false answers.
            gold_norm = normalize_phrase(reference)
            pred_norm = normalize_phrase(unbox(raw_actual or prediction))
            ok = gold_norm == pred_norm
            detail.update({"expected_literal": gold_norm, "actual_literal": pred_norm})
            return {
                **detail,
                "score": 1.0 if ok else 0.0,
                "reason": "literal_match" if ok else "literal_mismatch",
            }
        pred = extract_choice_letters(raw_actual or prediction)
        detail.update({"expected_choices": gold, "actual_choices": pred})
        if not pred:
            return {**detail, "score": 0.0, "reason": "no_choice_letter_found"}
        if family == "mc_choice_match":
            ok = len(pred) == 1 and pred[0] == gold[0]
        else:
            ok = set(pred) == set(gold)
        return {
            **detail,
            "score": 1.0 if ok else 0.0,
            "reason": "mc_match" if ok else "mc_mismatch",
        }

    norm = {
        "lower": _flag(opts, "lower", True),
        "normalize_hyphen": _flag(opts, "normalize_hyphen", True),
        "strip_punct": _flag(opts, "strip_punct", True),
    }
    separators = opts.get("separators") or DEFAULT_SEPARATORS
    gold_phrases = split_phrases(reference, separators, **norm)
    pred_phrases = split_phrases(prediction, separators, **norm)
    detail.update(
        {
            "expected_phrases": gold_phrases,
            "actual_phrases": pred_phrases,
            "separators": separators,
        }
    )

    if not pred_phrases:
        return {**detail, "score": 0.0, "reason": "empty_prediction"}

    if family == "norm_phrase_set_match_ordered":
        ok = gold_phrases == pred_phrases
        reason = "phrase_list_match" if ok else "phrase_list_mismatch"
    else:
        ok = set(gold_phrases) == set(pred_phrases)
        reason = "phrase_set_match" if ok else "phrase_set_mismatch"
        if not ok:
            missing = [p for p in gold_phrases if p not in set(pred_phrases)]
            extra = [p for p in pred_phrases if p not in set(gold_phrases)]
            detail.update({"missing_phrases": missing, "extra_phrases": extra})
            if not missing and extra:
                reason = "phrase_set_over_answered"
            elif missing and not extra:
                reason = "phrase_set_under_answered"
    # Only a diagnostic relabel: "none" is a legitimate gold answer in this dataset.
    if not ok and _looks_like_non_answer(prediction):
        reason = "llm_answered_unknown"
    return {**detail, "score": 1.0 if ok else 0.0, "reason": reason}


def question_eval_function(question: Dict[str, Any]) -> str:
    return str(question.get("eval_function") or "")


def eval_function_family(question: Dict[str, Any]) -> str:
    family, _ = parse_eval_function(question_eval_function(question))
    return family or "unspecified"


def requires_image(question: Dict[str, Any]) -> bool:
    return bool(question.get("image"))


__all__ = [
    "LLM_JUDGE_FAMILIES",
    "eval_function_family",
    "extract_choice_letters",
    "normalize_phrase",
    "parse_eval_function",
    "question_eval_function",
    "requires_image",
    "score_case",
    "split_phrases",
]
