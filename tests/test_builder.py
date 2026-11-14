"""The dropdown builder's and/or rows (docs/GAPS.md #16, #30).

The builder shows a `where` list as a column of rows joined by `and`/`or` connectors; a run of
`or` rows is one `{"any": [...]}` group. These two shapes have to survive a round trip in both
directions, or steps loaded from an example, the AI draft or the JSON box would silently change.
"""
from cohort_studio.builder import _flatten, _regroup

A = {"column": "er_status", "operator": "eq", "values": ["Positive"]}
B = {"column": "her2_ihc", "operator": "eq", "values": ["Positive"]}
C = {"column": "her2_ish", "operator": "eq", "values": ["Positive"]}


def test_plain_conditions_are_all_and_rows():
    rows, extras = _flatten([A, B])
    assert rows == [(A, "and"), (B, "and")] and not extras
    assert _regroup(rows) == [A, B]


def test_an_or_group_becomes_a_run_of_or_rows():
    rows, extras = _flatten([A, {"any": [B, C]}])
    assert rows == [(A, "and"), (B, "and"), (C, "or")] and not extras
    assert _regroup(rows) == [A, {"any": [B, C]}]


def test_an_or_group_first_keeps_its_place():
    where = [{"any": [A, B]}, C]
    rows, _ = _flatten(where)
    assert [j for _, j in rows] == ["and", "or", "and"]
    assert _regroup(rows) == where


def test_a_nested_group_is_kept_aside_for_the_json_view():
    nested = {"any": [A, {"all": [B, C]}]}
    rows, extras = _flatten([A, nested, {"all": [B]}])
    assert rows == [(A, "and")]
    assert extras == [nested, {"all": [B]}]


def test_an_or_row_with_nothing_before_it_starts_its_own_group():
    """The row above can be unfinished and dropped, so "or" may lead. It must not vanish."""
    assert _regroup([(B, "or"), (C, "or")]) == [{"any": [B, C]}]
