import pytest

from research.delta_pinets_catalogue import FMZ_REF
from research.fmz_round7_pine import (
    migrate_legacy,
    pending_pine,
    rejection,
    strip_fmz_wrapper,
    summarize,
    verify_trade,
)


def test_only_still_pending_non_magnifier_pine_is_selected():
    url = f"https://github.com/fmzquant/strategies/blob/{FMZ_REF}/a.md"
    items = [
        {"id": 111, "source": url, "status": "Pending · FMZ Pine compiler research"},
        {"id": 59, "source": url, "status": "Pending · FMZ historical feeds"},
        {"id": 222, "source": url, "status": "Tested · replay"},
        {"id": 333, "source": url, "status": "Framework inputs needed"},
    ]
    assert set(pending_pine(items)) == {111}


def test_only_top_level_fmz_metadata_is_removed():
    pine = (
        '//@version=5\nstrategy("literal /*backtest")\n'
        'strategy.entry("L", strategy.long)\n'
    )
    raw = "/*backtest\nstart: 2024-01-01\nperiod: 15m\n*/\n" + pine
    assert strip_fmz_wrapper(raw) == (pine, True)
    assert strip_fmz_wrapper(pine) == (pine, False)


def test_data_requirements_remain_pending_and_noncode_comments_do_not_block():
    item = {"header_version": ["5"]}
    result = {"isStrategy": True, "diagnostics": [], "security": []}
    assert (
        rejection(item, result, "// timenow used in differently dated variant\n") == ""
    )
    assert "timenow" in rejection(item, result, "timestamp(year(timenow))")
    assert "currency" in rejection(
        item, result, "strategy(title, currency=currency.USD)"
    )
    assert rejection(item, result, "strategy(title, currency=currency.USDT)") == ""
    assert "auxiliary" in rejection(
        item, {**result, "security": [{"timeframe": "D"}]}, ""
    )
    assert "legacy" in rejection({"header_version": ["4"]}, result, "")


def test_validated_cashflow_cumulative_drawdown_uses_source_capital():
    row = {
        "qty": 2,
        "entryPrice": 101,
        "exitPrice": 100,
        "dir": 1,
        "entryBar": 0,
        "exitBar": 1,
        "entryTime": 10,
        "exitTime": 25,
        "commission": 0.23718,
        "profit": -2.23718,
    }
    actual = verify_trade(row, [10, 25])
    assert actual == pytest.approx((25, -2, 0.23718, 0.1206))
    assert summarize([actual], 0, 100)["net_dd_pct"] == pytest.approx(0.0235778)
    with pytest.raises(AssertionError):
        verify_trade({**row, "commission": 0}, [10, 25])


def test_legacy_migration_explicitly_routes_bare_sma():
    before = {
        "id": 9001,
        "source_sha256": "original hash",
        "header_version": ["4"],
    }
    pine = (
        '//@version=4\nstrategy("Legacy averaging")\n'
        "average = sma(close, 2)\n"
        'if crossover(close, average)\n    strategy.entry("L", strategy.long)\n'
        'if crossunder(close, average)\n    strategy.close("L")\n'
    )
    migrated, code = migrate_legacy(before, pine)
    assert migrated["archived_header_version"] == ["4"]
    assert migrated["archived_source_sha256"] == before["source_sha256"]
    assert migrated["header_version"] == ["5"]
    assert b"ta.sma(close, 2)" in code and b"ta.crossover(close, average)" in code
