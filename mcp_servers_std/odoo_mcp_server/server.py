"""
Odoo MCP Server: Connects to an Odoo ERP instance via XML-RPC.
Exposes tools to support a "three-way matching" document validation workflow.
"""

from __future__ import annotations

import os
import sys
import json
import logging
import re
import xmlrpc.client
from typing import Any, Dict, List, Union

# Add project root to sys.path to resolve any potential import dependencies from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from dotenv import load_dotenv
from fastmcp import FastMCP

# Configure logging to stderr to prevent contaminating stdout (used for MCP stdio protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("odoo_mcp_server")

# Load environment variables
load_dotenv()

ODOO_URL: str | None = os.environ.get("ODOO_URL")
ODOO_DB: str | None = os.environ.get("ODOO_DB")
ODOO_USER: str | None = os.environ.get("ODOO_USER")
ODOO_API_KEY: str | None = os.environ.get("ODOO_API_KEY")

# Validate environment variables presence
missing_vars: list[str] = [
    var_name for var_name, var_val in [
        ("ODOO_URL", ODOO_URL),
        ("ODOO_DB", ODOO_DB),
        ("ODOO_USER", ODOO_USER),
        ("ODOO_API_KEY", ODOO_API_KEY)
    ] if not var_val
]

if missing_vars:
    err_msg = f"Missing required environment variables for Odoo: {', '.join(missing_vars)}"
    logger.error(err_msg)
    raise ValueError(err_msg)

# Clean endpoints URLs
base_url: str = ODOO_URL.rstrip("/")
common_endpoint: str = f"{base_url}/xmlrpc/2/common"
object_endpoint: str = f"{base_url}/xmlrpc/2/object"

# Perform initial Odoo authentication validation at startup
logger.info("Initializing Odoo ERP connection...")
try:
    common = xmlrpc.client.ServerProxy(common_endpoint)
    logger.info(f"Authenticating user '{ODOO_USER}' on database '{ODOO_DB}'...")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_API_KEY, {})
    
    # In Odoo, a failed authentication returns False or empty value
    if not uid or isinstance(uid, bool):
        raise ValueError("Invalid username or API key.")
        
    logger.info(f"Successfully authenticated with Odoo. Assigned UID: {uid}")
except Exception as e:
    err_msg = f"Odoo ERP authentication failure at startup: {e}"
    logger.error(err_msg)
    # Raise RuntimeError to abort server startup with a clean diagnostic error
    raise RuntimeError(err_msg) from e

# Initialize FastMCP Server
mcp = FastMCP("Odoo_ERP_Tools")

@mcp.tool()
def get_odoo_model_schema(model_name: str) -> str:
    """
    Estrae la struttura completa (nomi dei campi, tipi, relazioni) di un modello Odoo.
    Usa SEMPRE questo tool prima di interrogare una tabella che non conosci per capire
    quali campi puoi richiedere.
    
    Args:
        model_name: Il nome tecnico del modello (es. 'account.move', 'purchase.order' o il modello dei rifiuti).
    """
    try:
        models = xmlrpc.client.ServerProxy(object_endpoint)
        schema = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            model_name, 'fields_get',
            [],
            {'attributes': ['string', 'type', 'help']}
        )
        return json.dumps(schema)
    except Exception as e:
        return json.dumps({"error": f"Impossibile leggere lo schema di {model_name}: {str(e)}"})

