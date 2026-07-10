import pytest
from unittest.mock import AsyncMock
from src.research.deep_research import DeepResearcher


@pytest.mark.anyio
async def test_deep_researcher_sets_language():
    researcher = DeepResearcher(llm_endpoint="", llm_model="test-model", language="it")
    assert researcher.language == "it"


@pytest.mark.anyio
async def test_deep_researcher_plan_injects_language():
    researcher = DeepResearcher(llm_endpoint="", llm_model="test-model", language="it")

    # Mock LLM response
    researcher._llm = AsyncMock(
        return_value='{"sub_questions": [], "key_topics": [], "success_criteria": ""}'
    )

    await researcher._create_plan("Cosa sono i LLM?")

    # Check that LLM was called with the Italian instruction
    called_messages = researcher._llm.call_args[0][0]
    prompt_content = called_messages[0]["content"]
    assert "strictly in Italiano" in prompt_content


@pytest.mark.anyio
async def test_deep_researcher_synthesis_injects_language():
    researcher = DeepResearcher(llm_endpoint="", llm_model="test-model", language="it")

    researcher._llm = AsyncMock(return_value="Rapporto di prova")

    await researcher._synthesize("Cosa sono i LLM?", [{"summary": "prova"}], "")

    called_messages = researcher._llm.call_args[0][0]
    prompt_content = called_messages[0]["content"]
    assert "strictly in Italiano" in prompt_content


@pytest.mark.anyio
async def test_deep_researcher_final_report_injects_language():
    researcher = DeepResearcher(llm_endpoint="", llm_model="test-model", language="fr")

    researcher._llm = AsyncMock(return_value="Rapport final détaillé")

    await researcher._final_report("Cosa sono i LLM?", "Report intermedio")

    called_messages = researcher._llm.call_args[0][0]
    prompt_content = called_messages[0]["content"]
    assert "strictly in Français" in prompt_content
