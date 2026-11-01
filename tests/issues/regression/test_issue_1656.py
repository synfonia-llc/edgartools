"""Expose source-selected periods without changing scalar financial metrics.

GitHub Issue: https://github.com/dgunning/edgartools/issues/1656

Apple Q3 FY2023, accession 0000320193-23-000077: revenue f-65/c-21,
OCF f-327/c-1 and PP&E purchases f-335/c-1. Tesla Q2 2024, accession
0001628280-24-032662: revenue f-140/c-33, OCF f-448/c-1 and capex
f-450/c-1. Amounts and dates were inspected in retained XBRL facts/contexts,
independently of Financials selectors. These filings mix quarter income
with YTD cash flow; the option reports those dates without aligning values.
"""
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from edgar.financials import Financials, _period_descriptor, _select_period_column
from edgar.xbrl import XBRL
from edgar.xbrl.rendering import PeriodData, RenderedStatement, StatementCell, StatementHeader, StatementRow

pytestmark = pytest.mark.fast

METRIC_NAMES = {
    'revenue', 'operating_income', 'net_income',
    'total_assets', 'total_liabilities', 'stockholders_equity',
    'current_assets', 'current_liabilities',
    'operating_cash_flow', 'capital_expenditures', 'free_cash_flow',
    'shares_outstanding_basic', 'shares_outstanding_diluted',
    'current_ratio', 'debt_to_assets',
}


def duration(start, end):
    return {'period_type': 'duration', 'start_date': start, 'end_date': end}


def instant(end):
    return {'period_type': 'instant', 'start_date': None, 'end_date': end}


# Raw source controls: Apple annual 0000320193-23-000106 c-1/f-69/f-298/f-310;
# Netflix Q1 0001065280-24-000128 c-1/f-30/f-104/f-106; Netflix Q3
# 0001065280-24-000287 quarter c-3/f-30/f-198/f-202. Netflix Q3 genuinely
# files discrete cash flow, distinct from its YTD OCF 5,824,470,000.
SOURCE_CASES = [
    ('aapl/10q_2023', '2023-04-02', '2022-09-25', '2023-07-01',
     81797000000, 88945000000, 8796000000, 80149000000),
    ('tsla', '2024-04-01', '2024-01-01', '2024-06-30',
     25500000000, 3854000000, 5043000000, -1189000000),
    ('aapl/10k_2023', '2022-09-25', '2022-09-25', '2023-09-30',
     383285000000, 110543000000, 10959000000, 99584000000),
    ('nflx/2024', '2024-01-01', '2024-01-01', '2024-03-31',
     9370440000, 2212522000, 75714000, 2136808000),
    ('nflx/10q_2024', '2024-07-01', '2024-07-01', '2024-09-30',
     9824703000, 2321101000, 126863000, 2194238000),
]


@pytest.fixture(scope='module')
def apple_quarter():
    return Financials(XBRL.from_directory(Path('tests/fixtures/xbrl/aapl/10q_2023')))


@pytest.mark.parametrize(
    'fixture,income_start,cash_start,end,revenue,ocf,capex,fcf', SOURCE_CASES)
def test_selected_periods_match_retained_filing(
        fixture, income_start, cash_start, end, revenue, ocf, capex, fcf):
    financials = Financials(XBRL.from_directory(Path('tests/fixtures/xbrl') / fixture))
    default = financials.get_financial_metrics()
    detailed = financials.get_financial_metrics(include_periods=True)

    assert set(default) == METRIC_NAMES
    assert set(detailed) == METRIC_NAMES | {'periods'}
    assert set(detailed['periods']) == METRIC_NAMES
    for name in METRIC_NAMES:
        assert detailed[name] == default[name], name
        assert default[name] is None or isinstance(default[name], (int, float)), name
    assert detailed['revenue'] == revenue
    assert detailed['operating_cash_flow'] == ocf
    assert detailed['capital_expenditures'] == capex
    assert detailed['free_cash_flow'] == fcf == ocf - abs(capex)
    if fixture == 'tsla':
        assert detailed['net_income'] == 1478000000  # Filed quarter f-220/c-33.
    assert detailed['periods']['revenue'] == duration(income_start, end)
    for name in ('operating_cash_flow', 'capital_expenditures', 'free_cash_flow'):
        assert detailed['periods'][name] == duration(cash_start, end)
    for name in ('total_assets', 'total_liabilities', 'stockholders_equity',
                 'current_assets', 'current_liabilities', 'current_ratio', 'debt_to_assets'):
        expected = instant(end) if detailed[name] is not None else None
        assert detailed['periods'][name] == expected, name
    for name in ('operating_income', 'net_income',
                 'shares_outstanding_basic', 'shares_outstanding_diluted'):
        expected = duration(income_start, end) if detailed[name] is not None else None
        assert detailed['periods'][name] == expected, name


