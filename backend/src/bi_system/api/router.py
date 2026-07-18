from fastapi import APIRouter

from bi_system.api.routes import (
    auth,
    dashboards,
    data_sources,
    dataset_queries,
    datasets,
    health,
    identity,
    import_batches,
    import_templates,
    metrics,
    row_policies,
    semantic_models,
    source_files,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(identity.router, prefix="/identity", tags=["identity"])
api_router.include_router(source_files.router, prefix="/source-files", tags=["source-files"])
api_router.include_router(data_sources.router, prefix="/data-sources", tags=["data-sources"])
api_router.include_router(dashboards.router, prefix="/dashboards", tags=["dashboards"])
api_router.include_router(
    dashboards.template_router,
    prefix="/dashboard-templates",
    tags=["dashboard-templates"],
)
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
api_router.include_router(
    row_policies.router,
    prefix="/row-policies",
    tags=["row-policies"],
)
api_router.include_router(
    dataset_queries.router,
    prefix="/dataset-queries",
    tags=["dataset-queries"],
)
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
