import pytest

from onetl.connection import Hive
from onetl.db import DBReader
from tests.util.rand import rand_str

pytestmark = pytest.mark.hive


def test_hive_reader(spark, processing, load_table_data):
    hive = Hive(cluster="rnd-dwh", spark=spark)

    reader = DBReader(
        connection=hive,
        source=load_table_data.full_name,
    )
    df = reader.run()

    processing.assert_equal_df(
        schema=load_table_data.schema,
        table=load_table_data.table,
        df=df,
        order_by="id_int",
    )


def test_hive_reader_snapshot_with_columns(spark, processing, load_table_data):
    hive = Hive(cluster="rnd-dwh", spark=spark)

    reader1 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
    )
    table_df = reader1.run()

    columns = [
        "text_string",
        "hwm_int",
        "float_value",
        "id_int",
        "hwm_date",
        "hwm_datetime",
    ]

    reader2 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
        columns=columns,
    )
    table_df_with_columns = reader2.run()

    # columns order is same as expected
    assert table_df.columns != table_df_with_columns.columns
    assert table_df_with_columns.columns == columns
    # dataframe content is unchanged
    processing.assert_equal_df(
        table_df_with_columns,
        other_frame=table_df,
        order_by="id_int",
    )

    reader3 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
        columns=["count(*) as abc"],
    )
    count_df = reader3.run()

    # expressions are allowed
    assert count_df.columns == ["abc"]
    assert count_df.collect()[0][0] == table_df.count()


def test_hive_reader_snapshot_with_columns_duplicated(spark, prepare_schema_table):
    hive = Hive(cluster="rnd-dwh", spark=spark)

    reader1 = DBReader(
        connection=hive,
        source=prepare_schema_table.full_name,
    )
    df1 = reader1.run()

    reader2 = DBReader(
        connection=hive,
        source=prepare_schema_table.full_name,
        columns=[
            "*",
            "id_int",
        ],
    )

    df2 = reader2.run()
    assert df2.columns == df1.columns + ["id_int"]


def test_hive_reader_snapshot_with_columns_mixed_naming(spark, processing, get_schema_table):
    hive = Hive(cluster="rnd-dwh", spark=spark)

    # create table with mixed column names, e.g. IdInt
    full_name, schema, table = get_schema_table
    column_names = []
    table_fields = {}
    for original_name in processing.column_names:
        column_type = processing.get_column_type(original_name)
        new_name = rand_str()
        # wrap column names in DDL with quotes to preserve case
        table_fields[f"`{new_name}`"] = column_type
        column_names.append(new_name)

    processing.create_table(schema=schema, table=table, fields=table_fields)

    # before 0.10 this caused errors because * in column names was replaced with real column names,
    # but they were not escaped
    reader = DBReader(
        connection=hive,
        source=full_name,
        columns=["*"],
    )

    df = reader.run()
    assert df.columns == column_names


def test_hive_reader_snapshot_with_where(spark, processing, load_table_data):
    hive = Hive(cluster="rnd-dwh", spark=spark)

    reader1 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
        where="id_int < 1000",
    )
    table_df = reader1.run()

    assert table_df.count() == 100
    processing.assert_equal_df(
        schema=load_table_data.schema,
        table=load_table_data.table,
        df=table_df,
        order_by="id_int",
    )

    reader2 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
        where="id_int = 50",
    )
    one_df = reader2.run()
    assert one_df.count() == 1

    reader3 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
        where="id_int > 1000",
    )
    empty_df = reader3.run()

    assert not empty_df.count()


def test_hive_reader_snapshot_with_columns_and_where(spark, processing, load_table_data):
    hive = Hive(cluster="rnd-dwh", spark=spark)

    reader1 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
        where="id_int < 80 AND id_int > 10",
    )
    table_df = reader1.run()

    reader2 = DBReader(
        connection=hive,
        source=load_table_data.full_name,
        columns=["count(*)"],
        where="id_int < 80 AND id_int > 10",
    )
    count_df = reader2.run()

    assert count_df.collect()[0][0] == table_df.count()


def test_hive_reader_non_existing_table(spark, get_schema_table):
    from pyspark.sql.utils import AnalysisException

    hive = Hive(cluster="rnd-dwh", spark=spark)
    reader = DBReader(
        connection=hive,
        source=get_schema_table.full_name,
    )

    with pytest.raises(AnalysisException) as excinfo:
        reader.run()
        assert "does not exists" in str(excinfo.value)
