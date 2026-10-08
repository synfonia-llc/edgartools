"""Selected legal-entity facts for face statements in two AAL filing packages.

Expected amounts come from original XML and filed HTML cells, never queries.
Fixture manifests pin the original SEC document URLs and fragment provenance.

GitHub Issue: https://github.com/dgunning/edgartools/issues/1468
"""

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from edgar.xbrl import XBRL
from edgar.xbrl.rendering import render_statement

pytestmark = pytest.mark.fast
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "selected_entity_1468"
ROLE = "http://www.aa.com/role/CondensedConsolidatedBalanceSheetsAmericanAirlinesInc"
AXIS = "dei:LegalEntityAxis"
MEMBER = "aal:AmericanAirlinesIncMember"
BINDING = ("dei_LegalEntityAxis", "aal_AmericanAirlinesIncMember")
INSTANT = "instant_2026-06-30"
PRODUCT = "srt:ProductOrServiceAxis"
EQUITY = "us-gaap:StatementEquityComponentsAxis"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"


def _load(directory, stem):
    folder = FIXTURES / directory
    xbrl = XBRL.from_files(
        instance_file=folder / (stem + "_htm.xml"),
        schema_file=folder / (stem + ".xsd"),
        presentation_file=folder / (stem + "_pre.xml"),
        label_file=folder / (stem + "_lab.xml"),
        calculation_file=folder / (stem + "_cal.xml"),
        definition_file=folder / (stem + "_def.xml"),
    )
    xml = ET.parse(folder / (stem + "_htm.xml")).getroot()  # noqa: S314 - Checked-in, pinned SEC fixture only.
    return SimpleNamespace(
        x=xbrl,
        manifest=json.loads((folder / "manifest.json").read_text()),
        anchors={a["fact_id"]: a for a in json.loads((folder / "expected-anchors.json").read_text())},
        xml={fact.get("id"): fact for fact in xml if fact.get("contextRef")},
    )


@pytest.fixture(scope="module")
def q2():
    return _load("aal_q2_2026", "aal-20260630")


@pytest.fixture(scope="module")
def annual():
    return _load("aal_fy2025", "aal-20251231")


def _anchor(filing, fact_id):
    anchor, raw = filing.anchors[fact_id], filing.xml[fact_id]
    actual = (raw.get("id"), raw.get("contextRef"), raw.get("unitRef"), raw.get("decimals"), raw.get(XSI_NIL) == "true")
    expected = tuple(anchor[k] for k in ("fact_id", "context_ref", "unit_ref", "decimals", "nil"))
    assert actual == expected
    assert raw.text == anchor["raw_value"]
    assert raw.tag.endswith("}" + anchor["concept"].split(":", 1)[1])
    value = "" if raw.text is None else Decimal(raw.text)
    return anchor, value


def _period(filing, anchor):
    period = filing.manifest["contexts"][anchor["context_ref"]]["period"]
    if "instant" in period:
        return "instant_" + period["instant"]
    return "duration_" + period["startDate"] + "_" + period["endDate"]


def _ordinary_rows(rows, concept, period):
    return [
        row
        for row in rows
        if row["concept"] == concept and not row.get("is_dimension") and not row.get("is_abstract") and period in row.get("values", {})
    ]


def _amounts(rows, concept, period):
    return {row["values"][period] for row in _ordinary_rows(rows, concept, period)}


def _assert_face_metadata(rows, anchor, period):
    for row in _ordinary_rows(rows, anchor["concept"].replace(":", "_", 1), period):
        assert row["units"][period] == anchor["unit_ref"]
        assert row["decimals"][period] == int(anchor["decimals"])
        assert row["period_types"][period] == period.split("_", 1)[0]


def _assert_consumed_entity(rows):
    assert all(info["dimension"].replace(":", "_", 1) != BINDING[0] for row in rows for info in row.get("dimension_metadata") or [])


def _faces(filing, specimens):
    for fact_id, expected, cell in specimens:
        anchor, value = _anchor(filing, fact_id)
        assert value == Decimal(expected)
        assert anchor["html"]["cell_text"].replace(" ", "") == cell
        period = _period(filing, anchor)
        for display_dimensions in (False, True):
            rows = filing.x.get_statement(anchor["role_uri"], period_filter=period, should_display_dimensions=display_dimensions)
            assert _amounts(rows, anchor["concept"].replace(":", "_", 1), period) == {value}
            _assert_face_metadata(rows, anchor, period)
            if anchor["scope"] == "subsidiary":
                _assert_consumed_entity(rows)