@mcp.tool()
def search_invoices(move_type: str = 'all', partner_name: str = "", limit: int = 10) -> str:
    """
    Cerca fatture (clienti o fornitori) in Odoo.
    
    Args:
        move_type (str): 'out_invoice' per fatture clienti, 'in_invoice' per fatture fornitori, 'all' per entrambe.
        partner_name (str): Opzionale. Filtra parzialmente per nome del cliente/fornitore.
        limit (int): Numero massimo di risultati.
    """
    try:
        models = xmlrpc.client.ServerProxy(object_endpoint)
        domain = []
        
        if move_type in ['out_invoice', 'in_invoice']:
            domain.append(('move_type', '=', move_type))
        else:
            domain.append(('move_type', 'in', ['out_invoice', 'in_invoice']))
            
        if partner_name:
            domain.append(('partner_id.name', 'ilike', partner_name))
            
        invoices = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move', 'search_read',
            [domain],
            {'fields': ['name', 'ref', 'partner_id', 'invoice_date', 'amount_total', 'state'], 'limit': limit}
        )
        return json.dumps(invoices, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def search_purchases(state: str = 'all', partner_name: str = "", limit: int = 10) -> str:
    """
    Cerca ordini di acquisto e preventivi in Odoo.
    
    Args:
        state (str): 'draft' o 'sent' per Preventivi (RfQ), 'purchase' per Ordini Confermati, 'all' per tutto.
        partner_name (str): Opzionale. Filtra parzialmente per nome del fornitore.
        limit (int): Numero massimo di risultati.
    """
    try:
        models = xmlrpc.client.ServerProxy(object_endpoint)
        domain = []
        
        if state != 'all':
            domain.append(('state', '=', state))
            
        if partner_name:
            domain.append(('partner_id.name', 'ilike', partner_name))
            
        purchases = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'purchase.order', 'search_read',
            [domain],
            {'fields': ['name', 'partner_id', 'date_order', 'amount_total', 'state'], 'limit': limit}
        )
        return json.dumps(purchases, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

import base64

def sanitize_filename(filename: str) -> str:
    """
    Sanitizza il nome del file per assicurarsi che contenga solo caratteri sicuri.
    Risolve possibili eccezioni dovute a caratteri speciali non ammessi in safe_resolve.
    """
    # Teniamo solo caratteri alfanumerici, punti, trattini e underscore
    sanitized = ""
    for char in filename:
        if char.isalnum() or char in ['.', '_', '-']:
            sanitized += char
        else:
            sanitized += '_'
            
    # safe_resolve rifiuta qualsiasi path che contenga ".."
    while ".." in sanitized:
        sanitized = sanitized.replace("..", "_")
        
    if not sanitized or all(c in ['.', '_', '-'] for c in sanitized):
        sanitized = "attachment"
    return sanitized

@mcp.tool()
def get_document_attachments(model_name: str, record_id: int, extract_xml_text: bool = True, chat_session_id: str = None) -> str:
    """
    Scarica gli allegati (file) associati a uno specifico record Odoo.
    Ideale per recuperare gli XML delle fatture elettroniche o i PDF scansionati.
    
    Args:
        model_name (str): Il nome del modello (es. 'account.move' per le fatture, 'purchase.order' per gli acquisti).
        record_id (int): L'ID numerico del record.
        extract_xml_text (bool): Se True, decodifica automaticamente gli allegati XML e text in stringhe leggibili dall'AI.
        chat_session_id (str): Opzionale. L'ID della sessione chat in cui salvare i file (iniettato automaticamente).
    """
    try:
        models = xmlrpc.client.ServerProxy(object_endpoint)
        
        # Cerchiamo gli allegati collegati al record specifico
        attachments = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'ir.attachment', 'search_read',
            [[('res_model', '=', model_name), ('res_id', '=', record_id)]],
            {'fields': ['name', 'mimetype', 'datas']}
        )
        
        if not attachments:
            return json.dumps({"message": f"Nessun allegato trovato per il record {record_id} di {model_name}."})
            
        session_id = (chat_session_id or os.environ.get("AION_CHAT_SESSION_ID") or "").strip()
        results = []
        for att in attachments:
            file_data = att.get('datas')
            if not file_data:
                continue
                
            orig_name = att['name']
            sanitized_name = sanitize_filename(orig_name)
            
            result_item = {
                "file_name": orig_name,
                "mime_type": att['mimetype']
            }
            
            saved_path = None
            if session_id:
                try:
                    from src.session_workspace import safe_resolve, ensure_session_dirs
                    ensure_session_dirs(session_id)
                    relative_path = f"derived/{sanitized_name}"
                    abs_path = safe_resolve(session_id, relative_path)
                    
                    file_bytes = base64.b64decode(file_data)
                    abs_path.write_bytes(file_bytes)
                    
                    saved_path = relative_path
                    result_item["saved_path"] = saved_path
                except Exception as save_err:
                    logger.error(f"Errore durante il salvataggio dell'allegato {orig_name} nella sessione {session_id}: {save_err}")
                    result_item["save_error"] = str(save_err)
            
            # Se è un XML e vogliamo il testo, lo decodifichiamo per l'LLM
            if extract_xml_text and att['mimetype'] in ['application/xml', 'text/xml']:
                try:
                    xml_content = base64.b64decode(file_data).decode('utf-8')
                    result_item["content"] = xml_content
                except Exception:
                    if not saved_path:
                        result_item["base64_data"] = file_data # Fallback
            else:
                if not saved_path:
                    result_item["base64_data"] = file_data
                
            results.append(result_item)
            
        return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool()
