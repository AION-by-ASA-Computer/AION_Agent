"""Pure helpers for plan sidebar refresh deduplication (unit-testable)."""


def plan_sidebar_event_is_noop(
    *,
    stored_plan_id: str,
    incoming_plan_id: str,
    stored_revision: int,
    incoming_revision: int,
) -> bool:
    """
    Returns True when an orchestration_plan_pending event should not replace/update the sidebar.

    - Different plan_id → always apply (caller replaces singleton).
    - Same plan_id and incoming_revision <= stored_revision → duplicate / stale.
    """
    sp = (stored_plan_id or "").strip()
    ip = (incoming_plan_id or "").strip()
    if not ip:
        return True
    if sp != ip:
        return False
    return int(incoming_revision or 1) <= int(stored_revision or 0)
