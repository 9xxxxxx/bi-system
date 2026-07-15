from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Engine,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
    and_,
    delete,
    exists,
    select,
    update,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session
from sqlalchemy.sql.type_api import TypeEngine

from bi_system.db.models import ImportTarget
from bi_system.ingestion.domain import FileDataType, ImportMode
from bi_system.ingestion.template_contracts import ImportTemplateDefinition
from bi_system.ingestion.validation import ConvertedValue, EvaluatedRow


def build_target_table(
    target: ImportTarget,
    definition: ImportTemplateDefinition,
    *,
    metadata: MetaData | None = None,
) -> Table:
    table_metadata = metadata or MetaData()
    columns = [
        Column("_row_id", Uuid(as_uuid=True), primary_key=True, default=uuid4),
        Column("_batch_id", Uuid(as_uuid=True), nullable=False),
        Column("_row_number", Integer, nullable=False),
        Column("_active", Boolean, nullable=False, default=False),
        *[
            Column(
                column.target_name,
                _column_type(column.data_type),
                nullable=True,
            )
            for column in definition.columns
        ],
    ]
    table = Table(target.physical_table_name, table_metadata, *columns)
    Index(f"ix_{target.physical_table_name}_batch", table.c._batch_id)
    Index(f"ix_{target.physical_table_name}_active", table.c._active)
    if definition.business_key:
        Index(
            f"ix_{target.physical_table_name}_business_key",
            *[table.c[column] for column in definition.business_key],
        )
    return table


def ensure_target_table(engine: Engine, table: Table) -> None:
    table.create(engine, checkfirst=True)


def stage_evaluated_rows(
    session: Session,
    table: Table,
    *,
    batch_id: UUID,
    rows: Iterable[EvaluatedRow],
) -> None:
    values = [
        {
            "_row_id": uuid4(),
            "_batch_id": batch_id,
            "_row_number": row.row_number,
            "_active": False,
            **_database_values(row.values),
        }
        for row in rows
        if row.accepted
    ]
    if values:
        session.execute(table.insert(), values)


def discard_batch_rows(session: Session, table: Table, *, batch_id: UUID) -> None:
    session.execute(delete(table).where(table.c._batch_id == batch_id))


def finalize_batch_rows(
    session: Session,
    table: Table,
    *,
    batch_id: UUID,
    mode: ImportMode,
    business_key: list[str],
) -> None:
    if mode is ImportMode.REPLACE:
        session.execute(delete(table).where(table.c._active.is_(True)))
    elif mode is ImportMode.UPSERT:
        if not business_key:
            raise ValueError("Upsert requires a business key")
        staged = table.alias("staged")
        matching_key = and_(
            staged.c._batch_id == batch_id,
            *[table.c[column] == staged.c[column] for column in business_key],
        )
        session.execute(
            delete(table).where(
                table.c._active.is_(True),
                exists(select(1).select_from(staged).where(matching_key)),
            ),
        )

    session.execute(
        update(table).where(table.c._batch_id == batch_id).values(_active=True),
    )


def read_active_rows(session: Session, table: Table) -> Sequence[RowMapping]:
    return (
        session.execute(
            select(table).where(table.c["_active"].is_(True)).order_by(table.c["_row_number"]),
        )
        .mappings()
        .all()
    )


def _column_type(data_type: FileDataType) -> TypeEngine[Any]:
    if data_type is FileDataType.STRING:
        return Text()
    if data_type is FileDataType.INTEGER:
        return BigInteger()
    if data_type is FileDataType.DECIMAL:
        return Numeric(38, 10)
    if data_type is FileDataType.BOOLEAN:
        return Boolean()
    if data_type is FileDataType.DATE:
        return Date()
    if data_type is FileDataType.DATETIME:
        return DateTime(timezone=True)
    return String(2000)


def _database_values(values: dict[str, ConvertedValue]) -> dict[str, object]:
    return dict(values)
