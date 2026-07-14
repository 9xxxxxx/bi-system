from fastapi import FastAPI

from bi_system.api.router import api_router
from bi_system.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name)
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
