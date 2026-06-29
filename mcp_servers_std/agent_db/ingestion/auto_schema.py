# mcp_servers/agent_db/ingestion/auto_schema.py
import json
from typing import List, Dict, Any
from .normalizers import normalize_name

def infer_schema_from_sample(rows: List[Dict[str, Any]], sample_size: int = 50) -> List[Dict[str, Any]]:
    """Infers column types from a data sample."""
    if not rows:
        return []
    
    sample = rows[:sample_size]
    headers = rows[0].keys()
    column_defs = []
    
    for header in headers:
        physical_name = normalize_name(header)
        
        # Check values in sample for this header
        values = [row.get(header) for row in sample if row.get(header) is not None]
        
        inferred_type = "TEXT"
        nullable = len(values) < len(sample)
        
        if values:
            # Try to infer type
            is_int = True
            is_real = True
            is_bool = True
            is_json = True
            
            for v in values:
                v_str = str(v).strip().lower()
                
                # Check INT
                try:
                    int(v_str)
                except ValueError:
                    is_int = False
                
                # Check REAL
                try:
                    float(v_str.replace(',', '.')) # Basic check
                except ValueError:
                    is_real = False
                
                # Check BOOL
                if v_str not in ('true', 'false', '0', '1', 'si', 'no', 'sì'):
                    is_bool = False
                
                # Check JSON
                if not (v_str.startswith('{') or v_str.startswith('[')):
                    is_json = False
            
            if is_int:
                inferred_type = "INTEGER"
            elif is_real:
                inferred_type = "REAL"
            elif is_bool:
                inferred_type = "BOOLEAN"
            elif is_json:
                inferred_type = "JSON"
            # Date detection can be added here if needed
            
        column_defs.append({
            "name": header,
            "physical_name": physical_name,
            "type": inferred_type,
            "nullable": nullable,
            "description": f"Inferred column from header '{header}'"
        })
        
    return column_defs
