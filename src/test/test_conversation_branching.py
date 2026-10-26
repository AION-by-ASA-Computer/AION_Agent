import asyncio
from pathlib import Path
import pytest
from fastapi import HTTPException

from src.api.chat_ui import (
    ConversationForkBody,
    fork_conversation_chat_ui,
    get_conversation_branches_chat_ui,
    get_conversation_chat_ui,
    get_conversation_messages_chat_ui,
    list_conversations_chat_ui,
)
from src.data.history_bridge import UnifiedHistoryBridge


async def _reset_unified_db(monkeypatch, tmp_path: Path) -> None:
    import src.data.engine as engine

    if engine._engine is not None:
        await engine._engine.dispose()
    engine._engine = None
    engine._session_factory = None
    monkeypatch.setenv("AION_UNIFIED_DB", "1")
    monkeypatch.setenv("AION_DEFAULT_TENANT_ID", "default")
    monkeypatch.setenv("AION_DB_URL", f"sqlite+aiosqlite:///{tmp_path / 'aion.db'}")
    monkeypatch.delenv("AION_CHAT_UI_INTERNAL_SECRET", raising=False)
    from src.settings import get_settings

    get_settings.cache_clear()


async def _seed_chat_tree() -> dict:
    bridge = UnifiedHistoryBridge()
    # Parent conv: 2 turni (seq 1, 2, 3, 4)
    m1 = await bridge.add_message(
        "conv_root", "user", "Primo messaggio utente", user_id="u1", message_id="m-u1"
    )
    m2 = await bridge.add_message(
        "conv_root",
        "assistant",
        "Prima risposta assistente",
        user_id="u1",
        message_id="m-a1",
    )
    m3 = await bridge.add_message(
        "conv_root",
        "user",
        "Secondo messaggio originale",
        user_id="u1",
        message_id="m-u2",
    )
    m4 = await bridge.add_message(
        "conv_root",
        "assistant",
        "Seconda risposta originale",
        user_id="u1",
        message_id="m-a2",
    )
    return {"m1": m1, "m2": m2, "m3": m3, "m4": m4}


