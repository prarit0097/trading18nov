"""Replay remaining non-magnifier FMZ Pine on pinned historical archives."""

import argparse
import re
from base64 import b64encode
from hashlib import sha512
from itertools import pairwise
from math import floor, isclose, isfinite
from pathlib import Path
from shutil import copy2, copytree
from tarfile import open as open_tar

from research.delta_pine_liquid_replay import MARKETS, checksum
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_pinets_migration import VERSION
from research.delta_strategy_replay import ROOT
from research.fmz_round4_compile import local_state, pre_migration
from research.fmz_round6_pine import (
    archival_items,
    prepare_feed,
    request_tokens,
    source_edits,
)
from research.fmz_round6_pine import finalize as finish_sessions
from research.nonpine_round4_metrics import metrics

BASE = "36bf6943a058b829c433b45f579830a3bc5193c1"
LEDGER = ROOT / "remaining-backtest-round6-coverage.json"
PINE6 = ROOT / "fmz-round6-pine.json"
FEEDS = ROOT / "fmz-round5-feeds.json"
BATCH = "followup-refs-1"
MAGNIFIER = {59, 3254, 3843, 4167, 4601, 5540, 4721, 5117, 5514, 5520}
SESSIONS = {1089, 1252, 1361, 2953}
BACKTEST = re.compile(r"(?m)^[ \t]*/\*backtest\r?\n[\s\S]*?^\*/[ \t]*\r?\n")
UNPROVEN = re.compile(
    r"\b(?:timenow|backtest_fill_limits_assumption|calc_on_order_fills|"
    r"calc_on_every_tick|use_bar_magnifier|strategy\.risk|math\.random|"
    r"syminfo\.(?:sector|industry|country|timezone|session|expiration_date))\b"
)
FEE = 0.00059
EXECUTION = 0.0003
GROUP = "FMZ Pine · Piner dual-backend OHLC replay"
PINER_VERSION = "0.13.0"
PINER_PIN = "wyZp7irvRiBBoSkLINDqufqRsc6rZH7uoIwk1dZHlKIkLBz+fpeBi7mbgumRxiyBNZf2dN6YmiE6swRhWE9wNw=="


def pending_pine(disposition):
    return {
        item["id"]: item
        for item in disposition
        if FMZ_REF in item["source"]
        and item["id"] not in MAGNIFIER
        and item["status"].startswith("Pending")
        and any(
            word in item["status"]
            for word in ("Pine", "historical", "intrabar", "feeds")
        )
    }


def strip_fmz_wrapper(code):
    output, count = BACKTEST.subn("", code, count=1)
    return output, bool(count)


def migrate_legacy(item, source):
    archived, specific = source_edits(source, item["id"])
    archived, state = pre_migration(archived)
    code, _, migration, fill, clock, delayed = prepare_feed(
        item["id"], archived, advanced=True, late=True
    )
    if fill or clock or delayed or list(request_tokens(code)):
        raise ValueError(
            "Migration still needs data or execution beyond one chart-bar stream"
        )
    version = VERSION.search(code)
    if not version or version[1] != "5":
        raise ValueError("Pine v5 migration was not established")
    raw = code.encode("utf-8")
    return {
        **item,
        "archived_source_sha256": item["source_sha256"],
        "archived_header_version": item["header_version"],
        "source_sha256": checksum(raw),
        "header_version": [version[1]],
        "repairs": {**specific, **state, **migration},
    }, raw


def stage_legacy(prior, work):
    audit = read(prior / "archive-audit.json")
    assert audit["baseline_commit"] == BASE
    assert audit["prior_audit_sha256"] == checksum(LEDGER.read_bytes())
    work.mkdir(parents=True, exist_ok=True)
    candidates, reasons = [], {}
    for item in read(prior / "compile-input.json"):
        ident = item["id"]
        if item["header_version"] not in (["2"], ["3"], ["4"]) or ident in SESSIONS:
            continue
        source = (prior / f"source-{ident}.pine").read_bytes()
        assert checksum(source) == item["source_sha256"]
        assert (
            item["document_sha256"] == audit["evidence"][str(ident)]["document_sha256"]
        )
        try:
            adapted, raw = migrate_legacy(item, source.decode("utf-8"))
        except (ValueError, AssertionError) as error:
            reasons[ident] = str(error) or "Archived source failed a migration premise"
            continue
        candidates.append(adapted)
        (work / f"source-{ident}.pine").write_bytes(raw)
    copy_runtime(prior, work)
    write(work / "compile-input.json", candidates)
    write(
        work / "archive-audit.json",
        {
            **audit,
            "migration_variant": True,
            "migration_blockers": reasons,
            "scope": sorted({*reasons, *(item["id"] for item in candidates)}),
        },
    )
    print(
        f"Staged {len(candidates)} Pine v5 migrations. {len(reasons)} require more source or runtime support."
    )


