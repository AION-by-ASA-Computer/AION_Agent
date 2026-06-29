# mcp_servers/agent_db/ingestion/csv_ingestor.py
import csv
import io
from typing import List, Dict, Any

def read_csv(content: str, delimiter: str = ',') -> List[Dict[str, Any]]:
    """Reads CSV content and returns a list of dictionaries."""
    f = io.StringIO(content)
    reader = csv.DictReader(f, delimiter=delimiter)
    return [row for row in reader]
