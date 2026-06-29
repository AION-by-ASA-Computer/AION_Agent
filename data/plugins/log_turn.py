"""Example plugin: register a no-op hook slot (extend for token logging)."""


def register(app):
    from src.runtime.hooks import HookContext

    async def _log_post_llm(ctx: HookContext):
        return

    app.hooks.register("post_llm_call", _log_post_llm, priority=90)
