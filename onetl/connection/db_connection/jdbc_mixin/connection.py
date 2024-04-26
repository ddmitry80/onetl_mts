# SPDX-FileCopyrightText: 2021-2024 MTS (Mobile Telesystems)
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
import threading
from abc import abstractmethod
from contextlib import closing, suppress
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable, ClassVar, Optional, TypeVar

try:
    from pydantic.v1 import Field, PrivateAttr, SecretStr, validator
except (ImportError, AttributeError):
    from pydantic import Field, PrivateAttr, SecretStr, validator  # type: ignore[no-redef, assignment]

from onetl._internal import clear_statement, stringify
from onetl._util.java import get_java_gateway, try_import_java_class
from onetl._util.spark import get_spark_version
from onetl._util.version import Version
from onetl.connection.db_connection.jdbc_mixin.options import (
    JDBCOptions as JDBCMixinOptions,
)
from onetl.exception import MISSING_JVM_CLASS_MSG
from onetl.hooks import slot, support_hooks
from onetl.impl import FrozenModel
from onetl.log import log_lines

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

log = logging.getLogger(__name__)

T = TypeVar("T")

# options generated by JDBCMixin methods
PROHIBITED_OPTIONS = frozenset(
    (
        "user",
        "password",
        "driver",
        "url",
    ),
)


class JDBCStatementType(Enum):
    GENERIC = auto()
    PREPARED = auto()
    CALL = auto()


