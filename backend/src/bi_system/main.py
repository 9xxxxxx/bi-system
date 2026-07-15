from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bi_system.api.router import api_router
from bi_system.core.config import get_settings
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.storage import LocalContentAddressedStorage


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    application.state.engine = engine
    application.state.session_factory = create_session_factory(engine)
    application.state.file_storage = LocalContentAddressedStorage(
        settings.storage_root,
        max_bytes=settings.upload_max_bytes,
    )

    try:
        yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()
