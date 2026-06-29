import json
import logging

logger = logging.getLogger("aion.json_recovery")

# Stats for monitoring
_STATS = {"attempts": 0, "recovered": 0, "failed": 0}

def try_recover_json(raw: str) -> dict | None:
    """Attempt to repair malformed JSON from LLM tool calls."""
    _STATS["attempts"] += 1
    
    # Strategy 1: unescaped newlines/tabs
    try:
        fixed = _fix_unescaped_newlines(raw)
        result = json.loads(fixed)
        _STATS["recovered"] += 1
        logger.info("JSON recovered via newline fix")
        return result
    except json.JSONDecodeError:
        pass
    
    # Strategy 1.5: common truncations/empty objects (e.g. '{' or missing closing brace)
    stripped = raw.strip()
    if stripped == "{":
        _STATS["recovered"] += 1
        logger.info("JSON recovered: simple open brace '{' -> '{}'")
        return {}
    if stripped == "":
        _STATS["recovered"] += 1
        logger.info("JSON recovered: empty string -> '{}'")
        return {}
    if stripped.startswith("{") and not stripped.endswith("}"):
        try:
            result = json.loads(stripped + "}")
            _STATS["recovered"] += 1
            logger.info("JSON recovered: added closing brace '}'")
            return result
        except json.JSONDecodeError:
            pass

    # Strategy 2: json_repair library (if available)
    try:
        import json_repair
        result = json_repair.loads(raw)
        if isinstance(result, dict):
            _STATS["recovered"] += 1
            logger.info("JSON recovered via json_repair")
            return result
    except Exception:
        pass
    
    _STATS["failed"] += 1
    return None

def _fix_unescaped_newlines(s: str) -> str:
    """Fix literal newlines/tabs inside JSON string values."""
    in_string = False
    escape_next = False
    result = []
    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            result.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string:
            if ch == '\n': result.append('\\n')
            elif ch == '\r': result.append('\\r')
            elif ch == '\t': result.append('\\t')
            else: result.append(ch)
        else:
            result.append(ch)
    return ''.join(result)

def get_recovery_stats() -> dict:
    return dict(_STATS)