def test_apple_all_fifteen_values_match_filed_sources(apple_quarter):
    # Quarter c-21: operating income f-97; NI f-113; basic/diluted f-125/f-129.
    # Instant c-24: assets f-195; liabilities f-215; equity f-233;
    # current assets f-185; current liabilities f-207. USD and shares, respectively.
    expected = {
        'revenue': 81797000000, 'operating_income': 22998000000,
        'net_income': 19881000000, 'total_assets': 335038000000,
        'total_liabilities': 274764000000, 'stockholders_equity': 60274000000,
        'current_assets': 122659000000, 'current_liabilities': 124963000000,
        'operating_cash_flow': 88945000000, 'capital_expenditures': 8796000000,
        'free_cash_flow': 80149000000, 'shares_outstanding_basic': 15697614000,
        'shares_outstanding_diluted': 15775021000,
        'current_ratio': 122659 / 124963, 'debt_to_assets': 274764 / 335038,
    }
    metrics = apple_quarter.get_financial_metrics(include_periods=True)
    for name, value in expected.items():
        assert metrics[name] == value, name
    assert metrics['total_assets'] == metrics['total_liabilities'] + metrics['stockholders_equity']


def test_option_is_keyword_only():
    with pytest.raises(TypeError):
        Financials(None).get_financial_metrics(True)


@pytest.mark.parametrize('periods,column,expected', [
    ([], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30')], 'unmapped', None),
    ([PeriodData('x', 'x', 'invalid')], 'invalid', None),
    ([PeriodData('x', '2024-06-30')], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30', None, True)], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30', 'invalid', True)], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30', 'invalid', False)], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30', '2024-07-01', True)], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30', '2024-01-01', True),
      PeriodData('y', 'y', '2024-06-30', '2024-04-01', True)], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30'),
      PeriodData('y', 'y', '2024-06-30', '2024-04-01', True)], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30', '2024-04-01', True),
      PeriodData('y', 'y', '2024-06-30', None, True)], '2024-06-30', None),
    ([PeriodData('x', 'x', '2024-06-30', '2024-04-01', True),
      PeriodData('y', 'y', '2024-06-30', '2024-04-01', True)],
     '2024-06-30', duration('2024-04-01', '2024-06-30')),
    ([PeriodData('x', 'x', '2024-06-30', '2024-04-01', False)],
     '2024-06-30', duration('2024-04-01', '2024-06-30')),
    ([PeriodData('x', 'x', '2024-06-30', None, False)], '2024-06-30', instant('2024-06-30')),
    ([PeriodData('x', 'x', '2024-06-30', '2024-04-01', True, 'Q2')],
     '2024-06-30 (Q2)', duration('2024-04-01', '2024-06-30')),
])
def test_unknown_and_duplicate_source_periods(periods, column, expected):
    """Synthetic malformed/custom metadata never supplies guessed source dates."""
    rendered = SimpleNamespace(periods=periods)
    frame = pd.DataFrame({'concept': ['custom:Revenue'], column: [0]})
    selected = _select_period_column(rendered, frame)
    descriptor = _period_descriptor(rendered, selected)
    assert selected == column
    assert descriptor == expected


def _rendered(periods, rows, statement_type='IncomeStatement'):
    """Use the actual rendering/dataframe contract for synthetic source controls."""
    return RenderedStatement(
        title='Synthetic source selection', statement_type=statement_type,
        header=StatementHeader(columns=[p.label for p in periods],
                               period_keys=[p.key for p in periods], periods=periods),
        rows=[StatementRow(label=label, level=0, metadata={'concept': concept},
                           cells=[StatementCell(value) for value in values])
              for concept, label, values in rows],
    )


