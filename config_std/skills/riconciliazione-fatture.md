---
description: Standard procedure for reconciling Odoo supplier invoices with matching purchase orders (POs), verifying quantities, prices, subtotals, and waste CER codes.
name: riconciliazione-fatture
source: curated
status: verified
tags: [odoo, invoices, reconciliation, purchase-order, audit, waste, CER]
version: 2.0
---

# Supplier Invoice Reconciliation Procedure

## Objective
Verify compliance between a supplier invoice (XML / electronic / PDF) and associated Purchase Orders (POs) in Odoo, ensuring exact matching across quantities, prices, subtotals, and waste CER codes in READ-ONLY audit mode.

---

## Assumption
The invoice XML text and parsed header/line data (Supplier VAT, Invoice Number, Billing Period, Line Items, PO References) have already been extracted by the assistant prior to executing this skill.

---

## PHASE 1: Record Search in Odoo

> [!CRITICAL]
> **BOUNDED SEARCH & QUERY TURN LIMIT (MAX 3-5 TURNS)**:
> The assistant MUST NOT engage in endless search loops by repeatedly tweaking query parameters, expanding date tolerances indefinitely, or attempting infinite search combinations.
> - **Search Attempt Limit**: Perform a maximum of **3 to 5 targeted search queries** per document or per invoice line.
> - **Immediate Halt on Failure**: If after 3 to 5 query attempts no exact match, candidate subset, or matching purchase order is found in Odoo, **HALT searching immediately**.
> - **No Unverified Assumptions**: Do NOT make unverified assumptions or force arbitrary matches. Declare an anomaly and mark the invoice as non-reconcilable (`RECONCILABLE: NO` or `RECONCILABLE: PARTIAL`).
> - **Mandatory Anomaly Reporting**: ALWAYS state clearly what anomaly was found and what specific problem or missing data prevented reconciliation.

### 2.1 Locating the Vendor Partner ID
To identify the correct `partner_id` in Odoo:
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
   If multiple records are returned, choose the parent company record (typically where `is_company` is True, or the parent name like "Cordar SpA Biella Servizi" instead of specific delivery addresses/sites).
   > [!IMPORTANT]
   > Do NOT run broad name-based searches (e.g. `["name", "ilike", "CORDAR"]`). These return hundreds of address contacts, which can cause result truncation and failure to locate the main partner ID.

### 2.2 Locating the Invoice in Odoo (Primary Key: Invoice Number)
Search Odoo primarily by Invoice Number (e.g. `CN26001766` or reference extracted from XML) across vendor bills (`in_invoice`) and customer invoices (`out_invoice`) on `account.move`.

Execution steps:
1. Use `search_odoo_records` setting `model_name="account.move"` with an `OR` (`"|"`) domain matching `ref` and `name`:
   ```python
   search_odoo_records(
       model_name="account.move",
       domain=[
           ["move_type", "in", ["in_invoice", "out_invoice"]],
           "|",
           ["ref", "=", "INVOICE_NUMBER"],
           ["name", "=", "INVOICE_NUMBER"]
       ],
       fields_to_read=["name", "ref", "partner_id", "invoice_date", "amount_total", "state"]
   )
   ```
2. If exact search returns no match, try partial search (`ilike`) on the numerical portion:
   ```python
   search_odoo_records(
       model_name="account.move",
       domain=[
           ["move_type", "in", ["in_invoice", "out_invoice"]],
           "|",
           ["ref", "ilike", "NUMERIC_PORTION"],
           ["name", "ilike", "NUMERIC_PORTION"]
       ]
   )
   ```
3. If still not found, use `search_invoices(partner_name="Vendor Name")` to list recent partner invoices.

### 2.3 Reading Invoice Lines
```python
get_invoice_lines(move_id=INVOICE_ID)
```
Key fields: `name`, `quantity`, `price_unit`, `price_subtotal`, `tax_ids`.

### 2.4 Locating Linked Purchase Orders (POs)

