#!/usr/bin/env python3
"""Build config_std/benchmarks/mnemos_recall_adversarial.json.

This suite is designed to FAIL against the current Mnemos implementation.
Each category targets a known or suspected weakness; a passing score here is a
regression guard, a failing score is a work item.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config_std" / "benchmarks" / "mnemos_recall_adversarial.json"

_STOPWORDS = frozenset(
    """
    a an and are as at be been by can did do does for from had has have how i in
    is it its me my of on or our so than that the their them there they this to
    us was we were what when where which who whom why will with you your
    """.split()
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS}


def _case(
    id: str,
    category: str,
    scope_type: str,
    setup_notes: list,
    query: str,
    expected_substrings: list[str],
    *,
    recall_limit: int = 5,
    min_hits: int = 1,
    expect_top_k: int | None = None,
    forbidden_substrings: list[str] | None = None,
    prefer_hybrid: bool = False,
    filler: dict | None = None,
    extra_scope_type: str | None = None,
    extra_scope_notes: list | None = None,
    recall_scope: str | None = None,
    as_of: str | None = None,
    hard_delete_index: int | None = None,
    wake_forbidden_substrings: list[str] | None = None,
    rationale: str = "",
) -> dict:
    row: dict = {
        "id": id,
        "category": category,
        "scope_type": scope_type,
        "setup_notes": setup_notes,
        "query": query,
        "expected_substrings": expected_substrings,
        "recall_limit": recall_limit,
        "min_hits": min_hits,
    }
    if expect_top_k is not None:
        row["expect_top_k"] = expect_top_k
    if forbidden_substrings:
        row["forbidden_substrings"] = forbidden_substrings
    if prefer_hybrid:
        row["prefer_hybrid"] = True
    if filler:
        row["filler"] = filler
    if extra_scope_type:
        row["extra_scope_type"] = extra_scope_type
        row["extra_scope_notes"] = extra_scope_notes or []
    if recall_scope:
        row["recall_scope"] = recall_scope
    if as_of:
        row["as_of"] = as_of
    if hard_delete_index is not None:
        row["hard_delete_index"] = hard_delete_index
    if wake_forbidden_substrings:
        row["wake_forbidden_substrings"] = wake_forbidden_substrings
    if rationale:
        row["rationale"] = rationale
    return row


def _note(content: str, **kw) -> dict:
    row = {"content": content}
    row.update(kw)
    return row


# --------------------------------------------------------------------------
# 1. Alias / coreference — the discriminative term never appears verbatim
# --------------------------------------------------------------------------
def _alias_cases() -> list[dict]:
    """Every case carries sibling distractors that share the query's generic words,
    so the alias is the only signal that can separate the target."""
    rows = [
        ("alias_k8s", "project",
         "Kubernetes cluster prod-eu-1 hosts the payment service",
         ["Docker Swarm cluster legacy-1 hosts the reporting service",
          "Nomad cluster batch-1 hosts the ETL service",
          "OpenShift cluster sandbox-1 hosts the demo service"],
         "which k8s cluster runs payments", ["prod-eu-1"]),
        ("alias_postgres", "user",
         "Analytics warehouse runs on PostgreSQL 16 with columnar extensions",
         ["Reporting warehouse runs on MySQL 8 with row storage",
          "Archive warehouse runs on SQLite with plain files",
          "Streaming warehouse runs on ClickHouse with merge trees"],
         "which version of pg backs the analytics warehouse", ["PostgreSQL 16"]),
        ("alias_mfa_expand", "user",
         "MFA is enforced for every administrative account",
         ["SSO is enforced for every administrative account",
          "IP allowlisting is enforced for every administrative account",
          "Session timeout is enforced for every administrative account"],
         "is multi-factor authentication mandatory for admins", ["MFA"]),
        ("alias_sla_expand", "project",
         "Service Level Agreement guarantees 99.95 percent monthly uptime",
         ["Internal target guarantees 99.50 percent monthly uptime",
          "Best effort tier guarantees 95.00 percent monthly uptime",
          "Free tier guarantees no percent monthly uptime"],
         "what uptime does the SLA promise", ["99.95"]),
        ("alias_ci_expand", "project",
         "Continuous Integration pipeline runs on GitHub Actions runner pool",
         ["Deployment pipeline runs on ArgoCD controller pool",
          "Security scanning pipeline runs on Snyk cloud pool",
          "Release pipeline runs on Jenkins agent pool"],
         "where does CI execute the builds", ["GitHub Actions"]),
        ("alias_person_initial", "user",
         "Maria Rossi is the primary on-call engineer for the platform team",
         ["Luca Bianchi is the primary on-call engineer for the data team",
          "Anna Verdi is the primary on-call engineer for the mobile team",
          "Paolo Neri is the primary on-call engineer for the network team"],
         "who is M. Rossi on-call for", ["Maria Rossi"]),
        ("alias_region_name", "project",
         "Primary workloads run in eu-west-1 for lowest latency",
         ["Backup workloads run in eu-central-1 for lowest latency",
          "Batch workloads run in us-east-1 for lowest latency",
          "Training workloads run in us-west-2 for lowest latency"],
         "which Ireland region runs the primary workloads", ["eu-west-1"]),
        ("alias_iam_expand", "user",
         "IAM roles are provisioned through Terraform modules only",
         ["Network rules are provisioned through Ansible playbooks only",
          "DNS records are provisioned through Pulumi stacks only",
          "TLS certificates are provisioned through cert-manager only"],
         "how is identity and access management provisioned", ["Terraform"]),
    ]
    return [
        _case(cid, "alias_coref", scope, [target, *distractors], q, exp,
              recall_limit=5, expect_top_k=1,
              rationale="Distractors share every generic word; only the alias identifies the target.")
        for cid, scope, target, distractors, q, exp in rows
    ]


# --------------------------------------------------------------------------
# 9. Precision under stopword noise — irrelevant notes must not be returned
# --------------------------------------------------------------------------
def _precision_cases() -> list[dict]:
    """The default FTS path (AION_MNEMOS_FTS_PHRASE_QUERY=0) ORs every token of
    two characters or more, with no stopword filtering. Filler notes here share
    only articles and prepositions with the query: any filler that comes back is
    pure noise occupying a context slot."""
    rows = [
        ("prec_vault", "project",
         "Production credentials are stored in the Vault path secret/aion/prod",
         "where are the production credentials stored", ["secret/aion/prod"]),
        ("prec_snapshot", "project",
         "The rollback snapshot for the billing database is snap-db-4417",
         "what is the rollback snapshot for the billing database", ["snap-db-4417"]),
        ("prec_contact", "user",
         "The escalation contact for a security breach is secops@company.com",
         "who is the escalation contact for a security breach", ["secops@company.com"]),
        ("prec_endpoint", "project",
         "The metrics exporter for the API is on the port 9464",
         "what is the port of the metrics exporter for the API", ["9464"]),
        ("prec_window", "user",
         "The maintenance window for the cluster is on the first Tuesday",
         "when is the maintenance window for the cluster", ["first Tuesday"]),
    ]
    return [
        _case(cid, "precision_noise", scope, [target], q, exp,
              recall_limit=10,
              forbidden_substrings=["NOISEMARK"],
              filler={"count": 40, "position": "after",
                      "template": "NOISEMARK {i} is a note that has none of the terms in it"},
              rationale="Filler shares only stopwords with the query; returning any of it is a precision loss.")
        for cid, scope, target, q, exp in rows
    ]


# --------------------------------------------------------------------------
# 2. True paraphrase — zero content-token overlap (enforced by assertion)
# --------------------------------------------------------------------------
def _paraphrase_cases() -> list[dict]:
    """Each case ships sibling notes so that a stopword match cannot uniquely
    identify the target: without semantics the target has to be guessed."""
    _SIBLINGS = [
        "The office printer on the second floor needs a badge tap",
        "The cafeteria serves the soup of the day at noon",
        "The bike storage is behind the main entrance of the building",
    ]
    rows = [
        ("para_backup_retention", "project",
         ["Backups are retained 35 days inside an encrypted vault"],
         "how long do we keep copies of the production database", ["35 days"]),
        ("para_deploy_window", "user",
         ["Deploy window Sunday 02:00-04:00 UTC every week"],
         "when is the release slot scheduled on weekends", ["02:00"]),
        ("para_oncall", "user",
         ["Maria Rossi is primary on-call engineer"],
         "who should be paged during a production outage", ["Maria Rossi"]),
        ("para_password", "user",
         ["Passwords must rotate every 90 days per policy"],
         "credential renewal cadence enforced company wide", ["90"]),
        ("para_ratelimit", "project",
         ["API rate limit 1200 requests per minute per tenant"],
         "throttling ceiling applied to each customer", ["1200"]),
        ("para_encryption", "project",
         ["All customer data encrypted at rest with AES-256"],
         "which cipher protects stored records", ["AES-256"]),
        ("para_logs", "project",
         ["Application logs kept 14 days in hot storage then archived"],
         "how far back can engineers search runtime output", ["14"]),
        ("para_severity", "user",
         ["P1 incident means complete service outage affecting all users"],
         "what qualifies as a sev-one emergency", ["P1"]),
    ]
    return [
        _case(cid, "true_paraphrase", scope, [*notes, *_SIBLINGS], q, exp,
              prefer_hybrid=True, expect_top_k=1,
              rationale="Query shares zero content tokens with the target; siblings absorb stopword matches.")
        for cid, scope, notes, q, exp in rows
    ]


# --------------------------------------------------------------------------
# 3. Temporal validity — superseded values must never surface as current
# --------------------------------------------------------------------------
def _temporal_cases() -> list[dict]:
    return [
        _case("temporal_db_choice", "temporal_validity", "user",
              [_note("Analytics database of choice is MySQL 8", age_days=400),
               _note("Analytics database of choice is PostgreSQL 16", supersedes=0)],
              "analytics database of choice", ["PostgreSQL 16"],
              forbidden_substrings=["MySQL 8"],
              rationale="Supersede chain must resolve to the current value."),
        _case("temporal_oncall", "temporal_validity", "user",
              [_note("Primary on-call engineer is Luca Bianchi", age_days=300),
               _note("Primary on-call engineer is Maria Rossi", supersedes=0)],
              "primary on-call engineer", ["Maria Rossi"],
              forbidden_substrings=["Luca Bianchi"]),
        _case("temporal_three_gen", "temporal_validity", "project",
              [_note("API base URL is https://v1.example.com", age_days=500),
               _note("API base URL is https://v2.example.com", age_days=200, supersedes=0),
               _note("API base URL is https://v3.example.com", supersedes=1)],
              "API base URL", ["v3.example.com"],
              forbidden_substrings=["v1.example.com", "v2.example.com"],
              rationale="Three-generation chain; only the terminal note is current."),
        _case("temporal_stale_match", "temporal_validity", "project",
              [_note("Deployment uses Ansible playbooks for rollout", age_days=365),
               _note("Deployment now uses ArgoCD GitOps sync", supersedes=0)],
              "Ansible playbooks rollout deployment", ["ArgoCD"],
              forbidden_substrings=["Ansible"],
              rationale="Query matches the stale note lexically; chain must redirect."),
        _case("temporal_retention", "temporal_validity", "project",
              [_note("Log retention is 7 days", age_days=250),
               _note("Log retention is 30 days", supersedes=0)],
              "log retention days", ["30 days"],
              forbidden_substrings=["7 days"]),
    ]


def _as_of_cases() -> list[dict]:
    return [
        _case(
            "asof_lease_past",
            "as_of_query",
            "user",
            [
                _note("Office lease expires 2026-12-31", valid_from="2025-01-01T00:00:00Z"),
                _note("Office lease expires 2027-06-30", valid_from="2026-07-01T00:00:00Z"),
            ],
            "office lease expiration date",
            ["2026-12-31"],
            forbidden_substrings=["2027-06-30"],
            as_of="2026-03-01T00:00:00Z",
            rationale="as_of before the second fact's valid_from must surface the earlier lease.",
        ),
        _case(
            "asof_budget_future",
            "as_of_query",
            "project",
            [
                _note("Q1 budget cap is 120000 EUR", valid_from="2026-01-01T00:00:00Z"),
                _note("Q2 budget cap is 150000 EUR", valid_from="2026-04-01T00:00:00Z"),
            ],
            "budget cap amount",
            ["120000"],
            forbidden_substrings=["150000"],
            as_of="2026-02-15T00:00:00Z",
        ),
        _case(
            "asof_oncall_rotation",
            "as_of_query",
            "user",
            [
                _note("Primary on-call is Alice", valid_from="2026-01-01T00:00:00Z", valid_to="2026-03-01T00:00:00Z"),
                _note("Primary on-call is Bob", valid_from="2026-03-01T00:00:00Z"),
            ],
            "primary on-call engineer",
            ["Alice"],
            forbidden_substrings=["Bob"],
            as_of="2026-02-20T00:00:00Z",
        ),
    ]


def _deletion_cases() -> list[dict]:
    return [
        _case(
            "delete_hard_wake",
            "deletion_completeness",
            "user",
            [_note("Secret API token is sk-live-abcdef123456")],
            "secret API token",
            [],
            min_hits=0,
            hard_delete_index=0,
            wake_forbidden_substrings=["sk-live-abcdef123456"],
            rationale="Hard-deleted note must not appear in wake digest text.",
        ),
        _case(
            "delete_hard_recall",
            "deletion_completeness",
            "project",
            [_note("Deprecated endpoint is /api/v1/legacy/users")],
            "legacy users endpoint",
            [],
            min_hits=0,
            hard_delete_index=0,
            forbidden_substrings=["/api/v1/legacy/users"],
            rationale="Hard-deleted note must not be returned by recall.",
        ),
    ]


# --------------------------------------------------------------------------
# 4. Contradiction — both notes active, no supersede hint was ever emitted
# --------------------------------------------------------------------------
def _contradiction_cases() -> list[dict]:
    rows = [
        ("contra_region", "project",
         "Primary deploy region is eu-west-1",
         "Primary deploy region is eu-central-1",
         "primary deploy region", ["eu-central-1"], ["eu-west-1"]),
        ("contra_db", "user",
         "Preferred cache layer is Memcached",
         "Preferred cache layer is Redis",
         "preferred cache layer", ["Redis"], ["Memcached"]),
        ("contra_sla", "project",
         "Support SLA for P1 tickets is 4 hours",
         "Support SLA for P1 tickets is 1 hour",
         "support SLA P1 tickets", ["1 hour"], ["4 hours"]),
        ("contra_owner", "project",
         "Technical owner of the billing service is team Alpha",
         "Technical owner of the billing service is team Delta",
         "technical owner billing service", ["team Delta"], ["team Alpha"]),
        ("contra_language", "user",
         "Chat interface language preference is English",
         "Chat interface language preference is Italian",
         "chat interface language preference", ["Italian"], ["English"]),
    ]
    return [
        _case(cid, "contradiction", scope,
              [_note(old, age_days=180), _note(new)],
              q, exp, expect_top_k=1, forbidden_substrings=None,
              rationale="Both notes are active and contradictory; the newer must win rank 1.")
        for cid, scope, old, new, q, exp, _stale in rows
    ]


# --------------------------------------------------------------------------
# 5. Recency ranking — equal lexical match, newer must rank first
# --------------------------------------------------------------------------
def _recency_cases() -> list[dict]:
    rows = [
        ("recency_budget", "project",
         "Infrastructure budget approved at 120000 EUR",
         "Infrastructure budget approved at 180000 EUR",
         "infrastructure budget approved", ["180000"]),
        ("recency_headcount", "user",
         "Platform team headcount is 6 engineers",
         "Platform team headcount is 9 engineers",
         "platform team headcount engineers", ["9 engineers"]),
        ("recency_version", "project",
         "Runtime pinned to Python 3.11",
         "Runtime pinned to Python 3.13",
         "runtime pinned Python version", ["3.13"]),
        ("recency_threshold", "project",
         "Alert threshold for error rate is 5 percent",
         "Alert threshold for error rate is 2 percent",
         "alert threshold error rate percent", ["2 percent"]),
    ]
    return [
        _case(cid, "recency_rank", scope,
              [_note(old, age_days=540), _note(new)],
              q, exp, expect_top_k=1,
              rationale="Identical lexical profile; only created_at separates them.")
        for cid, scope, old, new, q, exp in rows
    ]


# --------------------------------------------------------------------------
# 6. Importance ranking — importance 5 must outrank importance 1
# --------------------------------------------------------------------------
def _importance_cases() -> list[dict]:
    rows = [
        ("imp_rollback", "project",
         "Rollback procedure mentioned casually in a side conversation",
         "Rollback procedure: run scripts/rollback.sh with the snapshot id",
         "rollback procedure", ["scripts/rollback.sh"]),
        ("imp_contact", "user",
         "Emergency contact discussed briefly during standup",
         "Emergency contact is secops@company.com available 24x7",
         "emergency contact", ["secops@company.com"]),
        ("imp_credentials", "project",
         "Credentials topic raised in a planning meeting",
         "Credentials are stored in Vault path secret/aion/prod",
         "credentials stored", ["secret/aion/prod"]),
        ("imp_policy", "user",
         "Data policy mentioned without detail in an email thread",
         "Data policy requires EU-only residency for all customer PII",
         "data policy", ["EU-only residency"]),
    ]
    return [
        _case(cid, "importance_rank", scope,
              [_note(low, importance=1), _note(high, importance=5)],
              q, exp, expect_top_k=1,
              rationale="Both notes match; importance is the only quality signal available.")
        for cid, scope, low, high, q, exp in rows
    ]


# --------------------------------------------------------------------------
# 7. Cross-scope competition — project note must survive a crowded user scope
# --------------------------------------------------------------------------
def _cross_scope_cases() -> list[dict]:
    def _crowd(topic: str) -> list[str]:
        return [f"User note {i} about {topic} in a general context" for i in range(1, 13)]

    rows = [
        ("cross_deploy", "deploy",
         "Project deploy target is namespace alibr-prod in cluster eu-west",
         "deploy target namespace", ["alibr-prod"]),
        ("cross_datasource", "datasource",
         "Project datasource DSN is postgres://alibr-ro@db/internal",
         "datasource DSN connection", ["alibr-ro"]),
        ("cross_owner", "owner",
         "Project technical owner is team-platform@company.com",
         "technical owner contact", ["team-platform"]),
        ("cross_runbook", "runbook",
         "Project runbook for restart lives at docs/runbooks/restart.md",
         "runbook restart location", ["docs/runbooks/restart.md"]),
        ("cross_quota", "quota",
         "Project quota is 40 vCPU and 160 GiB memory",
         "quota vCPU memory", ["40 vCPU"]),
    ]
    return [
        _case(cid, "cross_scope", "user", _crowd(topic), q, exp,
              recall_limit=10,
              extra_scope_type="project", extra_scope_notes=[proj],
              recall_scope="across",
              rationale="User scope returns a full page of lexical matches; project note must still surface.")
        for cid, topic, proj, q, exp in rows
    ]


# --------------------------------------------------------------------------
# 8. Scale — target buried under hundreds of notes
# --------------------------------------------------------------------------
def _scale_cases() -> list[dict]:
    """Filler deliberately contains the same articles and prepositions as the
    queries, so a target cannot be found by matching a stopword."""
    return [
        _case("scale_discriminative", "scale_recall", "project",
              ["Node 447 check outcome: the disk controller error, replaced 2026-04-02"],
              "the node 447 disk controller error outcome", ["disk controller error"],
              recall_limit=10, expect_top_k=1,
              filler={"count": 600, "position": "after",
                      "template": "Routine check completed for the service node {i} with the status nominal"},
              rationale="Discriminative token under 600 notes; measures BM25 and latency at scale."),
        _case("scale_semantic", "scale_recall", "project",
              ["The rollout was halted because the canary cohort showed elevated latency"],
              "why did we stop the gradual release", ["canary cohort"],
              recall_limit=10, prefer_hybrid=True, expect_top_k=1,
              filler={"count": 600, "position": "after",
                      "template": "Routine check completed for the service node {i} with the status nominal"},
              rationale="Semantic match beyond the embedding scan window (default 300 notes)."),
        _case("scale_phrase", "scale_recall", "project",
              ["Incident INC-2026-9911 root cause was a corrupted migration lock"],
              '"corrupted migration lock" incident root cause', ["INC-2026-9911"],
              recall_limit=10, expect_top_k=1,
              filler={"count": 400, "position": "before",
                      "template": "Deployment {i} for the service completed without a root cause finding"},
              rationale="Phrase query against 400 notes sharing the query's common words."),
        _case("scale_common_words", "scale_recall", "project",
              ["Service node 288 required a manual restart after the memory leak"],
              "which node needed a manual restart for a memory leak", ["node 288"],
              recall_limit=10, expect_top_k=1,
              filler={"count": 500, "position": "after",
                      "template": "Service node {i} restart check completed with no memory issue found"},
              rationale="Target shares almost every token with the filler; BM25 has little to work with."),
    ]


def build_cases() -> list[dict]:
    return [
        *_alias_cases(),
        *_paraphrase_cases(),
        *_temporal_cases(),
        *_as_of_cases(),
        *_deletion_cases(),
        *_contradiction_cases(),
        *_recency_cases(),
        *_importance_cases(),
        *_cross_scope_cases(),
        *_scale_cases(),
        *_precision_cases(),
    ]


def _assert_paraphrase_honesty(cases: list[dict]) -> None:
    """A 'true_paraphrase' case is only honest if the query shares no content token
    with its notes. Without this guard the category silently degrades into a
    keyword test that FTS can pass, which is exactly what happened in the
    original full dataset."""
    for case in cases:
        if case.get("category") != "true_paraphrase":
            continue
        note_tokens: set[str] = set()
        for note in case["setup_notes"]:
            content = note["content"] if isinstance(note, dict) else note
            note_tokens |= _tokens(content)
        overlap = _tokens(case["query"]) & note_tokens
        if overlap:
            raise AssertionError(
                f"{case['id']}: query overlaps note tokens {sorted(overlap)} — "
                "not a true paraphrase"
            )


def main() -> None:
    cases = build_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    _assert_paraphrase_honesty(cases)

    categories: dict[str, int] = {}
    for c in cases:
        cat = c.get("category", "uncategorized")
        categories[cat] = categories.get(cat, 0) + 1

    payload = {
        "title": "Mnemos recall adversarial benchmark",
        "description": (
            "Adversarial suite targeting known Mnemos weaknesses: alias resolution, "
            "true paraphrase, temporal validity, contradiction, ranking signals, "
            "cross-scope competition and scale. Failures are work items, not bugs "
            "in the dataset."
        ),
        "version": 1,
        "case_count": len(cases),
        "categories": categories,
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUT}")
    print("Categories:", categories)


if __name__ == "__main__":
    main()
