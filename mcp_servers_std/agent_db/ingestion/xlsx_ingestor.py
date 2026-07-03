# mcp_servers/agent_db/ingestion/xlsx_ingestor.py
import io
from typing import List, Dict, Any

try:
    import openpyxl
except ImportError:
    openpyxl = None


def read_xlsx(file_content: bytes) -> List[Dict[str, Any]]:
    """Reads XLSX binary content and returns a list of dictionaries."""
    if not openpyxl:
        raise ImportError("openpyxl is not installed. XLSX support is disabled.")

    f = io.BytesIO(file_content)
    wb = openpyxl.load_workbook(f, data_only=True)
    ws = wb.active

    rows = list(ws.rows)
    if not rows:
        return []

    headers = [cell.value for cell in rows[0]]
    data = []

    for row in rows[1:]:
        row_dict = {}
        for i, cell in enumerate(row):
            if i < len(headers):
                header = headers[i]
                if header:
                    row_dict[str(header)] = cell.value
        data.append(row_dict)

    return data