def _raw_state(xbrl):
    facts = {key: (id(fact), fact.model_dump()) for key, fact in xbrl._facts.items()}
    return (facts, {key: (id(context), context.model_dump()) for key, context in xbrl.contexts.items()})


def _tree(q2):
    return deepcopy(q2.x.presentation_trees[ROLE])


def _project(q2, concept):
    facts = q2.x._find_facts_for_element(concept, INSTANT)
    return facts, q2.x._project_statement_entity_facts(facts, BINDING)


def _assert_wrapper_copy(old, new):
    assert new is not old
    assert new["fact"] is old["fact"]
    assert new["dimension_info"] is not old["dimension_info"]
    for info in new["dimension_info"]:
        original = next(item for item in old["dimension_info"] if item["dimension"] == info["dimension"])
        _assert_info_copy(original, info)


def _assert_info_copy(old, new):
    assert new == old
    assert new is not old
    assert all(new[key] is old[key] for key in new)


def test_q2_face_amounts_and_parent_call_order(q2):
    before = _raw_state(q2.x)
    _faces(
        q2,
        [
            ("f-1002", 72_888_000_000, "72,888"),
            ("f-217", 64_233_000_000, "64,233"),
            ("f-936", 194_000_000, "194"),
            ("f-137", 71_000_000, "71"),
            ("f-1056", 4_648_000_000, "4,648"),
            ("f-271", 4_694_000_000, "4,694"),
            ("f-956", 209_000_000, "209"),
            ("f-173", 86_000_000, "86"),
            ("f-958", -48_000_000, "(48)"),
            ("f-175", -279_000_000, "(279)"),
            ("f-1130", 9_024_000_000, "9,024"),
            ("f-351", -3_972_000_000, "(3,972)"),
            ("f-1002", 72_888_000_000, "72,888"),
        ],
    )
    assert _raw_state(q2.x) == before


def test_annual_operations_cash_comprehensive_and_equity(annual):
    _faces(
        annual,
        [
            ("f-1801", 564_000_000, "564"),
            ("f-140", 111_000_000, "111"),
            ("f-1780", 1_511_000_000, "1,511"),
            ("f-119", 1_467_000_000, "1,467"),
            ("f-1963", 1_930_000_000, "1,930"),
            ("f-309", 3_099_000_000, "3,099"),
            ("f-1999", 47_000_000, "47"),
            ("f-345", -1_051_000_000, "(1,051)"),
            ("f-1816", 734_000_000, "734"),
            ("f-167", 287_000_000, "287"),
            ("f-2065", 9_028_000_000, "9,028"),
            ("f-419", -3_727_000_000, "(3,727)"),
            # Raw fact sign differs from filed display; rendering policy is separate.
            ("f-1951", 1_701_000_000, "(1,701)"),
        ],
    )


def test_exact_uri_with_blank_classification_keeps_subsidiary(q2):
    statement = q2.x.statements[ROLE]
    statement.canonical_type = ""
    assert _amounts(statement.get_raw_data(), "us-gaap_Assets", INSTANT) == {72_888_000_000}
    frame = statement.to_dataframe(standard=False, presentation=False, view="summary", period_filter=INSTANT)
    assert set(frame.loc[frame["concept"].eq("us-gaap_Assets"), "2026-06-30"]) == {72_888_000_000}


def _assert_rendered_assets(rendered):
    assets = next(row for row in rendered.rows if row.metadata.get("concept") == "us-gaap_Assets")
    assert assets.cells[0].value == 72_888_000_000
    assert assets.cells[0].get_formatted_value().replace("$", "") == "72,888"
    assert assets.metadata["units"][INSTANT] == "usd"


def test_selected_rows_keep_filed_assets_through_renderers(q2):
    rows = q2.x.get_statement(ROLE, period_filter=INSTANT)
    for kind in ("BalanceSheet", ROLE, ""):
        for standard in (False, True):
            rendered = render_statement(
                rows, [(INSTANT, "June 30, 2026")], "Balance Sheets", kind, q2.x.entity_info, standard, xbrl_instance=q2.x, role_uri=ROLE
            )
            _assert_rendered_assets(rendered)
    _assert_rendered_assets(q2.x.render_statement(ROLE, period_filter=INSTANT, standard=False))
    statement = q2.x.statements[ROLE]
    statement.canonical_type = ""
    _assert_rendered_assets(statement.render(period_filter=INSTANT, standard=False))


