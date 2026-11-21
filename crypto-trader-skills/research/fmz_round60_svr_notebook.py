"""Reproduce the VNC notebook's frozen linear-SVR recipe on causal BTC/ETH fills."""

from __future__ import annotations

import argparse
import re
from hashlib import sha256 as digest
from math import fsum, isclose, prod
from pathlib import Path
from zipfile import ZipFile

import clarabel
import numpy as np
import pandas as pd
import scipy
from numpy.lib.stride_tricks import sliding_window_view
from scipy import sparse

from research.delta_pinets_catalogue import read, write
from research.fmz_round4_feeds import documents
from research.fmz_round7_magnifier import FMZ_SHA256, date_ms, sha256
from research.fmz_round7_pine import EXECUTION, FEE, summarize
from research.fmz_round12_pine_authored import provider_bars

IDENT = 1045
TRAIN = 1500
LAGS = 20
CAPITAL = 1000.0
DAY = 86_400_000
HOUR = 3_600_000
CLARABEL_WHEEL = "557d5148a4377ae1980b65d00605ae870a8f34f95f0f6a41e04aa6d3edf67148"
START, END, HOURS_START = map(date_ms, ("2020-01-01", "2025-01-01", "2024-01-01"))
PERIOD = "Frozen holdout · Mar–Dec 2024 UTC"


def source_record(archive, baseline):
    assert sha256(archive) == FMZ_SHA256
    (item,) = [row for row in read(baseline)["disposition"] if row["id"] == IDENT]
    assert "pending" in item["status"].lower()
    with ZipFile(archive) as book:
        ((_, _, doc, doc_sha),) = documents(book, {IDENT: item})
    (script,) = re.findall(r"(?ms)^\x60{3}[ \t]*python[ \t]*\r?\n(.+?)^\x60{3}", doc)
    assert all(
        x in script
        for x in (
            'ticker=u"000300"',
            'beginDate=u"20100101"',
            'endDate=u"20180501"',
            "for i in range(1, 21, 1):",
            "hs_close = hs_close.iloc[:, ::-1]",
            "days = 1500",
            "clf_close = svm.SVR(kernel='linear')",
            "f_close_train = hs_close[:days]",
            "clf_close.fit(f_close_train, l_close_train)",
            "l_close_train = hs_close['closeIndex'].shift(-1)[:days]",
            "f_close_test = hs_close[days:]",
            "l_close_test = hs_close['closeIndex'].shift(-1)[days:]",
            "p_close_train = clf_close.predict(f_close_train)",
            "trigger = 1.0",
            "['predicted next close'] > df_close_train['next open'] * trigger",
            "(df_close_train['PL'].shift(1) + 1).cumprod()",
        )
    )
    assert "predict(f_close_test)" not in script
    return item, doc_sha


def tape(root):
    months = tuple(
        f"{year}-{month:02d}" for year in range(2020, 2025) for month in range(1, 13)
    )
    where = {}
    manifest = []
    market = {}
    for line in (root / "cache-names.txt").read_text(encoding="utf-8-sig").splitlines():
        path = Path(line)
        where.setdefault(path.name, []).append(path.with_suffix(""))
    for coin in ("BTC", "ETH"):
        pair = coin + "USDT"
        data = {}
        for interval, period, step in (("1d", months, DAY), ("1h", months[-12:], HOUR)):
            rows = []
            for month in period:
                leaf = f"{pair}-{interval}-{month}.zip"
                receipt = root / "official" / (leaf + ".CHECKSUM")
                expected, label = receipt.read_text(encoding="ascii").split()
                assert label == leaf
                candidates = [
                    *where.get(receipt.name, []),
                    root / leaf,
                    root / "official" / leaf,
                ]
                raw = next(
                    p for p in candidates if p.is_file() and sha256(p) == expected
                )
                rows.extend(provider_bars(raw, step))
                manifest.append(
                    {
                        "url": f"https://data.binance.vision/data/futures/um/monthly/klines/{pair}/{interval}/{leaf}",
                        "sha256": expected,
                        "official_sidecar_sha256": sha256(receipt),
                    }
                )
            data[interval] = rows
        days = data["1d"]
        hours = {row[0]: row for row in data["1h"]}
        assert [row[0] for row in days] == list(range(START, END, DAY))
        assert sorted(hours) == list(range(HOURS_START, END, HOUR)) and len(
            hours
        ) == len(data["1h"])
        executions = {}
        for stamp, op, hi, lo, cl, _ in days[TRAIN + LAGS :]:
            day = [hours[stamp + i * HOUR] for i in range(24)]
            assert [
                day[0][1],
                max(row[2] for row in day),
                min(row[3] for row in day),
                day[-1][4],
            ] == [op, hi, lo, cl]
            assert all(row[1] > 0 for row in day)
            executions[stamp] = (day[1][1], day[-1][1])
        market[coin] = (days, executions)
    assert len(manifest) == 144
    return market, manifest


