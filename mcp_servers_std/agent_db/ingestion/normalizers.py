# mcp_servers/agent_db/ingestion/normalizers.py
import re
from datetime import datetime
from typing import Any, Optional

def normalize_date(value: Any) -> Optional[str]:
    """Normalizes various date formats to ISO8601 (YYYY-MM-DD)."""
    if not value or not isinstance(value, str):
        return None
    
    value = value.strip()
    
    # Italian formats: dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
    patterns = [
        (r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', '%d/%m/%Y'),
        (r'(\d{4})-(\d{1,2})-(\d{1,2})', '%Y-%m-%d'), # ISO
    ]
    
    for pattern, date_fmt in patterns:
        match = re.match(pattern, value)
        if match:
            try:
                # Standardize separators for strptime
                std_value = value.replace('-', '/').replace('.', '/') if '/' in date_fmt else value
                dt = datetime.strptime(std_value, date_fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
    
    return value # Return as is if not matched, sqlite might handle or insert_batch will fail later

def normalize_decimal(value: Any) -> Optional[float]:
    """Normalizes EU and US decimal formats to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    
    if not isinstance(value, str):
        return None
    
    val = value.strip()
    # Remove currency symbols and spaces
    val = re.sub(r'[€$£\s]', '', val)
    
    # EU: 1.250,00 -> 1250.00
    # US: 1,250.00 -> 1250.00
    
    if ',' in val and '.' in val:
        if val.find('.') < val.find(','): # EU format
            val = val.replace('.', '').replace(',', '.')
        else: # US format
            val = val.replace(',', '')
    elif ',' in val:
        # Check if comma is decimal separator (e.g., 10,5) or thousand separator (e.g., 1,250)
        # Simple heuristic: if only one comma and < 3 digits after, it's likely decimal
        parts = val.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            val = val.replace(',', '.')
        else:
            val = val.replace(',', '')
    
    try:
        return float(val)
    except ValueError:
        return None

def normalize_name(name: str) -> str:
    """Normalizes headers to snake_case names."""
    # Lowercase, replace non-alphanumeric with underscore
    n = name.lower().strip()
    n = re.sub(r'[^a-z0-9]', '_', n)
    # Remove leading/trailing underscores
    n = n.strip('_')
    # Collapse multiple underscores
    n = re.sub(r'_{2,}', '_', n)
    # If starts with digit, prepend 'col_'
    if n and n[0].isdigit():
        n = 'col_' + n
    # Max 63 chars
    return n[:63]