def _financials(income=None, balance=None, cashflow=None, facts=None, cls=Financials):
    financials = cls(SimpleNamespace(facts=facts))
    for method, rendered in (('income_statement', income), ('balance_sheet', balance),
                             ('cash_flow_statement', cashflow)):
        statement = None if rendered is None else SimpleNamespace(render=lambda rendered=rendered, **kwargs: rendered)
        setattr(financials, method, lambda statement=statement: statement)
    return financials


class RawFacts:
    def __init__(self, frame):
        self.frame = frame
        self.calls = 0

    def query(self):
        self.calls += 1
        return self

    def by_concept(self, concept, exact=False):
        assert concept == 'us-gaap:Revenues'
        assert exact
        return self

    def to_dataframe(self):
        return self.frame.copy()


@pytest.mark.parametrize('colliding', [False, True])
def test_raw_revenue_fallback_preserves_its_selected_scalar(colliding):
    """Collision coverage preserves a legacy number without certifying its period."""
    periods = [PeriodData('ytd', 'Six months', '2024-06-30', '2024-01-01', True)]
    values = [11]
    if colliding:
        periods.append(PeriodData('quarter', 'Three months', '2024-06-30', '2024-04-01', True))
        values.append(22)
    rendered = _rendered(periods, [('us-gaap_NoninterestIncome', 'Noninterest income', values)])
    assert rendered.to_dataframe(presentation=False)['2024-06-30'].iloc[0] == values[-1]
    facts = RawFacts(pd.DataFrame([
        {'is_dimensioned': False, 'period_start': '2024-01-01', 'period_end': '2024-06-30', 'numeric_value': 111},
        {'is_dimensioned': False, 'period_start': '2024-04-01', 'period_end': '2024-06-30', 'numeric_value': 222},
        {'is_dimensioned': True, 'period_start': '2024-01-01', 'period_end': '2024-06-30', 'numeric_value': 999},
    ]))
    financials = _financials(income=rendered, facts=facts)
    assert financials.get_financial_metrics()['revenue'] == 111
    assert facts.calls == 1
    detailed = financials.get_financial_metrics(include_periods=True)
    assert detailed['revenue'] == 111
    assert facts.calls == 2, 'metadata must not scan raw facts again'
    expected = None if colliding else duration('2024-01-01', '2024-06-30')
    assert detailed['periods']['revenue'] == expected


@pytest.mark.parametrize('concept,label', [
    ('us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', 'Net sales'),
    ('custom_UnmappedSales', 'Revenue'),
])
@pytest.mark.parametrize('value', [None, float('nan'), '', 0, 123])
def test_concept_and_label_routes_distinguish_missing_and_zero(concept, label, value):
    period = PeriodData('q', 'Quarter', '2024-06-30', '2024-04-01', True)
    financials = _financials(income=_rendered([period], [(concept, label, [value])]))
    metrics = financials.get_financial_metrics(include_periods=True)
    if pd.isna(value) or value == '':
        assert metrics['revenue'] is None
        assert metrics['periods']['revenue'] is None
    else:
        assert metrics['revenue'] == value
        assert metrics['periods']['revenue'] == duration('2024-04-01', '2024-06-30')


def test_shares_and_nci_derived_net_income_use_the_income_duration():
    period = PeriodData('q', 'Quarter', '2024-06-30', '2024-04-01', True)
    rendered = _rendered([period], [
        ('us-gaap_ProfitLoss', 'Consolidated profit', [100]),
        ('us-gaap_NetIncomeLossAttributableToNoncontrollingInterest', 'NCI', [-2]),
        ('us-gaap_WeightedAverageNumberOfSharesOutstandingBasic', 'Basic weighted average shares', [20]),
        ('us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding', 'Diluted weighted average shares', [21]),
    ])
    metrics = _financials(income=rendered).get_financial_metrics(include_periods=True)
    for name, value in (('net_income', 102), ('shares_outstanding_basic', 20), ('shares_outstanding_diluted', 21)):
        assert metrics[name] == value
        assert metrics['periods'][name] == duration('2024-04-01', '2024-06-30')