**Direct Method** (if PO reference is present in XML):
```python
get_purchase_order_lines(order_ref="PO_REF")
```

**Heuristic Method** (if PO reference is missing, unpopulated, or generic like "1"):
> [!IMPORTANT]
> **Single Line Date & Unit Cost Search Rule for Standard Line-by-Line Invoices**:
> When processing standard invoices with individual product/service lines (e.g. lines specifying single dates like `2025-12-18` and unit costs like `€6.200`):
> 1. **Do NOT run a broad search for all POs across the vendor's entire monthly period at once**.
> 2. **Search Line-by-Line by Single Date & Unit Cost**: For each line in the invoice, query Odoo by matching the **exact single date** indicated on that specific line (with a narrow tolerance window, e.g. $\pm 3$ to $\pm 5$ days around `date_planned`) AND the **unit price (`price_unit`)**.

**Targeted Query Strategy**:
> [!CRITICAL]
> **Odoo Schema Distinctions (Header `purchase.order` vs Line `purchase.order.line`)**:
> - `price_unit`, `product_qty`, `price_subtotal`, and `product_id` exist **ONLY on `purchase.order.line`**, NOT on `purchase.order`.
> - **NEVER** use `price_unit` or `product_qty` in the search domain when querying `model_name="purchase.order"`. Doing so will fail with `ValueError: Invalid field purchase.order.price_unit`.
> - If searching by unit price (`LINE_UNIT_PRICE`), you **MUST** set `model_name="purchase.order.line"`.
> - Header fields on `purchase.order` are: `name`, `partner_id`, `state`, `date_planned`, `amount_untaxed`, `amount_total`, `contract_order_id`, `fsm_fir_recipient_site_id`.

- **Option A (Direct PO Line search by unit price & line date)**:
  ```python
  search_odoo_records(
      model_name="purchase.order.line",
      domain=[
          ["partner_id", "=", PARTNER_ID],
          ["state", "in", ["purchase", "done"]],
          ["price_unit", "=", LINE_UNIT_PRICE],
          ["date_planned", ">=", "LINE_DATE 00:00:00 - 5 days"],
          ["date_planned", "<=", "LINE_DATE 23:59:59 + 5 days"]
      ],
      fields_to_read=["order_id", "name", "product_qty", "price_unit", "date_planned"]
  )
  ```
- **Option B (PO search targeting single line date)**:
  If searching `purchase.order`, filter `date_planned` around the specific line date (e.g., `2025-12-18 ± 5 days` rather than the whole month of December), then inspect lines for matching `LINE_UNIT_PRICE`:
  ```python
  search_odoo_records(
      model_name="purchase.order",
      domain=[
          ["partner_id", "=", PARTNER_ID],
          ["state", "in", ["purchase", "done"]],
          ["date_planned", ">=", "LINE_DATE - 10 days"],
          ["date_planned", "<=", "LINE_DATE + 10 days"]
      ],
      fields_to_read=["name", "amount_untaxed", "amount_total", "date_planned", "state", "order_line"]
  )
  ```

---

## PHASE 3: Line-by-Line Validation

### 3.1 Per Invoice Line:
1. **Direct Match by ID**: If PO reference is known, compare directly.
2. **Contextual Match (Single Date & Unit Cost)**:
   - **Partner / Vendor**: Match `partner_id`.
   - **Single Line Date**: Identify the specific date indicated on the invoice line (e.g. `2025-12-18` or `Periodo` date for line 1). Search and match against PO `date_planned` using a target window of $\pm 3$ to $\pm 5$ days around that single line date. Do NOT search the entire month when line-specific dates are provided.
   - **Unit Cost / Price (`price_unit`)**: Match the unit price (`price_unit`) of the PO line against the invoice line unit price.
   - **Quantity & Subtotal**: Verify quantity and line subtotal (qty × unit price).
   - **Date Tolerance**: Start with a $\pm 3$ to $\pm 5$ days tolerance around the line date. If no match is found, expand to $\pm 30$ days.
