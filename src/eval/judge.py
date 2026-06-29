import json
import asyncio
from src.main import get_agent
from src.agent_pipeline import AgentPipeline
from typing import Tuple


async def evaluate_with_llm_judge(case: dict, actual_output: str) -> Tuple[float, str]:
    """Valuta l'output usando il profilo LLM Judge."""
    expected = case.get("expected_output", "")
    input_text = case.get("input_text", "")

    prompt = f"""
    VALUTAZIONE:
    Input utente originale: {input_text}
    Output atteso (se presente): {expected}
    
    Output generato da valutare: {actual_output}
    
    Valuta accuratamente la risposta generata rispetto all'input e all'output atteso.
    Ricorda: Devi emettere SOLO un JSON valido con le chiavi "score" e "reasoning".
    """

    agent_instance, profile_name = await get_agent(
        "LLM Judge", session_id="eval_judge", user_id="eval"
    )
    pipeline = AgentPipeline(
        agent_instance,
        session_id="eval_judge",
        profile_name=profile_name,
        user_id="eval",
    )

    result = await pipeline.run(prompt)
    text = result.get("text", "")

    # Extract JSON
    try:
        # Pulisci markdown code blocks se presenti
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text.strip())
        score = float(data.get("score", 0.0))
        reasoning = data.get("reasoning", "")
        return score, reasoning
    except Exception as e:
        return 0.0, f"Error parsing judge output: {e}\nRaw output: {text}"
