"""AION Mnemos — native long-term memory (notes + hierarchical digests)."""

__all__ = ["mnemos_orchestrator"]


def __getattr__(name: str):
    if name == "mnemos_orchestrator":
        from .orchestrator import mnemos_orchestrator

        return mnemos_orchestrator
    raise AttributeError(name)
