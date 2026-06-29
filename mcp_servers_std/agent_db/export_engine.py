# mcp_servers/agent_db/export_engine.py
import csv
import io
import json
from typing import List, Dict, Any, Literal

class ExportEngine:
    def export_to_csv(self, columns: List[str], rows: List[List[Any]]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        writer.writerows(rows)
        return output.getvalue()

    def export_to_json(self, columns: List[str], rows: List[List[Any]]) -> str:
        data = []
        for row in rows:
            data.append(dict(zip(columns, row)))
        return json.dumps(data, indent=2)

    def export_to_xlsx(self, columns: List[str], rows: List[List[Any]]) -> bytes:
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl is not installed. XLSX export is disabled.")
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(columns)
        for row in rows:
            ws.append(row)
        
        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()
