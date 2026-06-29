from src.a2a.plan_sidebar_dedup import plan_sidebar_event_is_noop


def test_dedup_same_plan_same_revision_is_noop():
    assert plan_sidebar_event_is_noop(
        stored_plan_id="p1",
        incoming_plan_id="p1",
        stored_revision=3,
        incoming_revision=3,
    )


def test_dedup_same_plan_lower_revision_is_noop():
    assert plan_sidebar_event_is_noop(
        stored_plan_id="p1",
        incoming_plan_id="p1",
        stored_revision=3,
        incoming_revision=2,
    )


def test_dedup_same_plan_higher_revision_applies():
    assert not plan_sidebar_event_is_noop(
        stored_plan_id="p1",
        incoming_plan_id="p1",
        stored_revision=3,
        incoming_revision=4,
    )


def test_dedup_different_plan_always_applies():
    assert not plan_sidebar_event_is_noop(
        stored_plan_id="p1",
        incoming_plan_id="p2",
        stored_revision=9,
        incoming_revision=1,
    )


def test_dedup_first_open_stored_zero():
    assert not plan_sidebar_event_is_noop(
        stored_plan_id="p1",
        incoming_plan_id="p1",
        stored_revision=0,
        incoming_revision=1,
    )
