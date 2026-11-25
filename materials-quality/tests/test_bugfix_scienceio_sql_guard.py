"""The read-only SQL guard must judge statements, not literal data or comments."""

import sqlite3

import pytest

from materials_quality.science.io_nodes import database_import


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "samples.db"
    with sqlite3.connect(path) as connection:
        connection.execute("create table samples (id text, note text)")
        connection.executemany(
            "insert into samples values (?, ?)",
            [("S1", "a;b"), ("S2", "delete"), ("S3", "into")],
        )
    return path


def test_select_with_literal_semicolon_and_write_words_is_accepted(database):
    result = database_import(
        config={
            "path": str(database),
            "query": "select note from samples where note in ('a;b', 'delete', 'into') order by id",
        }
    )

    assert result.table["note"].tolist() == ["a;b", "delete", "into"]


def test_select_with_semicolon_inside_comment_is_accepted(database):
    result = database_import(
        config={
            "path": str(database),
            "query": "select count(*) as n from samples /* ; delete */ where id = 'S1'",
        }
    )

    assert result.table["n"].tolist() == [1]


def test_genuine_multiple_statements_are_still_rejected(database):
    with pytest.raises(ValueError, match="single SQL statement"):
        database_import(config={"path": str(database), "query": "select id from samples; drop table samples"})
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from samples").fetchone()[0] == 3


@pytest.mark.parametrize(
    "query",
    [
        "select 1; drop table samples",
        "with x as (select 1) delete from samples",
        "select load_extension('evil')",
        "select * into other from samples",
    ],
)
def test_write_operations_remain_rejected(database, query):
    with pytest.raises(ValueError):
        database_import(config={"path": str(database), "query": query})


def test_unterminated_literals_are_configuration_errors(database):
    with pytest.raises(ValueError, match="unterminated"):
        database_import(config={"path": str(database), "query": "select * from samples where note = 'oops"})
