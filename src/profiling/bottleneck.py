import os
import json
from collections import defaultdict
from typing import List, Dict, Any

class BottleneckDetector:
    def __init__(self, jsonl_dir="data/profiling"):
        self.jsonl_dir = jsonl_dir

    def _load_recent_profiles(self, max_records=1000) -> List[Dict[str, Any]]:
        if not os.path.exists(self.jsonl_dir):
            return []
            
        records = []
        # Legge gli ultimi file jsonl in ordine inverso (i più recenti prima)
        files = sorted([f for f in os.listdir(self.jsonl_dir) if f.endswith(".jsonl")], reverse=True)
        for fname in files:
            filepath = os.path.join(self.jsonl_dir, fname)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in reversed(lines):
                        if line.strip():
                            records.append(json.loads(line))
                            if len(records) >= max_records:
                                return records
            except Exception:
                continue
        return records

    def detect(self) -> Dict[str, Any]:
        records = self._load_recent_profiles()
        if not records:
            return {"status": "no_data", "bottlenecks": []}
            
        bottlenecks = []
        
        # 1. LLM-bound: if llm_total > 70% of total_seconds in >50% of turns
        llm_heavy_turns = 0
        for r in records:
            llm_tot = r.get("phases", {}).get("llm_total", 0)
            tot = r.get("total_seconds", 0)
            if tot > 0 and (llm_tot / tot) > 0.7:
                llm_heavy_turns += 1
                
        if len(records) > 0 and (llm_heavy_turns / len(records)) > 0.5:
            bottlenecks.append({
                "type": "llm_bound",
                "severity": "high",
                "message": "Il modello LLM impiega oltre il 70% del tempo totale in più della metà dei turni. Considerare un modello più rapido o la riduzione del max_tokens."
            })
            
        # 2. Tool-bound: if tool_total > 50% of total_seconds
        tool_heavy_turns = 0
        slowest_tool_counts = defaultdict(int)
        
        for r in records:
            tool_tot = r.get("phases", {}).get("tool_total", 0)
            tot = r.get("total_seconds", 0)
            if tot > 0 and (tool_tot / tot) > 0.5:
                tool_heavy_turns += 1
                tools = r.get("tool_per_call", [])
                if tools:
                    slowest = max(tools, key=lambda t: t.get("duration", 0))
                    slowest_tool_counts[slowest.get("name")] += 1
                    
        if len(records) > 0 and (tool_heavy_turns / len(records)) > 0.2:
            top_slow_tool = max(slowest_tool_counts.items(), key=lambda x: x[1])[0] if slowest_tool_counts else "unknown"
            bottlenecks.append({
                "type": "tool_bound",
                "severity": "medium",
                "message": f"I tool consumano oltre il 50% del tempo di risposta. Il tool più frequentemente lento è '{top_slow_tool}'."
            })

        # 3. Context Builder / Wake Up (MemPalace-bound)
        # Assuming wake_up > 1.0s is slow
        slow_wakeups = sum(1 for r in records if r.get("phases", {}).get("wake_up", 0) > 1.0)
        if len(records) > 0 and (slow_wakeups / len(records)) > 0.3:
            bottlenecks.append({
                "type": "mempalace_bound",
                "severity": "low",
                "message": "Il recupero della LTM (MemPalace wake_up) impiega più di 1 secondo in oltre il 30% dei casi. Ridurre top_drawers."
            })

        return {
            "status": "ok",
            "analyzed_turns": len(records),
            "bottlenecks": bottlenecks
        }

detector = BottleneckDetector()
