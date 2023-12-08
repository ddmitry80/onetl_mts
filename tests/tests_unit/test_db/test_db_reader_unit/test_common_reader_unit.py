import re
import textwrap

import pytest

from onetl.connection import Hive
from onetl.db import DBReader

pytestmark = pytest.mark.hive


def test_reader_deprecated_import():
    msg = textwrap.dedent(
        """
        This import is deprecated since v0.8.0:

            from onetl.core import DBReader

        Please use instead:

            from onetl.db import DBReader
        """,
    )
    with pytest.warns(UserWarning, match=re.escape(msg)):
        from onetl.core import DBReader as OldDBReader

        assert OldDBReader is DBReader


def test_reader_source_alias(spark_mock):
    reader1 = DBReader(
        connection=Hive(cluster="rnd-dwh", spark=spark_mock),
        source="schema.table",
    )
    reader2 = DBReader(
        connection=Hive(cluster="rnd-dwh", spark=spark_mock),
        table="schema.table",
    )

    assert reader1.source == reader2.source


def test_reader_hive_with_read_options(spark_mock):
    with pytest.raises(ValueError, match=r"Hive does not implement ReadOptions, but \{'some': 'option'\} is passed"):
        DBReader(
            connection=Hive(cluster="rnd-dwh", spark=spark_mock),
            table="schema.table",
            options={"some": "option"},
        )


@pytest.mark.parametrize(
    "columns",
    [
        [],
        (),
        {},
        set(),
        "any,string",
    ],
)
def test_reader_invalid_columns(spark_mock, columns):
    with pytest.raises(ValueError):
        DBReader(
            connection=Hive(cluster="rnd-dwh", spark=spark_mock),
            table="schema.table",
            columns=columns,
        )


@pytest.mark.parametrize(
    "columns, real_columns",
    [
        (["*"], ["*"]),
        (["abc", "cde"], ["abc", "cde"]),
        (["*", "abc"], ["*", "abc"]),
    ],
)
def test_reader_valid_columns(spark_mock, columns, real_columns):
    reader = DBReader(
        connection=Hive(cluster="rnd-dwh", spark=spark_mock),
        table="schema.table",
        columns=columns,
    )

    assert reader.columns == real_columns


@pytest.mark.parametrize(
    "hwm_column, real_hwm_expression",
    [
        ("hwm_column", "hwm_column"),
        (("hwm_column", "expression"), "expression"),
        (("hwm_column", "hwm_column"), "hwm_column"),
    ],
)
def test_reader_deprecated_hwm_column(spark_mock, hwm_column, real_hwm_expression):
    error_msg = 'Passing "hwm_column" in DBReader class is deprecated since version 0.10.0'
    with pytest.warns(UserWarning, match=error_msg):
        reader = DBReader(
            connection=Hive(cluster="rnd-dwh", spark=spark_mock),
            table="schema.table",
            hwm_column=hwm_column,
        )

    assert isinstance(reader.hwm, reader.AutoDetectHWM)
    assert reader.hwm.entity == "schema.table"
    assert reader.hwm.expression == real_hwm_expression


def test_reader_autofill_hwm_source(spark_mock):
    reader = DBReader(
        connection=Hive(cluster="rnd-dwh", spark=spark_mock),
        table="schema.table",
        hwm=DBReader.AutoDetectHWM(
            name="some_name",
            expression="some_expression",
        ),
    )

    assert reader.hwm.entity == "schema.table"
    assert reader.hwm.expression == "some_expression"


def test_reader_hwm_has_same_source(spark_mock):
    reader = DBReader(
        connection=Hive(cluster="rnd-dwh", spark=spark_mock),
        source="schema.table",
        hwm=DBReader.AutoDetectHWM(
            name="some_name",
            source="schema.table",
            expression="some_expression",
        ),
    )

    assert reader.hwm.entity == "schema.table"
    assert reader.hwm.expression == "some_expression"


def test_reader_hwm_has_different_source(spark_mock):
    error_msg = "Passed `hwm.source` is different from `source`"
    with pytest.raises(ValueError, match=error_msg):
        DBReader(
            connection=Hive(cluster="rnd-dwh", spark=spark_mock),
            table="schema.table",
            hwm=DBReader.AutoDetectHWM(
                name="some_name",
                source="another.table",
                expression="some_expression",
            ),
        )


def test_reader_no_hwm_expression(spark_mock):
    with pytest.raises(ValueError, match="`hwm.expression` cannot be None"):
        DBReader(
            connection=Hive(cluster="rnd-dwh", spark=spark_mock),
            table="schema.table",
            hwm=DBReader.AutoDetectHWM(name="some_name"),
        )
