from __future__ import annotations

import operator
from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from pydantic import BaseModel

from onetl.base import BaseConnection
from onetl.impl import DBWriteMode
from onetl.log import log_with_indent

if TYPE_CHECKING:
    from pyspark.sql import DataFrame
    from pyspark.sql.types import StructType

log = getLogger(__name__)


@dataclass(frozen=True)
class DBConnection(BaseConnection):
    # TODO:(@dypedchenk) Create abstract class for engine. Engine uses pyhive session or Engine uses pyspark session
    spark: pyspark.sql.SparkSession

    _check_query: ClassVar[str] = "SELECT 1"
    _compare_statements: ClassVar[dict[Callable, str]] = {
        operator.ge: "{} >= {}",
        operator.gt: "{} > {}",
        operator.le: "{} <= {}",
        operator.lt: "{} < {}",
        operator.eq: "{} == {}",
        operator.ne: "{} != {}",
    }

    class Options(BaseModel):  # noqa: WPS431
        """Hive or JDBC options"""

        mode: DBWriteMode = DBWriteMode.APPEND

        class Config:  # noqa: WPS431
            use_enum_values = True
            allow_population_by_field_name = True
            frozen = True
            extra = "allow"

    @property
    @abstractmethod
    def instance_url(self) -> str:
        """Instance URL"""

    @abstractmethod
    def check(self) -> None:
        """
        Check if database is accessible.

        If not, an exception will be raised.

        Executes some simple query, like ``SELECT 1``, in the database.

        Examples
        --------

        Database is online:

        .. code:: python

            connection.check()

        Database is offline or not accessible:

        .. code:: python

            connection.check()  # raises RuntimeError exception
        """

    @abstractmethod
    def get_schema(
        self,
        table: str,
        columns: list[str] | None = None,
        options: Options | None = None,
    ) -> StructType:
        """
        Get table schema
        """

    @abstractmethod
    def read_table(
        self,
        table: str,
        columns: list[str] | None = None,
        hint: str | None = None,
        where: str | None = None,
        options: Options | None = None,
    ) -> DataFrame:
        """
        Reads the table to dataframe
        """

    @abstractmethod
    def save_df(
        self,
        df: DataFrame,
        table: str,
        options: Options | None = None,
    ) -> None:
        """
        Saves dataframe to a specific table
        """

    @abstractmethod
    def get_min_max_bounds(
        self,
        table: str,
        column: str,
        expression: str | None = None,
        hint: str | None = None,
        where: str | None = None,
        options: Options | None = None,
    ) -> tuple[Any, Any]:
        """
        Get MIN and MAX values for the column
        """

    def get_sql_query(
        self,
        table: str,
        columns: list[str] | None = None,
        where: str | None = None,
        hint: str | None = None,
    ) -> str:
        """
        Generates a SQL query using input arguments
        """

        columns_str = ", ".join(columns) if columns else "*"
        hint = f"/*+ {hint} */" if hint else None
        where = f"WHERE {where}" if where else None

        return " ".join(
            filter(
                None,
                [
                    "SELECT",
                    hint,
                    columns_str,
                    "FROM",
                    table,
                    where,
                ],
            ),
        )

    def expression_with_alias(self, expression: str, alias: str) -> str:
        """
        Return "expression AS alias" statement
        """

        return f"{expression} AS {alias}"

    def to_options(
        self,
        options: Options | dict | None = None,
    ):
        """
        Сonverting <options> is performed depending on which class the <options> parameter was passed.
        If a parameter inherited from the Option class was passed, then it will be returned unchanged.
        If a Dict object was passed it will be converted to Options.
        If the JDBC connect class was used and the Hive options class was used,
        then a ValueError exception will be thrown. If it is the other way around, an exception will also be thrown.
        """

        if not options:
            return self.Options()

        if isinstance(options, dict):
            options = self.Options.parse_obj(options)

        if not isinstance(options, self.Options):
            raise TypeError(
                f"{options.__class__.__name__} cannot be passed to {self.__class__.__name__}",
            )

        return options

    def get_compare_statement(self, comparator: Callable, arg1: Any, arg2: Any) -> str:
        template = self._compare_statements[comparator]
        return template.format(arg1, self._get_value_sql(arg2))

    def log_parameters(self):
        log.info("|Spark| Using connection parameters:")
        log_with_indent(f"type = {self.__class__.__name__}")
        for attr in sorted(self._log_fields() - self._log_exclude_fields()):
            value_attr = getattr(self, attr)

            if value_attr:
                log_with_indent(f"{attr} = {value_attr}")

    @classmethod
    def _log_fields(cls) -> set[str]:
        # TODO(dypedchenk): until using pydantic dataclass
        return {
            field
            for field in cls.__dataclass_fields__.keys()  # type: ignore[attr-defined]
            if not field.startswith("_")
        }

    @classmethod
    def _log_exclude_fields(cls) -> set[str]:
        # TODO(dypedchenk): until using pydantic dataclass
        return {"spark"}

    def _get_value_sql(self, value: Any) -> str:
        """
        Transform the value into an SQL Dialect-supported form.
        """

        if isinstance(value, datetime):
            return self._get_datetime_value_sql(value)

        if isinstance(value, date):
            return self._get_date_value_sql(value)

        return str(value)

    def _get_datetime_value_sql(self, value: datetime) -> str:
        """
        Transform the datetime value into supported by SQL Dialect
        """
        result = value.isoformat()
        return f"'{result}'"

    def _get_date_value_sql(self, value: date) -> str:
        """
        Transform the date value into supported by SQL Dialect
        """
        result = value.isoformat()
        return f"'{result}'"

    def _get_max_value_sql(self, value: Any) -> str:
        """
        Generate `MAX(value)` clause for given value
        """

        result = self._get_value_sql(value)

        return f"MAX({result})"

    def _get_min_value_sql(self, value: Any) -> str:
        """
        Generate `MIN(value)` clause for given value
        """

        result = self._get_value_sql(value)

        return f"MIN({result})"