def test_present_values_with_ambiguous_periods_remain_available():
    periods = [PeriodData('one', 'First', '2024-06-30', '2024-01-01', True),
               PeriodData('two', 'Second', '2024-06-30', '2024-04-01', True)]
    rendered = _rendered(periods, [
        ('us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', 'Net sales', [100, 50]),
    ])
    financials = _financials(income=rendered)
    assert financials.get_financial_metrics()['revenue'] == 50
    detailed = financials.get_financial_metrics(include_periods=True)
    assert detailed['revenue'] == 50
    assert detailed['periods']['revenue'] is None


@pytest.mark.parametrize('unknown', [False, True])
@pytest.mark.parametrize('wrong_type', [False, True])
def test_derived_periods_require_known_expected_period_types(unknown, wrong_type):
    """Synthetic wrong-type sources are a safety control, not a filing defect."""
    end = None if unknown else '2024-06-30'
    cash_period = PeriodData('cash', 'Cash period', end,
                             None if wrong_type else '2024-01-01', not wrong_type)
    balance_period = PeriodData('balance', 'Balance period', end,
                                '2024-01-01' if wrong_type else None, wrong_type)
    cashflow = _rendered([cash_period], [
        ('us-gaap_NetCashProvidedByUsedInOperatingActivities', 'Operating cash flow', [50]),
        ('us-gaap_PaymentsToAcquirePropertyPlantAndEquipment', 'Capital expenditures', [10]),
    ], 'CashFlowStatement')
    balance = _rendered([balance_period], [
        ('us-gaap_Assets', 'Total assets', [100]),
        ('us-gaap_Liabilities', 'Total liabilities', [60]),
        ('us-gaap_AssetsCurrent', 'Total current assets', [30]),
        ('us-gaap_LiabilitiesCurrent', 'Total current liabilities', [20]),
    ], 'BalanceSheet')
    metrics = _financials(cashflow=cashflow, balance=balance).get_financial_metrics(include_periods=True)
    assert metrics['free_cash_flow'] == 40
    assert metrics['current_ratio'] == 1.5
    assert metrics['debt_to_assets'] == 0.6
    for name in ('free_cash_flow', 'current_ratio', 'debt_to_assets'):
        expected = None
        if not unknown and not wrong_type:
            expected = duration('2024-01-01', '2024-06-30') if name == 'free_cash_flow' else instant('2024-06-30')
        assert metrics['periods'][name] == expected, name


def test_zero_cash_flows_and_existing_zero_ratio_behavior_are_unchanged():
    cash_period = PeriodData('cash', 'Six months', '2024-06-30', '2024-01-01', True)
    balance_period = PeriodData('balance', 'June 30', '2024-06-30')
    cashflow = _rendered([cash_period], [
        ('us-gaap_NetCashProvidedByUsedInOperatingActivities', 'Operating cash flow', [0]),
        ('us-gaap_PaymentsToAcquirePropertyPlantAndEquipment', 'Capital expenditures', [0]),
    ], 'CashFlowStatement')
    balance = _rendered([balance_period], [
        ('us-gaap_Assets', 'Total assets', [100]),
        ('us-gaap_Liabilities', 'Total liabilities', [0]),
        ('us-gaap_AssetsCurrent', 'Total current assets', [0]),
        ('us-gaap_LiabilitiesCurrent', 'Total current liabilities', [0]),
    ], 'BalanceSheet')
    metrics = _financials(cashflow=cashflow, balance=balance).get_financial_metrics(include_periods=True)
    for name in ('operating_cash_flow', 'capital_expenditures', 'free_cash_flow'):
        assert metrics[name] == 0
        assert metrics['periods'][name] == duration('2024-01-01', '2024-06-30')
    assert metrics['current_assets'] == metrics['current_liabilities'] == 0
    assert metrics['periods']['current_assets'] == instant('2024-06-30')
    for name in ('current_ratio', 'debt_to_assets'):
        assert metrics[name] is None
        assert metrics['periods'][name] is None