def get_invoice_lines(move_id: int, fields_to_read: list[str] = None) -> str:
    """
    Recupera le singole righe (account.move.line) di una specifica fattura partendo dal suo ID.
    Questo tool è essenziale per il 'three-way matching': usalo quando hai già trovato 
    l'ID della fattura (move_id) e hai bisogno di leggere i dettagli su quantità, prezzi e prodotti.

    Args:
        move_id (int): L'ID numerico della fattura (il record di account.move).
        fields_to_read (list[str]): Opzionale. I nomi tecnici dei campi da estrarre.
                                    Se omesso, estrarrà un set predefinito ideale per la riconciliazione.
                                    ATTENZIONE: in caso di errori su campi calcolati, richiama il tool
                                    specificando solo i campi base sicuri.
    """
    logger.info(f"Esecuzione get_invoice_lines per move_id: {move_id}")
    try:
        models = xmlrpc.client.ServerProxy(object_endpoint)

        # Filtriamo le righe in base all'ID della fattura
        domain = [('move_id', '=', move_id)]
        
        # Se l'agente non specifica i campi, diamo noi un set ottimizzato per il matching
        if not fields_to_read:
            fields_to_read = [
                'product_id', 
                'name', 
                'quantity', 
                'price_unit', 
                'price_subtotal',
                'display_type' # Utile per scartare righe di testo o sezioni
            ]

        lines = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'account.move.line', 'search_read',
            [domain],
            {'fields': fields_to_read}
        )
        
        # Filtriamo per restituire solo le righe prodotto (ignorando le righe puramente contabili come l'IVA o i totali)
        # In Odoo, le righe che non sono prodotti hanno spesso display_type popolato ('line_section', 'line_note')
        # o non hanno un prodotto e una quantità associata, ma l'agente saprà interpretarlo.
        
        return json.dumps({
            "move_id": move_id,
            "lines_count": len(lines),
            "lines": lines
        }, indent=2)

    except Exception as e:
        logger.exception(f"Errore durante l'estrazione delle righe per move_id {move_id}: {e}")
        return json.dumps({
            "error_type": "Odoo RPC Exception",
            "details": str(e),
            "agent_instruction": "Usa il tool 'get_odoo_model_schema' per verificare quali campi esistono in 'account.move.line', poi richiama 'get_invoice_lines' escludendo eventuali campi calcolati problematici."
        })

@mcp.tool()
def search_odoo_records(model_name: str, domain: list = None, fields_to_read: list[str] = None, limit: int = 10) -> str:
    """
    Cerca e legge record da QUALSIASI modello Odoo. 
    Usa questo tool per interrogare tabelle generiche o nuovi moduli.

    Args:
        model_name (str): Il nome tecnico del modello (es. 'stock.picking', 'res.partner', 'product.template').
        domain (list): La lista dei filtri di ricerca in sintassi Odoo (es. [["state", "=", "done"], ["name", "ilike", "INV"]]). 
                       Usa un array vuoto [] per prendere gli ultimi record senza filtri.
        fields_to_read (list[str]): Opzionale. La lista dei nomi tecnici dei campi da estrarre.
        limit (int): Il numero massimo di record da restituire (default 10).
    """
    logger.info(f"Esecuzione search_odoo_records su {model_name} con filtri {domain}")
    try:
        models = xmlrpc.client.ServerProxy(object_endpoint)
        
        # Odoo si aspetta sempre una lista di liste per il dominio, anche se vuota
        search_domain = domain if domain else []
        
        kwargs = {'limit': limit}
        if fields_to_read:
            kwargs['fields'] = fields_to_read
            
        records = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            model_name, 'search_read',
            [search_domain],
            kwargs
        )
        
        return json.dumps({
            "model": model_name,
            "count": len(records),
            "data": records
        }, indent=2)

    except Exception as e:
        logger.exception(f"Errore ricerca generica su {model_name}: {e}")
        return json.dumps({
            "error_type": "Odoo RPC Exception",
            "details": str(e),
            "agent_instruction": f"Usa 'get_odoo_model_schema' per verificare che il modello '{model_name}' e i campi richiesti esistano. Assicurati che il 'domain' sia una lista di liste valida per Odoo."
        })
      
@mcp.tool()
def get_purchase_order_lines(order_ref: str) -> str:
    """
    Retrieve all detailed line items of a specific Purchase Order (PO) from Odoo ERP.
    
    This tool is essential for performing "three-way matching" document validation,
    allowing you to match invoice details or receipt notes with the original Purchase Order.
    It extracts exact ordered quantities, unit prices, subtotal amounts, and product identifiers.

    Args:
        order_ref (str): The exact reference code of the Purchase Order (e.g., 'P00042', 'PO001').

    Returns:
        str: A JSON string containing either:
             - 'order_ref' (str) and 'lines' (list of dicts) with keys: product_id (tuple [id, name]), 
               product_qty (float), price_unit (float), and price_subtotal (float).
             - A JSON object with an 'error' or 'message' field if the order does not exist,
               has no lines, or if a database query issue arises.
    """
    logger.info(f"Executing get_purchase_order_lines for reference: '{order_ref}'")
    try:
        # Re-initialize ServerProxy in the thread to ensure thread-safety of socket connections
        models = xmlrpc.client.ServerProxy(object_endpoint)

        # 1. Search for the purchase order matching the reference
        logger.info(f"Searching for purchase.order with name='{order_ref}'")
        orders: list[dict[str, Any]] = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_API_KEY,
            'purchase.order',
            'search_read',
            [[('name', '=', order_ref)]],
            {'fields': ['order_line'], 'limit': 1}
        )

        if not orders:
            logger.warning(f"Purchase order '{order_ref}' not found in Odoo database.")
            return json.dumps({"error": f"Purchase order '{order_ref}' not found."})

        # 2. Extract line IDs from the order
        line_ids: list[int] = orders[0].get('order_line', [])
        logger.info(f"Found purchase order '{order_ref}' with line IDs: {line_ids}")

        if not line_ids:
            logger.warning(f"Purchase order '{order_ref}' exists but contains no lines.")
            return json.dumps({
                "order_ref": order_ref,
                "lines": [],
                "message": f"Purchase order '{order_ref}' has no lines."
            })

        # 3. Read specific fields from purchase.order.line
        logger.info(f"Reading details for line IDs: {line_ids}")
        lines: list[dict[str, Any]] = models.execute_kw(
            ODOO_DB,
            uid,
            ODOO_API_KEY,
            'purchase.order.line',
            'search_read',
            [[('id', 'in', line_ids)]],
            {'fields': ['product_id', 'product_qty', 'price_unit', 'price_subtotal']}
        )

        logger.info(f"Successfully retrieved {len(lines)} lines for purchase order '{order_ref}'")
        return json.dumps({
            "order_ref": order_ref,
            "lines": lines
        }, indent=2)

    except Exception as e:
        logger.exception(f"Error occurred while retrieving purchase order lines for '{order_ref}': {e}")
        return json.dumps({"error": f"Failed to retrieve purchase order lines: {str(e)} "})

