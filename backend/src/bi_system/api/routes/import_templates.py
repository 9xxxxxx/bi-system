from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bi_system.api.dependencies import get_database_session
from bi_system.core.config import Settings, get_settings
from bi_system.ingestion.template_contracts import CreateImportTemplate, ImportTemplateDefinition
from bi_system.ingestion.templates import (
    StoredImportTemplate,
    create_import_template,
    get_import_template,
    list_import_templates,
)

router = APIRouter()

DatabaseSession = Annotated[Session, Depends(get_database_session)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class ImportTemplateResponse(BaseModel):
    id: UUID
    name: str
    version: int
    status: str
    definition: ImportTemplateDefinition
    created_at: datetime


@router.post(
    "",
    response_model=ImportTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_import_template_endpoint(
    request_body: CreateImportTemplate,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> ImportTemplateResponse:
    stored = create_import_template(
        session,
        workspace_id=settings.workspace_id,
        request=request_body,
    )
    return _template_response(stored)


@router.get("", response_model=list[ImportTemplateResponse])
def list_import_templates_endpoint(
    session: DatabaseSession,
    settings: ApplicationSettings,
    include_archived: Annotated[bool, Query()] = False,
) -> list[ImportTemplateResponse]:
    return [
        _template_response(stored)
        for stored in list_import_templates(
            session,
            workspace_id=settings.workspace_id,
            include_archived=include_archived,
        )
    ]


@router.get("/{template_id}", response_model=ImportTemplateResponse)
def read_import_template_endpoint(
    template_id: UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> ImportTemplateResponse:
    stored = get_import_template(
        session,
        workspace_id=settings.workspace_id,
        template_id=template_id,
    )
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "import_template_not_found",
                "message": "Import template was not found",
                "action": "Choose an available template",
            },
        )
    return _template_response(stored)


def _template_response(stored: StoredImportTemplate) -> ImportTemplateResponse:
    return ImportTemplateResponse(
        id=stored.template.id,
        name=stored.template.name,
        version=stored.template.version,
        status=stored.template.status,
        definition=stored.definition,
        created_at=stored.template.created_at,
    )
