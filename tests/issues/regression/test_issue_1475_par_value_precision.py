"""Exact stock par values must not become zero in rendered statements.

GitHub Issue: https://github.com/dgunning/edgartools/issues/1475

Apple's FY2023 10-K (0000320193-23-000106) files common-stock par value
of 0.00001 USD per share at 2023-09-30 and 2022-09-24. Tesla's Q2 2024
10-Q (0001628280-24-032662) files preferred- and common-stock par values
of 0.001 USD per share at 2024-06-30 and 2023-12-31. The unchanged local
filing fixtures retain those values, usdPerShare units and INF decimals.

The direct renderer keeps the formatter regression independent of statement
selection. Additional numeric inputs below are synthetic controls for finer
precision, scaling and presentation signs, rather than reported company facts.
"""

import math
from copy import deepcopy
from pathlib import Path

import pytest

from edgar.xbrl import XBRL
from edgar.xbrl.presentation import StatementView
from edgar.xbrl.rendering import RenderedStatement, render_statement

pytestmark = pytest.mark.fast

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "xbrl"
COMMON_PAR = "us-gaap_CommonStockParOrStatedValuePerShare"
PREFERRED_PAR = "us-gaap_PreferredStockParOrStatedValuePerShare"
APPLE_ROLE = "http://www.apple.com/role/CONSOLIDATEDBALANCESHEETSParenthetical"
TESLA_ROLE = "http://www.tesla.com/role/ConsolidatedBalanceSheetsParenthetical"
CURRENT = "instant_2024-06-30"
PREVIOUS = "instant_2023-12-31"
PERIODS = [(CURRENT, "Jun 30, 2024"), (PREVIOUS, "Dec 31, 2023")]


def _row(rendered, concept):
    return next(row for row in rendered.rows if row.metadata.get("concept") == concept)


@pytest.mark.parametrize("standard", [False, True], ids=["plain", "standard"])
@pytest.mark.parametrize("statement_path", ["typed", "uri", "blank"])
@pytest.mark.parametrize(
    "directory,role,cik,dates,concept,value,display",
    [
        pytest.param(
            "aapl/10k_2023",
            APPLE_ROLE,
            "0000320193",
            ("2023-09-30", "2022-09-24"),
            COMMON_PAR,
            0.00001,
            "0.00001",
            id="apple-common-par",
        ),
        pytest.param(
            "tsla",
            TESLA_ROLE,
            "0001318605",
            ("2024-06-30", "2023-12-31"),
            PREFERRED_PAR,
            0.001,
            "0.001",
            id="tesla-preferred-par",
        ),
        pytest.param(
            "tsla",
            TESLA_ROLE,
            "0001318605",
            ("2024-06-30", "2023-12-31"),
            COMMON_PAR,
            0.001,
            "0.001",
            id="tesla-common-par-control",
        ),
    ],
)
def test_filed_par_values_keep_precision(directory, role, cik, dates, concept, value, display, statement_path, standard):
    xbrl = XBRL.from_directory(FIXTURES / directory)
    facts = xbrl.query().by_concept(concept.replace("us-gaap_", "us-gaap:"), exact=True).execute()
    facts = [fact for fact in facts if fact.get("period_instant") in dates]
    assert len(facts) == len(dates)
    assert {fact["period_instant"] for fact in facts} == set(dates)
    for fact in facts:
        assert fact["numeric_value"] == value
        assert fact["unit_ref"] == "usdPerShare"
        assert fact["decimals"] == "INF"
        assert fact["entity_identifier"] == cik

    raw = xbrl.get_statement(role, should_display_dimensions=True, view=StatementView.DETAILED)
    raw_before = deepcopy(raw)
    period_keys = [f"instant_{date}" for date in dates]
    item = next(item for item in raw if item.get("concept") == concept)
    assert item["values"] == dict.fromkeys(period_keys, value)
    assert item["decimals"] == dict.fromkeys(period_keys, "INF")
    assert item["units"] == dict.fromkeys(period_keys, "usdPerShare")
    assert item["preferred_signs"] == dict.fromkeys(period_keys, 1)
    title = next(item["definition"] for item in xbrl.get_all_statements() if item["role"] == role)
    statement_type = {"typed": "BalanceSheetParenthetical", "uri": role, "blank": ""}[statement_path]
    rendered = render_statement(
        deepcopy(raw),
        periods_to_display=list(zip(period_keys, dates)),
        statement_title=title,
        statement_type=statement_type,
        entity_info=xbrl.entity_info,
        standard=standard,
        xbrl_instance=xbrl,
        include_dimensions=False,
        role_uri=role,
        view=StatementView.STANDARD,
    )
    assert raw == raw_before
    assert rendered.header.period_keys == period_keys
    row = _row(rendered, concept)
    assert [cell.value for cell in row.cells] == [value, value]
    assert [cell.get_formatted_value() for cell in row.cells] == [display, display]
    assert row.metadata["units"] == item["units"]
    assert row.metadata["preferred_signs"] == item["preferred_signs"]
    assert row.metadata["period_types"] == dict.fromkeys(period_keys, "instant")
    for presentation in (False, True):
        frame = rendered.to_dataframe(presentation=presentation, include_unit=True, include_point_in_time=True)
        selected = frame.loc[frame["concept"].eq(concept)]
        assert selected["unit"].tolist() == ["usdPerShare"]
        assert selected["point_in_time"].tolist() == [True]
        for date in dates:
            assert selected[date].tolist() == [value]
    serialized = rendered.to_dict()
    assert RenderedStatement.from_dict(serialized).to_dict() == serialized
    markdown_row = next(line for line in rendered.to_markdown().splitlines() if row.label in line)
    assert markdown_row.count(display) == len(dates)


