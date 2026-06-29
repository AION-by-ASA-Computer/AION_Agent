from enum import Enum
import asyncio

class TTCStrategyType(Enum):
    BEST_OF_N = "best_of_n"
    SELF_CONSISTENCY = "self_consistency"
    REFINEMENT = "refinement"

class TTCStrategy:
    def __init__(self, budget):
        self.budget = budget

    async def run(self, pipeline, input_text: str):
        raise NotImplementedError("Sottoclassare e implementare run()")

class RefinementStrategy(TTCStrategy):
    """
    Strategia: Chiede all'agente di risolvere il problema. 
    Se c'è budget, chiede all'agente di riflettere e migliorare la risposta.
    """
    async def run(self, pipeline, input_text: str):
        # 1. First Attempt
        self.budget.consume_attempt()
        res = await pipeline.run(input_text)
        current_text = res.get("text", "")
        self.budget.consume_tokens(res.get("tokens_out", 500)) # stima se non fornito
        
        # 2. Refinements
        while self.budget.can_continue():
            self.budget.consume_attempt()
            refine_prompt = "Rifletti sulla tua risposta precedente. C'è qualche errore logico o margine di miglioramento? Se sì, correggila fornendo una nuova versione completa. Se è già perfetta, rispondi 'PERFETTA' e basta."
            
            refine_res = await pipeline.run(refine_prompt)
            refine_text = refine_res.get("text", "").strip()
            self.budget.consume_tokens(refine_res.get("tokens_out", 500))
            
            if "PERFETTA" in refine_text[:50].upper():
                break
                
            current_text = refine_text
            
        return {"text": current_text, "success": True, "attempts": self.budget.attempts_used}

class BestOfNStrategy(TTCStrategy):
    """
    Strategia: Genera N risposte in parallelo e usa un valutatore (o un'altra istanza) 
    per scegliere la migliore.
    """
    async def run(self, pipeline, input_text: str):
        N = min(3, self.budget.max_attempts)
        
        # Genera N task
        tasks = []
        for _ in range(N):
            tasks.append(pipeline.run(input_text))
            self.budget.consume_attempt()
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Sceglie la più lunga per simulare la "migliore" (in realtà andrebbe passata a llm_judge)
        valid_results = [r for r in results if isinstance(r, dict) and r.get("success")]
        
        if not valid_results:
            return {"text": "Errore nella generazione multipla", "success": False}
            
        best = max(valid_results, key=lambda x: len(x.get("text", "")))
        return best
