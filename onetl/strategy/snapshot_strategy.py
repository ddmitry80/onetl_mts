from __future__ import annotations

import logging
import operator
from typing import Callable

from onetl.strategy.base_strategy import BaseStrategy
from onetl.strategy.batch_hwm_strategy import BatchHWMStrategy

log = logging.getLogger(__name__)


class SnapshotStrategy(BaseStrategy):
    """Snapshot strategy for DBReader.

    .. note::

        This is a default strategy.

    Every snapshot run is just executing the raw query generated by :obj:`onetl.reader.db_reader.DBReader`, like:

    .. code:: sql

        SELECT id, data FROM mydata;

    Examples
    --------

    Snapshot run

    .. code:: python

        from onetl.connection import Postgres
        from onetl.reader import DBReader
        from onetl.strategy import SnapshotStrategy

        from mtspark import get_spark

        spark = get_spark({"appName": "spark-app-name"})

        postgres = Postgres(
            host="test-db-vip.msk.mts.ru",
            user="appmetrica_test",
            password="*****",
            database="target_database",
            spark=spark,
        )

        reader = DBReader(
            postgres,
            table="default.mydata",
            columns=["id", "data"],
            hwm_column="id",
        )

        writer = DBWriter(hive, "newtable")

        with SnapshotStrategy():
            df = reader.run()

        # current run will execute following query:

        # SELECT id, data FROM mydata;
    """


