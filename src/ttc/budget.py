import os


class CostBudget:
    """
    Gestisce un budget di costi (es. in token o latenza/denaro simulato) per
    un task complesso gestito via TTC (Test-Time Compute).
    """

    def __init__(self, max_tokens: int = None, max_attempts: int = 3):
        # Budget totale in token (se specificato)
        self.max_tokens = max_tokens or int(os.getenv("AION_TTC_MAX_TOKENS", "10000"))

        # Budget in iterazioni massime per le strategie
        self.max_attempts = max_attempts or int(os.getenv("AION_TTC_MAX_ATTEMPTS", "3"))

        # Token spesi finora nel task
        self.spent_tokens = 0
        self.attempts_used = 0

    def can_continue(self, estimated_next_cost: int = 1000) -> bool:
        if self.attempts_used >= self.max_attempts:
            return False

        if (self.spent_tokens + estimated_next_cost) > self.max_tokens:
            return False

        return True

    def consume_tokens(self, tokens: int):
        self.spent_tokens += tokens

    def consume_attempt(self):
        self.attempts_used += 1