def test_conversation_fork_and_branch_navigation(monkeypatch, tmp_path):
    async def run():
        await _reset_unified_db(monkeypatch, tmp_path)
        seed = await _seed_chat_tree()

        # 1. Verifica che la conversazione root appaia nella lista
        listed_init = await list_conversations_chat_ui(x_aion_user_id="u1")
        conv_ids_init = [c["id"] for c in listed_init["data"]]
        assert "conv_root" in conv_ids_init

        # 2. Esegui il fork su m-u2 (seq 3) con nuovo contenuto
        fork_res = await fork_conversation_chat_ui(
            "conv_root",
            ConversationForkBody(
                source_message_id="m-u2",
                new_content="Secondo messaggio MODIFICATO (ramo 2)",
            ),
            x_aion_user_id="u1",
        )

        child_id = fork_res["conversation_id"]
        new_msg_id = fork_res["message_id"]
        assert fork_res["root_conversation_id"] == "conv_root"
        assert fork_res["fork_seq"] == 3

        # 3. Dettagli conversazione child
        child_details = await get_conversation_chat_ui(child_id, x_aion_user_id="u1")
        assert child_details["root_conversation_id"] == "conv_root"
        assert child_details["forked_from_id"] == "conv_root"
        assert child_details["forked_at_message_id"] == "m-u2"
        assert child_details["fork_seq"] == 3

        # 4. Verifica sidebar: child non deve apparire se include_branches=False
        listed_default = await list_conversations_chat_ui(
            x_aion_user_id="u1", include_branches=False
        )
        default_ids = [c["id"] for c in listed_default["data"]]
        assert "conv_root" in default_ids
        assert child_id not in default_ids

        listed_with_branches = await list_conversations_chat_ui(
            x_aion_user_id="u1", include_branches=True
        )
        branch_ids = [c["id"] for c in listed_with_branches["data"]]
        assert "conv_root" in branch_ids
        assert child_id in branch_ids

        # 5. Verifica messaggi e navigazione branch nel parent
        parent_msgs = await get_conversation_messages_chat_ui(
            "conv_root", x_aion_user_id="u1"
        )
        msgs_p = parent_msgs["messages"]
        # seq 1 (primo messaggio) non ha biforcazioni
        assert "branches" not in msgs_p[0]

        # seq 3 (m-u2) deve avere le info del branch (1 / 2)
        u2_branch = msgs_p[2].get("branches")
        assert u2_branch is not None
        assert u2_branch["total"] == 2
        assert u2_branch["current_index"] == 1
        assert u2_branch["prev_branch_conversation_id"] is None
        assert u2_branch["next_branch_conversation_id"] == child_id

        # 6. Verifica messaggi e navigazione branch nel child
        child_msgs = await get_conversation_messages_chat_ui(
            child_id, x_aion_user_id="u1"
        )
        msgs_c = child_msgs["messages"]
        # Messaggio 1 clonato (seq 1)
        assert msgs_c[0]["content"] == "Primo messaggio utente"
        assert "branches" not in msgs_c[0]

        # Messaggio 2 clonato (seq 2)
        assert msgs_c[1]["content"] == "Prima risposta assistente"

        # Messaggio 3 modificato (seq 3) deve avere le info del branch (2 / 2)
        assert msgs_c[2]["content"] == "Secondo messaggio MODIFICATO (ramo 2)"
        child_u2_branch = msgs_c[2].get("branches")
        assert child_u2_branch is not None
        assert child_u2_branch["total"] == 2
        assert child_u2_branch["current_index"] == 2
        assert child_u2_branch["prev_branch_conversation_id"] == "conv_root"
        assert child_u2_branch["next_branch_conversation_id"] is None

        # 7. Terzo ramo dallo stesso punto di fork m-u2
        fork_res_3 = await fork_conversation_chat_ui(
            "conv_root",
            ConversationForkBody(
                source_message_id="m-u2",
                new_content="Terzo messaggio alternativo (ramo 3)",
            ),
            x_aion_user_id="u1",
        )
        child3_id = fork_res_3["conversation_id"]

        # Verifica che ora a seq 3 ci siano 3 rami (1/3, 2/3, 3/3)
        msgs_p_after = (
            await get_conversation_messages_chat_ui("conv_root", x_aion_user_id="u1")
        )["messages"]
        assert msgs_p_after[2]["branches"]["total"] == 3
        assert msgs_p_after[2]["branches"]["current_index"] == 1

        msgs_c1_after = (
            await get_conversation_messages_chat_ui(child_id, x_aion_user_id="u1")
        )["messages"]
        assert msgs_c1_after[2]["branches"]["total"] == 3
        assert msgs_c1_after[2]["branches"]["current_index"] == 2

        msgs_c3_after = (
            await get_conversation_messages_chat_ui(child3_id, x_aion_user_id="u1")
        )["messages"]
        assert msgs_c3_after[2]["branches"]["total"] == 3
        assert msgs_c3_after[2]["branches"]["current_index"] == 3

        # 8. Endpoint /branches
        branches_data = await get_conversation_branches_chat_ui(
            "conv_root", x_aion_user_id="u1"
        )
        assert branches_data["root_conversation_id"] == "conv_root"
        assert 3 in branches_data["branches"]
        assert branches_data["branches"][3]["total"] == 3

        # 9. Test isolamento rami: Fork a seq 1 (divergenza iniziale)
        fork_res_seq1 = await fork_conversation_chat_ui(
            "conv_root",
            ConversationForkBody(
                source_message_id="m-u1",
                new_content="Meteo Torino invece di Milano (fork seq 1)",
            ),
            x_aion_user_id="u1",
        )
        child_seq1_id = fork_res_seq1["conversation_id"]

        # A seq 1 ora ci sono 2 rami tra conv_root e child_seq1_id
        msgs_p_seq1 = (
            await get_conversation_messages_chat_ui("conv_root", x_aion_user_id="u1")
        )["messages"]
        assert msgs_p_seq1[0]["branches"]["total"] == 2
        assert msgs_p_seq1[0]["branches"]["current_index"] == 1
        assert (
            msgs_p_seq1[0]["branches"]["next_branch_conversation_id"] == child_seq1_id
        )

        msgs_c_seq1 = (
            await get_conversation_messages_chat_ui(child_seq1_id, x_aion_user_id="u1")
        )["messages"]
        assert msgs_c_seq1[0]["branches"]["total"] == 2
        assert msgs_c_seq1[0]["branches"]["current_index"] == 2
        assert msgs_c_seq1[0]["branches"]["prev_branch_conversation_id"] == "conv_root"

        # I rami di seq 3 di conv_root non devono confondersi né essere visibili in child_seq1_id
        assert len(msgs_c_seq1) == 1  # solo il nuovo messaggio forked a seq 1

    asyncio.run(run())
