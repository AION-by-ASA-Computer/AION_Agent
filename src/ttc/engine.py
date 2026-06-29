from .budget import CostBudget
from .strategies import TTCStrategyType, RefinementStrategy, BestOfNStrategy


class TTCEngine:
    """
    Motore principale per l'esecuzione di task tramite Test-Time Compute.
    Sceglie la strategia migliore basandosi sui parametri o sui preset.
    """

    def __init__(self):
        pass

    def get_strategy(
        self,
        strategy_type: TTCStrategyType,
        max_attempts: int = 3,
        max_tokens: int = 10000,
    ):
        budget = CostBudget(max_tokens=max_tokens, max_attempts=max_attempts)

        if strategy_type == TTCStrategyType.REFINEMENT:
            return RefinementStrategy(budget)
        elif strategy_type == TTCStrategyType.BEST_OF_N:
            return BestOfNStrategy(budget)
        else:
            # Default fallback
            return RefinementStrategy(budget)


ttc_engine = TTCEngine()
