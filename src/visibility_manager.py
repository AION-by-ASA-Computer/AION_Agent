import logging
import json
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("aion.visibility")

class VisibilityManager:
    """
    Manages tool execution visibility, logging starts, ends, and errors.
    This is a stub implementation to restore functionality and prevent ImportErrors.
    """
    def __init__(self, log_dir: str = "data/logs/visibility"):
        self.log_dir = log_dir
        import os
        os.makedirs(log_dir, exist_ok=True)

    def log_tool_call(self, session_id: str, tool_name: str, event_type: str, call_id: str, data: Dict[str, Any]):
        """Logs a tool call event to the console and potentially a file."""
        msg = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "tool_name": tool_name,
            "event": event_type,
            "call_id": call_id,
            "data": data
        }
        
        # Determine log level based on event type
        if event_type == "error":
            logger.error(f"🛠️ TOOL ERROR [{tool_name}]: {json.dumps(data)}")
        elif event_type == "start":
            logger.info(f"🛠️ TOOL START [{tool_name}]: {call_id}")
        else:
            logger.info(f"🛠️ TOOL END [{tool_name}]: {call_id}")

        # Save to file
        log_file = f"{self.log_dir}/{session_id}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(msg) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write visibility log: {e}")

# Singleton instance
visibility_manager = VisibilityManager()