@mcp.tool()
def calculate_po_totals(po_list: Union[List[str], str]) -> str:
    """
    Calcola la somma dei costi degli Ordini di Acquisto (PO) specificati su Odoo.

    Args:
        po_list: Lista di nomi/codici di PO (es. ["LA00120910", "LA00120895"]) oppure stringa separata da virgole.

    Returns:
        str: JSON con la somma dei costi senza IVA (total_untaxed) e con IVA (total_with_vat).
    """
    try:
        if isinstance(po_list, str):
            names = [x.strip().strip("'\"[]") for x in po_list.replace("\n", ",").split(",") if x.strip()]
        else:
            names = [str(x).strip().strip("'\"[]") for x in po_list if str(x).strip()]

        if not names:
            return json.dumps({"total_untaxed": 0.0, "total_with_vat": 0.0})

        models = xmlrpc.client.ServerProxy(object_endpoint)
        orders = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'purchase.order', 'search_read',
            [[['name', 'in', names]]],
            {'fields': ['amount_untaxed', 'amount_total']}
        )
        total_untaxed = sum(float(po.get('amount_untaxed') or 0.0) for po in orders)
        total_with_vat = sum(float(po.get('amount_total') or 0.0) for po in orders)

        return json.dumps({
            "total_untaxed": round(total_untaxed, 2),
            "total_with_vat": round(total_with_vat, 2)
        })
    except Exception as e:
        return json.dumps({"error": f"Errore nel calcolo somme PO: {str(e)}"})

def _clean_dynamic_site_name(site_val: Any, contract_name: str = "", line_name: str = "") -> str:
    """
    Estrae e pulisce in modo dinamico e generico il nome dell'impianto di destinazione
    senza utilizzare parole chiave o città hardcoded.
    """
    site_str = ""
    if site_val:
        site_str = str(site_val[1] if isinstance(site_val, (list, tuple)) else site_val).strip()

    if site_str:
        # Se ci sono virgole, prendiamo la parte dopo la virgola (solitamente l'impianto specifico)
        parts = [p.strip() for p in site_str.split(",") if p.strip()]
        candidate = parts[-1] if len(parts) > 1 else parts[0]
        if "-" in candidate:
            subparts = [p.strip() for p in candidate.split("-") if p.strip()]
            if len(subparts) > 1:
                candidate = subparts[-1]
        
        # Rimuoviamo prefissi generici di impianti in modo case-insensitive
        clean = re.sub(r'^(IMPIANTO DI|IMPIANTO|DEPURATORE DI|DEPURATORE|DISCARICA DI|DISCARICA|C/O|POLO DI|STADIO DI)\s+', '', candidate, flags=re.IGNORECASE).strip()
        if clean:
            return clean.title()

    # Fallback su contract_name o line_name
    for text in [contract_name, line_name]:
        if not text:
            continue
        match = re.search(r'(?:impianto|depuratore|discarica)\s+(?:di\s+)?([A-Za-z0-9àèéìòùÀÈÉÌÒÙ\s]+)', text, flags=re.IGNORECASE)
        if match:
            extracted = match.group(1).strip().split()[0]
            if len(extracted) > 2:
                return extracted.title()

    return ""