def copy_runtime(prior, work):
    for name in (
        "chart-bars.json",
        "node.exe",
        f"piner-{PINER_VERSION}.tgz",
        "probe.cjs",
        "sandbox.ps1",
    ):
        copy2(prior / name, work / name)
    if not (work / "package").exists():
        copytree(prior / "package", work / "package")
    copy2(Path(__file__).with_suffix(".mjs"), work / "study.mjs")


def stage_panel(prior, work):
    ident = 2999
    audit = read(prior / "archive-audit.json")
    [item] = [
        item for item in read(prior / "compile-input.json") if item["id"] == ident
    ]
    source = (prior / f"source-{ident}.pine").read_bytes()
    assert checksum(source) == item["source_sha256"]
    assert item["document_sha256"] == audit["evidence"][str(ident)]["document_sha256"]
    marker = "// Please copy the code below and paste it into the strategy"
    active, match, panel = source.decode("utf-8").partition(marker)
    assert match and len(re.findall(r"\bstrategy\.entry\(", active)) == 2
    assert set(re.findall(r"\bstrategy\.(\w+)", panel)) <= {
        "equity",
        "closedtrades",
        "netprofit",
    }
    assert not re.search(r"\b(?:longCondition|shortCondition)\b", panel)
    raw = active.encode("utf-8")
    work.mkdir(parents=True, exist_ok=True)
    copy_runtime(prior, work)
    (work / f"source-{ident}.pine").write_bytes(raw)
    write(
        work / "compile-input.json",
        [
            {
                **item,
                "archived_source_sha256": item["source_sha256"],
                "source_sha256": checksum(raw),
                "archived_header_version": item["header_version"],
                "repairs": {
                    "Trailing standalone performance panel excluded from historical broker replay": 1
                },
            }
        ],
    )
    write(
        work / "archive-audit.json",
        {**audit, "display_panel_variant": True, "scope": [ident]},
    )


def verify_panel(case, bars):
    prices = [bar["close"] for bar in bars]
    prior = None
    fills = []
    for i in range(27, len(prices) - 1):
        current = sum(prices[i - 13 : i + 1]) / 14 - sum(prices[i - 27 : i + 1]) / 28
        if prior is not None and current > 0 >= prior:
            fills.append((1, i + 1))
        elif prior is not None and current < 0 <= prior:
            fills.append((-1, i + 1))
        prior = current
    assert case["unsettled"] == bool(fills)
    assert len(case["closed"]) == max(0, len(fills) - 1)
    for trade, ((direction, entry), (_, exit)) in zip(
        case["closed"], pairwise(fills), strict=True
    ):
        assert [trade[key] for key in ("dir", "entryBar", "exitBar")] == [
            direction,
            entry,
            exit,
        ]
        assert trade["entryPrice"] == bars[entry]["open"]
        assert trade["exitPrice"] == bars[exit]["open"]
        lot_step = 0.001
        expected_qty = floor(1000 / trade["entryPrice"] / lot_step) * lot_step
        assert isclose(trade["qty"], expected_qty, rel_tol=1e-9)


def stage(archive, prior_feeds, work):
    rows = pending_pine(read(LEDGER)["disposition"])
    fifth = read(FEEDS)
    sixth = read(PINE6)
    archive_digest = checksum(archive.read_bytes())
    assert archive_digest == fifth["source_archive_sha256"]
    evidence, unique = archival_items(archive, rows)
    for ident, entry in evidence.items():
        assert sixth["archive_evidence"][ident] == entry
    work.mkdir(parents=True, exist_ok=True)
    candidates = []
    for ident, (code, digest, interval) in unique.items():
        cleaned, removed = strip_fmz_wrapper(code)
        raw = cleaned.encode("utf-8")
        (work / f"source-{ident}.pine").write_bytes(raw)
        candidates.append(
            {
                "id": ident,
                "name": rows[ident]["name"],
                "document_sha256": digest,
                "source_sha256": checksum(raw),
                "archived_interval": interval,
                "header_version": evidence[str(ident)]["pine_versions"],
                "fmz_wrapper_removed": removed,
            }
        )
    candle_path = prior_feeds / BATCH / "candles.json"
    candle_digest = checksum(candle_path.read_bytes())
    assert candle_digest == fifth["batches"][BATCH]["candles.json"]
    used = {}
    for period, fields in read(candle_path).items():
        used[period] = {market: fields[market] for market in MARKETS}
    write(work / "compile-input.json", candidates)
    write(work / "chart-bars.json", used)
    write(
        work / "archive-audit.json",
        {
            "baseline_commit": BASE,
            "prior_audit_sha256": checksum(LEDGER.read_bytes()),
            "source_archive_sha256": archive_digest,
            "upstream_input_sha256": candle_digest,
            "chart_input_sha256": checksum((work / "chart-bars.json").read_bytes()),
            "scope": sorted(rows),
            "evidence": evidence,
        },
    )
    print(
        f"Audited {len(rows)} archive entries and staged {len(candidates)} single-order Pine sources."
    )


