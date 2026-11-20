import pytest

from research.fmz_round6_pine import (
    chart_symbol_helpers,
    float_steps,
    inline_historical_helper,
    requested_frames,
)


def test_fractional_step_only_changes_named_numeric_input():
    text = "risk = input(2, minval=0.1)\nlen = input(8, step=1)\nlimit = input(1, step=0.5)\n"
    updated, count = float_steps(text, {"risk", "limit"})
    assert count == 2
    assert updated == text.replace("risk = input(", "risk = input.float(").replace(
        "limit = input(", "limit = input.float("
    )
    with pytest.raises(ValueError):
        float_steps(text, {"len"})


def test_reference_retention_is_conservative_for_variable_frames():
    assert requested_frames(
        'request.security(syminfo.tickerid, "1D", close)\nrequest.security(syminfo.tickerid,timeframe.period,open)'
    ) == {"D", "15"}
    assert (
        requested_frames("request.security(syminfo.tickerid, timeframeInput, close)")
        is None
    )
    assert requested_frames("x = ta.sma(close, 12)") == set()


def test_chart_helper_requires_all_call_sites_to_use_chart_symbol():
    script = 'req(id, frame) => request.security(id, frame, close)\na = req(syminfo.tickerid, "D")\n'
    amended, count = chart_symbol_helpers(script, {"req": "id"})
    assert count == 1
    assert "request.security(syminfo.tickerid, frame, close)" in amended
    with pytest.raises(ValueError, match="external or nonstandard"):
        chart_symbol_helpers(
            script + 'b = req("EXCHANGE:EXTERNAL", "D")\n', {"req": "id"}
        )


def test_historical_helper_retains_the_outer_chart_bar_delay():
    script = (
        "f_security(_sym, _res, _src, _rep) => request.security(_sym, _res, _src[not _rep and barstate.isrealtime ? 1 : 0])[_rep or barstate.isrealtime ? 0 : 1]\n"
        'h = f_security(syminfo.tickerid, "D", high, false)\n'
        'c = f_security(syminfo.tickerid, "1D", close, false)\n'
    )
    amended, count = inline_historical_helper(script, "f_security")
    assert count == 2
    assert 'h = request.security(syminfo.tickerid, "D", high)[1]' in amended
    assert 'c = request.security(syminfo.tickerid, "1D", close)[1]' in amended
    with pytest.raises(ValueError):
        inline_historical_helper(
            script.replace("high, false", "high, true"), "f_security"
        )