def _numeric_item(concept, label, value, decimals, unit):
    return {
        "concept": concept,
        "label": label,
        "level": 0,
        "has_values": True,
        "is_abstract": False,
        "is_total": False,
        "values": {CURRENT: value, PREVIOUS: -value},
        "decimals": {CURRENT: decimals, PREVIOUS: decimals},
        "units": {CURRENT: unit, PREVIOUS: unit},
        "preferred_signs": {CURRENT: 1, PREVIOUS: 1},
    }


@pytest.mark.parametrize("standard", [False, True], ids=["plain", "standard"])
@pytest.mark.parametrize("statement_type", ["BalanceSheet", APPLE_ROLE, ""], ids=["typed", "uri", "blank"])
@pytest.mark.parametrize("scale", [-3, -6, -9])
@pytest.mark.parametrize(
    "value,display",
    [(0.00001, "0.00001"), (0.000000000001, "0.000000000001"), (1.25, "1.25"), (1000.0, "1,000.00")],
)
def test_par_values_ignore_money_and_share_scales(value, display, scale, statement_type, standard):
    items = [
        _numeric_item("us-gaap_Assets", "Assets", 123 * 10 ** (-scale), scale, "usd"),
        _numeric_item("us-gaap_CommonStockSharesOutstanding", "Shares outstanding", 276 * 10 ** (-scale), scale, "shares"),
        _numeric_item("us-gaap_EarningsPerShareBasic", "Basic earnings per share", 1.25, 2, "usdPerShare"),
        *[_numeric_item(concept, "Stock par value", value, "INF", "usdPerShare") for concept in (COMMON_PAR, PREFERRED_PAR)],
    ]
    rendered = render_statement(items, PERIODS, "Precision and scale controls", statement_type, standard=standard)
    assert rendered.header.metadata["dominant_scale"] == scale
    assert rendered.header.metadata["shares_scale"] == scale
    for concept in (COMMON_PAR, PREFERRED_PAR):
        row = _row(rendered, concept)
        assert [cell.value for cell in row.cells] == [value, -value]
        assert [cell.get_formatted_value() for cell in row.cells] == [display, f"-{display}"]
        assert row.metadata["units"] == {CURRENT: "usdPerShare", PREVIOUS: "usdPerShare"}
    assert [cell.get_formatted_value() for cell in _row(rendered, "us-gaap_CommonStockSharesOutstanding").cells] == ["276", "-276"]
    assert [cell.get_formatted_value() for cell in _row(rendered, "us-gaap_EarningsPerShareBasic").cells] == ["1.25", "-1.25"]
    currency = "$" if statement_type == "BalanceSheet" else ""
    assert [cell.get_formatted_value() for cell in _row(rendered, "us-gaap_Assets").cells] == [f"{currency}123", f"{currency}(123)"]


