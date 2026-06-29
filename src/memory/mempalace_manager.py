"""
Compat: long-term memory is implemented by LTMOrchestrator.
"""
from .ltm_orchestrator import LTMOrchestrator, ltm_orchestrator

MemPalaceManager = LTMOrchestrator
mempalace_manager = ltm_orchestrator