def test_product_precision_residual_metadata_and_derived_total(q2):
    before = _raw_state(q2.x)
    old, selected = _project(q2, "us-gaap_ContractWithCustomerLiabilityCurrent")
    assert set(selected) == {"c-297", "c-299"}
    assert selected["c-299"]["fact"].fact_id == "f-1012"
    for context_id, wrapper in selected.items():
        _assert_wrapper_copy(old[context_id], wrapper)
        assert [info["dimension"] for info in wrapper["dimension_info"]] == [PRODUCT]
    assert sum(wrapper["fact"].numeric_value for wrapper in selected.values()) == 13_904_000_000
    assert _raw_state(q2.x) == before
    # This is derived from 9,551M + 4,353M; it is not another directly filed fact.
    rows = q2.x.get_statement(ROLE, period_filter=INSTANT, should_display_dimensions=False)
    assert _amounts(rows, "us-gaap_ContractWithCustomerLiabilityCurrent", INSTANT) == {13_904_000_000}


def test_nil_and_true_equity_zero_stay_distinct(q2):
    _, nil = _project(q2, "us-gaap_CommitmentsAndContingencies")
    _, equity = _project(q2, "us-gaap_StockholdersEquity")
    fact = nil["c-295"]["fact"]
    assert (fact.fact_id, fact.numeric_value, fact.value) == ("f-1034", None, "")
    assert nil["c-295"]["dimension_info"] == []
    zero = equity["c-319"]["fact"]
    assert (zero.fact_id, zero.numeric_value) == ("f-1126", 0)
    assert [i["dimension"] for i in equity["c-319"]["dimension_info"]] == [EQUITY]
    anchor, value = _anchor(q2, "f-1126")
    assert (value, anchor["nil"], anchor["html"]["cell_text"]) == (0, False, "—")


def test_parent_inf_precision_cannot_win_subsidiary_par_value(annual):
    facts = annual.x._find_facts_for_element("us-gaap_CommonStockParOrStatedValuePerShare", "instant_2025-12-31")
    selected = annual.x._project_statement_entity_facts(facts, BINDING)
    fact = selected["c-514"]["fact"]
    # Original f-1895 and f-2068 are exact duplicate face facts; either is valid.
    assert fact.fact_id in {"f-1895", "f-2068"}
    assert (fact.numeric_value, fact.unit_ref, str(fact.decimals)) == (1, "usdPerShare", "2")
    assert set(selected) == {"c-514"}
    role = "http://www.aa.com/role/ConsolidatedBalanceSheetsAmericanAirlinesIncParenthetical"
    rows = annual.x.get_statement(role, period_filter="instant_2025-12-31")
    assert _amounts(rows, "us-gaap_CommonStockParOrStatedValuePerShare", "instant_2025-12-31") == {1}


def test_bound_nil_or_absence_never_falls_back_to_non_nil_parent(q2, monkeypatch):
    original = q2.x._find_facts_for_element
    commitments = original("us-gaap_CommitmentsAndContingencies", INSTANT)
    parent = {**commitments["c-22"], "fact": commitments["c-22"]["fact"].model_copy(update={"numeric_value": 17, "value": "17", "decimals": "INF"})}

    # Synthetic witness: original parent and subsidiary commitments are both nil.
    def witness(element, *args, **kwargs):
        if element.replace(":", "_", 1) == "us-gaap_CommitmentsAndContingencies":
            return choices
        return original(element, *args, **kwargs)

    monkeypatch.setattr(q2.x, "_find_facts_for_element", witness)
    choices = {"c-22": parent, "c-295": commitments["c-295"]}
    rows = q2.x.get_statement(ROLE, period_filter=INSTANT)
    assert _amounts(rows, "us-gaap_CommitmentsAndContingencies", INSTANT) == {""}
    choices = {"c-22": parent}
    rows = q2.x.get_statement(ROLE, period_filter=INSTANT)
    assert _amounts(rows, "us-gaap_CommitmentsAndContingencies", INSTANT) == set()


def test_same_cik_other_member_and_conflicting_axis_alias_are_rejected(q2, monkeypatch):
    facts = q2.x._find_facts_for_element("us-gaap_Assets", INSTANT)
    wrapper = facts["c-22"]
    context = q2.x.contexts["c-22"].model_copy(deep=True)
    dimensions = {AXIS: "aal:OtherEntityMember"}
    context.dimensions.clear()
    context.dimensions.update(dimensions)
    # Synthetic member mutation retains the real parent context ID and same CIK.
    monkeypatch.setitem(q2.x.contexts, "c-22", context)
    assert q2.x._project_statement_entity_facts({"c-22": wrapper}, BINDING) == {}
    dimensions = context.dimensions
    dimensions[AXIS] = MEMBER
    dimensions["dei_LegalEntityAxis"] = "aal_OtherEntityMember"
    assert q2.x._project_statement_entity_facts({"c-22": wrapper}, BINDING) == {}
    assert q2.x._project_statement_entity_facts({"absent-context": wrapper}, BINDING) == {}