class SnapshotBatchStrategy(BatchHWMStrategy):
    """Snapshot batch strategy for DBReader.

    Same as :obj:`onetl.strategy.snapshot_strategy.SnapshotStrategy`,
    but reads data from the source in batches like:

    .. code:: sql

        SELECT id, data FROM mydata WHERE id >= 1000 AND id <= 1100; -- from start to start+step (INCLUDING FIRST ROW)
        SELECT id, data FROM mydata WHERE id > 1100 AND id <= 1200; -- + step
        SELECT id, data FROM mydata WHERE id > 1200 AND id <= 1200; -- + step
        SELECT id, data FROM mydata WHERE id > 1300 AND id <= 1400; -- until stop

    This allows to use less resources than reading all the data in the one batch.

    Parameters
    ----------
    step : Any, default: ``1000``

        The value of step.

        Each query is look like:

        .. code:: sql

            SELECT id, data
            FROM mydata
            WHERE id >= 1000 AND id <= 1100;

            -- from start to start+step

    start : Any, default: ``None``

        If passed, the value will be used as a minimum value of ``hwm_column`` which will be read from the source.

        If not set, the value is determined by a separated query:

        .. code:: sql

            SELECT min(id) as start
            FROM mydata
            WHERE id <= 1400;

            -- 1400 here is stop value

    stop : Any, default: ``None``

        If passed, the value will be used as a maximum value of ``hwm_column`` which will be read from the source.

        If not set, the value is determined by a separated query:

        .. code:: sql

            SELECT max(id) as stop
            FROM mydata
            WHERE id >= 1000;

            -- 1000 here is start value

    Examples
    --------

    SnapshotBatch run

    .. code:: python

        from onetl.connection import Postgres, Hive
        from onetl.reader import DBReader
        from onetl.strategy import SnapshotBatchStrategy

        from mtspark import get_spark

        spark = get_spark({"appName": "spark-app-name"})

        postgres = Postgres(
            host="test-db-vip.msk.mts.ru",
            user="appmetrica_test",
            password="*****",
            database="target_database",
            spark=spark,
        )

        hive = Hive(spark=spark)

        reader = DBReader(
            postgres,
            table="default.mydata",
            columns=["id", "data"],
            hwm_column="id",
        )

        writer = DBWriter(hive, "newtable")

        with SnapshotBatchStrategy(step=100) as batches:
            for _ in batches:
                df = reader.run()
                writer.run(df)

    .. code:: sql

        -- get start and stop values
            SELECT min(id) as start, max(id) as stop
            FROM mydata;
        -- for example, start=1000 and stop=2345

        -- when each batch will perform a query which return some part of input data

            SELECT id, data
            FROM mydata
            WHERE id >= 1000 AND id <= 1100; --- from start to start+step (INCLUDING FIRST ROW)

        ... WHERE id > 1100 AND id <= 1200; -- next step
        ... WHERE id > 1200 AND id <= 1300; --- another step
        ...
        ... WHERE id > 2300 AND id <= 2345; --- until stop

    SnapshotBatch run with stop value

    .. code:: python

        with SnapshotBatchStrategy(step=100, stop=1234) as batches:
            for _ in batches:
                df = reader.run()
                writer.run(df)

    .. code:: sql

        -- get start value
            SELECT min(id) as start
            FROM mydata
            WHERE id <= 1234;
        -- for example, start=1000

        -- when each batch will perform a query which return some part of input data

            SELECT id, data
            FROM mydata
            WHERE id >= 1000 AND id <= 1100; --- from start to start+step (INCLUDING FIRST ROW)

        ... WHERE id > 1100 AND id <= 1200; -- next step
        ... WHERE id > 1200 AND id <= 1300; --- another step
        ... WHERE id > 1300 AND id <= 1234; --- until stop

    SnapshotBatch run with start value

    .. code:: python

        with SnapshotBatchStrategy(step=100, start=500) as batches:
            for _ in batches:
                df = reader.run()
                writer.run(df)

    .. code:: sql

        -- get stop value
            SELECT max(id) as stop
            FROM mydata
            WHERE id >= 500;
        -- for example, stop=2345

        -- when each batch will perform a query which return some part of input data

            SELECT id, data
            FROM mydata
            WHERE id >= 500 AND id <= 600; --- from start to start+step (INCLUDING FIRST ROW)

        ... WHERE id > 600 AND id <= 700; -- next step
        ... WHERE id > 700 AND id <= 800; --- another step
        ...
        ... WHERE id > 2300 AND id <= 2345; --- until stop

    SnapshotBatch run with all options

    .. code:: python

        with SnapshotBatchStrategy(
            step=100,
            stop=2000,
            offset=100,
        ) as batches:
            for _ in batches:
                df = reader.run()
                writer.run(df)

    .. code:: sql

        -- previous HWM value was 1000
        -- stop value is set, so no need to fetch boundaries from DB

        -- each batch will perform a query which return some part of input data

            SELECT id, data
            FROM mydata
            WHERE id >= 500 AND id <= 600; --- from HWM-offset to HWM-offset+step (INCLUDING FIRST ROW)

        ... WHERE id > 900 AND id <= 1000; -- next step
        ... WHERE id > 1000 AND id <= 1100; --- another step
        ... WHERE id > 1100 AND id <= 1200; --- one more step
        ...
        ... WHERE id > 1900 AND id <= 2000; --- until stop

    ``step``, ``stop`` and ``start`` could be any HWM type, not only integer

    .. code:: python

        from datetime import date, timedelta

        reader = DBReader(
            postgres,
            table="default.mydata",
            columns=["business_dt", "data"],
            hwm_column="business_dt",
        )

        with SnapshotBatchStrategy(
            step=timedelta(days=5),
            start=date("2021-01-01"),
            stop=date("2021-01-31"),
        ) as batches:
            for _ in batches:
                df = reader.run()
                writer.run(df)

    .. code:: sql

        -- previous HWM value was '2021-01-10'
        -- stop value is set, so no need to fetch boundaries from DB

        -- each batch will perform a query which return some part of input data

            SELECT business_dt, data
            FROM mydata
            WHERE business_dt >= '2021-01-09'; --- from HWM-offset to HWM-offset+step (INCLUDING FIRST ROW)

        ... WHERE business_dt > '2021-01-10' AND business_dt <= '2021-01-15'; -- next step
        ... WHERE business_dt > '2021-01-15' AND business_dt <= '2021-01-20'; --- another step
        ...
        ... WHERE business_dt > '2021-01-30' AND business_dt <= '2021-01-31'; --- until stop

    """

    def fetch_hwm(self) -> None:
        pass  # noqa: WPS420,WPS604

    @property
    def current_value_comparator(self) -> Callable:
        if self.is_first_run:
            return operator.ge

        return super().current_value_comparator
