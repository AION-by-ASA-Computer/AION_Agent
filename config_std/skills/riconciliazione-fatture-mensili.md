---
description: Perform read-only audit of waste disposal supplier invoices. Validate PO purchase prices against agreed Contract rates, verify linked FIR waste transport forms (waste.fir), check quantities (tons/m³), and match producer clients to determine if an invoice is RECONCILABLE (YES/NO).
name: riconciliazione-fatture-mensili
source: curated
status: verified
tags: [odoo, invoices, reconciliation, waste, fir, purchase-order, contract]
version: 4.0
---

# Monthly Disposal Invoice Reconciliation (Contract & FIR Audit)

## Core Principles
1. **STRICT READ-ONLY MODE (NO ODOO MUTATIONS)**: The agent MUST NOT create, confirm, post, or modify any documents in Odoo. It performs read-only checks and verification audits.
2. **CORE AUDIT FOCUS**:
   - **Check 1: PO Price vs Contract Price**: Ensure the unit purchase price (€/ton or €/m³) on the PO line (`purchase.order.line`) matches the contracted unit price on the original Contract (`contract_order_id`).
   - **Check 2: FIR Transport Form Audit (`waste.fir`)**: Ensure the linked FIR form matches the Producer Client (`producer_id`), Waste CER code (`waste_cer_code`), and that the FIR quantities (`source_qty` / `dest_qty`) match the PO line volume (`product_qty`) within operational weighbridge tolerance (Max 5%).
3. **GENERIC & MODULAR**: No hardcoded supplier names, plant names, or CER codes. The workflow applies dynamically to ANY waste disposal supplier and client contract.
4. **FINAL DECISION**: Output **`RECONCILABLE: YES`** or **`RECONCILABLE: NO`** with explicit discrepancy reporting.
5. **ANOMALY & DISCREPANCY REPORTING**: If values do not match (prices, quantities exceeding 5% weighbridge tolerance, missing POs/FIRs), perform targeted additional queries (e.g. checking plant consolidation or contract date ranges). If after additional investigation the discrepancies persist, declare **anomalies**. State explicitly which values are incorrect and what records or details are missing.
6. **BOUNDED SEARCH & MANDATORY ANOMALY REPORTING (MAX 3-5 TURNS)**: The agent MUST NOT engage in endless search turns in Odoo. Limit queries to maximum 3 to 5 search turns per monthly reconciliation. If after 3 to 5 query attempts matching POs, contract rates, or FIR transport weights cannot be located or reconciled, HALT searching immediately. Conclude with **`RECONCILABLE: NO`** (or **`RECONCILABLE: PARTIAL`**) and ALWAYS report the exact anomaly and problem (which values differ, what records/PO/FIR are missing, and why matching failed).

---

## Logical Audit Workflow

```
[1. Read Invoice] ➔ [2. Locate Partner & Invoice in Odoo] ➔ [3. Execute Reconciliation Tool] ➔ [4. Audit & Category Matching] ➔ [5. Final Decision & Report]
```

---

### Step 1: Upload and Read Supplier Invoice
1. **Extract Data**: Extract supplier details, invoice reference number, date, billing period, line items, and taxable amounts from `.p7m` XML or PDF.
2. **Extract Key Header Fields**:
   - Supplier VAT ID and Odoo `partner_id`
   - Total Taxable Amount and VAT subtotals
   - Billing Period Start Date and End Date
   - **Document Type (`TipoDocumento` from XML)**:
     * **TD01, TD24, TD25**: Ordinary / Deferred Invoice representing standard costs (Fattura / Fattura differita).
     * **TD04**: Credit Note representing deductions (Nota di Credito).
     * **TD05**: Debit Note (Nota di Debito).
     > [!IMPORTANT]
     > Do NOT classify **TD24** or **TD25** as a Credit Note (Nota di Credito). They behave exactly like standard invoices representing costs.

---

### Step 2: Locate the Partner and Invoice in Odoo