def _determine_dynamic_waste_type(prod_val: Any, line_name: str = "", cer_val: Any = "") -> str:
    """
    Determina in modo dinamico e generico il tipo di rifiuto / prodotto / servizio
    estratto da Odoo per consentire l'associazione corretta con le righe di fattura.
    """
    prod_name = (prod_val[1] if isinstance(prod_val, (list, tuple)) else str(prod_val or "")).strip()
    line_name_clean = (line_name or "").strip()
    raw_desc = f"{prod_name} {line_name_clean}".upper()

    # 1. PERCOLATO / CER 190703
    if "PERCOLATO" in raw_desc or "190703" in raw_desc:
        return "PERCOLATO"

    # 2. Servizi specifici non di smaltimento (es. 'Trasporto Intermodale', 'Noleggio', 'Consulenza')
    if prod_name and prod_name.upper() not in ["SMALTIMENTO RIFIUTI", "SMALTIMENTO", "SERVIZIO", "GENERICO"]:
        if not any(k in prod_name.upper() for k in ["SMALTIMENTO", "RIFIUTI"]):
            return prod_name

    # 3. Tutti gli altri rifiuti / smaltimenti confluiscono in ALTRI RIFIUTI per sito ed aliquota IVA
    return "ALTRI RIFIUTI"


