"""Haystack Agent con hook compattazione intra-turno (senza monkey-patch di run/run_async)."""

from __future__ import annotations

import inspect
import json
import logging
import time
from typing import Any, Type

from src.runtime.turn_compaction import set_agent_execution_context

logger = logging.getLogger("aion.agent")


_AionAgentCls: Type[Any] | None = None


# region agent log
def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    from src.runtime.turn_diagnostics import agent_debug_log

    agent_debug_log(hypothesis_id, location, message, data, run_id="aion_agent")


# endregion


def _signature_report(agent_cls: type) -> dict[str, Any]:
    try:
        run_p = len(inspect.signature(agent_cls.run).parameters)
        async_p = len(inspect.signature(agent_cls.run_async).parameters)
        return {
            "run_params": run_p,
            "async_params": async_p,
            "match": run_p == async_p,
            "run_id": id(agent_cls.run),
            "async_id": id(agent_cls.run_async),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _reload_haystack_agent_module() -> type:
    """Restituisce la classe Haystack Agent; reload solo se le firme run/run_async non coincidono."""
    import importlib
    import sys

    agents_pkg_name = "haystack.components.agents"
    agent_mod_name = "haystack.components.agents.agent"

    agents_mod = importlib.import_module(agents_pkg_name)
    Agent = agents_mod.Agent
    sig = _signature_report(Agent)
    # region agent log
    _dbg(
        "H6",
        "aion_agent.py:_reload_haystack_agent_module",
        "import_module",
        {
            "agents_in_sys": agents_pkg_name in sys.modules,
            "agent_in_sys": agent_mod_name in sys.modules,
            **sig,
        },
    )
    # endregion
    if sig.get("match"):
        return Agent

    logger.warning("Haystack Agent.run signature mismatch — reloading agent modules")
    importlib.import_module(agent_mod_name)
    if agent_mod_name in sys.modules:
        importlib.reload(sys.modules[agent_mod_name])
    if agents_pkg_name in sys.modules:
        importlib.reload(sys.modules[agents_pkg_name])
    else:
        importlib.import_module(agents_pkg_name)

    agents_mod = importlib.import_module(agents_pkg_name)
    # region agent log
    _dbg(
        "H6",
        "aion_agent.py:_reload_haystack_agent_module",
        "after_reload",
        _signature_report(agents_mod.Agent),
    )
    # endregion
    return agents_mod.Agent


def _build_aion_agent_class(base_agent: type) -> type:
    class AionAgent(base_agent):
        """Agent Haystack che espone ExecutionContext per compattazione mid-turn."""

        def _initialize_fresh_execution(self, *args: Any, **kwargs: Any):
            ctx = super()._initialize_fresh_execution(*args, **kwargs)
            set_agent_execution_context(ctx)
            # region agent log
            _dbg(
                "H4",
                "aion_agent.py:_initialize_fresh_execution",
                "exec_ctx_registered",
                {"has_state": bool(getattr(ctx, "state", None))},
            )
            # endregion
            return ctx

        def _initialize_from_snapshot(self, *args: Any, **kwargs: Any):
            ctx = super()._initialize_from_snapshot(*args, **kwargs)
            set_agent_execution_context(ctx)
            return ctx

    AionAgent.__name__ = "AionAgent"
    return AionAgent


def get_aion_agent_class() -> type:
    """Classe Agent sempre agganciata al modulo Haystack corrente (safe con uvicorn --reload)."""
    global _AionAgentCls
    base = _reload_haystack_agent_module()
    sig = _signature_report(base)
    # region agent log
    _dbg("H1", "aion_agent.py:get_aion_agent_class", "base_agent_signatures", sig)
    # endregion
    if not sig.get("match"):
        raise RuntimeError(
            f"Haystack Agent signatures invalid after reload: {sig}. "
            "Restart API: ./scripts/dev-api.sh"
        )
    _AionAgentCls = _build_aion_agent_class(base)
    sub_sig = _signature_report(_AionAgentCls)
    # region agent log
    _dbg(
        "H2", "aion_agent.py:get_aion_agent_class", "aion_subclass_signatures", sub_sig
    )
    # endregion
    if not sub_sig.get("match"):
        raise RuntimeError(f"AionAgent subclass signatures invalid: {sub_sig}")
    return _AionAgentCls


def create_aion_agent(*args: Any, **kwargs: Any) -> Any:
    """Factory: istanzia AionAgent con firme run/run_async valide."""
    cls = get_aion_agent_class()
    # region agent log
    _dbg(
        "H3",
        "aion_agent.py:create_aion_agent",
        "instantiate",
        {"class_name": cls.__name__, "base": cls.__mro__[1].__name__},
    )
    # endregion
    try:
        instance = cls(*args, **kwargs)
        # region agent log
        _dbg("H3", "aion_agent.py:create_aion_agent", "instantiate_ok", {"ok": True})
        # endregion
        return instance
    except Exception as exc:
        # region agent log
        _dbg(
            "H3",
            "aion_agent.py:create_aion_agent",
            "instantiate_failed",
            {"exc_type": type(exc).__name__, "exc": str(exc)[:500]},
        )
        # endregion
        raise


def ensure_haystack_agent_signatures_valid() -> None:
    """Verifica/ricostruisce la classe AionAgent (no-op se già valida)."""
    try:
        get_aion_agent_class()
    except Exception as exc:
        logger.warning("ensure_haystack_agent_signatures_valid: %s", exc)
        raise
