"""
Odoo MCP Server: Connects to an Odoo ERP instance via XML-RPC.
Exposes tools to support a "three-way matching" document validation workflow.
"""

from __future__ import annotations

import os
import sys
import json
import logging
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
        return json.dumps({"error": f"Failed to retrieve purchase order lines: {str(e)}"})

if __name__ == "__main__":
    # Runs the FastMCP server on stdio transport
    mcp.run()