def fit_primal(train, y, scale, eps=0.1, c=1):
    n, d = train.shape
    center = train.mean(axis=0)
    anchor = np.mean(y)
    t = (train - center) / scale
    r = (y - anchor) / scale
    e = eps / scale
    a = sparse.csc_matrix(np.column_stack((t, np.ones(n))))
    z = sparse.csc_matrix((n, d + 1))
    i = sparse.identity(n, format="csc")
    lhs = sparse.vstack(
        [sparse.hstack([a, -i]), sparse.hstack([-a, -i]), sparse.hstack([z, -i])],
        format="csc",
    )
    bound = np.r_[r + e, -r + e, np.zeros(n)]
    p = sparse.diags(np.r_[np.ones(d) / scale, np.zeros(n + 1)], format="csc")
    q = np.r_[np.zeros(d + 1), np.full(n, c)]
    opts = clarabel.DefaultSettings()
    opts.verbose = False
    opts.time_limit = 20
    opts.max_iter = 120
    opts.tol_gap_abs = 1e-12
    opts.tol_gap_rel = 1e-12
    opts.tol_feas = 1e-12
    opts.static_regularization_constant = 1e-10
    solve = clarabel.DefaultSolver(
        p, q, lhs, bound, [clarabel.NonnegativeConeT(len(bound))], opts
    ).solve()
    w = np.array(solve.x[:d])
    intercept = solve.x[d] * scale + anchor - center @ w
    raw_dual = np.array(solve.z[n : 2 * n]) - np.array(solve.z[:n])
    low, high = -1.0, 1.0
    for _ in range(80):
        shift = (low + high) * 0.5
        u = np.clip(raw_dual - shift, -c, c)
        if np.sum(u) > 0:
            low = shift
        else:
            high = shift
    dcheck = np.linalg.norm((train - center).T @ u - w)
    primal = 0.5 * np.dot(w, w) + c * np.sum(
        np.maximum(np.abs(train @ w + intercept - y) - eps, 0)
    )
    ww = (train - center).T @ u
    dual = float(np.dot(y - anchor, u) - eps * np.abs(u).sum() - 0.5 * np.dot(ww, ww))
    free = (np.abs(u) < c - 1e-7) & (np.abs(u) > 1e-7)
    x = train[free]
    pred = train @ w + intercept
    np.sign(y - pred)
    assert int(free.sum()) == d + 1
    centered_basis = np.column_stack((t, np.ones(n)))
    direct = np.linalg.solve(centered_basis[free], r[free] - e * np.sign(u[free]))
    direct_w = direct[:d]
    direct_b = direct[d] * scale + anchor - center @ direct_w
    v = train @ direct_w + direct_b - y
    assert np.max(np.abs(np.abs(v[free]) - eps)) < 1e-7
    assert np.min(np.abs(np.abs(v[~free]) - eps)) > 1e-5
    adj = np.where(np.abs(v) > eps, -np.sign(v), 0.0)
    adj[free] = 0
    # Full-rank held-at-epsilon active rows and independent stationarity solve.
    system = np.vstack(((train - center).T, np.ones(n)))
    right = np.r_[direct_w, 0] - system @ adj
    adj[free] = np.linalg.solve(system[:, free], right)
    assert np.all(np.abs(adj[free]) < 1 - 1e-6) and np.all(np.abs(adj[free]) > 1e-6)
    assert np.all(np.sign(adj[free]) == np.sign(u[free]))
    assert np.linalg.norm(system @ adj - np.r_[direct_w, 0]) < 1e-7
    d_primal = (
        0.5 * np.dot(direct_w, direct_w) + c * np.maximum(np.abs(v) - eps, 0).sum()
    )
    d_dual = (
        np.dot(y - anchor, adj)
        - eps * np.abs(adj).sum()
        - 0.5 * np.dot(direct_w, direct_w)
    )
    assert abs(d_primal - d_dual) < 1e-6
    return (
        direct_w,
        direct_b,
        {
            "tight_certificate_gap": float(abs(d_primal - d_dual)),
            "support_rank": int(np.linalg.matrix_rank(centered_basis[free])),
            "status": str(solve.status),
            "pstat": solve.r_prim,
            "dstat": solve.r_dual,
            "iterations": solve.iterations,
            "primal": primal,
            "dual": dual,
            "gap": primal - dual,
            "stationarity": dcheck,
            "free": int(free.sum()),
            "rank": int(np.linalg.matrix_rank(np.column_stack((x, np.ones(len(x)))))),
            "max_free_gap": np.max(
                np.abs(np.abs(pred[free] - y[free]) - 0.1), initial=0
            ),
        },
    )


