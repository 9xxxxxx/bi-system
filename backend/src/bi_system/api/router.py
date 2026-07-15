from fastapi import APIRouter

from bi_system.api.routes import health, import_templates, source_files

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(source_files.router, prefix="/source-files", tags=["source-files"])
api_router.include_router(
    import_templates.router,
    prefix="/import-templates",
    tags=["import-templates"],
)
