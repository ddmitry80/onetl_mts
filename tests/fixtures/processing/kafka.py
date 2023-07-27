from __future__ import annotations
import os

import pandas
from typing import TYPE_CHECKING

from pyspark.sql.types import StructType, StructField, LongType, StringType, FloatType

from tests.fixtures.processing.base_processing import BaseProcessing
from pyspark.sql.functions import from_json, col
from confluent_kafka import Producer

from tests.util.assert_df import assert_equal_df
from tests.util.to_pandas import to_pandas

if TYPE_CHECKING:
    from pyspark.sql import DataFrame as SparkDataFrame


class KafkaProcessing(BaseProcessing):
    column_names: list[str] = ["id_int", "text_string", "hwm_int", "float_value"]
    schema = StructType(
        [
            StructField("id_int", LongType(), True),
            StructField("text_string", StringType(), True),
            StructField("hwm_int", LongType(), True),
            StructField("float_value", FloatType(), True),
        ],
    )

    def __enter__(self):
        self.connection = self.get_conn()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def get_conn(self) -> Producer:
        return Producer({"bootstrap.servers": f"{self.host}:{self.port}"})

    @property
    def user(self) -> str:
        return os.environ["ONETL_KAFKA_USER"]

    @property
    def password(self) -> str:
        return os.environ["ONETL_KAFKA_PASSWORD"]

    @property
    def host(self) -> str:
        return os.environ["ONETL_KAFKA_HOST"]

    @property
    def port(self) -> int:
        return int(os.environ["ONETL_KAFKA_PORT"])

    def create_schema(self, schema: str) -> None:
        pass

    def create_table(self, table: str, fields: dict[str, str], schema: str) -> None:
        pass

    def drop_database(self, schema: str) -> None:
        pass

    def drop_table(self, table: str, schema: str) -> None:
        pass

    @staticmethod
    def delivery_report(err, msg):
        """Called once for each message produced to indicate delivery result.
        Triggered by poll() or flush()."""
        if err is not None:
            print("Message delivery failed: {}".format(err))
        else:
            pass

    def send_message(self, topic, message):
        producer = self.get_conn()
        producer.produce(topic, message, callback=self.delivery_report)
        producer.flush()

    def insert_data(self, schema: str, table: str, values: list) -> None:
        pass

    def get_expected_dataframe(  # noqa: WPS463
        self,
        schema: str,
        table: str,
        order_by: str | None = None,
    ) -> pandas.DataFrame:
        pass

    def assert_equal_df(
        self,
        df: SparkDataFrame,
        schema: str | None = None,
        table: str | None = None,
        order_by: str | None = None,
        other_frame: pandas.DataFrame | SparkDataFrame | None = None,
        **kwargs,
    ) -> None:
        """Checks that df and other_frame are equal"""

        value_df = df.select(from_json(col=col("value").cast("string"), schema=self.schema).alias("value"))
        value_df = (
            value_df.withColumn("id_int", col("value").getField("id_int"))
            .withColumn("text_string", col("value").getField("text_string"))
            .withColumn("hwm_int", col("value").getField("hwm_int"))
            .withColumn("float_value", col("value").getField("float_value"))
        ).select(["id_int", "text_string", "hwm_int", "float_value"])

        return super().assert_equal_df(df=value_df, other_frame=other_frame)
