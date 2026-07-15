from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.orm import Session

from bi_system.db.models import ImportBatch, ImportColumn, ImportTarget
from bi_system.ingestion.domain import ImportBatchStatus


@dataclass(frozen=True, slots=True)
class DataSourceField:
    id: UUID
    display_name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class DataSourceCatalogEntry:
    id: UUID
    name: str
    status: str
    latest_active_batch_id: UUID | None
    active_row_count: int
    fields: tuple[DataSourceField, ...]


def list_data_sources(
    session: Session,
    *,
    workspace_id: UUID,
) -> list[DataSourceCatalogEntry]:
    targets = session.scalars(
        select(ImportTarget)
        .where(ImportTarget.workspace_id == workspace_id)
        .order_by(ImportTarget.name, ImportTarget.created_at),
    ).all()
    return [_catalog_entry(session, target=target, include_fields=True) for target in targets]


def get_data_source_schema(
    session: Session,
    *,
    workspace_id: UUID,
    data_source_id: UUID,
) -> DataSourceCatalogEntry | None:
    target = session.get(ImportTarget, data_source_id)
    if target is None or target.workspace_id != workspace_id:
        return None
    return _catalog_entry(session, target=target, include_fields=True)


def _catalog_entry(
    session: Session,
    *,
    target: ImportTarget,
    include_fields: bool,
) -> DataSourceCatalogEntry:
    latest_batch_id = session.scalar(
        select(ImportBatch.id)
        .where(
            ImportBatch.target_id == target.id,
            ImportBatch.status.in_(
                (
                    ImportBatchStatus.SUCCEEDED.value,
                    ImportBatchStatus.PARTIALLY_SUCCEEDED.value,
                ),
            ),
        )
        .order_by(ImportBatch.finished_at.desc(), ImportBatch.created_at.desc())
        .limit(1),
    )
    fields: tuple[DataSourceField, ...] = ()
    if include_fields:
        columns = session.scalars(
            select(ImportColumn)
            .where(ImportColumn.target_id == target.id)
            .order_by(ImportColumn.ordinal),
        ).all()
        fields = tuple(
            DataSourceField(
                id=column.id,
                display_name=column.source_name,
                data_type=column.data_type,
                nullable=column.nullable,
            )
            for column in columns
        )
    return DataSourceCatalogEntry(
        id=target.id,
        name=target.name,
        status=target.status,
        latest_active_batch_id=latest_batch_id,
        active_row_count=_active_row_count(session, target=target),
        fields=fields,
    )


def _active_row_count(session: Session, *, target: ImportTarget) -> int:
    bind = session.get_bind()
    if not inspect(bind).has_table(target.physical_table_name):
        return 0
    table = Table(target.physical_table_name, MetaData(), autoload_with=bind)
    count = session.scalar(
        select(func.count()).select_from(table).where(table.c["_active"].is_(True)),
    )
    return count or 0