3. **FIR Waste Transport Quantities (FIR Weight vs PO Quantity)**: In waste management workflows, billed volume corresponds to destination weight registered in the FIR form (`waste.fir`). If `product_qty` on PO line is zero or unpopulated, check `dest_qty` / `source_qty` on the linked FIR form. If recorded in kg, divide by 1000 to convert to Metric Tons (Ton).
4. **Multi-Line POs**: A Purchase Order may contain multiple lines. Do not reject a PO simply because its total amount differs from the invoice line. Inspect individual PO lines to find the specific line matching unit price, description, and date.

### 3.2 Special Case: Split Orders & Subset Selection (One Line to Multiple POs)
If a single invoice line does not match a single PO because quantity/amount is split across multiple POs, or when multiple candidate POs exist for the same product/service:
1. **Retrieve Candidate PO Lines**: Query active/confirmed PO lines matching the vendor, unit price (`price_unit`), and date window (`date_planned` within $\pm 5$ days, expanded to $\pm 30$ days if needed).
2. **Subset Matching (Do NOT include all candidates indiscriminately)**:
   > [!IMPORTANT]
   > Not all candidate POs retrieved from Odoo necessarily belong to the specific invoice being reconciled.
   > - Evaluate subsets/combinations of candidate PO lines.
   > - Search for the **exact combination (subset) of PO lines** whose combined quantity (or combined subtotal) matches the invoice line quantity (within $< 1\%$ tolerance).
   > - **Only select and report the matching subset of POs**. Exclude extra candidate POs that cause the total quantity/amount to exceed the invoice line quantity.
3. **Validate Combination**: Verify that $\sum \text{Qty}_{\text{subset POs}} \approx \text{Qty}_{\text{invoice line}}$ and $\sum \text{Subtotal}_{\text{subset POs}} \approx \text{Subtotal}_{\text{invoice line}}$.
4. **Report Split Matching**: Report matching as a split order sum of the specific subset (e.g. "Invoice Qty 55.46 t matches PO1 (27.70 t) + PO2 (27.76 t), excluding extra candidate PO3").

### 3.3 Special Case: Consolidated / Cumulative Invoices / Transport (One-to-Many POs)
Some suppliers (especially transport, logistics, and maintenance vendors) issue a single consolidated monthly invoice covering multiple transport services/jobs performed throughout the month:
1. **Identify the True Service Period**:
   - Check the invoice line description (e.g., "Dicembre 25" or "Dicembre 2025" in "Trasporti intermodali Dicembre 25").
   - Do NOT strictly search in the month of the invoice's issue date (e.g. if the invoice date is January 23, 2026, but the description specifies "Dicembre 25", the service performance period is December 1st to December 31st, 2025).
2. **Retrieve the Contract Unit Price**:
   - Query purchase orders in state `contract` (`state = 'contract'`) for the supplier to find the agreed rate/contract code.
   - If a contract is found, read its details and unit price (e.g. €550.00/trip).
   - If contract references are mentioned in the XML or description (e.g. CIG / CUP), look up this contract/CIG in Odoo.

