from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from bi_system.db.models import ImportTemplate, QualityRule
from bi_system.ingestion.template_contracts import CreateImportTemplate, ImportTemplateDefinition


@dataclass(frozen=True, slots=True)
class StoredImportTemplate:
    template: ImportTemplate
    definition: ImportTemplateDefinition


def create_import_template(
    session: Session,
    *,
    workspace_id: UUID,
    request: CreateImportTemplate,
) -> StoredImportTemplate:
    with session.begin():
        current_version = session.scalar(
            select(func.max(ImportTemplate.version)).where(
                ImportTemplate.workspace_id == workspace_id,
                ImportTemplate.name == request.name,
            ),
        )
        version = (current_version or 0) + 1
        session.execute(
            update(ImportTemplate)
            .where(
                ImportTemplate.workspace_id == workspace_id,
                ImportTemplate.name == request.name,
                ImportTemplate.status == "active",
            )
            .values(status="archived"),
        )

        template = ImportTemplate(
            workspace_id=workspace_id,
            name=request.name,
            version=version,
            status="active",
            configuration=request.definition.model_dump(mode="json"),
        )
        session.add(template)
        session.flush()

        session.add_all(
            [
                QualityRule(
                    workspace_id=workspace_id,
                    template_id=template.id,
                    name=rule.name,
                    rule_type=rule.rule_type,
                    severity=rule.severity.value,
                    column_name=rule.column_name,
                    parameters=rule.parameters.model_dump(mode="json"),
                    version=version,
                    enabled=True,
                )
                for rule in request.definition.quality_rules
            ],
        )

    return StoredImportTemplate(template=template, definition=request.definition)


def get_import_template(
    session: Session,
    *,
    workspace_id: UUID,
    template_id: UUID,
) -> StoredImportTemplate | None:
    template = session.get(ImportTemplate, template_id)
    if template is None or template.workspace_id != workspace_id:
        return None
    definition = ImportTemplateDefinition.model_validate(template.configuration)
    return StoredImportTemplate(template=template, definition=definition)


def list_import_templates(
    session: Session,
    *,
    workspace_id: UUID,
    include_archived: bool,
) -> list[StoredImportTemplate]:
    query = select(ImportTemplate).where(ImportTemplate.workspace_id == workspace_id)
    if not include_archived:
        query = query.where(ImportTemplate.status == "active")
    query = query.order_by(ImportTemplate.name, ImportTemplate.version.desc())
    templates = session.scalars(query).all()
    return [
        StoredImportTemplate(
            template=template,
            definition=ImportTemplateDefinition.model_validate(template.configuration),
        )
        for template in templates
    ]