def rejection(item, result, code):
    if result.get("error"):
        detail = result["error"].splitlines()[-1].strip()
        return f"Piner compiler rejected the archived source. {detail}"
    if not result["isStrategy"]:
        return "Piner classified the archived declaration as an indicator."
    if result["diagnostics"]:
        detail = result["diagnostics"][0]["message"]
        return f"Piner emitted a semantic diagnostic. {detail}"
    if item["header_version"] not in (["5"], ["6"]):
        return "Piner compiled it but the original legacy Pine semantics remain unverified."
    if result["security"]:
        return "Piner requires independently matched auxiliary symbols and timeframes."
    executable = re.sub(r"(?m)//.*$", "", code)
    blocked = UNPROVEN.search(executable)
    if blocked:
        return f"No equivalent historical behavior for {blocked[0]} is qualified in this lane."
    if re.search(r"\bcurrency\s*=\s*(?!currency\.USDT\b)\S+", executable):
        return "The archive declares an account currency other than USDT."
    return ""


def eligible(work):
    compilation = {row["id"]: row for row in read(work / "compile-results.json")}
    inputs = read(work / "compile-input.json")
    assert set(compilation) == {item["id"] for item in inputs}
    reasons = {}
    for item in inputs:
        ident = item["id"]
        code = (work / f"source-{ident}.pine").read_bytes()
        assert checksum(code) == item["source_sha256"]
        reason = rejection(item, compilation[ident], code.decode("utf-8"))
        if reason:
            reasons[ident] = reason
    return [item for item in inputs if item["id"] not in reasons], reasons


def select(work):
    candidates, _ = eligible(work)
    write(work / "replay-input.json", candidates)
    print("Prepared Pine source IDs:", *(item["id"] for item in candidates))


def verify_trade(trade, times):
    qty, entry, exit = (trade[key] for key in ("qty", "entryPrice", "exitPrice"))
    assert all(isfinite(x) and x > 0 for x in (qty, entry, exit))
    assert trade["dir"] in {-1, 1}
    assert 0 <= trade["entryBar"] <= trade["exitBar"] < len(times)
    assert times[trade["entryBar"]] == trade["entryTime"]
    assert times[trade["exitBar"]] == trade["exitTime"]
    assert trade["entryTime"] <= trade["exitTime"]
    turnover = (entry + exit) * qty
    fee, gross = turnover * FEE, (exit - entry) * qty * trade["dir"]
    assert isclose(trade["commission"], fee, rel_tol=1e-9, abs_tol=1e-9)
    assert isclose(trade["profit"], gross - fee, rel_tol=1e-9, abs_tol=1e-9)
    return trade["exitTime"], gross, fee, turnover * EXECUTION


def summarize(cashflows, unsettled, capital):
    assert isfinite(capital) and capital > 0
    ratio = capital / 10_000
    normalized = [
        (timestamp, gross / ratio, fees / ratio, execution / ratio)
        for timestamp, gross, fees, execution in cashflows
    ]
    result = metrics(normalized, unsettled)
    for key in (
        "gross",
        "after_fees",
        "net",
        "fees",
        "execution",
        "gross_dd",
        "fee_dd",
        "net_dd",
    ):
        result[key] *= ratio
    return result


