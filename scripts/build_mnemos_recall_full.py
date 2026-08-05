#!/usr/bin/env python3
"""Build config_std/benchmarks/mnemos_recall_full.json from structured case definitions."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config_std" / "benchmarks" / "mnemos_recall_full.json"

# Shared distractor notes for dense-corpus cases
_DENSE_NOISE = [
    "Team standup every Monday at 09:30 in room B12",
    "Coffee machine refill requested for floor 2 pantry",
    "Parking lot gate code rotates on the first of each month",
    "Office Wi-Fi SSID is AION-CORP guest password at reception",
    "HR policy: submit PTO requests two weeks in advance",
    "Printer on floor 3 requires badge tap before release",
    "Cafeteria menu: soup and salad bar on Wednesdays",
    "Fire drill scheduled quarterly, follow green exit signs",
    "VPN client must be updated to version 5.4.2 or later",
    "Expense reports due by Friday 17:00 Europe/Rome",
    "Meeting room Maple seats 8 people with HDMI adapter",
    "Slack channel #platform-alerts is for production incidents only",
    "Badge access to server room requires manager approval",
    "Annual security training completion tracked in LMS portal",
    "Desk booking system opens reservations at 08:00 daily",
    "Guest Wi-Fi voucher expires after 24 hours",
    "Elevator maintenance window Sunday 06:00-08:00",
    "Lost badge report to reception desk immediately",
    "Kitchen dishwasher load before leaving office",
    "Bike storage registration form on intranet home page",
]


def _case(
    id: str,
    category: str,
    scope_type: str,
    setup_notes: list[str],
    query: str,
    expected_substrings: list[str],
    *,
    recall_limit: int = 5,
    min_hits: int = 1,
    forbidden_substrings: list[str] | None = None,
    prefer_hybrid: bool = False,
    negative_scope_type: str | None = None,
    negative_notes: list[str] | None = None,
    negative_query: str | None = None,
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
    if forbidden_substrings:
        row["forbidden_substrings"] = forbidden_substrings
    if prefer_hybrid:
        row["prefer_hybrid"] = True
    if negative_scope_type:
        row["negative_scope_type"] = negative_scope_type
        row["negative_notes"] = negative_notes or []
        row["negative_query"] = negative_query or query
    return row


def build_cases() -> list[dict]:
    cases: list[dict] = []

    # --- FTS keyword (10) ---
    fts_kw = [
        ("kw_postgres", "user", ["User prefers PostgreSQL over MySQL for analytics workloads", "Lunch at noon on Fridays"], "database preference PostgreSQL", ["PostgreSQL"]),
        ("kw_kubernetes", "project", ["Production cluster runs on Kubernetes 1.29 in eu-west-1", "Staging still on docker-compose"], "kubernetes production cluster version", ["Kubernetes", "1.29"]),
        ("kw_stripe", "user", ["Billing integration uses Stripe webhook endpoint /hooks/stripe", "PayPal deprecated last quarter"], "payment stripe webhook", ["Stripe"]),
        ("kw_pagerduty", "project", ["On-call rotation synced from PagerDuty schedule PLATFORM", "Backup contact is ops-hotline@company.com"], "on-call pagerduty platform", ["PagerDuty"]),
        ("kw_redis", "user", ["Session cache stored in Redis DB 2 with 30min TTL", "Memcached removed from legacy stack"], "session cache redis TTL", ["Redis"]),
        ("kw_grafana", "project", ["Dashboards live in Grafana folder SRE-Core", "Kibana only used for logs"], "grafana dashboards SRE", ["Grafana"]),
        ("kw_saml", "user", ["SSO login via SAML IdP Okta prod tenant", "Local accounts disabled for staff"], "SSO SAML Okta login", ["SAML", "Okta"]),
        ("kw_terraform", "project", ["IaC managed with Terraform Cloud workspace aion-prod", "Manual console changes forbidden"], "infrastructure terraform cloud", ["Terraform"]),
        ("kw_jira", "user", ["Sprint board JIRA project KEY=PLAT", "Linear trial ended"], "sprint board jira PLAT", ["JIRA", "PLAT"]),
        ("kw_openapi", "project", ["Public API spec published as OpenAPI 3.1 at /docs/openapi.json", "SOAP gateway retired"], "API OpenAPI specification", ["OpenAPI"]),
    ]
    for cid, scope, notes, query, expected in fts_kw:
        cases.append(_case(cid, "fts_keyword", scope, notes, query, expected))

    # --- FTS phrase (8) ---
    phrase_cases = [
        ("ph_incident_mobile", "project", ["menu_options: Incident Mobile, Incident Portal, My Open Incidents", "traj=t1 step=2 url=/incidents action=open Filters"], '"Incident Mobile" Filters portal', ["Incident Mobile"]),
        ("ph_dell_xps", "project", ["catalog_options: Dell XPS 15, Lenovo ThinkPad X1", "Price filter max 1500 EUR"], '"Dell XPS" laptop catalog', ["Dell XPS"]),
        ("ph_my_open", "project", ["menu_options: All Incidents, My Open Incidents, Assigned to me", "User role: fulfiller"], '"My Open Incidents" filter list', ["My Open Incidents"]),
        ("ph_service_catalog", "project", ["Page title: Service Catalog - Request something", "Category Hardware visible"], '"Service Catalog" request hardware', ["Service Catalog"]),
        ("ph_change_advisory", "user", ["CAB meeting notes: Change Advisory Board meets Thursdays", "Emergency changes need VP approval"], '"Change Advisory Board" meeting', ["Change Advisory Board"]),
        ("ph_data_residency", "project", ["Policy: Data Residency EU-only for customer PII", "US shard is analytics only"], '"Data Residency" EU customer PII', ["Data Residency"]),
        ("ph_zero_trust", "user", ["Architecture principle: Zero Trust network access for all VPN users", "Legacy flat network decommissioned"], '"Zero Trust" VPN access', ["Zero Trust"]),
        ("ph_runbook_restart", "project", ["runbook: Restart API pods Runbook v3.2 after memory leak alert", "Do not restart during backup window"], '"Restart API pods" runbook', ["Restart API pods"]),
    ]
    for cid, scope, notes, query, expected in phrase_cases:
        cases.append(_case(cid, "fts_phrase", scope, notes, query, expected))

    # --- Scope isolation (8) ---
    cases.append(_case("scope_user_secret", "scope_isolation", "user", ["Secret user token ALPHA-42 for staging API"], "ALPHA-42 secret token", ["ALPHA-42"], negative_scope_type="project", negative_notes=["Unrelated billing dashboard config"]))
    cases.append(_case("scope_user_pii", "scope_isolation", "user", ["Personal phone +39-333-1234567 only for on-call contact"], "phone on-call contact", ["333-1234567"], negative_scope_type="project", negative_notes=["Project wiki homepage content"]))
    cases.append(_case("scope_user_salary", "scope_isolation", "user", ["Salary band L4 approved for user giuseppe 2026"], "salary band giuseppe L4", ["L4"], negative_scope_type="project", negative_notes=["Office seating plan floor 2"]))
    cases.append(_case("scope_proj_api_key", "scope_isolation", "project", ["Project API key sk-proj-ALIBR-9f2a for alibr integration"], "sk-proj-ALIBR API key", ["sk-proj-ALIBR"], negative_scope_type="user", negative_notes=["User hobby: weekend hiking trails"]))
    cases.append(_case("scope_proj_webhook", "scope_isolation", "project", ["Webhook signing secret whsec_alibr_prod_88 for alibr"], "webhook secret alibr prod", ["whsec_alibr"], negative_scope_type="user", negative_notes=["User prefers dark mode in chat"]))
    cases.append(_case("scope_proj_datasource", "scope_isolation", "project", ["Datasource DSN postgres://alibr-ro@db/internal for read-only queries"], "datasource alibr read-only postgres", ["alibr-ro"], negative_scope_type="user", negative_notes=["User lunch preference vegetarian"]))
    cases.append(_case("scope_proj_deploy", "scope_isolation", "project", ["Deploy target namespace alibr-prod in cluster eu-west"], "deploy namespace alibr-prod", ["alibr-prod"], negative_scope_type="user", negative_notes=["User timezone Europe/Rome"]))
    cases.append(_case("scope_proj_owner", "scope_isolation", "project", ["Technical owner for alibr project: team-platform@company.com"], "technical owner alibr platform team", ["team-platform"], negative_scope_type="user", negative_notes=["User favorite IDE VS Code"]))

    # --- Semantic paraphrase / hybrid (12) ---
    semantic = [
        ("sem_deploy_window", "user", ["Production deploy window Sunday 02:00-04:00 UTC", "Coffee on floor 2"], "when can we deploy to production", ["Sunday", "02:00"], True),
        ("sem_oncall_contact", "user", ["Primary on-call engineer is Maria Rossi for platform team", "Secondary is ops rotation"], "who do I call for production emergencies", ["Maria Rossi"], True),
        ("sem_password_policy", "user", ["Passwords must be rotated every 90 days per security policy", "MFA required for admin roles"], "how often must I change my password", ["90 days"], True),
        ("sem_backup_retention", "project", ["Database backups retained for 35 days in encrypted vault", "Weekly full plus daily incremental"], "how long are database backups kept", ["35 days"], True),
        ("sem_rate_limit", "project", ["API rate limit 1200 requests per minute per tenant", "Burst allowance 200 extra"], "what is the API throttling limit per tenant", ["1200"], True),
        ("sem_support_sla", "user", ["Premium support SLA response within 1 hour for P1 tickets", "P2 within 4 business hours"], "how fast does premium support respond to critical issues", ["1 hour"], True),
        ("sem_data_export", "project", ["GDPR export requests fulfilled within 30 calendar days", "Legal review required for bulk export"], "deadline for customer data export under GDPR", ["30"], True),
        ("sem_maintenance", "project", ["Monthly maintenance first Tuesday 22:00-23:00 CET", "Customers notified 7 days ahead"], "when is the scheduled monthly downtime", ["Tuesday", "22:00"], True),
        ("sem_approval_flow", "user", ["Production changes need approval from change manager and QA sign-off", "Hotfix path exists for P1"], "what approvals are needed before production release", ["change manager", "QA"], True),
        ("sem_log_retention", "project", ["Application logs kept 14 days in hot storage then archived", "Audit logs 7 years"], "how long are application logs available for search", ["14 days"], True),
        ("sem_incident_severity", "user", ["P1 incident means complete service outage affecting all users", "P2 is partial degradation"], "definition of a P1 production incident", ["complete service outage"], True),
        ("sem_encryption_rest", "project", ["All customer data encrypted at rest with AES-256", "Keys rotated annually"], "what encryption protects stored customer data", ["AES-256"], True),
    ]
    for row in semantic:
        cid, scope, notes, query, expected, hybrid = row
        cases.append(_case(cid, "semantic_paraphrase", scope, notes, query, expected, prefer_hybrid=hybrid, min_hits=len(expected) if len(expected) > 1 else 1))

    # --- Short discriminative tokens (6) ---
    short = [
        ("short_class_price", "project", ["Class Price State columns in laptop catalog table", "Navigation chrome on every page"], "Class Price State laptop catalog", ["Class", "Price"]),
        ("short_state_code", "project", ["US State NY and CA ship free over 50 USD", "International shipping varies"], "State NY CA shipping free", ["NY", "CA"]),
        ("short_ssd", "project", ["Storage option SSD 1TB available on XPS line", "HDD discontinued"], "SSD 1TB storage option", ["SSD", "1TB"]),
        ("short_api_v2", "project", ["API version v2 deprecated on 2026-12-31", "v3 is current"], "API v2 deprecation date", ["v2", "2026"]),
        ("short_rto", "user", ["Disaster recovery RTO target 4 hours for core services", "RPO 15 minutes"], "recovery time objective RTO hours", ["RTO", "4 hours"]),
        ("short_mfa", "user", ["MFA enforced for admin and billing roles", "Optional for read-only"], "MFA required roles admin billing", ["MFA", "admin"]),
    ]
    for cid, scope, notes, query, expected in short:
        cases.append(_case(cid, "short_token", scope, notes, query, expected, min_hits=2))

    # --- Noise rejection (6) ---
    noise = [
        ("noise_contract", "user", ["Customer ID 998877 linked to contract C-2024-11", "Generic portal working phrases answer boxed"], "contract C-2024-11 customer", ["C-2024-11"], ["boxed"]),
        ("noise_ticket", "project", ["Ticket INC1044552 assigned to network team", "Portal navigation skip links on all pages"], "incident INC1044552 network", ["INC1044552"], ["skip links"]),
        ("noise_version", "user", ["Release version 4.8.2 deployed to production", "Mark your answer in boxed format for exams"], "release 4.8.2 production", ["4.8.2"], ["boxed"]),
        ("noise_uuid", "project", ["Resource UUID a1b2c3d4-e5f6-7890-abcd-ef1234567890 in eu-west", "Working portal phrases answer template"], "resource a1b2c3d4-e5f6", ["a1b2c3d4"], ["portal phrases"]),
        ("noise_email", "user", ["Escalation email secops@company.com for breaches", "Answer should be short phrases separated by commas"], "escalation secops email breaches", ["secops@company.com"], ["short phrases"]),
        ("noise_ip", "project", ["Bastion host 10.20.30.40 allows SSH from VPN only", "ServiceNow portal filter dropdown labels"], "bastion 10.20.30.40 SSH VPN", ["10.20.30.40"], ["ServiceNow"]),
    ]
    for cid, scope, notes, query, expected, forbidden in noise:
        cases.append(_case(cid, "noise_rejection", scope, notes, query, expected, forbidden_substrings=list(forbidden)))

    # --- Disambiguation: many similar notes (8) ---
    disamb_templates = [
        ("disamb_customer_acme", "project", [
            "Customer Acme Corp account tier Enterprise renewal 2026-07",
            "Customer Beta Ltd account tier Standard renewal 2026-03",
            "Customer Gamma SA account tier Enterprise renewal 2025-11",
            "Customer Delta Inc account tier Starter trial ends 2026-01",
            "Customer Epsilon GmbH account tier Enterprise renewal 2026-09",
            "Customer Zeta LLC account tier Standard renewal 2026-05",
            "Customer Eta PLC account tier Enterprise support phone +44-20-7946",
            "Customer Theta NV account tier Standard NPS score 42",
        ], "Acme Corp Enterprise renewal 2026", ["Acme", "Enterprise", "2026-07"]),
        ("disamb_server_prod", "project", [
            "server prod-api-01 memory alert 92 percent",
            "server prod-api-02 memory alert 45 percent",
            "server staging-api-01 cpu alert 78 percent",
            "server prod-db-01 disk alert 88 percent",
            "server prod-cache-01 evictions high",
            "server prod-api-03 memory alert 91 percent",
            "server dev-api-01 unused last 30 days",
            "server prod-worker-07 queue backlog",
        ], "prod-api memory alert above 90", ["prod-api-01", "92"]),
        ("disamb_region", "user", [
            "Preference: deploy primary region eu-west-1 for latency",
            "Preference: DR region eu-central-1 for failover",
            "Preference: analytics bucket in us-east-1",
            "Preference: CDN edge eu-west-1 and us-east-1",
            "Preference: logs archive eu-south-1",
            "Preference: ML training us-west-2",
        ], "primary deploy region eu-west-1 latency", ["eu-west-1", "primary region"]),
        ("disamb_team", "project", [
            "team Alpha owns payments microservice",
            "team Beta owns auth microservice",
            "team Gamma owns notifications service",
            "team Delta owns data pipeline",
            "team Epsilon owns mobile apps",
            "team Zeta owns internal tools",
        ], "team owns notifications service", ["Gamma", "notifications"]),
        ("disamb_env", "project", [
            "env staging URL https://staging.example.com/api",
            "env production URL https://api.example.com/v1",
            "env dev URL http://localhost:8001",
            "env QA URL https://qa.example.com/api",
            "env demo URL https://demo.example.com",
        ], "production API base URL api.example.com", ["api.example.com", "production"]),
        ("disamb_language", "user", [
            "preference UI language Italian for chat client",
            "preference UI language English for admin panel",
            "preference date format DD/MM/YYYY",
            "preference timezone Europe/Rome",
            "preference number format 1.234,56",
        ], "chat UI language Italian", ["Italian", "chat"]),
        ("disamb_skill", "project", [
            "skill prometheus_query validates PromQL before execution",
            "skill grafana_dashboard lists folders and panels",
            "skill sql_query_memory caches validated SELECT statements",
            "skill khub_rag searches company knowledge base",
            "skill mempalace_navigation explores agent DB wings",
        ], "sql_query_memory caches validated SELECT", ["sql_query_memory", "SELECT"]),
        ("disamb_alert", "user", [
            "alert HighErrorRate fires when 5xx above 2 percent 5m",
            "alert DiskAlmostFull fires at 85 percent usage",
            "alert CertificateExpiry fires 14 days before expiry",
            "alert QueueLag fires when depth above 10000",
            "alert LoginFailureSpike fires on brute force pattern",
        ], "alert certificate expires 14 days before", ["CertificateExpiry", "14 days"]),
    ]
    for cid, scope, notes, query, expected in disamb_templates:
        cases.append(_case(cid, "disambiguation", scope, notes, query, expected, recall_limit=8, min_hits=2))

    # --- Numeric / ID (6) ---
    numeric = [
        ("num_ticket", "project", ["Incident INC-2026-8842 root cause memory leak in worker", "INC-2026-8841 was DNS issue"], "incident INC-2026-8842 memory leak", ["INC-2026-8842"]),
        ("num_order", "user", ["Order ORD-55102 shipped via DHL tracking 1234567890", "ORD-55101 cancelled"], "order ORD-55102 DHL tracking", ["ORD-55102"]),
        ("num_vlan", "project", ["VLAN 2048 assigned to production Kubernetes nodes", "VLAN 2049 for management"], "VLAN production kubernetes 2048", ["2048"]),
        ("num_port", "project", ["Metrics exporter listens on port 9464 on all pods", "Health check port 8080"], "metrics exporter port 9464", ["9464"]),
        ("num_iban", "user", ["Vendor payment IBAN IT60X0542811101000000123456 for invoices", "Old IBAN deprecated"], "vendor IBAN IT60X0542811101", ["IT60X0542811101"]),
        ("num_build", "project", ["CI build 18429 promoted to production on 2026-03-01", "Build 18428 failed tests"], "build 18429 promoted production", ["18429"]),
    ]
    for cid, scope, notes, query, expected in numeric:
        cases.append(_case(cid, "numeric_id", scope, notes, query, expected))

    # --- URL / navigation context (6) ---
    url_cases = [
        ("url_incidents", "project", ["traj=t99 step=4 url=/incidents/list action=open Filters dropdown", "goal: find incident filters"], "url /incidents Filters dropdown", ["/incidents", "Filters"]),
        ("url_catalog", "project", ["traj=t12 step=2 url=/catalog/laptops thought=compare SSD options", "catalog_options: XPS, ThinkPad"], "catalog laptops SSD url", ["/catalog/laptops", "SSD"]),
        ("url_admin_users", "project", ["traj=admin step=1 url=/admin/users action=search role=admin", "only admins see this page"], "admin users page search role", ["/admin/users", "admin"]),
        ("url_api_health", "project", ["traj=mon step=0 url=/api/health outcome=200 OK latency 12ms", "synthetic probe every 30s"], "health check endpoint latency", ["/api/health", "200"]),
        ("url_docs", "user", ["Bookmark docs path /memory/mnemos on internal docs site", "Old wiki deprecated"], "mnemos memory documentation path", ["memory/mnemos", "internal docs"]),
        ("url_grafana", "project", ["traj=dash step=3 url=/grafana/d/sre-core/latency thought=spike at 14:00", "dashboard SRE-Core latency"], "grafana dashboard latency spike", ["sre-core", "latency"]),
    ]
    for cid, scope, notes, query, expected in url_cases:
        cases.append(_case(cid, "url_context", scope, notes, query, expected, min_hits=2))

    # --- Dense corpus: target buried in 20+ notes (6) ---
    dense_targets = [
        ("dense_runbook_rollback", "Target note: RUNBOOK rollback database migration 2026-02-15 use snapshot snap-db-9921", ["RUNBOOK", "snap-db-9921"]),
        ("dense_vendor_acme", "Target note: Preferred vendor Acme Supplies contract VND-8821 renewal Q3", ["Acme Supplies", "VND-8821"]),
        ("dense_feature_flag", "Target note: Feature flag ff-checkout-v2 enabled 10 percent canary cohort", ["ff-checkout-v2", "canary"]),
        ("dense_compliance_soc2", "Target note: SOC2 audit evidence bucket s3://compliance-evidence-2026", ["SOC2", "compliance-evidence"]),
        ("dense_oncall_runbook", "Target note: Oncall runbook step 7 restart pod aion-api if OOMKilled", ["step 7", "OOMKilled"]),
        ("dense_customer_sla", "Target note: Customer Contoso SLA 99.95 percent uptime credits tier B", ["Contoso", "99.95"]),
    ]
    for cid, target_note, expected in dense_targets:
        notes = _DENSE_NOISE.copy() + [target_note]
        cases.append(_case(cid, "dense_corpus", "project", notes, " ".join(expected[:2]).lower(), expected, recall_limit=10, min_hits=2))

    # --- Multi-hit: require multiple phrases in results (5) ---
    multi = [
        ("multi_filter_labels", "project", ["Filters dropdown labels: Open, Closed, My Open Incidents, Unassigned", "Page Incidents list ServiceNow"], "Filters Open Closed My Open Incidents", ["Open", "Closed", "My Open Incidents"], 8, 3),
        ("multi_contact", "user", ["Emergency contact Maria Rossi phone +39-02-1234567 email maria@company.com", "HR contact separate"], "emergency Maria Rossi phone email", ["Maria Rossi", "+39-02", "maria@company.com"], 5, 3),
        ("multi_version", "project", ["Stack Python 3.13 FastAPI 0.115 PostgreSQL 16 Redis 7", "Legacy Python 3.9 decommissioned"], "Python 3.13 FastAPI PostgreSQL version", ["Python 3.13", "FastAPI", "PostgreSQL 16"], 8, 3),
        ("multi_endpoints", "project", ["POST /v1/chat streams SSE tokens", "GET /v1/health returns status", "GET /v1/profiles lists agents"], "chat SSE profiles health endpoints", ["/v1/chat", "/v1/health", "/v1/profiles"], 10, 3),
        ("multi_regions", "user", ["Offices in Milan Italy, Munich Germany, Austin USA", "Remote-first company"], "offices Milan Munich Austin locations", ["Milan", "Munich", "Austin"], 8, 3),
    ]
    for cid, scope, notes, query, expected, lim, mh in multi:
        cases.append(_case(cid, "multi_hit", scope, notes, query, expected, recall_limit=lim, min_hits=mh))

    return cases


def main() -> None:
    cases = build_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    categories: dict[str, int] = {}
    for c in cases:
        cat = c.get("category", "uncategorized")
        categories[cat] = categories.get(cat, 0) + 1

    payload = {
        "title": "Mnemos recall full benchmark",
        "description": "Comprehensive dev validation for Mnemos FTS and hybrid embedding recall across realistic note patterns",
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
