from bi_system.modeling.contracts import TimeGrain
from bi_system.modeling.dialect import compile_time_grain
from sqlalchemy import Column, DateTime, MetaData, Table, select
from sqlalchemy.dialects import postgresql


def test_postgresql_time_grain_is_literal_in_select_and_group_by() -> None:
    table = Table("sales", MetaData(), Column("sold_at", DateTime(timezone=True)))
    selected = compile_time_grain(
        TimeGrain.MONTH,
        table.c.sold_at,
        dialect_name="postgresql",
    )
    grouped = compile_time_grain(
        TimeGrain.MONTH,
        table.c.sold_at,
        dialect_name="postgresql",
    )

    sql = str(
        select(selected)
        .group_by(grouped)
        .compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert sql.count("date_trunc('month', sales.sold_at)") == 2