def test_missing_statements_and_overridden_getters_have_no_inferred_period(monkeypatch):
    financials = Financials(None)
    default = financials.get_financial_metrics()
    assert set(default) == METRIC_NAMES
    assert all(value is None for value in default.values())
    detailed = financials.get_financial_metrics(include_periods=True)
    assert all(value is None for value in detailed['periods'].values())
    monkeypatch.setattr(financials, 'get_revenue', lambda: 123)
    detailed = financials.get_financial_metrics(include_periods=True)
    assert detailed['revenue'] == 123
    assert detailed['periods']['revenue'] is None


def test_metadata_is_fresh_and_metric_descriptors_are_independent():
    period = PeriodData('q', 'Quarter', '2024-06-30', '2024-04-01', True)
    rendered = _rendered([period], [
        ('us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax', 'Net sales', [50]),
        ('us-gaap_NetIncomeLoss', 'Net income', [10]),
    ])
    financials = _financials(income=rendered)
    first = financials.get_financial_metrics(include_periods=True)
    first['periods']['revenue']['start_date'] = '2000-01-01'
    assert first['periods']['net_income'] == duration('2024-04-01', '2024-06-30')

    period.start_date, period.end_date = '2024-07-01', '2024-09-30'
    rendered.rows[0].cells[0].value = 70
    second = financials.get_financial_metrics(include_periods=True)
    assert second['revenue'] == 70
    assert second['periods']['revenue'] == duration('2024-07-01', '2024-09-30')
    assert first['periods']['net_income'] == duration('2024-04-01', '2024-06-30')


@pytest.mark.parametrize('start', [
    pytest.param(pd.NA, id='pandas-missing'),
    pytest.param(0, id='numeric-zero'),
    pytest.param(False, id='false'),
    pytest.param([], id='empty-sequence'),
    pytest.param('', id='empty-string'),
])
def test_malformed_start_metadata_preserves_scalar_values(start):
    """Bad metadata cannot become a numerical lookup prerequisite or an instant."""
    period = PeriodData('q', 'Quarter', '2024-06-30', start, False)
    rendered = _rendered([period], [('us-gaap_Revenues', 'Revenue', [100]),
                                    ('us-gaap_NetIncomeLoss', 'Net income', [20])])
    financials = _financials(income=rendered)
    assert financials.get_revenue() == 100
    assert financials.get_financial_metrics()['revenue'] == 100
    detailed = financials.get_financial_metrics(include_periods=True)
    assert detailed['revenue'] == 100
    assert detailed['net_income'] == 20
    assert detailed['periods']['revenue'] is None
    assert detailed['periods']['net_income'] is None
    assert financials._statement_frame_memo is None


@pytest.mark.parametrize('flag', [None, 0, [], pd.NA, 'duration'])
def test_malformed_duration_flag_has_unknown_descriptor(flag):
    period = PeriodData('q', 'Quarter', '2024-06-30', '2024-04-01', flag)
    assert _period_descriptor(SimpleNamespace(periods=[period]), '2024-06-30') is None


def test_default_getters_do_not_evaluate_optional_period_metadata(monkeypatch):
    import edgar.financials as financials_module

    period = PeriodData('q', 'Q2', '2024-06-30', '2024-04-01', True)
    rendered = _rendered([period], [('us-gaap_Revenues', 'Revenue', [100]),
                                    ('us-gaap_NetIncomeLoss', 'Net income', [20])])
    financials = _financials(income=rendered)

    def unavailable_metadata(*args, **kwargs):
        raise AssertionError('optional metadata must not run during scalar selection')

    monkeypatch.setattr(financials_module, '_period_descriptor', unavailable_metadata)
    assert financials.get_revenue() == 100
    assert financials.get_financial_metrics()['revenue'] == 100