def finalize(work, output):
    audit = read(work / "archive-audit.json")
    assert audit["baseline_commit"] == BASE
    assert audit["prior_audit_sha256"] == checksum(LEDGER.read_bytes())
    assert audit["source_archive_sha256"] == read(FEEDS)["source_archive_sha256"]
    assert audit["chart_input_sha256"] == checksum(
        (work / "chart-bars.json").read_bytes()
    )
    isolation = read(work / "isolation-probe.json")
    assert isolation == {"privateDenied": True, "networkDenied": True}
    fixture = read(work / "fixture.json")
    assert (
        fixture["verified"]
        and fixture["bothBackendsEqual"]
        and len(fixture["sample"]) == 3
        and fixture["feesPerSide"] == FEE
    )
    fixture_times = [1_767_225_600_000 + index * 900_000 for index in range(7)]
    assert [verify_trade(row, fixture_times)[1] for row in fixture["sample"]] == [
        18,
        6,
        20,
    ]
    assert (work / "replay.exit").read_text().strip() == "0"
    study = Path(__file__).with_suffix(".mjs").read_bytes()
    assert (work / "study.mjs").read_bytes() == study
    package = work / f"piner-{PINER_VERSION}.tgz"
    assert b64encode(sha512(package.read_bytes()).digest()).decode("ascii") == PINER_PIN
    with open_tar(package, "r:gz") as distribution:
        packaged = distribution.extractfile("package/dist/index.js").read()
    assert (work / "package/dist/index.js").read_bytes() == packaged
    candidates, reasons = eligible(work)
    assert candidates == read(work / "replay-input.json")
    original = pending_pine(read(LEDGER)["disposition"])
    ledger = {
        ident: original[ident] for ident in audit["scope"] if ident not in SESSIONS
    }
    group = GROUP
    if audit.get("migration_variant"):
        group += " · source-audited Pine v5 migration"
        reasons.update(
            {
                int(ident): reason
                for ident, reason in audit["migration_blockers"].items()
            }
        )
    if audit.get("display_panel_variant"):
        group += " · display-only panel excluded"
    outcomes = {row["id"]: row for row in read(work / "replay-receipts.json")}
    assert set(outcomes) == {item["id"] for item in candidates}
    charts = read(work / "chart-bars.json")
    clock = {
        (period, market): [bar["openTime"] for bar in candles]
        for period, markets in charts.items()
        for market, (candles,) in markets.items()
    }
    tested, results, attempts = {}, [], {}
    for item in candidates:
        ident = item["id"]
        outcome = outcomes[ident]
        if outcome.get("error"):
            reasons[ident] = outcome["error"]
            continue
        assert outcome["source_sha256"] == item["source_sha256"]
        capital = outcome["settings"]["initialCapital"]
        assert {
            (case["period"], case["market"]) for case in outcome["cases"]
        } == clock.keys()
        assert len(outcome["cases"]) == len(clock)
        flow, unsettled = {}, {}
        for case in outcome["cases"]:
            key = case["period"], case["market"]
            if audit.get("display_panel_variant"):
                verify_panel(case, charts[key[0]][key[1]][0])
            flow[key] = [verify_trade(trade, clock[key]) for trade in case["closed"]]
            unsettled[key] = case["unsettled"]
            assert isinstance(unsettled[key], int) and unsettled[key] >= 0
        common = {
            "id": ident,
            "name": item["name"],
            "group": group,
            "interval": "15m",
            "archive_interval": item["archived_interval"],
            "source": ledger[ident]["source"],
            "source_sha256": item["document_sha256"],
            "executed_source_sha256": item["source_sha256"],
            "quote_currency": "USDT",
            "exit": "Archived Pine exits",
            "market_data": "Binance USD-M historical candles",
        }
        if audit.get("migration_variant") or audit.get("display_panel_variant"):
            common.update(
                {
                    "pine_source_version": item["archived_header_version"][0],
                    "archived_source_sha256": item["archived_source_sha256"],
                    "repairs": item["repairs"],
                }
            )
        for period in charts:
            for market in (*MARKETS, "BTCUSDT + ETHUSDT"):
                pooled = market not in MARKETS
                keys = [(period, name) for name in (MARKETS if pooled else (market,))]
                result = summarize(
                    [move for key in keys for move in flow[key]],
                    sum(unsettled[key] for key in keys),
                    capital * len(keys),
                )
                results.append({**common, **result, "period": period, "market": market})
        closes = sum(map(len, flow.values()))
        tested[ident] = [
            ident,
            f"Tested · {group}" + ("" if closes else ", no closes"),
            "Both Piner execution backends agreed on all fills. Closed accounting independently reconciled.",
        ]
        attempts[ident] = {"closed": closes, "settings": outcome["settings"]}
    write(
        output,
        {
            **audit,
            "isolation_probe": isolation,
            "fixture": fixture,
            "attempts": attempts,
            "piner_version": PINER_VERSION,
            "piner_npm_sha512": PINER_PIN,
            "piner_bundle_sha256": checksum(packaged),
            "historical_model": {
                "chart_interval": "15m",
                "chart_data": "Pinned Binance USD-M BTCUSDT and ETHUSDT half-open UTC candles",
                "fills": "Piner broker emulator with explicit source settings retained, apart from normalized commission",
                "unspecified_settings": "10,000 USDT initial equity; 1,000 USDT cash when sizing is unspecified; Pine margin defaults by version",
                "drawdown": "Closed equity from source starting capital; pooled drawdown sums two equal independently funded sleeves",
                "scope": "Historical OHLC runs distinct from archived FMZ exchange/candle settings. Dual backend agreement does not establish TradingView parity.",
            },
            "cost_model": {"fee_per_side": FEE, "execution_buffer_per_side": EXECUTION},
            "artifacts": {
                name: checksum((work / name).read_bytes())
                for name in (
                    "study.mjs",
                    "compile-results.json",
                    "replay-receipts.json",
                    "replay-input.json",
                )
            },
            "coverage": [
                tested.get(
                    ident, [ident, item["status"], reasons.get(ident, item["reason"])]
                )
                for ident, item in ledger.items()
            ],
            "results": results,
        },
    )
    print(f"Verified {len(tested)} strategies and {len(results)} result rows.")


