from fastapi import APIRouter

from bi_system.api.routes import (
    data_sources,
    datasets,
    health,
    import_batches,
    import_templates,
    semantic_models,
    source_files,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(source_files.router, prefix="/source-files", tags=["source-files"])
api_router.include_router(data_sources.router, prefix="/data-sources", tags=["data-sources"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(
    semantic_models.router,
    prefix="/semantic-models",
    tags=["semantic-models"],
)
api_router.include_router(
    import_templates.router,
    prefix="/import-templates",
    tags=["import-templates"],
)
api_router.include_router(
    import_batches.router,
    prefix="/import-batches",
    tags=["import-batches"],
)