#### 2.1 Find the Vendor Partner ID (`partner_id`)
To identify the correct `partner_id` for the supplier:
1. **Search by VAT / Partita IVA**:
   Use `search_odoo_records` with `model_name="res.partner"` filtering by the invoice's VAT ID (with and without the `IT` prefix):
   ```python
   search_odoo_records(
       model_name="res.partner",
       domain=["|", ["vat", "=", "IT_VAT_NUMBER"], ["vat", "=", "VAT_NUMBER"]],
       fields_to_read=["id", "name", "vat", "is_company"]
   )
   ```
2. **Select the Parent Company Record**:
   Select the main company record (typically where `is_company` is True, or the parent name like "Cordar SpA Biella Servizi" rather than individual delivery sites/addresses).
   > [!IMPORTANT]
   > Do NOT run broad name searches (e.g. `["name", "ilike", "CORDAR"]`). These return hundreds of address contacts, which can cause result truncation and failure to locate the main partner ID.

#### 2.2 Check Invoice in Odoo
1. Search vendor bill (`account.move`) by reference or invoice number.
2. Verify total registered amount matches extracted invoice header.

---

### Step 3: Execute Reconciliation Tool (`get_monthly_waste_reconciliation_data`)
1. **Identify the exact billing period**: 
   - Analyze the invoice description, notes, and line details to find the exact date range covered by the invoice (e.g., if the invoice states "Intermodal transport Jan 1 - Jan 23, 2026", the period is `2026-01-01` to `2026-01-23`).
   - Do NOT default to querying the full calendar month if the invoice details specify a shorter or longer range.
2. **Call the generic reconciliation tool**:
   ```python
   get_monthly_waste_reconciliation_data(partner_id=PARTNER_ID, start_date="YYYY-MM-DD", end_date="YYYY-MM-DD")
   ```
3. **Automated Tool Audits**:
   The tool automatically executes the full low-level audit in Odoo:
   - **PO Retrieval**: Retrieves all purchase orders for the supplier in the period.
   - **Contract Price Audit**: Compares PO line prices (`price_unit`) against agreed contract rates (`contract_order_id`).
   - **FIR Transport Form & Quantity Audit**: Reads linked FIR transport forms (`waste.fir`), matches producer clients, and verifies weighbridge quantities (kg to tons) within 5% operational tolerance.
   - **Category Subtotals**: Aggregates totals by destination site and VAT rate (`categories_with_vat`, `totals_by_category`).
   - **Client-Contract Mapping**: Aggregates unique clients and associated contract codes (`unique_clients_contracts`).
   - **Discrepancy Identification**: Identifies any price or quantity mismatches in the `discrepancies` array.
4. **Contract Cost Summation Tool**:
   Call `calculate_contracts_total_cost(contracts=[...], start_date="YYYY-MM-DD", end_date="YYYY-MM-DD")` passing the contract codes from `unique_clients_contracts`.

---

### Step 4: Audit & Category Matching

1. **Financial Totals Audit**:
   Compare extracted Invoice Totals (taxable and total with VAT) against Odoo PO Totals returned by the tool (`total_po_cost_untaxed`, `total_po_cost_with_vat`).

2. **Category Matching & Consolidation Rules**:
   > [!IMPORTANT]
   > **Category Mapping & Consolidation Rules**:
   > - **Sub-category Summation per Site and VAT Rate**:
   >   In Odoo, waste lines under the same plant and VAT rate may be returned with fine-grained descriptions (e.g. `Smaltimento rifiuti`, `Rifiuti Urbani / Fosse Settiche`, `Fanghi Trattamento Acque`).
   >   On supplier invoices (e.g. CORDAR), these are consolidated under a single macro-category line (e.g. `Altri Rifiuti c/o dep. Cossato (10%)` or `Altri Rifiuti c/o dep. Biella (10%)`).
   >   *Rule*: To evaluate an invoice line like `Altri Rifiuti - [Impianto] (10%)`, sum all non-percolato Odoo sub-categories for that same plant and VAT rate. Do NOT treat individual sub-categories as separate discrepancies if their sum matches the invoice line item!
   > 
   > - **Global Location Consolidation**:
   >   Some suppliers may centralize all "Altri Rifiuti" deliveries under a single plant (e.g., "depuratore di Biella") on the invoice, while in Odoo the POs are physically split between different sites (e.g., "Biella" and "Cossato").
   >   If you see matching deficits in one site and matching surpluses in another for the same waste type, sum "Altri Rifiuti" across all locations in Odoo and compare against invoice lines.

