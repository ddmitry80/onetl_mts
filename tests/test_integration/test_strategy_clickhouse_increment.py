import pytest

from onetl.connection import Clickhouse
from onetl.reader.db_reader import DBReader
from onetl.strategy import IncrementalStrategy
from onetl.strategy.hwm_store import HWMClassRegistry, HWMStoreManager


@pytest.mark.parametrize(
    "hwm_type_name, hwm_column",
    [
        ("integer", "hwm_int"),
        ("date", "hwm_date"),
        ("timestamp", "hwm_datetime"),
    ],
)
@pytest.mark.parametrize(
    "span_gap, span_length",
    [
        (10, 100),
        (10, 50),
    ],
)
def test_clickhouse_strategy_increment(
    spark,
    processing,
    prepare_schema_table,
    hwm_type_name,
    hwm_column,
    span_gap,
    span_length,
):
    store = HWMStoreManager.get_current()

    clickhouse = Clickhouse(
        host=processing.host,
        port=processing.port,
        user=processing.user,
        password=processing.password,
        spark=spark,
    )
    reader = DBReader(connection=clickhouse, table=prepare_schema_table.full_name, hwm_column=hwm_column)

    hwm_type = HWMClassRegistry.get(hwm_type_name)
    hwm = hwm_type(source=reader.table, column=reader.hwm_column)

    # there are 2 spans with a gap between

    # 0..100
    first_span_begin = 0
    first_span_end = first_span_begin + span_length

    # 110..210
    second_span_begin = first_span_end + span_gap
    second_span_end = second_span_begin + span_length

    first_span = processing.create_pandas_df(min_id=first_span_begin, max_id=first_span_end)
    second_span = processing.create_pandas_df(min_id=second_span_begin, max_id=second_span_end)

    first_span_max = first_span[hwm_column].max()
    second_span_max = second_span[hwm_column].max()

    # insert first span
    processing.insert_data(
        schema=prepare_schema_table.schema,
        table=prepare_schema_table.table,
        values=first_span,
    )

    # incremental run
    with IncrementalStrategy():
        first_df = reader.run()

    hwm = store.get(hwm.qualified_name)
    assert hwm is not None
    assert isinstance(hwm, hwm_type)
    assert hwm.value == first_span_max

    # all the data has been read
    processing.assert_equal_df(df=first_df, other_frame=first_span)

    # insert second span
    processing.insert_data(
        schema=prepare_schema_table.schema,
        table=prepare_schema_table.table,
        values=second_span,
    )

    with IncrementalStrategy():
        second_df = reader.run()

    assert store.get(hwm.qualified_name).value == second_span_max

    if "int" in hwm_column:
        # only changed data has been read
        processing.assert_equal_df(df=second_df, other_frame=second_span)
    else:
        # date and datetime values have a random part
        # so instead of checking the whole dataframe a partial comparison should be performed
        processing.assert_subset_df(df=second_df, other_frame=second_span)


# Fail if HWM is Numeric or Decimal with fractional part
def test_clickhouse_strategy_increment_float(spark, processing, prepare_schema_table):
    hwm_column = "float_value"

    clickhouse = Clickhouse(
        host=processing.host,
        port=processing.port,
        user=processing.user,
        password=processing.password,
        spark=spark,
    )
    reader = DBReader(connection=clickhouse, table=prepare_schema_table.full_name, hwm_column=hwm_column)

    data = processing.create_pandas_df()

    # insert first span
    processing.insert_data(
        schema=prepare_schema_table.schema,
        table=prepare_schema_table.table,
        values=data,
    )

    with pytest.raises(ValueError):
        # incremental run
        with IncrementalStrategy():
            reader.run()