@pytest.mark.parametrize('offset', [None, 1])
def test_overridden_revenue_never_borrows_another_getters_period(offset):
    class CustomRevenue(Financials):
        def get_revenue(self, period_offset=0):
            return 987 if offset is None else super().get_revenue(period_offset=offset)

    periods = [PeriodData('q2', 'Q2', '2024-06-30', '2024-04-01', True),
               PeriodData('q1', 'Q1', '2024-03-31', '2024-01-01', True)]
    rendered = _rendered(periods, [('us-gaap_Revenues', 'Revenue', [100, 200]),
                                   ('us-gaap_NetIncomeLoss', 'Net income', [20, 40])])
    metrics = _financials(income=rendered, cls=CustomRevenue).get_financial_metrics(include_periods=True)
    assert metrics['revenue'] == (987 if offset is None else 200)
    assert metrics['periods']['revenue'] is None
    assert metrics['net_income'] == 20
    assert metrics['periods']['net_income'] == duration('2024-04-01', '2024-06-30')


def test_instance_overridden_getter_has_unknown_period(monkeypatch):
    period = PeriodData('q', 'Q2', '2024-06-30', '2024-04-01', True)
    rendered = _rendered([period], [('us-gaap_Revenues', 'Revenue', [100]),
                                    ('us-gaap_NetIncomeLoss', 'Net income', [20])])
    financials = _financials(income=rendered)
    monkeypatch.setattr(financials, 'get_revenue', lambda: 987)
    metrics = financials.get_financial_metrics(include_periods=True)
    assert metrics['revenue'] == 987
    assert metrics['periods']['revenue'] is None
    assert metrics['periods']['net_income'] == duration('2024-04-01', '2024-06-30')


@pytest.mark.parametrize('method', ['get_free_cash_flow', 'get_operating_cash_flow', 'get_capital_expenditures'])
def test_overridden_cash_flow_getter_makes_derived_period_unknown(method, monkeypatch):
    period = PeriodData('cash', 'Six months', '2024-06-30', '2024-01-01', True)
    rendered = _rendered([period], [
        ('us-gaap_NetCashProvidedByUsedInOperatingActivities', 'Operating cash flow', [50]),
        ('us-gaap_PaymentsToAcquirePropertyPlantAndEquipment', 'Capital expenditures', [10]),
    ], 'CashFlowStatement')
    financials = _financials(cashflow=rendered)
    monkeypatch.setattr(financials, method, lambda period_offset=0: 7)
    metrics = financials.get_financial_metrics(include_periods=True)
    expected = {'get_free_cash_flow': 7, 'get_operating_cash_flow': -3, 'get_capital_expenditures': 43}
    assert metrics['free_cash_flow'] == expected[method]
    assert metrics['periods']['free_cash_flow'] is None
    for name in ('operating_cash_flow', 'capital_expenditures'):
        if method == 'get_' + name:
            assert metrics[name] == 7
            assert metrics['periods'][name] is None
        else:
            assert metrics['periods'][name] == duration('2024-01-01', '2024-06-30')


@pytest.mark.parametrize('name,ratio', [('current_assets', 'current_ratio'),
                                       ('total_liabilities', 'debt_to_assets')])
def test_overridden_ratio_operand_has_unknown_period(name, ratio, monkeypatch):
    period = PeriodData('balance', 'June 30', '2024-06-30')
    rendered = _rendered([period], [
        ('us-gaap_Assets', 'Total assets', [100]),
        ('us-gaap_Liabilities', 'Total liabilities', [60]),
        ('us-gaap_AssetsCurrent', 'Total current assets', [30]),
        ('us-gaap_LiabilitiesCurrent', 'Total current liabilities', [20]),
    ], 'BalanceSheet')
    financials = _financials(balance=rendered)
    monkeypatch.setattr(financials, 'get_' + name, lambda period_offset=0: 10)
    metrics = financials.get_financial_metrics(include_periods=True)
    assert metrics[name] == 10
    assert metrics[ratio] == (0.5 if ratio == 'current_ratio' else 0.1)
    assert metrics['periods'][name] is None
    assert metrics['periods'][ratio] is None


