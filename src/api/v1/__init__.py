from fastapi import APIRouter

from . import (
    chat,
    conversations,
    files,
    mcp_integrations,
    project_memory,
    query_memory,
    steps,
    user_memory,
)
from src.api.cron_user import router as cron_user_router

api_v1_router = APIRouter(prefix="/v1")
api_v1_router.include_router(conversations.router, tags=["v1-conversations"])
api_v1_router.include_router(chat.router, tags=["v1-chat"])
api_v1_router.include_router(query_memory.router, tags=["v1-query-memory"])
api_v1_router.include_router(project_memory.router, tags=["v1-project-memory"])
api_v1_router.include_router(user_memory.router, tags=["v1-user-memory"])
api_v1_router.include_router(files.router, tags=["v1-files"])
api_v1_router.include_router(steps.router, tags=["v1-steps"])
api_v1_router.include_router(mcp_integrations.router, tags=["v1-mcp-integrations"])
api_v1_router.include_router(cron_user_router, tags=["v1-cron-jobs"])
