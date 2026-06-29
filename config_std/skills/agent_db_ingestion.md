---
name: agent_db_ingestion
description: CSV/XLSX/text ingestion into Agent DB after sandbox/OCR extraction.
tags: [ingestion, csv, excel, database]
version: 3
---

# Agent DB File Ingestion

1. Read the source via sandbox tools (or `ocr_file` for PDF).
2. Normalize rows into JSON objects matching target columns.
3. Run `agent_db_insert_batch(validate_only=true)` first.
4. If validation succeeds, insert with `validate_only=false`.
5. Use meaningful `source` values (for traceability).
6. Reply in the same language used by the user unless explicitly requested otherwise.