@pytest.mark.parametrize('method', [
    '_collect_financial_metrics', '_render_statement_frame',
    '_get_standardized_concept_by_xbrl', '_get_standardized_concept_value', '_get_concept_value',
])
def test_overridden_shared_selection_path_has_unknown_periods(method, monkeypatch):
    period = PeriodData('q', 'Q2', '2024-06-30', '2024-04-01', True)
    rendered = _rendered([period], [('us-gaap_Revenues', 'Revenue', [100]),
                                    ('us-gaap_NetIncomeLoss', 'Net income', [20])])
    financials = _financials(income=rendered)
    original = getattr(financials, method)
    monkeypatch.setattr(financials, method, lambda *args, **kwargs: original(*args, **kwargs))
    metrics = financials.get_financial_metrics(include_periods=True)
    assert metrics['revenue'] == 100
    assert metrics['net_income'] == 20
    assert all(period is None for period in metrics['periods'].values())


@pytest.mark.parametrize('method,metric', [
    ('_get_revenue', 'revenue'), ('_filed_total_for_statement_period', 'revenue'),
    ('_noncontrolling_interest_share', 'net_income'),
])
def test_overridden_specific_source_path_has_unknown_metric_period(method, metric, monkeypatch):
    period = PeriodData('q', 'Q2', '2024-06-30', '2024-04-01', True)
    rendered = _rendered([period], [('us-gaap_Revenues', 'Revenue', [100]),
                                    ('us-gaap_NetIncomeLoss', 'Net income', [20])])
    financials = _financials(income=rendered)
    original = getattr(financials, method)
    monkeypatch.setattr(financials, method, lambda *args, **kwargs: original(*args, **kwargs))
    metrics = financials.get_financial_metrics(include_periods=True)
    assert metrics[metric] == (100 if metric == 'revenue' else 20)
    assert metrics['periods'][metric] is None


def test_malformed_flag_with_overridden_revenue_preserves_available_value():
    class CustomRevenue(Financials):
        def get_revenue(self, period_offset=0):
            return 987

    period = PeriodData('q', 'Q2', '2024-06-30', '2024-04-01', pd.NA)
    rendered = _rendered([period], [('us-gaap_Revenues', 'Revenue', [100]),
                                    ('us-gaap_NetIncomeLoss', 'Net income', [20])])
    financials = _financials(income=rendered, cls=CustomRevenue)
    assert financials.get_revenue() == 987
    assert financials.get_financial_metrics()['revenue'] == 987
    detailed = financials.get_financial_metrics(include_periods=True)
    assert detailed['revenue'] == 987
    assert detailed['periods']['revenue'] is None
    assert financials._statement_frame_memo is None


def test_metadata_failure_preserves_values_and_unrelated_periods(monkeypatch):
    # This unmapped record is ignored by scalar ordering. Its nullable label
    # cannot establish descriptor equality with the selected, valid column.
    income = _rendered([PeriodData('q', 'Q2', '2024-06-30', '2024-04-01', True),
                        PeriodData('unmapped', pd.NA)], [
        ('us-gaap_Revenues', 'Revenue', [100]),
        ('us-gaap_NetIncomeLoss', 'Net income', [20]),
    ])
    balance = _rendered([PeriodData('balance', 'June 30', '2024-06-30')], [
        ('us-gaap_Assets', 'Total assets', [200]),
        ('us-gaap_Liabilities', 'Total liabilities', [60]),
    ], 'BalanceSheet')
    facts = RawFacts(pd.DataFrame())
    financials = _financials(income=income, balance=balance, facts=facts)
    renders = {'income': 0, 'balance': 0}
    for name, statement in (('income', financials.income_statement()), ('balance', financials.balance_sheet())):
        original = statement.render

        def counted_render(*args, name=name, original=original, **kwargs):
            renders[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(statement, 'render', counted_render)

    metrics = financials.get_financial_metrics(include_periods=True)
    assert metrics['revenue'] == 100
    assert metrics['net_income'] == 20
    assert metrics['periods']['revenue'] is None
    assert metrics['periods']['net_income'] is None
    assert metrics['total_assets'] == 200
    assert metrics['debt_to_assets'] == 0.3
    assert metrics['periods']['total_assets'] == instant('2024-06-30')
    assert metrics['periods']['debt_to_assets'] == instant('2024-06-30')
    assert renders == {'income': 1, 'balance': 1}
    assert facts.calls == 0
    assert financials._statement_frame_memo is None
