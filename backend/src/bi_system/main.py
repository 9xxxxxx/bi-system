from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from bi_system.api.router import api_router
from bi_system.core.config import get_settings
from bi_system.db.session import create_database_engine


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    application.state.engine = engine

    try:
        yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
