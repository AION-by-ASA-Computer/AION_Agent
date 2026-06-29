---
skill_id: agent_db_workflow_accounting
title: Agent DB Accounting Workflow
version: 1
description: Step-by-step protocol for invoices, orders, and structured financial data
applicable_profiles: [accountant_agent, financial_advisor, contabilità]
tools_required: [agent_db_create_table, agent_db_insert_batch, agent_db_query]
tags: [accounting, workflow, fatture, excel]
---

# Accounting operational protocol

When you receive files (Excel, CSV) containing accounting or financial data, follow these steps strictly:

## 1. Multi-sheet analysis (discovery)
If the file is Excel, list all available sheets. Do not stop at the first one.
- For each sheet, read the first 5 rows to understand content.
- Identify relationships (e.g. `client_id` present in both 'Clients' and 'Orders').

## 2. Schema design (autonomous design)
Propose an optimized schema to the user before proceeding.
- **Data types**: Use `MONEY` (or `REAL`) for amounts, `DATE` for dates, `INTEGER` for IDs.
- **Normalization**: If you see repeated data, suggest separate master-data tables.
- **Indexes**: Suggest indexes on columns used frequently for search (e.g. `partita_iva`, `codice_fiscale`, `data_fattura`).

## 3. Validation and ingestion
Before inserting data:
- Verify dates are in `YYYY-MM-DD` format.
- Verify numbers have no thousand separators that could confuse SQLite.
- Use `agent_db_insert_batch` for bulk insert to ensure atomic integrity.

## 4. Reporting and insight
After ingestion, automatically run a summary query to confirm success and deliver immediate value:
- Total amounts per category.
- Count of inserted records.
- Any anomalies (e.g. future dates or suspicious negative amounts).

## Example behavior
"I found two sheets: 'Invoices' and 'Suppliers'. I will create table `anagrafica_fornitori` as the primary key table and `registro_fatture` with a foreign key to suppliers. Do you confirm this schema?"