@mcp.tool()
def get_monthly_waste_reconciliation_data(
    partner_id: int,
    start_date: str,
    end_date: str,
    contract_id: int = None,
    group_by_site: bool = True
) -> str:
    """
    Recupera e aggrega tutti i dati di riconciliazione mensile rifiuti per un fornitore in un periodo specifico.
    Produce l'output JSON completo con la suddivisione dei costi per le 5 categorie di impianto/tipo/IVA,
    la mappa dei clienti/contratti unici e l'elenco dettagliato delle discrepanze (discrepancies).

    OBBLIGATORIO PER L'AGENTE: Dopo aver chiamato questo tool e calculate_contracts_total_cost,
    DEVI SEMPRE STAMPARE nel testo della risposta le tabelle di riconciliazione:
    1. Tabella Sintesi Finanziaria (Fattura vs Totale PO Odoo)
    2. Tabella Impianti / Categorie di Destinazione (categories_with_vat)
    3. Tabella Dettaglio Clienti e Contratti Associati con Costi Totali per Cliente
    4. Tabella Audit Discrepanze e Anomalie Identificate (se presenti)

    Args:
        partner_id (int): L'ID numerico del fornitore su Odoo (res.partner).
        start_date (str): Data inizio periodo nel formato 'YYYY-MM-DD' (es. '2025-12-01').
        end_date (str): Data fine periodo nel formato 'YYYY-MM-DD' (es. '2025-12-31').
        contract_id (int): Opzionale. Filtra solo per uno specifico contratto ID se presente.
    Returns:
        str: JSON formattato con i totali per categoria, clienti unici e discrepanze di peso e prezzo.
    """
    logger.info(f"Esecuzione get_monthly_waste_reconciliation_data per partner_id={partner_id}, periodo={start_date} - {end_date}")
    try:
        models = xmlrpc.client.ServerProxy(object_endpoint)
        start_dt = f"{start_date} 00:00:00"
        end_dt = f"{end_date} 23:59:59"
        # Supplier Name
        partner_info = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'res.partner', 'read',
            [[partner_id]],
            {'fields': ['name']}
        )
        supplier_name = partner_info[0]['name'] if partner_info else "Fornitore"
       
        # 1. Cerca ordini di acquisto
        po_domain = [
            ('partner_id', '=', partner_id),
            ('state', 'in', ['purchase', 'done', 'contract']),
            ('date_planned', '>=', start_dt),
            ('date_planned', '<=', end_dt),
            ('amount_untaxed', '>', 0.0)
        ]

        if contract_id:
            po_domain.append(('contract_order_id', '=', contract_id))
       
        orders = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'purchase.order', 'search_read',
            [po_domain],
            {'fields': ['id', 'name', 'date_planned', 'amount_untaxed', 'amount_total', 'order_line', 'contract_order_id', 'atl_contract_id'], 'limit': 500}
        )
        
        # Scarta PO con imponibile pari a 0.0
        orders = [o for o in orders if float(o.get('amount_untaxed') or 0.0) > 0.0]
        
        all_line_ids = []
        for o in orders:
            all_line_ids.extend(o.get('order_line', []))
            
        # 2. Cerca le righe PO
        order_lines = []
        if all_line_ids:
            order_lines = models.execute_kw(
                ODOO_DB, uid, ODOO_API_KEY,
                'purchase.order.line', 'search_read',
                [[['id', 'in', all_line_ids]]],
                {'fields': [
                    'id', 'order_id', 'product_id', 'name', 'product_qty', 'price_unit', 'price_subtotal',
                    'date_planned', 'taxes_id', 'contract_order_id', 'source_contract_line_id',
                    'fir_ids', 'fsm_fir_ids', 'fir_dest_qty_kg', 'fir_producer_id',
                    'recipient_site_id', 'fsm_recipient_site_id', 'fir_waste_cer'
                ]}
            )

        # 3. Mappe contratti, tasse e formulari FIR
        contract_line_ids = set()
        tax_ids = set()
        fir_ids_set = set()

        for line in order_lines:
            s_c = line.get('source_contract_line_id')
            if s_c:
                contract_line_ids.add(s_c[0] if isinstance(s_c, (list, tuple)) else s_c)
            for t in line.get('taxes_id') or []:
                tax_ids.add(t)
            for f in line.get('fsm_fir_ids') or line.get('fir_ids') or []:
                fir_ids_set.add(f)

        contract_prices_map = {}
        if contract_line_ids:
            try:
                c_lines = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'purchase.order.line', 'search_read',
                    [[['id', 'in', list(contract_line_ids)]]],
                    {'fields': ['id', 'price_unit']})
                for cl in c_lines:
                    contract_prices_map[cl['id']] = cl.get('price_unit')
            except Exception:
                pass
        
        tax_rates_map = {}
        if tax_ids:
           try:
                taxes = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'account.tax', 'search_read',
                    [[['id', 'in', list(tax_ids)]]],
                    {'fields': ['id', 'amount']}
                )
                for tax in taxes:
                    tax_rates_map[tax['id']] = tax.get('amount', 10.0)
           except Exception:
                pass
        
        fir_names_map = {}
        if fir_ids_set:
            try:
                firs = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'waste.fir', 'search_read',
                    [[['id', 'in', list(fir_ids_set)]]],
                    {'fields': ['id', 'name']}
 )
                for f in firs:
                    fir_names_map[f['id']] = f.get('name', '')
            except Exception:
                pass

        # 4. Pre-aggregazione quantita e righe per ciascun PO (order_id)
        po_qty_totals = {}
        po_lines_map = {}
        for line in order_lines:
            po_info = line.get('order_id')
            po_id = po_info[0] if isinstance(po_info, (list, tuple)) else po_info
            p_qty = float(line.get('product_qty') or 0.0)
            if po_id not in po_qty_totals:
                po_qty_totals[po_id] = 0.0
                po_lines_map[po_id] = []
            po_qty_totals[po_id] += p_qty
            po_lines_map[po_id].append(line)

        client_contracts_map = {}
        discrepancies = []
        totals_by_category_map = {}
        total_po_cost_untaxed = 0.0
        total_po_cost_with_vat = 0.0
        for line in order_lines:
            po_info = line.get('order_id')
            po_id = po_info[0] if isinstance(po_info, (list, tuple)) else po_info
            po_name = po_info[1] if isinstance(po_info, (list, tuple)) else str(po_info)
            line_date = str(line.get('date_planned', ''))[:10]
            
            # Cliente produttore
            p_val = line.get('fir_producer_id')
            client_name = p_val[1] if isinstance(p_val, (list, tuple)) else "Non Specificato"
 
            # Contratto
            c_val = line.get('contract_order_id')
            contract_name = c_val[1] if isinstance(c_val, (list, tuple)) else ""
            if client_name not in client_contracts_map:
                client_contracts_map[client_name] = set()
            if contract_name:
                client_contracts_map[client_name].add(contract_name)
            
            # Tipo Rifiuto / Prodotto / Servizio (Dinamico e generico)
            prod_val = line.get('product_id')
            prod_name = prod_val[1] if isinstance(prod_val, (list, tuple)) else ""
            line_name = (line.get('name') or "").strip()
            cer_val = line.get('fir_waste_cer')

            # Impianto di destinazione (Dinamico e generico)
            site_val = line.get('fsm_recipient_site_id') or line.get('recipient_site_id')
            site_clean = _clean_dynamic_site_name(site_val, contract_name, line_name)

            waste_type = _determine_dynamic_waste_type(prod_val, line_name, cer_val)

            # Aliquota IVA
            vat_rate = 10.0
            for tid in (line.get('taxes_id') or []):
                rate = tax_rates_map.get(tid, 10.0)
                if round(rate) == 22:
                    vat_rate = 22.0
                    break
                elif round(rate) == 0:
                    vat_rate = 0.0
            # Costruzione dinamica della chiave di categoria
            if group_by_site and site_clean:
                cat_key = f"{waste_type} - {site_clean} ({int(vat_rate)}%)"
            else:
                cat_key = f"{waste_type} ({int(vat_rate)}%)"
            if cat_key not in totals_by_category_map:
                totals_by_category_map[cat_key] = {
                    "category": cat_key,
                    "po_count": 0,
                    "matching_po_count": 0,
                    "total_po_qty_tons": 0.0,
                    "total_fir_qty_tons": 0.0,
                    "total_amount_untaxed": 0.0,
                    "total_amount_with_vat": 0.0,
                    "qty_deviation_pct": 0.0
                }
            po_qty = float(line.get('product_qty') or 0.0)
            po_price = float(line.get('price_unit') or 0.0)
            subtotal = float(line.get('price_subtotal') or 0.0)

            line_with_vat = subtotal * (1.0 + vat_rate / 100.0)
            total_po_cost_untaxed += subtotal
            total_po_cost_with_vat += line_with_vat
            fir_kg = line.get('fir_dest_qty_kg') or 0.0
            fir_qty = fir_kg / 1000.0 if fir_kg > 0 else 0.0

            # Prezzo contratto
            s_c = line.get('source_contract_line_id')
            s_id = s_c[0] if isinstance(s_c, (list, tuple)) else s_c
            contract_price = contract_prices_map.get(s_id, po_price)
            
            # Check discrepanze smart per PO multi-linea
            po_total_qty = po_qty_totals.get(po_id, 0.0)
            if po_qty == 0.0 and subtotal == 0.0:
                if abs(po_total_qty - fir_qty) <= 0.01:
                    is_qty_mismatch = False
                else:
                    is_first_line = (line.get('id') == po_lines_map[po_id][0].get('id'))
                    is_qty_mismatch = is_first_line and (abs(po_total_qty - fir_qty) > 0.01)
            else:
                qty_diff = abs(po_qty - fir_qty)
                is_qty_mismatch = (qty_diff > 0.01)

            price_diff = round(po_price - contract_price, 4)
            is_price_mismatch = (abs(price_diff) > 0.01 and po_qty > 0.0)
            cat_data = totals_by_category_map[cat_key]
            cat_data["po_count"] += 1
            cat_data["total_po_qty_tons"] += po_qty
            cat_data["total_fir_qty_tons"] += fir_qty
            cat_data["total_amount_untaxed"] += subtotal
            cat_data["total_amount_with_vat"] += line_with_vat
            
            if not is_qty_mismatch and not is_price_mismatch:
                cat_data["matching_po_count"] += 1
            
            # Codice FIR
            fir_list = line.get('fsm_fir_ids') or line.get('fir_ids') or []
            fir_str = ", ".join(fir_names_map.get(f, str(f)) for f in fir_list) if fir_list else ""
            
            # Codice CER
            cer_val = line.get('fir_waste_cer')
            if isinstance(cer_val, (list, tuple)):
                cer_str = str(cer_val[1]).split()[0]
            else:
                cer_str = str(cer_val or "")
            
            if is_qty_mismatch or is_price_mismatch:
                status_str = "WARNING: QTY_MISMATCH" if is_qty_mismatch else "WARNING: PRICE_MISMATCH"
                discrepancies.append({
                    "po": po_name,
                    "date": line_date,
                    "client": client_name,
                    "site": site_clean or "N/A",
                    "contract": contract_name,
                    "cer": cer_str,
                    "firs": fir_str,
                    "po_qty": po_total_qty if po_qty == 0.0 else po_qty,
                    "fir_qty": fir_qty,
                    "po_price": po_price,
                    "contract_price": contract_price,
                    "price_diff": price_diff,
                    "status": status_str
                })
        
        # Calcolo totali per categoria e percentuali
        totals_by_category_list = []
        categories_with_vat_dict = {}
        
        for k, v in totals_by_category_map.items():
            v["total_po_qty_tons"] = round(v["total_po_qty_tons"], 2)
            v["total_fir_qty_tons"] = round(v["total_fir_qty_tons"], 2)
            v["total_amount_untaxed"] = round(v["total_amount_untaxed"], 2)
            v["total_amount_with_vat"] = round(v["total_amount_with_vat"], 2)
            if v["total_fir_qty_tons"] > 0:
                v["qty_deviation_pct"] = round(((v["total_po_qty_tons"] - v["total_fir_qty_tons"]) / v["total_fir_qty_tons"]) * 100, 2)
            else:
                v["qty_deviation_pct"] = 0.0
            totals_by_category_list.append(v)
            categories_with_vat_dict[k] = v["total_amount_with_vat"]
        unique_clients_contracts = [
            {"client": k, "contracts": sorted(list(v))} for k, v in sorted(client_contracts_map.items()) if k != "Non Specificato"
        ]
        result = {
            "period": f"{start_date} - {end_date}",
            "supplier_id": partner_id,
            "supplier_name": supplier_name,
            "total_po_count": len(orders),
            "total_po_cost_untaxed": round(total_po_cost_untaxed, 2),
            "total_po_cost_with_vat": round(total_po_cost_with_vat, 2),
            "categories_with_vat": categories_with_vat_dict,
            "total_discrepancies_count": len(discrepancies),
            "unique_clients_contracts": unique_clients_contracts,
            "totals_by_category": totals_by_category_list,
            "discrepancies": discrepancies
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.exception(f"Errore durante l'esecuzione di get_monthly_waste_reconciliation_data: {e}")
        return json.dumps({
            "error": f"Impossibile completare la riconciliazione mensile: {str(e)}"
        })


@mcp.tool()
def calculate_contracts_total_cost(
    contracts: Union[List[str], str],
    start_date: str,
    end_date: str = None
) -> str:
    """
    Calcola il costo totale da Odoo per ciascun contratto in una lista per un determinato periodo,
    cercando tutti i PO di quel contratto e quel periodo e facendo la somma degli importi.

    Args:
        contracts: Lista di codici/nomi di contratti (es. ["CONTRATTO_01", "CONTRATTO_02"]) oppure stringa separata da virgole/JSON.
        start_date (str): Data inizio periodo (formato 'YYYY-MM-DD').
        end_date (str): Opzionale. Data fine periodo (formato 'YYYY-MM-DD').

    Returns:
        str: Stringa JSON che ha per chiave il codice/nome del contratto e per valore il costo totale (float).
    """
    logger.info(f"Esecuzione calculate_contracts_total_cost per contratti={contracts}, periodo={start_date} - {end_date}")
    try:
        # Parsing dei contratti
        contract_names: list[str] = []
        if isinstance(contracts, str):
            contracts_str = contracts.strip()
            if contracts_str.startswith("[") and contracts_str.endswith("]"):
                try:
                    parsed = json.loads(contracts_str)
                    if isinstance(parsed, list):
                        contract_names = [str(c).strip() for c in parsed if str(c).strip()]
                except Exception:
                    pass
            if not contract_names:
                contract_names = [c.strip().strip("'\"") for c in contracts_str.replace("\n", ",").split(",") if c.strip()]
        elif isinstance(contracts, list):
            contract_names = [str(c).strip() for c in contracts if str(c).strip()]

        if not contract_names:
            return json.dumps({})

        # Parsing del periodo
        if not end_date and isinstance(start_date, str):
            if " - " in start_date:
                parts = start_date.split(" - ")
                start_date = parts[0].strip()
                end_date = parts[1].strip()
            elif "," in start_date:
                parts = start_date.split(",")
                start_date = parts[0].strip()
                end_date = parts[1].strip()

        start_dt = f"{start_date} 00:00:00" if start_date else ""
        end_dt = f"{end_date} 23:59:59" if end_date else ""

        models = xmlrpc.client.ServerProxy(object_endpoint)

        # Ricerca ordini di acquisto
        po_domain = [
            ('state', 'in', ['purchase', 'done', 'contract']),
            ('amount_untaxed', '>', 0.0)
        ]
        if start_dt:
            po_domain.append(('date_planned', '>=', start_dt))
        if end_dt:
            po_domain.append(('date_planned', '<=', end_dt))

        orders = models.execute_kw(
            ODOO_DB, uid, ODOO_API_KEY,
            'purchase.order', 'search_read',
            [po_domain],
            {
                'fields': ['id', 'name', 'date_planned', 'amount_untaxed', 'amount_total', 'order_line', 'contract_order_id', 'atl_contract_id'],
                'limit': 1000
            }
        )

        all_line_ids = []
        for o in orders:
            all_line_ids.extend(o.get('order_line', []))

        po_line_contracts = {}
        if all_line_ids:
            try:
                order_lines = models.execute_kw(
                    ODOO_DB, uid, ODOO_API_KEY,
                    'purchase.order.line', 'search_read',
                    [[['id', 'in', all_line_ids]]],
                    {'fields': ['id', 'order_id', 'contract_order_id', 'name']}
                )
                for line in order_lines:
                    po_info = line.get('order_id')
                    po_id = po_info[0] if isinstance(po_info, (list, tuple)) else po_info
                    c_val = line.get('contract_order_id')
                    if c_val:
                        c_name = c_val[1] if isinstance(c_val, (list, tuple)) else str(c_val)
                        if po_id not in po_line_contracts:
                            po_line_contracts[po_id] = set()
                        po_line_contracts[po_id].add(c_name)
            except Exception as line_err:
                logger.warning(f"Errore durante l'estrazione contratti dalle righe PO: {line_err}")

        contract_totals = {c: 0.0 for c in contract_names}

        for c_target in contract_names:
            t_clean = c_target.strip().lower()
            total_cost = 0.0
            matched_po_ids = set()

            for o in orders:
                o_id = o['id']
                if o_id in matched_po_ids:
                    continue

                candidates = set()
                c1 = o.get('contract_order_id')
                if c1:
                    candidates.add(c1[1] if isinstance(c1, (list, tuple)) else str(c1))
                c2 = o.get('atl_contract_id')
                if c2:
                    candidates.add(c2[1] if isinstance(c2, (list, tuple)) else str(c2))
                for line_c in po_line_contracts.get(o_id, []):
                    candidates.add(line_c)

                po_name = o.get('name', '')
                if po_name:
                    candidates.add(po_name)

                is_match = False
                for cand in candidates:
                    cand_clean = str(cand).strip().lower()
                    if not cand_clean:
                        continue
                    if t_clean == cand_clean or t_clean in cand_clean or cand_clean in t_clean:
                        is_match = True
                        break

                if is_match:
                    matched_po_ids.add(o_id)
                    total_cost += float(o.get('amount_total') or 0.0)

            contract_totals[c_target] = round(total_cost, 2)

        return json.dumps(contract_totals, indent=2)

    except Exception as e:
        logger.exception(f"Errore durante l'esecuzione di calculate_contracts_total_cost: {e}")
        return json.dumps({
            "error": f"Impossibile calcolare il costo totale dei contratti: {str(e)}"
        })


if __name__ == "__main__":
    # Runs the FastMCP server on stdio transport
    mcp.run()


