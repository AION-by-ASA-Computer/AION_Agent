import re

def exact_match(expected: str, actual: str) -> float:
    return 1.0 if expected.strip() == actual.strip() else 0.0

def contains_match(expected: str, actual: str) -> float:
    return 1.0 if expected.strip().lower() in actual.strip().lower() else 0.0

def regex_match(pattern: str, actual: str) -> float:
    try:
        return 1.0 if re.search(pattern, actual) else 0.0
    except re.error:
        return 0.0

EVALUATORS = {
    "exact_match": exact_match,
    "contains": contains_match,
    "regex": regex_match
}

def evaluate_case(case: dict, actual_output: str) -> float:
    eval_type = case.get("eval_type", "exact_match")
    expected = case.get("expected_output", "")
    
    eval_func = EVALUATORS.get(eval_type)
    if not eval_func:
        return 0.0
        
    return eval_func(expected, actual_output)