def stock_control(root, coin):
    path = root / f"1045-{coin}-1000000.json"
    stock = read(path)
    assert stock["library"] == "1.9.1" and stock["fit_status"] == 1
    assert stock["n_iter"] == 1_000_000 and stock["params"]["max_iter"] == 1_000_000
    assert stock["params"]["kernel"] == "linear" and stock["params"]["C"] == 1
    assert stock["params"]["epsilon"] == 0.1 and stock["params"]["tol"] == 0.001
    return {
        "sklearn": stock["library"],
        "one_million_iteration_fit_status": stock["fit_status"],
        "one_million_iteration_receipt": sha256(path),
        "stock_wall_clock_control": "Timed out after 50 seconds on this host",
    }


def market_replay(coin, days, executions):
    prices = np.array([row[4] for row in days])
    windows = sliding_window_view(prices, LAGS + 1)
    labels = prices[LAGS + 1 :]
    frame = pd.Series(prices)
    as_authored = pd.DataFrame(
        {f"close-{i}d": frame.shift(i) for i in range(LAGS, -1, -1)}
    ).iloc[LAGS:]
    assert np.array_equal(as_authored.values, windows)
    train = windows[:TRAIN]
    y = labels[:TRAIN]
    heldout = windows[TRAIN:-1]
    assert train.shape == (1500, 21) and heldout.shape == (306, 21)
    assert np.array_equal(frame.shift(-1).iloc[LAGS : LAGS + TRAIN].to_numpy(), y)
    assert y[-1] == heldout[0, -1]
    verified = []
    predictions = []
    for scale in (100, 1000, 10000):
        weights, intercept, receipt = fit_primal(train, y, scale)
        assert receipt["status"] == "Solved" and receipt["support_rank"] == 21 + 1
        assert (
            float(receipt["tight_certificate_gap"]) < 1e-7
            and float(receipt["gap"]) < 2e-6
        )
        linear = heldout @ weights + intercept
        for i, forecast in enumerate(linear, TRAIN + LAGS):
            assert isclose(
                forecast,
                float(prices[i - LAGS : i + 1] @ weights + intercept),
                abs_tol=1e-8,
            )
        predictions.append(linear)
        verified.append(
            {
                "coordinate_scale": scale,
                "weights": weights.tolist(),
                "intercept": intercept,
                **{
                    k: float(v) if isinstance(v, np.floating) else v
                    for k, v in receipt.items()
                },
            }
        )
    base = predictions[1]
    assert all(np.allclose(base, x, rtol=0, atol=1e-7) for x in predictions)
    reference = np.array([row[1] for row in days[TRAIN + LAGS + 1 :]])
    directions = base > reference
    assert all(np.array_equal(x > reference, directions) for x in predictions)
    min_margin = min(abs(base - reference))
    assert min_margin > 0.2
    flows = []
    equities = CAPITAL
    ideal_returns = []
    causal_nocost_returns = []
    for forecast, long, (stamp, opening, _, _, closing, _) in zip(
        base, directions, days[TRAIN + LAGS + 1 :], strict=True
    ):
        if long:
            assert forecast > opening
            buy, sell = executions[stamp]
            quantity = equities / (buy * (1 + FEE + EXECUTION))
            assert isclose(
                quantity * buy * (1 + FEE + EXECUTION), equities, rel_tol=1e-14
            )
            value = quantity * (buy + sell)
            gross = quantity * (sell - buy)
            fee = value * FEE
            friction = value * EXECUTION
            equities += gross - fee - friction
            flows.append((stamp + 23 * HOUR, gross, fee, friction))
            ideal_returns.append(closing / opening)
            causal_nocost_returns.append(sell / buy)
    assert isclose(
        CAPITAL + fsum(gross - fee - cost for _, gross, fee, cost in flows),
        equities,
        abs_tol=1e-9,
    )
    realized = np.array([r[4] for r in days[TRAIN + LAGS + 1 :]])
    return flows, {
        "market": coin + "USDT",
        "train_observations": len(train),
        "heldout_target_days": len(base),
        "last_label_day_open_utc_ms": days[TRAIN + LAGS][0],
        "first_heldout_outcome_day_open_utc_ms": days[TRAIN + LAGS + 1][0],
        "first_decision_after_previous_daily_close": True,
        "predictive_mae_usdt": float(np.mean(np.abs(realized - base))),
        "previous_close_mae_usdt": float(np.mean(np.abs(realized - heldout[:, -1]))),
        "prediction_sha256": digest(base.astype("<f8").tobytes()).hexdigest(),
        "minimum_decision_margin_usdt": float(min_margin),
        "causal_closes": len(flows),
        "hindsight_at_observed_open_and_daily_close_cost_free_multiplier": prod(
            ideal_returns
        ),
        "causal_window_cost_free_multiplier": prod(causal_nocost_returns),
        "end_equity_after_comparison_costs_usdt": equities,
        "certificates": verified,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "baseline", "cache", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    item, source_sha = source_record(args.archive, args.baseline)
    assert clarabel.__version__ == "0.11.1"
    assert (
        sha256(args.cache / "clarabel-0.11.1-cp39-abi3-win_amd64.whl") == CLARABEL_WHEEL
    )
    markets, archives = tape(args.cache)
    shared = {
        "id": IDENT,
        "source": item["source"],
        "source_sha256": source_sha,
        "group": "FMZ notebook · causal BTC/ETH linear SVR adaptation",
        "period": PERIOD,
        "interval": "1d",
        "archive_interval": "1h",
        "currency": "USDT",
        "quote_currency": "USDT",
        "market_data": "Official Binance USD-M daily and joined hourly archives",
        "exit": "Fixed 23:00 UTC hourly opening, following 01:00 UTC delayed entry",
    }
    all_flows = []
    results = []
    findings = []
    for coin, (days, execution) in markets.items():
        flows, detail = market_replay(coin, days, execution)
        detail["stock_solver_control"] = stock_control(args.cache, coin)
        findings.append(detail)
        results.append(
            {**shared, "market": coin + "USDT", **summarize(flows, 0, CAPITAL)}
        )
        all_flows.extend(flows)
    results.append(
        {
            **shared,
            "market": "BTCUSDT + ETHUSDT",
            **summarize(all_flows, 0, 2 * CAPITAL),
        }
    )
    assert [r["trades"] for r in results] == [157, 180, 337]
    write(
        args.out,
        {
            "baseline_coverage_sha256": sha256(args.baseline),
            "archive_sha256": FMZ_SHA256,
            "document_sha256": source_sha,
            "provider_archives": archives,
            "wheel_sha256": CLARABEL_WHEEL,
            "libraries": {
                "clarabel": clarabel.__version__,
                "numpy": np.__version__,
                "scipy": scipy.__version__,
                "pandas": pd.__version__,
            },
            "source_scope": "The original FMZ script loads CSI300 equity data for 2010–2018 and only plots training results. This is a BTC/ETH market-data and heldout decision adaptation. No original equity-account hook was executed.",
            "method": [
                "The feature uses the current and 20 preceding daily closes. The first 1,500 valid samples train once, with a one-day-ahead close label. The last training label is the close of February 29, which is also the first test feature's current close. The first scored outcome is March 1. No outcome in the scored holdout enters the fit.",
                "A time-bounded stock linear SVR did not converge. The reported model solves the same unscaled regularized epsilon-insensitive linear SVR objective, C=1 and epsilon=0.1 quote units, as a quadratic program. Three equivalent centered/scaled coordinates and a direct full-rank free-support primal and dual solve independently reproduce every decision.",
                "The source's prediction-to-next-open comparison is evaluated after the next UTC day's opening quote has become observable. The research fill is delayed to the 01:00 hourly open. The scheduled 23:00 exit uses that same day's 23:00 hourly open as the predeclared closing proxy. Source open-to-daily-close figures are diagnostic only.",
                "Each asset has an independent 1,000 USDT sleeve. A qualifying trade uses the current cost-adjusted sleeve value with an entry cost reserve and fractional base units. Compare gross, fees and execution buffer on those same executed quantities. Two sleeves are pooled. Trading-impact, quantity ticks, margin liquidation and actual perpetual funding are outside this adaptation. This historical result does not qualify any execution route.",
            ],
            "cost_model": {
                "fee_per_side": FEE,
                "execution_buffer_per_side": EXECUTION,
                "starting_capital_per_sleeve_usdt": CAPITAL,
            },
            "fit_proofs": findings,
            "references": [
                "https://www.fmz.com/strategy/112188",
                "https://github.com/binance/binance-public-data",
                "https://scikit-learn.org/stable/modules/generated/sklearn.svm.SVR.html",
                "https://clarabel.org/stable/python/getting_started_py/",
            ],
            "coverage": [
                [
                    IDENT,
                    "Tested · causal BTC/ETH adaptation of FMZ SVR notebook",
                    "Frozen 1,500-training-row and 20-lag linear SVR verified on 306 heldout days per asset with causal hour-open executions and 337 closed lots. Results cover the crypto adaptation only.",
                ]
            ],
            "results": results,
        },
    )
    print(
        "Verified 144 archives, six numerical certificates and 337 closed lots across three workbook rows."
    )


if __name__ == "__main__":
    main()