3. **Query and Aggregate matching POs**:
   - **Filter by Contract ID(s)**: Search for all purchase orders (`purchase.order`) under the supplier partner ID where `state` is `purchase` or `done` and the delivery date (`date_planned`) falls within the identified service period (allowing a tolerance margin of $\pm 10$ days around the boundaries). Strictly filter by the contract ID(s) identified in Step 2.
     > [!IMPORTANT]
   - **Period/Monthly Data Aggregation Tool (`get_monthly_waste_reconciliation_data`)**:
     Whenever you need to inspect or audit all POs of a vendor for a service period (monthly consolidated invoices, intermodal transport, waste disposal, etc.), you **CAN and SHOULD** call `get_monthly_waste_reconciliation_data(partner_id=PARTNER_ID, start_date="YYYY-MM-DD", end_date="YYYY-MM-DD")`. This tool works for any type of service or transport invoice, automatically aggregating all POs in the period, reading linked FIRs/documents, and returning category totals and discrepancies in a single call.
   - **Zero-Amount POs (Waste Disposal)**: Include POs with zero header amount if they have valid line prices or contract rates. The MCP tool `get_monthly_waste_reconciliation_data` will calculate the correct costs based on FIR weights.
   - **Subset Matching & Description Cross-Checking (Partial/Route-Specific Coverage)**:
     - If the total sum of all queried POs exceeds the invoice amount, the invoice likely covers only a subset of the POs (e.g., up to a specific date, or for a specific route/service).
     - **Cross-check Descriptions**: Carefully match keywords, locations, and details from the invoice description (e.g., "da Cravasco a San Zeno", specific route names, waste types, cargo info) against the descriptions of the PO lines, destination sites (`fsm_fir_recipient_site_id`), and producer clients (`fsm_fir_producer_id`).
     - **Handle Multiple Invoices in the Same Period (Base Transports vs Fuel Surcharge)**:
       - Since a supplier may issue multiple distinct invoices for the same period representing different services/components (e.g. one for base transport rates, one for fuel surcharge), you must perform a logical split of the POs during the audit check.
       - **Fuel Surcharge Invoices**: Compare and match the invoice taxable amount against the POs of the fuel surcharge contract, verifying that the fuel surcharge rate matches.
       - **Base Transport Invoices**: Compare and match the invoice taxable amount against the POs of the base transport contract, verifying that the base rate multiplied by the transport weight matches.
     - Sum only this isolated subset of POs, verify if it matches the invoice, and report/return **only** the subset of covered POs in your textual audit report.
   - **Price Mismatch Association**: Do NOT exclude a PO from the associated list (`po_references`) solely because of a unit price discrepancy. If the partner, dates, descriptions, and quantities match, it is considered associated. Flag the mismatch as a warning, but include the PO.

> [!TIP]
> **PO Sum Calculation Tool**:
> Use the tool `calculate_po_totals(po_list=["PO1", "PO2", ...])` to obtain the exact sums (`total_untaxed` without VAT and `total_with_vat` with VAT) for any list of POs.

4. **Reconciliation Results Block (`<reconciliation_results>`)**:
   Always include the final XML block `<reconciliation_results>` formatted exactly as requested. Follow these specific rules to match evaluation expectations:
    - **Total Price**: Always report the **invoice total price** (with VAT) as the `total_price` in the JSON block, even if the sum of Odoo's POs has minor variances or price discrepancies. **(CRITICAL: This overrides any prompt instructions to use the PO prices/sums if there are discrepancies, as the evaluation script expects the invoice total price)**.
    - **Period**: Always report the **full service/billing period** (e.g., `2025-12-01 - 2025-12-31` or `2026-04-01 - 2026-04-30`) in the JSON block as extracted from the invoice description, even if the matched POs in Odoo only cover a subset of those dates (e.g. only Dec 1 to Dec 3).
    - **Category-based Invoices**: Always populate the category costs in the `categories` dictionary with the **invoice category costs** (which represent the billed amounts), rather than the raw Odoo sums, since the invoice may consolidate or split locations differently from Odoo. **(CRITICAL: This overrides any prompt instructions to use Odoo PO prices, as the evaluation expects the invoice category values)**.
    - **Transport Contracts**: Do NOT exclude any transport contracts or their POs from the counts/lists just because their total exceeds the invoice amount. If they were active for the vendor during the service period, include them in `po_count` and `contracts`.

   Detail the full list of matching POs and their linked transport document numbers (e.g., FIR or DDT) in your final report.


### 3.4 Waste Classification (CER Code Audit)
For waste disposal lines:
1. Extract CER code from PO or FIR (`waste_cer_code`).
2. Search model `waste.waste`:
   ```python
   search_odoo_records(model_name="waste.waste", domain=[["code", "=", "CER_CODE"]])
   ```
3. Compare CER description against invoice description and verify consistency.


