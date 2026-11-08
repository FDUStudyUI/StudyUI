"""Boundary: query/database failures must be actionable ValueError results."""

import sqlite3

import pytest

from materials_quality.science.io_nodes import database_import


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "samples.db"
    with sqlite3.connect(path) as connection:
        connection.execute("create table samples (id text, value real)")
        connection.executemany("insert into samples values (?, ?)", [("S1", 1.5), ("S2", 2.5)])
    return path


def test_sql_with_trailing_statement_terminators_executes(database):
    result = database_import(config={"path": str(database), "query": "select 1;;;"})

    assert result.table.shape == (1, 1)


def test_invalid_sql_is_a_value_error(database):
    with pytest.raises(ValueError, match="query failed|database"):
        database_import(config={"path": str(database), "query": "select * from missing_table"})


def test_missing_binding_parameter_is_a_value_error(database):
    with pytest.raises(ValueError, match="query failed|database|binding"):
        database_import(
            config={
                "path": str(database),
                "query": "select * from samples where value > :threshold",
                "parameters": {"unrelated": 1},
            }
        )


def test_corrupt_database_file_is_a_value_error(tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"this is not a sqlite database")

    with pytest.raises(ValueError, match="query failed|database"):
        database_import(config={"path": str(path), "query": "select 1"})
