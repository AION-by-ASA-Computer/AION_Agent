import asyncio
from haystack.tools import Tool
from .delegate_subagent import delegate_to_subagent_async

class DelegationTool:
    """Callable class for delegation to avoid nested function serialization issues."""
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id

    def __call__(self, subagent_profile: str, task: str) -> str:
        """
        Delegate a task to another specialized agent profile.
        The sub-agent works in an isolated session and returns the final result.
        """
        from ..main import _GLOBAL_LOOP
        loop = _GLOBAL_LOOP
        if not loop:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass
        if not loop:
            raise RuntimeError("No event loop found to execute delegation tool.")

        coro = delegate_to_subagent_async(
            subagent_profile=subagent_profile,
            task=task,
            user_id=self.user_id,
            parent_session_id=self.session_id,
        )
        
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        # Timeout della delega (indipendente dal timeout LLM dell'agente chiamante)
        return future.result(timeout=600) 

def get_delegation_tool(session_id: str, user_id: str) -> Tool:
    """Returns a Haystack tool for agent-to-agent delegation."""
    
    executor = DelegationTool(session_id, user_id)
    
    return Tool(
        name="delegate_task",
        description="Delegate a task to a specialized sub-agent (es. 'planner', 'security_auditor'). Requires profile name and task.",
        function=executor,
        parameters={
            "type": "object",
            "properties": {
                "subagent_profile": {"type": "string", "description": "Name or slug of the agent profile to activate."},
                "task": {"type": "string", "description": "Description of the task to assign to the sub-agent."}
            },
            "required": ["subagent_profile", "task"]
        }
    )