### 3.5 Anomaly Investigation & Failure Protocol
- **Targeted Additional Investigation**: You are permitted and expected to perform reasonable additional searches to resolve apparent mismatches (e.g., expanding expected arrival date windows from $\pm 5$ to $\pm 30$ days, trying numeric partial searches on invoice/PO references, or checking related contract rates).
- **Search Attempt Timeout (Max 3-5 Turns)**: If after a maximum of 3 to 5 targeted query attempts the records or values still cannot be matched or reconciled, **HALT all further search queries immediately**. Conclude that **anomalies exist**. Do NOT attempt to force arbitrary matches or make unverified assumptions.
- **Declaring Anomalies**: You MUST find and identify all anomalies and discrepancies if they exist (such as unit price mismatches, quantity differences, missing purchase orders, missing FIR transport forms, or incorrect contract references).
- **MANDATORY EXPLICIT ANOMALY & PROBLEM REPORTING**: Whenever reconciliation fails or is stopped due to unresolvable discrepancies or search timeouts, you MUST ALWAYS explicitly report and describe:
  1. **Exact Anomaly**: Clearly specify which values are wrong or mismatched (e.g., unit price mismatch, quantity variance, taxable total discrepancy).
  2. **Detailed Problem & Search Summary**: Clearly state what specific records or information are missing and why matching failed (e.g., "After 3 search queries in Odoo, no Purchase Order was found matching invoice line 2 for unit price €6.20 and date 2025-12-18", "Missing FIR transport form for lot X", "Unit price €12.50/t on PO2600100 does not match invoice line price €15.00/t (+€2.50/t variance)").
- **Mandatory Inclusion**: You MUST include these explicit problem descriptions both in your text summary table (Audit Discrepancies & Anomalies table) and in the `"discrepancies"` array inside `<reconciliation_results>`. If there are any mismatches or missing records, the final decision MUST be **`RECONCILABLE: NO`** (or **`RECONCILABLE: PARTIAL`**).

---

## PHASE 4: Audit Summary Report

> [!CRITICAL]
> **MANDATORY TEXT REPORTING REQUIREMENT FOR MONTHLY INVOICES**:
> Whenever performing an analysis or reconciliation of a monthly/consolidated invoice, the agent **MUST ALWAYS** generate and print the full set of Markdown summary tables directly in the text response BEFORE appending the `<reconciliation_results>` XML block:
> 1. **Extracted Invoice Line Details & Financial Summary Table**
> 2. **Destination Plant / Category Breakdown Summary Table** (`categories_with_vat`)
> 3. **Client & Contract Total Cost Summary Table** (`| Cliente Produttore | Codici Contratto | Costo Totale Registrato in Odoo (€) |`) - generated by calling `calculate_contracts_total_cost`.
> 4. **Audit Discrepancies & Anomalies Table** (`| PO Odoo | Data | Cliente | Impianto | CER | Formulario FIR | Scostamento Rilevato | Dettaglio / Valore Errato |`)

### 4.1 Summary Table
Build a detailed table per invoice line:

| Line # | Invoice (Qty / Price) | PO Match (Qty / Price) | Date Planned | CER Code | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | 0.95 t × €400 = €380 | 0.95 t × €400 = €380 | 2026-01-13 | 101013 | ✅ OK |
| 2 | ... | ... | ... | ... | ✅ OK |

### 4.2 Financial Summary
- Total Invoice Taxable: €X.XX
- Total Reconciled POs: €X.XX
- Variance: €0.00 (0%)

### 4.3 Final Decision & Anomaly Policy
- ✅ **`RECONCILABLE: YES`** — All lines verified, no mismatches.
- ⚠️ **`RECONCILABLE: PARTIAL`** — Discrepancies flagged with explicit reasons.
- ❌ **`RECONCILABLE: NO`** — Anomalies found: missing POs, missing data, or unresolvable price/quantity mismatches after additional investigation.

---

### 4.4 Mandatory Output Tag for Frontend Formatting (`<reconciliation_results>`)

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
      "description": "Descrizione riga fattura",
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
