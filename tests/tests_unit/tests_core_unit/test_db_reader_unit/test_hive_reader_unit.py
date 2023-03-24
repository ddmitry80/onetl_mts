import pytest
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from onetl.connection import Hive
from onetl.core import DBReader

pytestmark = pytest.mark.hive


def test_hive_reader_snapshot_error_pass_df_schema(spark_mock):
    df_schema = StructType(
        [
            StructField("_id", IntegerType()),
            StructField("text_string", StringType()),
            StructField("hwm_int", IntegerType()),
            StructField("hwm_datetime", TimestampType()),
            StructField("float_value", DoubleType()),
        ],
    )

    hive = Hive(cluster="rnd-dwh", spark=spark_mock)

    with pytest.raises(ValueError, match="'df_schema' parameter is not supported by Hive"):
        DBReader(
            connection=hive,
            table="schema.table",
            df_schema=df_schema,
        )


@pytest.mark.parametrize("table", ["table", "table.table.table"])
def test_reader_wrong_table(spark_mock, table):
    hive = Hive(cluster="rnd-dwh", spark=spark_mock)
    with pytest.raises(ValueError):
        DBReader(
            connection=hive,
            table=table,  # Required format: table="shema.table"
        )