def test_forward_edges_and_shared_bound_roots_survive_optional_metadata(q2, monkeypatch):
    tree = _tree(q2)
    tree.definition = ""
    for node in tree.all_nodes.values():
        node.parent, node.depth = "unrelated", 99
    tree.root_element_ids.append("us-gaap_IncomeStatementAbstract")
    tree.all_nodes["us-gaap_IncomeStatementAbstract"] = SimpleNamespace(children=["us-gaap_StatementTable"])
    monkeypatch.delitem(q2.x._filing_summary_categories, ROLE, raising=False)
    monkeypatch.delitem(q2.x.element_catalog, "dei_LegalEntityAxis", raising=False)
    assert q2.x._get_statement_entity_binding(tree) == BINDING


def test_multiple_entity_members_cannot_bind_whole_role(q2):
    tree = _tree(q2)
    tree.all_nodes["dei_EntityDomain"].children.append("aal_OtherEntityMember")
    tree.all_nodes["aal_OtherEntityMember"] = SimpleNamespace(children=[])
    assert q2.x._get_statement_entity_binding(tree) is None
    tree = _tree(q2)
    tree.all_nodes["aal_AmericanAirlinesIncMember"].children.append("test_ChildMember")
    tree.all_nodes["test_ChildMember"] = SimpleNamespace(children=[])
    assert q2.x._get_statement_entity_binding(tree) is None
    tree = _tree(q2)
    tree.all_nodes["dei_EntityDomain"].children = ["test_NotMemberAbstract"]
    tree.all_nodes["test_NotMemberAbstract"] = SimpleNamespace(children=[])
    assert q2.x._get_statement_entity_binding(tree) is None


def test_unbound_root_and_nested_table_cannot_be_promoted(q2):
    tree = _tree(q2)
    tree.root_element_ids.append("us-gaap_IncomeStatementAbstract")
    tree.all_nodes["us-gaap_IncomeStatementAbstract"] = SimpleNamespace(children=[])
    assert q2.x._get_statement_entity_binding(tree) is None
    tree = _tree(q2)
    tree.all_nodes["us-gaap_StatementLineItems"].children.append("test_ExtraTable")
    tree.all_nodes["test_ExtraTable"] = SimpleNamespace(children=[])
    assert q2.x._get_statement_entity_binding(tree) is None
    tree = _tree(q2)
    tree.all_nodes["us-gaap_StatementLineItems"].children.append("dei_LegalEntityAxis")
    assert q2.x._get_statement_entity_binding(tree) is None


def test_disclosure_category_and_typed_axis_veto(q2, monkeypatch):
    tree = _tree(q2)
    tree.definition = "123 - Disclosure - Entity role"
    assert q2.x._get_statement_entity_binding(tree) is None
    tree.definition = "123 - Notes to Consolidated Financial Statements"
    with monkeypatch.context() as patch:
        patch.delitem(q2.x._filing_summary_categories, ROLE, raising=False)
        assert q2.x._get_statement_entity_binding(tree) is None
    tree = _tree(q2)
    with monkeypatch.context() as patch:
        patch.setitem(q2.x._filing_summary_categories, ROLE, "note")
        assert q2.x._get_statement_entity_binding(tree) is None
    monkeypatch.setitem(q2.x.element_catalog, "dei_LegalEntityAxis", SimpleNamespace(typed_domain_ref="typed-domain"))
    assert q2.x._get_statement_entity_binding(tree) is None


def test_dangling_cycle_and_conflicting_node_alias_veto(q2):
    tree = _tree(q2)
    tree.all_nodes["us-gaap_StatementLineItems"].children.append("test_MissingNode")
    assert q2.x._get_statement_entity_binding(tree) is None
    tree = _tree(q2)
    tree.all_nodes["us-gaap_StatementLineItems"].children.append("us-gaap_StatementTable")
    assert q2.x._get_statement_entity_binding(tree) is None
    tree = _tree(q2)
    tree.all_nodes["dei:LegalEntityAxis"] = SimpleNamespace(children=[])
    assert q2.x._get_statement_entity_binding(tree) is None