@support_hooks
class JDBCMixin(FrozenModel):
    """
    Compatibility layer between Python and Java SQL Module.

    Spark does not allow to execute raw SQL/DDL/DML/etc statements, so this is a workaround.
    However, some of Spark's magic is used here, for example to convert raw ResultSet to move convenient DataFrame
    """

    spark: SparkSession = Field(repr=False)
    user: str
    password: SecretStr

    JDBCOptions = JDBCMixinOptions

    DRIVER: ClassVar[str]
    _CHECK_QUERY: ClassVar[str] = "SELECT 1"

    # cached JDBC connection (Java object), plus corresponding GenericOptions (Python object)
    _last_connection_and_options: Optional[threading.local] = PrivateAttr(default=None)

    @property
    @abstractmethod
    def jdbc_url(self) -> str:
        """JDBC Connection URL"""

    @property
    def jdbc_params(self) -> dict:
        """JDBC Connection params"""
        return {
            "user": self.user,
            "password": self.password.get_secret_value() if self.password is not None else "",
            "driver": self.DRIVER,
            "url": self.jdbc_url,
        }

    @slot
    def close(self):
        """
        Close all connections, opened by ``.fetch()``, ``.execute()`` or ``.check()`` methods. |support_hooks|

        .. note::

            Connection can be used again after it was closed.

        Returns
        -------
        Connection itself

        Examples
        --------

        Read data and close connection:

        .. code:: python

            df = connection.fetch("SELECT * FROM mytable LIMIT 10")
            assert df.count()
            connection.close()

            # or

            with connection:
                connection.execute("CREATE TABLE target_table(id NUMBER, data VARCHAR)")
                connection.execute("CREATE INDEX target_table_idx ON target_table (id)")

        """

        self._close_connections()
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):  # noqa: U101
        self.close()

    def __del__(self):  # noqa: WPS603
        # If current object is collected by GC, close all opened connections
        # This is safe because closing connection on Spark driver does not influence Spark executors
        self.close()

    @slot
    def check(self):
        log.info("|%s| Checking connection availability...", self.__class__.__name__)
        self._log_parameters()  # type: ignore

        log.debug("|%s| Executing SQL query (on driver):", self.__class__.__name__)
        log_lines(log, self._CHECK_QUERY, level=logging.DEBUG)

        try:
            self._query_optional_on_driver(self._CHECK_QUERY, self.JDBCOptions(fetchsize=1))  # type: ignore
            log.info("|%s| Connection is available.", self.__class__.__name__)
        except Exception as e:
            log.exception("|%s| Connection is unavailable", self.__class__.__name__)
            raise RuntimeError("Connection is unavailable") from e

        return self

    @slot
    def fetch(
        self,
        query: str,
        options: JDBCMixinOptions | dict | None = None,
    ) -> DataFrame:
        """
        **Immediately** execute SELECT statement **on Spark driver** and return in-memory DataFrame. |support_hooks|

        Works almost the same like :obj:`~sql`, but Spark executor is not used.

        .. note::

            Statement is executed in read-only connection, so it cannot change any data in the database.

        .. note::

            First call of the method opens the connection to a database.
            Call ``.close()`` method to close it, or use context manager to do it automatically.

        Parameters
        ----------
        query : str

            SQL query to be executed.

        options : dict, :obj:`~JDBCOptions`, default: ``None``

            Options to be passed directly to JDBC driver, like ``fetchsize`` or ``queryTimeout``

            .. note::

                You cannot use :obj:`~ReadOptions`, they are handled by Spark, not by JDBC driver itself

        Returns
        -------
        df : pyspark.sql.dataframe.DataFrame

            Spark dataframe
        """

        query = clear_statement(query)

        log.info("|%s| Executing SQL query (on driver):", self.__class__.__name__)
        log_lines(log, query)

        df = self._query_on_driver(query, self.JDBCOptions.parse(options))

        log.info(
            "|%s| Query succeeded, resulting in-memory dataframe contains %d rows",
            self.__class__.__name__,
            df.count(),
        )
        return df

    @slot
    def execute(
        self,
        statement: str,
        options: JDBCMixinOptions | dict | None = None,
    ) -> DataFrame | None:
        """
        **Immediately** execute DDL, DML or procedure/function **on Spark driver**. |support_hooks|

        There is no method like this in :obj:`pyspark.sql.SparkSession` object,
        but Spark internal methods works almost the same (but on executor side).

        .. note::

            First call of the method opens the connection to a database.
            Call ``.close()`` method to close it, or use context manager to do it automatically.

        Parameters
        ----------
        statement : str

            Statement to be executed.

        options : dict, :obj:`~JDBCOptions`, default: ``None``

            Options to be passed directly to JDBC driver, like ``queryTimeout``

            .. note::

                You cannot use :obj:`~WriteOptions`, they are handled by Spark, not by JDBC driver itself

        Returns
        -------
        df : pyspark.sql.dataframe.DataFrame, optional

            Spark DataFrame.

            DataFrame is returned only if input is DML statement with ``RETURNING ...`` clause,
            or a procedure/function call. In other cases returns ``None``.
        """

        statement = clear_statement(statement)

        log.info("|%s| Executing statement (on driver):", self.__class__.__name__)
        log_lines(log, statement)

        call_options = self.JDBCOptions.parse(options)
        df = self._call_on_driver(statement, call_options)

        if df is not None:
            rows_count = df.count()
            log.info(
                "|%s| Execution succeeded, resulting in-memory dataframe contains %d rows",
                self.__class__.__name__,
                rows_count,
            )
        else:
            log.info("|%s| Execution succeeded, nothing returned", self.__class__.__name__)
        return df

    @validator("spark")
    def _check_java_class_imported(cls, spark):
        try:
            try_import_java_class(spark, cls.DRIVER)
        except Exception as e:
            msg = MISSING_JVM_CLASS_MSG.format(
                java_class=cls.DRIVER,
                package_source=cls.__name__,
                args="",
            )
            if log.isEnabledFor(logging.DEBUG):
                log.debug("Missing Java class", exc_info=e, stack_info=True)
            raise ValueError(msg) from e
        return spark

    def _query_on_driver(
        self,
        query: str,
        options: JDBCMixinOptions,
    ) -> DataFrame:
        return self._execute_on_driver(
            statement=query,
            statement_type=JDBCStatementType.PREPARED,
            callback=self._statement_to_dataframe,
            options=options,
            read_only=True,
        )

    def _query_optional_on_driver(
        self,
        query: str,
        options: JDBCMixinOptions,
    ) -> DataFrame | None:
        return self._execute_on_driver(
            statement=query,
            statement_type=JDBCStatementType.PREPARED,
            callback=self._statement_to_optional_dataframe,
            options=options,
            read_only=True,
        )

    def _call_on_driver(
        self,
        query: str,
        options: JDBCMixinOptions,
    ) -> DataFrame | None:
        return self._execute_on_driver(
            statement=query,
            statement_type=JDBCStatementType.CALL,
            callback=self._statement_to_optional_dataframe,
            options=options,
            read_only=False,
        )

    def _get_jdbc_properties(
        self,
        options: JDBCMixinOptions,
        **kwargs,
    ) -> dict[str, str]:
        """
        Fills up human-readable Options class to a format required by Spark internal methods
        """
        result = self.jdbc_params
        result.update(options.dict(by_alias=True, **kwargs))
        return stringify(result)

    def _options_to_connection_properties(self, options: JDBCMixinOptions):
        """
        Converts human-readable Options class to ``java.util.Properties``.

        Spark's internal class ``JDBCOptions`` already contains all the magic we need.

        See:
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JDBCOptions.scala#L148
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/DataFrameReader.scala#L248-L255
        """

        jdbc_properties = self._get_jdbc_properties(options, exclude_none=True)
        jdbc_utils_package = self.spark._jvm.org.apache.spark.sql.execution.datasources.jdbc  # type: ignore
        jdbc_options = jdbc_utils_package.JDBCOptions(
            self.jdbc_url,
            # JDBCOptions class requires `table` argument to be passed, but it is not used in asConnectionProperties
            "table",
            self.spark._jvm.PythonUtils.toScalaMap(jdbc_properties),  # type: ignore
        )
        return jdbc_options.asConnectionProperties()

    def _get_jdbc_connection(self, options: JDBCMixinOptions):
        if not self._last_connection_and_options:
            # connection class can be used in multiple threads.
            # each Python thread creates its own thread in JVM
            # so we need local variable to create per-thread persistent connection
            self._last_connection_and_options = threading.local()

        with suppress(Exception):  # nothing cached, or JVM failed
            last_connection, last_options = self._last_connection_and_options.data
            if options == last_options and not last_connection.isClosed():
                return last_connection

            # only one connection can be opened in one moment of time
            last_connection.close()

        connection_properties = self._options_to_connection_properties(options)
        driver_manager = self.spark._jvm.java.sql.DriverManager  # type: ignore
        new_connection = driver_manager.getConnection(self.jdbc_url, connection_properties)

        self._last_connection_and_options.data = (new_connection, options)
        return new_connection

    def _close_connections(self):
        with suppress(Exception):
            # connection maybe not opened yet
            last_connection, _ = self._last_connection_and_options.data
            last_connection.close()

        with suppress(Exception):
            # connection maybe not opened yet
            del self._last_connection_and_options.data

    def _get_statement_args(self) -> tuple[int, ...]:
        resultset = self.spark._jvm.java.sql.ResultSet  # type: ignore

        return resultset.TYPE_FORWARD_ONLY, resultset.CONCUR_READ_ONLY

    def _execute_on_driver(
        self,
        statement: str,
        statement_type: JDBCStatementType,
        callback: Callable[..., T],
        options: JDBCMixinOptions,
        read_only: bool,
    ) -> T:
        """
        Actually execute statement on driver.

        Almost like ``org.apache.spark.sql.execution.datasources.jdbc.JDBCRDD`` is fetching data:
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JDBCRDD.scala#L297-L306
        """

        jdbc_connection = self._get_jdbc_connection(options)
        jdbc_connection.setReadOnly(read_only)  # type: ignore

        statement_args = self._get_statement_args()
        jdbc_statement = self._build_statement(statement, statement_type, jdbc_connection, statement_args)

        return self._execute_statement(jdbc_statement, statement, options, callback, read_only)

    def _execute_statement(
        self,
        jdbc_statement,
        statement: str,
        options: JDBCMixinOptions,
        callback: Callable[..., T],
        read_only: bool,
    ) -> T:
        """
        Executes ``java.sql.Statement`` or child class and passes it into the callback function.

        See:
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JdbcUtils.scala#L255-L257
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JDBCRDD.scala#L298-L301
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JdbcUtils.scala#L103-L105
        """
        from py4j.java_gateway import is_instance_of

        gateway = get_java_gateway(self.spark)
        prepared_statement = self.spark._jvm.java.sql.PreparedStatement  # type: ignore
        callable_statement = self.spark._jvm.java.sql.CallableStatement  # type: ignore

        with closing(jdbc_statement):
            if options.fetchsize is not None:
                jdbc_statement.setFetchSize(options.fetchsize)

            if options.query_timeout is not None:
                jdbc_statement.setQueryTimeout(options.query_timeout)

            # Java SQL classes are not consistent..
            if is_instance_of(gateway, jdbc_statement, prepared_statement):
                jdbc_statement.execute()
            elif is_instance_of(gateway, jdbc_statement, callable_statement):
                jdbc_statement.execute()
            elif read_only:
                jdbc_statement.executeQuery(statement)
            else:
                jdbc_statement.executeUpdate(statement)

            return callback(jdbc_statement)

    @staticmethod
    def _build_statement(
        statement: str,
        statement_type: JDBCStatementType,
        jdbc_connection,
        statement_args,
    ):
        """
        Builds ``java.sql.Statement``, ``java.sql.PreparedStatement`` or ``java.sql.CallableStatement``,
        depending on ``statement_type`` argument value.

        Raw ``java.sql.Statement`` does not support some features provided by db driver, like ``{call ...}`` syntax.
        This is handled by ``java.sql.PreparedStatement`` or ``java.sql.CallableStatement``.

        See:
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JDBCRDD.scala#L298-L299
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JdbcUtils.scala#L633
        """

        if statement_type == JDBCStatementType.PREPARED:
            return jdbc_connection.prepareStatement(statement, *statement_args)

        if statement_type == JDBCStatementType.CALL:
            return jdbc_connection.prepareCall(statement, *statement_args)

        return jdbc_connection.createStatement(*statement_args)

    def _statement_to_dataframe(self, jdbc_statement) -> DataFrame:
        result_set = jdbc_statement.getResultSet()
        return self._resultset_to_dataframe(result_set)

    def _statement_to_optional_dataframe(self, jdbc_statement) -> DataFrame | None:
        """
        Returns ``org.apache.spark.sql.DataFrame`` or ``None``, if ResultSet is does not contain any columns.

        DDL or DML statement without ``RETURNING`` clause usually do not return anything.
        """

        result_set = jdbc_statement.getResultSet()

        if not result_set or result_set.isClosed():
            return None

        result_metadata = result_set.getMetaData()
        result_column_count = result_metadata.getColumnCount()
        if not result_column_count:
            return None

        return self._resultset_to_dataframe(result_set)

    def _resultset_to_dataframe(self, result_set) -> DataFrame:
        """
        Converts ``java.sql.ResultSet`` to ``org.apache.spark.sql.DataFrame`` using Spark's internal methods.

        That's almost exactly like Spark is fetching the data, but on driver.

        See:
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JDBCRDD.scala#L297-L306
        * https://github.com/apache/spark/blob/v2.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/datasources/jdbc/JdbcUtils.scala#L317-L323
        """

        from pyspark.sql import DataFrame  # noqa: WPS442

        jdbc_dialects_package = self.spark._jvm.org.apache.spark.sql.jdbc  # type: ignore
        jdbc_dialect = jdbc_dialects_package.JdbcDialects.get(self.jdbc_url)

        jdbc_utils_package = self.spark._jvm.org.apache.spark.sql.execution.datasources.jdbc  # type: ignore
        jdbc_utils = jdbc_utils_package.JdbcUtils

        java_converters = self.spark._jvm.scala.collection.JavaConverters  # type: ignore

        if get_spark_version(self.spark) >= Version("3.4"):
            # https://github.com/apache/spark/commit/2349175e1b81b0a61e1ed90c2d051c01cf78de9b
            result_schema = jdbc_utils.getSchema(result_set, jdbc_dialect, False, False)  # noqa: WPS425
        else:
            result_schema = jdbc_utils.getSchema(result_set, jdbc_dialect, False)  # noqa: WPS425

        result_iterator = jdbc_utils.resultSetToRows(result_set, result_schema)
        result_list = java_converters.seqAsJavaListConverter(result_iterator.toSeq()).asJava()
        jdf = self.spark._jsparkSession.createDataFrame(result_list, result_schema)  # type: ignore

        # DataFrame constructor in Spark 2.3 and 2.4 required second argument to be a SQLContext class
        # E.g. spark._wrapped = SQLContext(spark).
        # But since 3.2 it is replaced with SparkSession itself, and in 3.3 "_wrapped"
        # attribute was removed from SparkSession
        spark_context = getattr(self.spark, "_wrapped", self.spark)

        return DataFrame(jdf, spark_context)  # type: ignore