@pytest.mark.parametrize("standard", [False, True], ids=["plain", "standard"])
@pytest.mark.parametrize(
    "statement_type,apply_sign",
    [
        ("BalanceSheet", True),
        ("IncomeStatement", True),
        ("CashFlowStatement", True),
        ("BalanceSheetParenthetical", False),
        (APPLE_ROLE, False),
        ("", False),
    ],
)
def test_par_precision_keeps_the_existing_presentation_sign_gate(statement_type, apply_sign, standard):
    items = [_numeric_item(concept, "Stock par value", 0.00001, "INF", "usdPerShare") for concept in (COMMON_PAR, PREFERRED_PAR)]
    for item in items:
        item["preferred_signs"] = {CURRENT: -1, PREVIOUS: 1}
    rendered = render_statement(items, PERIODS, "Par sign controls", statement_type, standard=standard)
    for concept in (COMMON_PAR, PREFERRED_PAR):
        row = _row(rendered, concept)
        assert [cell.value for cell in row.cells] == [0.00001, -0.00001]
        assert [cell.get_formatted_value() for cell in row.cells] == ["-0.00001" if apply_sign else "0.00001", "-0.00001"]
        for presentation in (False, True):
            frame = rendered.to_dataframe(presentation=presentation)
            selected = frame.loc[frame["concept"].eq(concept)]
            assert selected["2024-06-30"].tolist() == [-0.00001 if presentation and apply_sign else 0.00001]
            assert selected["2023-12-31"].tolist() == [-0.00001]


@pytest.mark.parametrize("standard", [False, True], ids=["plain", "standard"])
@pytest.mark.parametrize(
    "value,display",
    [(0.00001, "0.00"), (1, "1.00"), (1.25, "1.25"), (1.2344, "1.234"), (12.346, "12.35"), (1234.567, "1,234.57")],
)
def test_ordinary_eps_keeps_its_existing_precision(value, display, standard):
    concepts = ("us-gaap_EarningsPerShareBasic", "us-gaap_EarningsPerShareDiluted")
    items = [_numeric_item(concept, "Earnings per share", value, 2, "usdPerShare") for concept in concepts]
    rendered = render_statement(items, PERIODS, "EPS precision controls", "IncomeStatement", standard=standard)
    for concept in concepts:
        row = _row(rendered, concept)
        assert [cell.value for cell in row.cells] == [value, -value]
        assert [cell.get_formatted_value() for cell in row.cells] == [display, f"-{display}"]


@pytest.mark.parametrize("standard", [False, True], ids=["plain", "standard"])
@pytest.mark.parametrize(
    "statement_type,apply_sign",
    [
        ("BalanceSheet", True),
        ("IncomeStatement", True),
        ("CashFlowStatement", True),
        ("BalanceSheetParenthetical", False),
        (APPLE_ROLE, False),
        ("", False),
    ],
)
@pytest.mark.parametrize(
    "value,display,opposite_display",
    [
        pytest.param(float("nan"), "nan", "nan", id="nan"),
        pytest.param(float("inf"), "inf", "-inf", id="inf"),
        pytest.param(float("-inf"), "-inf", "inf", id="negative-inf"),
    ],
)
def test_par_nonfinite_float_placeholders_keep_display_and_signs(value, display, opposite_display, statement_type, apply_sign, standard):
    # A finite monetary row preserves the two period columns even for NaN.
    items = [_numeric_item("us-gaap_Assets", "Assets", 123_000_000, -6, "usd")]
    for concept in (COMMON_PAR, PREFERRED_PAR):
        item = _numeric_item(concept, "Stock par value", value, "INF", "usdPerShare")
        item["preferred_signs"] = {CURRENT: -1, PREVIOUS: 1}
        items.append(item)
    rendered = render_statement(items, PERIODS, "Nonfinite par controls", statement_type, standard=standard)
    assert rendered.header.period_keys == [CURRENT, PREVIOUS]
    for concept in (COMMON_PAR, PREFERRED_PAR):
        row = _row(rendered, concept)
        for cell, expected in zip(row.cells, (value, -value)):
            assert math.isnan(cell.value) if math.isnan(expected) else cell.value == expected
        assert [cell.get_formatted_value() for cell in row.cells] == [opposite_display if apply_sign else display, opposite_display]
        assert row.metadata["units"] == {CURRENT: "usdPerShare", PREVIOUS: "usdPerShare"}
        for presentation in (False, True):
            frame = rendered.to_dataframe(presentation=presentation)
            selected = frame.loc[frame["concept"].eq(concept)]
            expected = -value if presentation and apply_sign else value
            actual = selected["2024-06-30"].tolist()[0]
            assert math.isnan(actual) if math.isnan(expected) else actual == expected
            actual = selected["2023-12-31"].tolist()[0]
            assert math.isnan(actual) if math.isnan(value) else actual == -value
