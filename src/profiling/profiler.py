import time
import json
import os
from datetime import datetime
from src.runtime.hooks import hook_registry
from collections import defaultdict

class PerTurnProfiler:
    def __init__(self):
        self.enabled = os.getenv("AION_PROFILING_ENABLED", "1") == "1"
        self.storage = os.getenv("AION_PROFILING_STORAGE", "jsonl")
        self.out_dir = os.getenv("AION_PROFILING_JSONL_DIR", "data/profiling")
        if self.enabled and self.storage == "jsonl":
            os.makedirs(self.out_dir, exist_ok=True)
            
        # In-memory accumulator for active turns. Keyed by (session_id, user_id)
        self._active_profiles = defaultdict(lambda: {
            "timestamp": None,
            "total_seconds": 0,
            "phases": defaultdict(float),
            "tool_per_call": [],
            "tokens": {"in": 0, "out": 0},
            "cost_eur": 0.0,
            "_phase_starts": {}
        })

    def _get_key(self, ctx):
        return (ctx.conversation_id or "default", ctx.user_id or "default")

    def start_phase(self, ctx, phase_name):
        if not self.enabled: return
        key = self._get_key(ctx)
        prof = self._active_profiles[key]
        if not prof["timestamp"]:
            prof["timestamp"] = datetime.utcnow().isoformat() + "Z"
            prof["_phase_starts"]["_turn_start"] = time.monotonic()
            
        prof["_phase_starts"][phase_name] = time.monotonic()

    def end_phase(self, ctx, phase_name, custom_data=None):
        if not self.enabled: return
        key = self._get_key(ctx)
        prof = self._active_profiles[key]
        
        start = prof["_phase_starts"].pop(phase_name, None)
        if start is not None:
            duration = time.monotonic() - start
            prof["phases"][phase_name] += duration
            
            if phase_name == "tool_total" and custom_data:
                prof["tool_per_call"].append({
                    "name": custom_data.get("name", "unknown"),
                    "duration": duration
                })

    def finish_turn(self, ctx):
        if not self.enabled: return
        key = self._get_key(ctx)
        if key not in self._active_profiles: return
        
        prof = self._active_profiles.pop(key)
        
        turn_start = prof["_phase_starts"].get("_turn_start")
        if turn_start:
            prof["total_seconds"] = time.monotonic() - turn_start
            
        prof.pop("_phase_starts", None)
        
        # Serialize to JSONL
        if self.storage == "jsonl":
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            filepath = os.path.join(self.out_dir, f"{date_str}.jsonl")
            
            record = {
                "conversation_id": key[0],
                "user_id": key[1],
                **prof
            }
            try:
                with open(filepath, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as e:
                pass

profiler = PerTurnProfiler()

# Hook handlers
async def _prof_pre_llm_call(ctx):
    profiler.start_phase(ctx, "llm_total")
    
async def _prof_post_llm_call(ctx):
    profiler.end_phase(ctx, "llm_total")
    # record tokens if present
    
async def _prof_pre_tool(ctx):
    profiler.start_phase(ctx, "tool_total")

async def _prof_post_tool(ctx):
    profiler.end_phase(ctx, "tool_total", custom_data={"name": ctx.payload.get("tool_name")})

async def _prof_post_turn(ctx):
    profiler.finish_turn(ctx)

def register_profiler_hooks():
    hook_registry.register("pre_llm_call", _prof_pre_llm_call, priority=10)
    hook_registry.register("post_llm_call", _prof_post_llm_call, priority=10)
    hook_registry.register("pre_tool_use", _prof_pre_tool, priority=10)
    hook_registry.register("post_tool_use", _prof_post_tool, priority=10)
    hook_registry.register("post_turn", _prof_post_turn, priority=10)
    # ALtri hooks possono essere registrati qui o nei rispettivi layer (es. LTM wake_up)