def sessions(archive, previous, output):
    finish_sessions(archive, previous, output)
    current = pending_pine(read(LEDGER)["disposition"])
    report = read(output)
    assert {row[0] for row in report["coverage"]} == SESSIONS <= current.keys()
    assert set(report["scoped_ids"]) == SESSIONS
    report["previous_baseline_commit"] = report["baseline_commit"]
    report["baseline_commit"] = BASE
    report["resume_evidence"] = "Verified previously unpublished terminal replay."
    write(output, report)


def stage_zigzag(archive, prior, work):
    ident = 2953
    previous = read(prior / "preflight.json")
    assert checksum(archive.read_bytes()) == previous["source_archive_sha256"]
    rows = pending_pine(read(LEDGER)["disposition"])
    evidence, _ = archival_items(archive, {ident: rows[ident]})
    assert previous["archive_evidence"][str(ident)] == evidence[str(ident)]
    [item] = [
        item for item in read(prior / "pine-1/candidates.json") if item["id"] == ident
    ]
    assert previous["batches"]["pine-1"] == [1089, 2953]
    assert item["hash"] == evidence[str(ident)]["document_sha256"]
    published = read(ROOT / "fmz-round7-pine-sessions.json")["attempts"][str(ident)]
    assert published["migrated_source_sha256"] == checksum(item["code"].encode())
    item["code"], count = local_state(item["code"], {"zigzag": {"_direction": "int"}})
    assert count == 1
    item["repairs"][
        "ZigZag function-scoped integer direction retains its prior chart value"
    ] = count
    work.mkdir(parents=True)
    for name in (
        "engine.mjs",
        "node.exe",
        "run.cjs",
        "fixture-pine-node.exit",
        "session-check-node.exit",
    ):
        copy2(prior / name, work / name)
    probe = (prior / "probe.cjs").read_text(encoding="utf-8")
    old = 'catch(e){return e.code==="EACCES"||e.code==="EPERM"}'
    assert probe.count(old) == 1
    (work / "probe.cjs").write_text(
        probe.replace(old, old[:-1] + '||e.code==="ERR_ACCESS_DENIED"}'),
        encoding="utf-8",
    )
    for name in ("fixture-pine", "session-check"):
        copytree(prior / name, work / name)
    batch = work / "pine-1"
    batch.mkdir()
    for name in ("worker.mjs", "candles.json"):
        copy2(prior / "pine-1" / name, batch / name)
    write(batch / "candidates.json", [item])
    write(
        work / "preflight.json",
        {
            **previous,
            "archive_evidence": evidence,
            "batches": {"pine-1": [ident]},
            "scoped_ids": [ident],
        },
    )


def finish_zigzag(archive, work, output):
    finish_sessions(archive, work, output)
    report = read(output)
    assert {row[0] for row in report["coverage"]} == {2953}
    report["previous_baseline_commit"] = report["baseline_commit"]
    report["baseline_commit"] = BASE
    write(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name, names, action in (
        ("stage", ("archive", "prior_feeds", "work"), stage),
        ("stage-legacy", ("prior", "work"), stage_legacy),
        ("stage-panel", ("prior", "work"), stage_panel),
        ("sessions", ("archive", "previous", "output"), sessions),
        ("stage-zigzag", ("archive", "prior", "work"), stage_zigzag),
        ("finish-zigzag", ("archive", "work", "output"), finish_zigzag),
        ("select", ("work",), select),
        ("finalize", ("work", "output"), finalize),
    ):
        command = sub.add_parser(name)
        for argument in names:
            command.add_argument(argument, type=Path)
        command.set_defaults(run=action)
    args = vars(parser.parse_args())
    args.pop("action")
    args.pop("run")(**args)


if __name__ == "__main__":
    main()