3. **Discrepancies & Anomalies Review**:
   Inspect the `discrepancies` list returned by the tool. If there are unit price mismatches or quantity variances exceeding the 5% weighbridge tolerance, flag them as warnings/anomalies.

---

### Step 5: Final Decision & Mandatory Reconciliation Report Tables

> [!CRITICAL]
> **MANDATORY TEXT REPORTING REQUIREMENT**:
> Whenever performing an analysis or reconciliation of a monthly invoice, the agent **MUST ALWAYS** generate and print the following 4 Markdown summary tables directly in the text response BEFORE appending the `<reconciliation_results>` XML block:

1. **Table 1: Estratto Dettaglio Linee Fattura & Financial Summary**:
   - Table listing extracted invoice lines (Line #, Service Description/Plant, Taxable Amount, VAT rate, Gross Total with VAT).
   - Financial totals comparison: Supplier Invoice Taxable & Gross Total vs. Sum of Odoo POs.

2. **Table 2: Sintesi per Categoria / Impianto di Destinazione**:
   - Breakdown table comparing Invoice amount vs. Odoo PO amount per destination plant/category (`categories_with_vat`), showing category variances.

3. **Table 3: Dettaglio Clienti e Contratti Associati con Costi Totali per Cliente**:
   - **MUST** call `calculate_contracts_total_cost(contracts=[...], start_date=..., end_date=...)` passing the contract codes from `unique_clients_contracts`.
   - Sum the cost of all contracts assigned to each single client.
   - Render a Markdown table with columns: `| Cliente Produttore | Codici Contratto | Costo Totale Registrato in Odoo (€) |`.

4. **Table 4: Audit Discrepanze e Anomalie Identificate**:
   - Render a Markdown table detailing all price mismatches, quantity variances exceeding 5%, or missing PO/FIR records (Columns: `| PO Odoo | Data | Cliente | Impianto | CER | Formulario FIR | Scostamento Rilevato | Dettaglio / Valore Errato |`).

5. **Final Decision**:
   - Output **`RECONCILABLE: YES`**, **`RECONCILABLE: PARTIAL`**, or **`RECONCILABLE: NO`** with clear explanations.

---

### Mandatory Output Tag for Frontend Formatting (`<reconciliation_results>`)

At the very end of your response, you **MUST ALWAYS** append an XML block `<reconciliation_results>` containing a valid, clean JSON object. This block is required by the frontend interface and automated evaluation script to parse and render the interactive reconciliation table.

```json
<reconciliation_results>
{
  "reconciliation_summary": {
    "status": "OK",
    "total_invoice_tax_excluded": 1234.56,
    "total_reconciled": 1234.56,
    "percentage": 100.0
  },
  "period": "YYYY-MM-DD - YYYY-MM-DD",
  "total_price": 1506.16,
  "po_count": 5,
  "po_references": [
    "PO2600123",
    "PO2600124"
  ],
  "contracts": [
    "P2501974"
  ],
  "has_anomalies": false,
  "anomalies": [],
  "categories": {
    "ALTRI RIFIUTI - Biella (10%)": 0.0,
    "PERCOLATO - Biella (10%)": 0.0,
    "ALTRI RIFIUTI - Cossato (10%)": 0.0,
    "ALTRI RIFIUTI - Cossato (22%)": 0.0,
    "PERCOLATO - Cossato (10%)": 0.0
  },
  "lines": [
    {
      "line_number": 1,
      "description": "Smaltimento rifiuti CER 191212",
      "qty_invoice": 10.5,
      "price_unit_invoice": 100.0,
      "total_invoice": 1050.0,
      "status": "OK",
      "discrepancies": [],
      "matched_pos": [
        {
          "po_reference": "PO2600123",
          "qty_po": 10.5,
          "price_unit_po": 100.0,
          "total_po": 1050.0,
          "date_planned": "2026-01-15",
          "cer": "191212"
        }
      ]
    }
  ]
}
</reconciliation_results>
```

#### JSON Field Specifications:
- `reconciliation_summary`:
  - `status`: `"OK"` (all lines matched cleanly), `"PARTIAL"` (partial match or minor warnings), or `"NOT_FOUND"` (unreconciled/missing POs).
  - `total_invoice_tax_excluded`: Taxable total amount of the invoice (float).
  - `total_reconciled`: Sum of taxable amounts of all matched POs (float).
  - `percentage`: Coverage percentage `(total_reconciled / total_invoice_tax_excluded) * 100` (float).
- `period`: Billed service period in format `"YYYY-MM-DD - YYYY-MM-DD"` (string).
- `total_price`: Invoice total amount WITH VAT (float).
- `po_count`: Total count of unique matched POs (int).
- `po_references`: Array of PO reference strings (e.g. `["PO2600123"]`).
- `contracts`: Array of associated contract code strings (e.g. `["P2501974"]`).
- `has_anomalies`: `true` if anomalies/mismatches exist, `false` otherwise (boolean).
- `anomalies`: Array of anomaly strings (e.g. `["costo errato"]`, `["PO mancanti"]`, `["date errate"]`, `["contratto errato"]`).
- `categories`: Dictionary of category amounts CON IVA (gross total with VAT) for waste categories (especially for Cordar invoices). If a category is not present in the invoice, set its value to `0.0`.
- `lines`: Array of line reconciliation items:
  - `line_number`: 1-based invoice line index (int).
  - `description`: Billed service/product description (string).
  - `qty_invoice`: Billed quantity (float).
  - `price_unit_invoice`: Billed unit price (float).
  - `total_invoice`: Billed line taxable subtotal (float).
  - `status`: Line status (`"OK"`, `"PARTIAL"`, `"NOT_FOUND"`).
  - `discrepancies`: List of error/warning strings for this line (array of strings).
  - `matched_pos`: List of matched Odoo PO line objects, each containing:
    - `po_reference`: PO number string (e.g. `"PO2600123"`).
    - `qty_po`: PO line volume/quantity (float).
    - `price_unit_po`: PO line unit price (float).
    - `total_po`: PO line taxable subtotal (float).
    - `date_planned`: Planned date string `"YYYY-MM-DD"`.
    - `cer`: CER waste code string (e.g. `"191212"`).

---

### Anomaly Investigation & Explicit Failure Reporting
- **Search Attempt Timeout (Max 3-5 Turns)**: You MUST NOT spend endless turns searching for candidate POs or expanding date/contract ranges indefinitely. Enforce a hard limit of **maximum 3 to 5 search queries**. If matching data cannot be located or reconciled within this limit, HALT further search queries immediately.
- **Identifying & Declaring Anomalies**: You MUST find and identify all anomalies and discrepancies if they exist (such as unit price mismatches, quantity differences, missing purchase orders, missing FIR transport forms, or incorrect contract references).
- **MANDATORY EXPLICIT ANOMALY & PROBLEM REPORTING**: If anomalies or missing data are detected during the audit or if search attempts exceed the limit without a complete match:
  - Explicitly declare the presence of **anomalies**.
  - **Incorrect Values**: Clearly specify which values are wrong (e.g., PO unit price vs contract rate mismatch, weighbridge variance $> 5\%$, total amount mismatch).
  - **Missing Information & Problem Description**: Clearly state what items, records, or details are missing and why reconciliation failed (e.g., "After 3 search queries in Odoo, no Purchase Order was found for the billed period 01/12-31/12", "Missing linked FIR transport form for delivery X", "Unit price on PO €45.00/t does not match agreed contract rate €50.00/t").
  - Set status to **`RECONCILABLE: NO`** (or **`RECONCILABLE: PARTIAL`**) and include clear explanations in the report. If there are any mismatches or missing records, the final decision MUST be **`RECONCILABLE: NO`** (or **`RECONCILABLE: PARTIAL`**).
  - **Mandatory Output Inclusion**: You MUST populate these explicit anomaly descriptions both in Table 4 (`Audit Discrepanze e Anomalie Identificate`) and inside `<reconciliation_results>` (in `anomalies` array and line `discrepancies` arrays).
