"""Audit unresolved Pine and replay source-backed repairs with pinned Binance data."""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

from research.delta_pine_compatibility import plain_pine, rsi_calls
from research.delta_pine_followup import patch, rename_global
from research.delta_pine_liquid_replay import MARKETS, WINDOWS, checksum
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import FMZ_REF, read, write
from research.delta_pinets_migration import (
    VERSION,
    MigrationBlocked,
    arguments,
    keyword,
    tokens,
)
from research.delta_strategy_replay import ROOT
from research.fmz_intrabar_replay import constant_capital
from research.fmz_marketdata_replay import request_fields, script_blocks
from research.fmz_pine_remaining import ACTIVE_ORDER, BLOCKS
from research.fmz_round3_feed_fixture import prepare as prepare_fixture
from research.fmz_round3_liquid_feeds import reconcile
from research.fmz_round3_symbol_feeds import verified_source
from research.fmz_round3_timeframe_feeds import read_receipts
from research.fmz_round4_compile import eager_legacy_calls, pre_migration
from research.fmz_round4_feeds import (
    artifact_hashes,
    clock_worker,
    documents,
    fixture_receipts,
    normalize,
)
from research.fmz_round5_compile import duplicate_bool, named_history, replace
from research.fmz_round5_feeds import prepare_source as prepare_feed
from research.fmz_round5_feeds import session_fixture, verify_session_fixture

BASE = "91ad53db55d0a62ced88ce239d3200fc2029980a"
LEDGER = ROOT / "remaining-backtest-round5-coverage.json"
FEEDS = ROOT / "fmz-round5-feeds.json"
SOURCE_BATCH = "followup-refs-1"
TIME_LIMIT = 135_000
HEAP_MB = 1152
KNOWN_STOPS = {
    "time or memory budget exceeded",
    "compile or execute",
    "exact migrated source",
}
FRACTIONAL = {
    1329: {"risk"},
    2260: {"risk"},
    2425: {"risk"},
    2509: {"stopMultiplyer", "reentryStopMultiplyer"},
    3737: {"supertrendMult", "riskReward"},
    4480: {"BBStdDev"},
    5694: {"supertrendMult"},
}
DONCHIAN = {1329, 1472, 1473, 2260, 2425, 3481, 4858}
RSI = {
    747,
    1251,
    1562,
    2253,
    2514,
    2708,
    2794,
    2796,
    2909,
    2974,
    4098,
    4881,
    5211,
    5457,
}
SPECIFIC = {1728, 2855, 2864, 3458, 4739, 5297}
INDICATOR_CASES = {
    98,
    183,
    192,
    239,
    241,
    351,
    395,
    410,
    487,
    607,
    608,
    656,
    672,
    721,
    922,
    935,
    939,
    977,
    1105,
}
IMPLICIT_CASES = {2408, 2444, 2604, 4671}
CHART_HELPERS = {
    108: {"f_securitys": "_ticker"},
    591: {"callRSI": "id", "getStochastic": "id"},
    1586: {"nrp_funct": "_symbol"},
    1951: {"f_security": "_symbol"},
    2049: {"f_secureSecurity": "_symbol"},
    3307: {"f_sec": "_market"},
    3568: {"securityNoRepaint": "sym"},
    4054: {"callRSI": "id", "getStochastic": "id"},
    4063: {
        f"f_secureSecurity_{a}_{b}": "_symbol"
        for a in ("on", "off")
        for b in ("on", "off")
    },
    4106: {"f_Security": "_symbol"},
    4798: {"RequestSecurity_NonRP": "_market"},
    4915: {"f_secureSecurity": "_symbol"},
    5646: {"f_secureSecurity": "_symbol"},
}
INLINE_PREVIOUS = {1600: "f_secureSecurity"}
INLINE_HISTORICAL = {3366: "f_security", 5117: "f_security", 5514: "f_security"}
SESSION_CASES = {1089, 1252, 1361, 2953}
ADDITIONAL_REPAIRS = {350, 3458, 3749, 5588} | SESSION_CASES
EXTERNAL_REQUIREMENTS = {
    171: "Archived request is GLASSNODE:USDT_SUPPLY daily. The exact historical on-chain series is absent from the pinned inputs.",
    1013: "Archived USOIL daily and 240-minute requests need the original instrument mapping and session calendar.",
    1988: "Requests NSE:NIFTY and a separate unresolved symbol named swap. Both historical feeds must be identified.",
    2248: "Archived USOIL daily and 240-minute requests need the original instrument mapping and session calendar.",
    2637: "Archived SPY daily benchmark requires a verified equity data provider and the same split/session policy.",
    2833: "Archived request is FX:EURUSD on five-minute bars. Its original source and alignment remain unverified.",
    3315: "The VIX request uses the full chart interval. Daily VIX observations would omit intra-session values.",
    3424: "Archived NIFTY50 reference needs a verified index source, session, and date alignment.",
    3534: "Request uses a bare swap alias. The original market behind the alias was not established.",
    3828: "A bare SWAP alias feeds a variable named btcDom. Its underlying index or contract is not identified.",
    3845: "Archived NGAS daily and 240-minute requests require the exact gas instrument, roll rule and session.",
    4021: "Archived NGAS daily and 240-minute requests require the exact gas instrument, roll rule and session.",
    4699: "Archived request is USI:PCC daily. No exact source-pinned historical put/call series is present.",
    4802: "Archived default is INTOTHEBLOCK:BTC_HASHRATE daily. Another vendor's estimate would change the signals.",
    4805: "Archived setting is titled Bitfinex Short Symbol but defaults to BTC_USDT:swap. The intended position series remains ambiguous.",
    4868: "Archived VIX daily benchmark needs the verified source series and session alignment on these replay windows.",
    4957: "Archived default is CRYPTOCAP:TOTAL2. A BTC or ETH price series cannot replace the market-cap index.",
    5114: "Archived FX conversion branches cover specified fiat quote currencies and omit the USDT chart quote. Position sizing cannot be verified.",
    5617: "Archived BMFBOVESPA:IBOV historical benchmark and the corresponding session calendar are absent from the pinned inputs.",
    5745: "The saved VIX Symbol default is swap, providing no evidence of an exact VIX feed or equivalent archive.",
}
FIXED_PERPETUAL = {3106, 3514, 4575}
FIXED_MARKET = FIXED_PERPETUAL | {4645, 5175}
DIAGNOSTIC_FLOAT = {
    1946: {"initial_balance"},
    2914: {"TopBand", "LowBand"},
    3667: {"initial_balance"},
    4645: {"longtp", "shorttp", "capperc"},
    5175: {"capperc"},
    5211: {"long_tp1_inp", "multiplier"},
    5326: {"st_mult"},
}
DIAGNOSTIC = (
    {239, 351, 356, 388, 418, 421, 526, 939, 4106, 4130, 4283, 5190, 5646}
    | DIAGNOSTIC_FLOAT.keys()
    | FIXED_MARKET
)


def scoped(ledger=LEDGER, *, lane="main"):
    extras = (
        INDICATOR_CASES
        | IMPLICIT_CASES
        | CHART_HELPERS.keys()
        | INLINE_PREVIOUS.keys()
        | INLINE_HISTORICAL.keys()
        | ADDITIONAL_REPAIRS
    )
    unresolved = {
        row["id"]: row
        for row in read(ledger)["disposition"]
        if FMZ_REF in row["source"] and not row["status"].startswith("Tested")
    }
    targets = {"extra": extras, "diagnostic": DIAGNOSTIC}.get(lane)
    if targets is not None:
        return {ident: row for ident, row in unresolved.items() if ident in targets}
    return {
        ident: row
        for ident, row in unresolved.items()
        if any(
            term in row["status"]
            for term in ("Pine", "historical", "intrabar", "compile and feeds")
        )
    }


def float_steps(code, names):
    edits = []
    parts = tokens(code)
    start_indices = {part.start(): i for i, part in enumerate(parts)}
    for name in sorted(names):
        matches = list(
            re.finditer(rf"(?m)^{name}[ \t]*=[ \t]*(input(?:\.int)?)[ \t]*\(", code)
        )
        if len(matches) != 1:
            raise MigrationBlocked(f"Archived input {name} is absent or duplicated")
        match = matches[0]
        index = start_indices[match.end() - 1]
        _, spans = arguments(parts, index)
        fields = {
            key: "".join(values)
            for key, values in (keyword(parts, span) for span in spans)
            if key
        }
        if not any(
            re.fullmatch(r"0\.\d+", fields.get(k, ""))
            for k in ("step", "minval", "maxval")
        ):
            raise MigrationBlocked(
                f"No fractional bound or step for archived input {name}"
            )
        edits.append((*match.span(1), "input.float"))
    return patch(code, edits), len(edits)


def requested_frames(code):
    frames = set()
    parts = tokens(code)
    for index, part in enumerate(parts[:-1]):
        if part.group() != "security" or parts[index + 1].group() != "(":
            continue
        _, spans = arguments(parts, index + 1)
        value = request_fields(parts, spans).get("timeframe", ("", None))[0]
        if value == "timeframe.period":
            value = "15"
        elif re.fullmatch(r"['\"][0-9]*[DWM]?['\"]", value):
            value = value[1:-1] or "15"
        else:
            return None
        frames.add({"1D": "D", "1W": "W"}.get(value, value))
    return frames


def request_tokens(code):
    parts = tokens(code)
    for index, part in enumerate(parts[:-1]):
        if part.group() == "security" and parts[index + 1].group() == "(":
            _, spans = arguments(parts, index + 1)
            fields = request_fields(parts, spans)
            if {"symbol", "timeframe", "expression"} <= fields.keys():
                start, stop = fields["symbol"][1]
                yield fields, parts[start].start(), parts[stop - 1].end()


def chart_symbol_helpers(code, aliases):
    edits = []
    requests = list(request_tokens(code))
    parts = tokens(code)
    for name, symbol in aliases.items():
        (definition,) = re.finditer(
            rf"(?m)^{name}\([ \t]*{symbol}(?=[,\)])[\w ,\t]*\)[ \t]*=>[^\n]*(?:\n[ \t]+[^\n]*)*",
            code,
        )
        candidates = [
            (field, start, stop)
            for field, start, stop in requests
            if definition.start() < start < definition.end()
            and field["symbol"][0] == symbol
        ]
        if not candidates:
            raise MigrationBlocked(
                "No archived request uses the audited chart-symbol parameter"
            )
        calls = []
        for i, part in enumerate(parts[:-1]):
            if (
                part.group() != name
                or definition.start() <= part.start() < definition.end()
            ):
                continue
            if parts[i + 1].group() != "(":
                raise MigrationBlocked("Archived helper has an indirect reference")
            _, spans = arguments(parts, i + 1)
            a, b = spans[0]
            calls.append("".join(node.group() for node in parts[a:b]))
        if not calls and name != "f_security":
            raise MigrationBlocked("Archived helper has no verified call site")
        if any(value != "syminfo.tickerid" for value in calls):
            raise MigrationBlocked(
                "The source helper has an external or nonstandard symbol argument"
            )
        edits.extend((start, stop, "syminfo.tickerid") for _, start, stop in candidates)
    return patch(code, edits), len(edits)


def inline_historical_helper(code, name):
    historical = re.compile(
        rf"(?m)^{name}\(_sym, _res, _src, _rep\) => request\.security\(_sym, _res, _src\[not _rep and barstate\.isrealtime \? 1 : 0\]\)\[_rep or barstate\.isrealtime \? 0 : 1\][ \t]*$"
    )
    (definition,) = historical.finditer(code)
    edits = [(definition.start(), definition.end(), "")]
    parts = tokens(code)
    for i, part in enumerate(parts[:-1]):
        if part.group() != name or part.start() == definition.start():
            continue
        if parts[i + 1].group() != "(":
            raise MigrationBlocked("Unexpected helper reference")
        end, spans = arguments(parts, i + 1)
        symbol, frame, expr, repaint = [
            "".join(p.group() for p in parts[a:b]) for a, b in spans
        ]
        if (
            symbol != "syminfo.tickerid"
            or repaint != "false"
            or expr not in {"high", "low", "open", "close"}
        ):
            raise MigrationBlocked(
                "Historical helper has other symbol, expression or repaint options"
            )
        edits.append(
            (
                part.start(),
                parts[end].end(),
                f"request.security({symbol}, {frame}, {expr})[1]",
            )
        )
    if len(edits) != 3:
        raise MigrationBlocked("The two archived daily request calls did not match")
    return patch(code, edits), 2


def declaration_variant(code, ident):
    version = VERSION.search(code)
    if version is None or not ACTIVE_ORDER.search(NO_QUOTED.sub("", code)):
        raise MigrationBlocked(
            "No standalone Pine order source with a version directive"
        )
    if re.search(r"(?m)^\s*strategy\s*\(", NO_QUOTED.sub("", code)):
        return code
    return (
        code[: version.end()]
        + f'\nstrategy("FMZ archived orders {ident}")\n'
        + code[version.end() :]
    )


def extra_edits(code, ident):
    repairs = {}
    capital = None
    if ident in CHART_HELPERS:
        code, count = chart_symbol_helpers(code, CHART_HELPERS[ident])
        repairs["Every archived call supplies the active chart symbol"] = count
    if ident in INLINE_PREVIOUS:
        from research.fmz_round4_feeds import inline_confirmed_helper

        code, count = inline_confirmed_helper(code)
        repairs["Closed reference request preserves its prior-candle offset"] = count
    if ident in INLINE_HISTORICAL:
        code, count = inline_historical_helper(code, INLINE_HISTORICAL[ident])
        repairs["Historical no-repaint helper keeps its outer one-chart-bar delay"] = (
            count
        )
    if ident in {1089, 2953}:
        code = replace(code, r"\btime\(tf\)", "fmzAltClock", 2)
        code = replace(
            code,
            r"""(?m)^(tf = input\(['"]60['"],[^\n]+\))$""",
            r"\1\nfmzAltClock = time(tf)",
            1,
        )
        repairs[
            "Moving the existing one-argument timeframe clock preserves its value"
        ] = 2
    if ident == 1252:
        code = replace(
            code,
            r'\band time\("15", "1515-1530"\)',
            'and not na(time(timeframe.period, "1515-1530:23456"))',
            2,
        )
        repairs["Archived 15-minute UTC session membership keeps legacy weekdays"] = 2
    if ident == 1361:
        code = replace(
            code,
            r'(?m)^if time\("60", "1000-1600"\)',
            'if not na(time(timeframe.period, "1000-1600:23456"))',
            1,
        )
        repairs[
            "Hourly aligned UTC session membership retains the same 15-minute bars and legacy weekdays"
        ] = 1
    if ident == 350:
        code = replace(code, r"\bvwap(?=\[barstate\.isrealtime)", "ta.vwap", 1)
        repairs["Legacy typical-price VWAP namespace retained"] = 1
    if ident == 3458:
        code, repairs = source_edits(code, ident)
        code = replace(code, r"(?m)^(float i_pvt = )pvt[ \t]*$", r"\1ta.pvt", 1)
        repairs["Legacy price-volume trend namespace retained"] = 1
    if ident == 3749:
        if not re.search(r'(?m)^security = input\("",', code):
            raise MigrationBlocked(
                "Archived symbol default is not the empty-chart selector"
            )
        code = replace(code, r"(?m)^security = input\(", "fmzChartSymbol = input(", 1)
        code = replace(
            code,
            r'\bsecurity\(security,"", close\)',
            'security(syminfo.tickerid,"", close)',
            1,
        )
        repairs["Archived empty ticker evaluates on the active chart"] = 1
    if ident == 5588:
        code = replace(
            code, r"heikinashi\(syminfo\.ticker\)", "heikinashi(syminfo.tickerid)", 2
        )
        repairs["Heikin-Ashi feed retains the same active chart market"] = 2
    if ident in IMPLICIT_CASES:
        code, capital = constant_capital(code)
        repairs["Archived positive literal starting capital"] = 1
    if ident in IMPLICIT_CASES | {591, 4054}:
        code = declaration_variant(code, ident)
        repairs["Audited active orders receive a standalone strategy declaration"] = 1
    return code, repairs, capital


def diagnostic_edits(code, ident):
    if ident in DIAGNOSTIC_FLOAT:
        code, count = float_steps(code, DIAGNOSTIC_FLOAT[ident])
        return code, {"Archived fractional input and unchanged literal default": count}
    if ident in {356, 388}:
        code = replace(
            code,
            r'(?m)^(Position\s*=\s*)input\((?="Both",[^\n]+options\s*=)',
            r"\1input.string(",
            1,
        )
        return code, {"Archived direction option input is string-typed": 1}
    if ident == 526:
        code = replace(
            code,
            r"(?m)^((?:start_time|end_time)\s*=\s*)input\((?=timestamp\([^\n]+confirm = true\))",
            r"\1input.time(",
            2,
        )
        return code, {"Dated archive input retains its time-specific parameter": 2}
    if ident in {418, 421, 5190}:
        code = replace(
            code,
            r"(?m)^    Hull_retracted\s*=\s*(Hull_Line\s*[+-]\s*(?:2|Width))[ \t]*$",
            r"    \1",
            2,
        )
        return code, {"Original Hull branch values returned without local shadowing": 2}
    if ident == 4130:
        return replace(
            code, r"dayofweek == monday\b", "dayofweek == dayofweek.monday", 1
        ), {"Legacy weekday constant namespace": 1}
    if ident == 239:
        return replace(
            code, r'(?m)^ {3}(strategy.entry\("buy", strategy.long\))', r"    \1", 1
        ), {"Archived single entry indented as the existing if branch": 1}
    if ident in {351, 939}:
        count = 2 if ident == 351 else 4
        return replace(code, r"\bta\.hma(?=\()", "fmz_archived_hma", count), {
            "Archived custom Hull function binding restored": count
        }
    if ident == 4283:
        if not re.search(
            r"(?m)^    var bgcolor = color.new\(color = color.black, transp = 100\)$",
            code,
        ):
            raise MigrationBlocked("Archived table color variable no longer matches")
        code = replace(code, r"(?m)^    var bgcolor =", "    var tableShade =", 1)
        code = replace(
            code,
            r"(f_fillCell\(dashTable,[^\n]+),[ \t]*bgcolor,",
            r"\1, tableShade,",
            5,
        )
        return code, {"Keep chart bgcolor call separate from table color value": 1}
    if ident == 4106:
        return replace(code, r"(close [<>] )vwap\b", r"\1ta.vwap", 2), {
            "Legacy typical-price VWAP namespace retained": 2
        }
    if ident == 5646:
        return replace(
            code,
            r"(?<![.\w])cog\((open|high|low|close), length\)",
            r"ta.cog(\1, length)",
            4,
        ), {"Legacy center-of-gravity indicator namespace retained": 4}
    raise MigrationBlocked("No specific diagnostic repair")


def source_edits(code, ident):
    repairs = {}
    if ident in DONCHIAN:
        code, count = duplicate_bool(code)
        if count:
            repairs["Identical duplicated boolean defaults merged"] = count
        code, count = rename_global(code, {"max", "min", "offset"})
        if count:
            repairs["Chart state bindings keep separate names from Pine functions"] = (
                count
            )
    if ident in FRACTIONAL:
        code, count = float_steps(code, FRACTIONAL[ident])
        repairs["Archived fractional input range and literal default retained"] = count
    if ident in RSI:
        code, count = rsi_calls(code)
        if count:
            repairs["Verified legacy RSI integer argument"] = count
        if ident in {2253, 5211}:
            code = replace(
                code,
                r"(?<![.\w])rsi\(upper_s, lower_s\)",
                "(100.0 - 100.0 / (1.0 + upper_s / lower_s))",
                1,
            )
            repairs["Archived two-series RSI uses the ratio formula"] = 1
    if ident == 1728:
        code = replace(
            code,
            r"(?m)^(\s*res\s*=\s*CustSession \? SessionTF0 : )period$",
            r"\1timeframe.period",
            1,
        )
        code = replace(
            code,
            r"(?m)^    truer = (request\.security\(syminfo\.tickerid, res, tr\))\s*$",
            "",
            1,
        )
        code = replace(
            code,
            r"(?m)^dirmov\(len\)\s*=>",
            "truer = request.security(syminfo.tickerid, res, tr)\ndirmov(len) =>",
            1,
        )
        code = "\n".join(line.expandtabs(4) for line in code.splitlines()) + "\n"
        repairs[
            "Original chart-timeframe reference and unconditional true-range request"
        ] = 1
    if ident in {2855, 2864}:
        expr = (
            "crossover(rsiVWAP, ovrbgt)"
            if ident == 2855
            else "crossunder(rsiVWAP, ovrsld)"
        )
        code = named_history(
            code,
            'strategy.close("' + ("Long" if ident == 2855 else "Short") + '"',
            {"fmz_exit_cross": expr},
            "lateleave",
            28,
        )
        repairs["Eager crossover uses the archived 28-bar history"] = 1
    if ident == 3458:
        if len(re.findall(r"\binnercandle\b", NO_QUOTED.sub("", code))) != 1:
            raise MigrationBlocked(
                "The inner-candle expression value is used elsewhere"
            )
        code = replace(
            code,
            r"(?m)^icreturn = false\ninnercandle = if \(high < high\[1\]\) and \(low > low\[1\]\)\n    icreturn := true$",
            "icreturn = (high < high[1]) and (low > low[1])",
            1,
        )
        repairs["Unused if-result eliminated, keeping its boolean assignment"] = 1
    if ident == 4739:
        if len(re.findall(r"\bstopValue\b", NO_QUOTED.sub("", code))) != 2:
            raise MigrationBlocked("The stop branch's local variable is used elsewhere")
        code = replace(
            code,
            r"(?m)^    stopValue = (entry_price [+-] entry_stop_atr)[ \t]*$",
            r"    \1",
            2,
        )
        repairs["Archived stop price returned explicitly from each branch"] = 2
    if ident == 5297:
        code = replace(code, r"array\.abs\(P1 - P2\)", "math.abs(P1 - P2)", 1)
        repairs["Scalar ribbon distance uses the numeric absolute-value function"] = 1
    return code, repairs


def archival_items(archive, rows):
    evidence, originals = {}, {}
    with ZipFile(archive) as source:
        for ident, row, document, digest in documents(source, rows):
            blocks = script_blocks(document, False) or BLOCKS.findall(document)
            active = [
                plain_pine(block)
                for block in blocks
                if ACTIVE_ORDER.search(NO_QUOTED.sub("", plain_pine(block)))
            ]
            raw = NO_QUOTED.sub("", "\n".join(plain_pine(block) for block in blocks))
            evidence[str(ident)] = {
                "document_sha256": digest,
                "archived_code_blocks": len(blocks),
                "active_order_blocks": len(active),
                "pine_versions": sorted(
                    set(
                        re.findall(
                            r"(?m)^\s*//\s*@version\s*=\s*(\d+)", "\n".join(blocks)
                        )
                    )
                ),
                "source_bindings": sorted(
                    set(
                        re.findall(
                            r"\b(?:request\.[A-Za-z_]+|security|timenow|renko|kagi|linebreak|pointfigure|use_bar_magnifier|calc_on_every_history_tick|strategy\.initial_capital)\b",
                            raw,
                        )
                    )
                ),
            }
            if len(active) == 1:
                timeframe = re.search(r"(?m)^period:\s*(\S+)", document)
                originals[ident] = (
                    active[0],
                    digest,
                    timeframe[1] if timeframe else "",
                )
    return evidence, originals


def earlier_candidates(prior):
    result = {}
    for phase in ("batch", "sessions", "repair", "followup"):
        manifest = read(prior / f"{phase}-manifest.json")
        for label in manifest["batches"]:
            for item in read(prior / label / "candidates.json"):
                result[item["id"]] = item
    return result


def replay_worker(batch, *, cross=False):
    clock_worker(batch, cross=cross)
    path = batch / "worker.mjs"
    worker = path.read_text(encoding="utf-8")
    worker = replace(
        worker, r"const timeLimit = [0-9_]+;", f"const timeLimit = {TIME_LIMIT};", 1
    )
    worker = replace(
        worker, r"maxOldGenerationSizeMb: 768", f"maxOldGenerationSizeMb: {HEAP_MB}", 1
    )
    path.write_text(worker, encoding="utf-8", newline="\n")


def kept_inputs(windows, frames, heikin):
    result = {}
    for label, window in windows.items():
        market = {
            k: v
            for k, v in window["market"].items()
            if k not in {"references", "heikinAshi"}
        }
        for field in ("references", "heikinAshi"):
            if field == "heikinAshi" and not heikin:
                continue
            feeds = window["market"].get(field, {})
            market[field] = {
                symbol: {
                    frame: bars
                    for frame, bars in values.items()
                    if frames is None or frame in frames
                }
                for symbol, values in feeds.items()
            }
        result[label] = {**window, "market": market}
    return result


def stage(archive, prior, work, *, lane="main", diagnostic_inputs=(), only=()):
    rows = scoped(lane=lane)
    if only:
        rows = {ident: rows[ident] for ident in only}
    evidence, originals = archival_items(archive, rows)
    previous = earlier_candidates(prior)
    source = prior / SOURCE_BATCH / "candles.json"
    reference = read(FEEDS)
    assert checksum(archive.read_bytes()) == reference["source_archive_sha256"]
    assert (
        checksum(source.read_bytes())
        == reference["batches"][SOURCE_BATCH]["candles.json"]
    )
    windows = read(source)
    diagnostic = {}
    if lane == "diagnostic":
        for directory in diagnostic_inputs:
            inputs = (
                [directory / "candidates.json"]
                if (directory / "candidates.json").exists()
                else list(directory.glob("pine-*/candidates.json"))
            )
            for candidate_file in inputs:
                diagnostic.update({item["id"]: item for item in read(candidate_file)})
        cross_dir = next(
            directory
            for directory in diagnostic_inputs
            if (directory / "candles.json").exists()
        )
        cross_raw = read(cross_dir / "candles.json")
        cross_report = read(ROOT / "fmz-round3-symbols.json")
        assert checksum((cross_dir / "candles.json").read_bytes()) in json.dumps(
            cross_report
        )
        cross_inputs = {}
        for label, window in windows.items():
            original = cross_raw[label]
            assert all(window[m] == original[m] for m in MARKETS)
            market = {
                **window["market"],
                "referenceSymbols": ["BTCUSDT", "BTCUSDT_SPOT"],
            }
            market["references"] = {
                **market["references"],
                "BTCUSDT_SPOT": original["market"]["references"]["BTCUSDT_SPOT"],
            }
            market["references"]["BTCUSDT"] = {
                **market["references"]["BTCUSDT"],
                "15": window["BTCUSDT"][0],
            }
            cross_inputs[label] = {**window, "market": market}
    groups, blockers = defaultdict(list), {}
    for ident, (block, digest, interval) in originals.items():
        row = rows[ident]
        retry = (
            lane == "main"
            and ident in previous
            and "time or memory budget exceeded" in row["reason"]
        )
        if (
            lane == "main"
            and ident not in DONCHIAN | RSI | SPECIFIC | FRACTIONAL.keys()
            and not retry
            and not any(t in row["reason"] for t in KNOWN_STOPS)
        ):
            continue
        try:
            if lane == "diagnostic":
                if ident in FIXED_PERPETUAL:
                    original = fixed_archive_source(
                        path_to_archive(archive, row), ident
                    )
                    code, version, repairs, fill, capital = verified_source(
                        original, ident
                    )
                    item = {
                        "id": ident,
                        "name": row["name"],
                        "archived": interval,
                        "code": code,
                        "version": version,
                        "repairs": repairs,
                        "hash": digest,
                        "source": row["source"],
                        "allowFillRecalculation": fill,
                        "snapshotVariant": False,
                        "confirmedVariant": ident == 3514,
                    }
                    if capital is not None:
                        item["initialCapital"] = capital
                else:
                    item = dict(diagnostic[ident])
                    assert item["hash"] == digest
                    item.setdefault("version", item.get("old_version"))
                    item.setdefault("snapshotVariant", False)
                    item.setdefault("confirmedVariant", False)
                    item["code"], changes = diagnostic_edits(item["code"], ident)
                    item["repairs"] = {**item["repairs"], **changes}
            elif retry and ident not in SPECIFIC | RSI:
                item = dict(previous[ident])
                if "Fixed archived Binance BTC perpetual reference" in item["repairs"]:
                    raise MigrationBlocked(
                        "Previous retry requires an independently routed benchmark"
                    )
                assert item["hash"] == digest
            else:
                capital = None
                if lane == "extra":
                    repaired, repairs, capital = extra_edits(block, ident)
                else:
                    repaired, repairs = source_edits(block, ident)
                if lane == "main" and not repairs and ident in previous:
                    raise MigrationBlocked(
                        "Previous replay already exercised this source"
                    )
                if not repairs and "exact migrated source" in row["reason"]:
                    raise MigrationBlocked(
                        "Earlier compiler replay already exercised this migration"
                    )
                version = VERSION.search(repaired)
                if version and int(version[1]) < 5:
                    repaired, preliminary = pre_migration(repaired)
                    repairs.update(preliminary)
                try:
                    code, version, adapted, fill, clock, delayed = prepare_feed(
                        ident, repaired, advanced=True, late=True
                    )
                except MigrationBlocked as exc:
                    if "Eager iff branch" not in str(exc):
                        raise
                    repaired, count = eager_legacy_calls(repaired)
                    if not count:
                        raise
                    repairs["Archived eager iff evaluates both arguments"] = count
                    code, version, adapted, fill, clock, delayed = normalize(
                        repaired, legacy_session=True
                    )
                item = {
                    "id": ident,
                    "name": row["name"],
                    "source": row["source"],
                    "hash": digest,
                    "archived": interval,
                    "code": code,
                    "version": version,
                    "repairs": {**adapted, **repairs},
                    "allowFillRecalculation": fill,
                    "snapshotVariant": clock,
                    "confirmedVariant": delayed,
                }
                if capital is not None:
                    item["initialCapital"] = capital
                if ident in previous and item["code"] == previous[ident]["code"]:
                    raise MigrationBlocked(
                        "Prior replay already used the same migrated source"
                    )
            frames = requested_frames(item["code"])
        except (ValueError, AssertionError, KeyError) as exc:
            blockers[str(ident)] = (
                str(exc) or "Archived source could not be uniquely reconciled"
            )
            continue
        label = (
            None if frames is None else tuple(sorted(frames)),
            "ticker.heikinashi" in item["code"],
            ident in FIXED_MARKET,
        )
        groups[label].append(item)
    work.mkdir(parents=True, exist_ok=True)
    batches = {}
    for i, ((frames, heikin, cross), group) in enumerate(groups.items(), 1):
        name = f"pine-{i}"
        batch = work / name
        batch.mkdir(exist_ok=True)
        write(
            batch / "candles.json",
            kept_inputs(cross_inputs if cross else windows, frames, heikin),
        )
        write(batch / "candidates.json", group)
        replay_worker(batch, cross=cross)
        batches[name] = [item["id"] for item in group]
    fixture = work / "fixture-pine"
    prepare_fixture(fixture)
    replay_worker(fixture)
    fixtures = [fixture.name]
    if lane == "extra" and SESSION_CASES.intersection(rows):
        session_fixture(work, fixture)
    if lane == "diagnostic" and any(label[2] for label in groups):
        fixture = work / "fixture-cross"
        prepare_fixture(fixture, cross=True)
        replay_worker(fixture, cross=True)
        fixtures.append(fixture.name)
    write(
        work / "preflight.json",
        {
            "source_archive_sha256": checksum(archive.read_bytes()),
            "ledger_sha256": checksum(LEDGER.read_bytes()),
            "prior_candles_sha256": checksum(source.read_bytes()),
            "archive_evidence": evidence,
            "batches": batches,
            "blockers": blockers,
            "time_limit_ms": TIME_LIMIT,
            "heap_mb": HEAP_MB,
            "lane": lane,
            "fixture_names": fixtures,
            "scoped_ids": sorted(rows),
        },
    )
    print("Audited", len(evidence), "pinned documents. Staged", batches, flush=True)


def path_to_archive(archive, row):
    with ZipFile(archive) as source:
        _, _, document, _ = next(documents(source, {row["id"]: row}))
    (block,) = script_blocks(document, True)
    return block if isinstance(block, str) else block[0]


def fixed_archive_source(code, ident):
    if not re.search(
        r'(?m)^exchanges:\s*\[\{"eid":"Futures_Binance","currency":"BTC_USDT"', code
    ):
        raise MigrationBlocked("Archived Bitcoin perpetual venue binding is absent")
    if ident == 4575:
        return patch(
            code,
            [
                (part.start(), part.end(), "fmzPriceReturn")
                for part in tokens(code)
                if part.group() == "return"
            ],
        )
    if ident == 3106:
        if not re.search(
            r"""(?m)^supportSymbol = input\(['"]BTC_USDT:swap['"],""", code
        ):
            raise MigrationBlocked("Archived fixed BTC reference is absent")
        return replace(
            code,
            r"\brequest.security\(supportSymbol,",
            'request.security("BTC_USDT:swap",',
            1,
        )
    if ident == 3514:
        if not re.search(
            r"""(?m)^index_ticker\s*=\s*input\(['"]BTC_USDT:swap['"]\)""", code
        ):
            raise MigrationBlocked("Archived fixed BTC comparison market is absent")
        code = replace(
            code,
            r"(?m)^f_secureSecurity\(_symbol, _res, _src, _offset\) => security\(_symbol, _res, _src\[_offset\], lookahead = barmerge.lookahead_on\)[ \t]*$",
            "",
            1,
        )
        return replace(
            code,
            r"f_secureSecurity\(index_ticker, '1D', close, 0\)",
            'security("BTC_USDT:swap", "D", close, lookahead=barmerge.lookahead_off)',
            1,
        )
    raise MigrationBlocked("No exact archived perpetual market rule")


def finalize(archive, work, output):
    preflight = read(work / "preflight.json")
    rows = scoped(lane=preflight.get("lane", "main"))
    initial_ids = preflight.get("scoped_ids") or map(int, preflight["archive_evidence"])
    rows = {ident: rows[ident] for ident in initial_ids}
    assert preflight["ledger_sha256"] == checksum(LEDGER.read_bytes())
    assert preflight["source_archive_sha256"] == checksum(archive.read_bytes())
    assert preflight["source_archive_sha256"] == read(FEEDS)["source_archive_sha256"]
    fresh, _ = archival_items(archive, rows)
    assert fresh == preflight["archive_evidence"]
    isolated = read(work / "isolation-probe.json")
    assert isolated == {"privateDenied": True, "networkDenied": True}
    fixture = fixture_receipts(
        work, set(preflight.get("fixture_names", ["fixture-pine"])), isolated
    )
    if (work / "session-check/candidates.json").exists():
        fixture["session-check"] = verify_session_fixture(work, isolated)
    engine = checksum((work / "engine.mjs").read_bytes())
    assert engine == read(FEEDS)["engine_sha256"]
    artifacts, attempts, recovered, all_results = {}, {}, {}, []
    for label, ids in preflight["batches"].items():
        path = work / label
        if not (work / (label + "-node.exit")).exists():
            continue
        assert (work / (label + "-node.exit")).read_text().strip() == "0"
        artifacts[label] = artifact_hashes(
            path, ("candles.json", "candidates.json", "worker.mjs", "out.jsonl")
        )
        assert artifacts[label]["worker.mjs"] in {
            row["sha256"]["worker.mjs"] for row in fixture.values()
        }
        candidates = {item["id"]: item for item in read(path / "candidates.json")}
        receipts = read_receipts(path)
        assert set(ids) == candidates.keys() == receipts.keys()
        for ident, item in candidates.items():
            assert (
                item["source"] == rows[ident]["source"]
                and item["hash"] == fresh[str(ident)]["document_sha256"]
            )
            attempt = {
                "batch": label,
                "migrated_source_sha256": checksum(item["code"].encode()),
            }
            attempts[str(ident)] = attempt
            receipt = receipts[ident]
            if "reason" in receipt:
                attempt.update(
                    {
                        key: receipt[key]
                        for key in ("reason", "detail")
                        if key in receipt
                    }
                )
                continue
            result = receipt["results"]
            reconcile(result, tuple("Binance · " + key for key in WINDOWS), item, 15)
            group = "FMZ Pine · Source-audited historical replay"
            for enabled, name in (
                (item["confirmedVariant"], "confirmation-timing variant"),
                (item["snapshotVariant"], "window-end clock snapshot"),
                (item["allowFillRecalculation"], "OHLC-fill recalculation"),
                ("ticker.heikinashi" in item["code"], "Heikin-Ashi reference"),
                (
                    ident in INDICATOR_CASES | IMPLICIT_CASES | {591, 4054},
                    "standalone declaration variant",
                ),
                (ident in FIXED_PERPETUAL, "fixed archived BTC perpetual reference"),
                (ident in {1252, 1361}, "verified UTC weekday session variant"),
                (ident in {4645, 5175}, "fixed archived BTC spot reference"),
            ):
                if enabled:
                    group += " · " + name
            for cell in result:
                cell.update(
                    group=group,
                    quote_currency="USDT",
                    repairs=item["repairs"],
                    market_data="Binance USD-M BTCUSDT and ETHUSDT perpetuals",
                    pine_source_version=item["version"],
                    migration_sha256=attempt["migrated_source_sha256"],
                )
            attempt["closed_trades"] = sum(
                cell["trades"] for cell in result if cell["market"] in MARKETS
            )
            recovered[ident] = [
                ident,
                "Tested · "
                + group
                + ("" if attempt["closed_trades"] else ", no closes"),
                "Verified pinned source, AppContainer replay and Binance historical candles.",
            ]
            all_results.extend(result)
    coverage = []
    for ident, row in rows.items():
        if ident in recovered:
            coverage.append(recovered[ident])
            continue
        label = str(ident)
        attempt = attempts.get(label, {})
        reason = (
            attempt.get("detail")
            or attempt.get("reason")
            or preflight["blockers"].get(label)
            or row["reason"]
        )
        if ident == 682:
            reason = "Archived Pine v2 has exit calls, but its entry logic is commented out or absent. No standalone position entry can be verified."
        reason = EXTERNAL_REQUIREMENTS.get(ident, reason)
        coverage.append([ident, row["status"], reason])
    write(
        output,
        {
            **preflight,
            "baseline_commit": BASE,
            "engine_sha256": engine,
            "isolation_probe": isolated,
            "fixtures": fixture,
            "replay_artifacts": artifacts,
            "coverage": coverage,
            "attempts": attempts,
            "results": all_results,
        },
    )
    print(
        "Verified",
        len(recovered),
        "strategies and",
        len(all_results),
        "result rows",
        flush=True,
    )


def merge(archive, output, work):
    """Combine completed receipts while preserving a stronger earlier decision."""
    coverage, results, evidence, reports = {}, {}, {}, []
    for directory in work:
        partial = directory / "final-verification.json"
        finalize(archive, directory, partial)
        report = read(partial)
        for ident, item in report["archive_evidence"].items():
            assert ident not in evidence or evidence[ident] == item
            evidence[ident] = item
        for ident, status, reason in report["coverage"]:
            previous = coverage.get(ident)
            if previous and previous[1].startswith("Tested"):
                assert not status.startswith("Tested"), ident
                continue
            if (
                previous
                and not status.startswith("Tested")
                and str(ident) not in report["attempts"]
            ):
                continue
            coverage[ident] = [ident, status, reason]
        for row in report["results"]:
            results.setdefault(row["id"], []).append(row)
        reports.append(
            {
                k: v
                for k, v in report.items()
                if k not in {"results", "coverage", "archive_evidence"}
            }
        )
    assert {int(i) for i in evidence} == coverage.keys()
    assert results.keys() == {
        i for i, (_, status, _) in coverage.items() if status.startswith("Tested")
    }
    assert all(len(rows) == 6 for rows in results.values())
    completed = sum(any(row["trades"] for row in rows) for rows in results.values())
    write(
        output,
        {
            "baseline_commit": BASE,
            "archive_evidence": evidence,
            "reports": reports,
            "coverage": [coverage[i] for i in sorted(coverage)],
            "results": [row for ident in sorted(results) for row in results[ident]],
            "summary": {
                "audited_ids": len(coverage),
                "newly_tested": len(results),
                "with_closes": completed,
                "without_closes": len(results) - completed,
                "remaining": dict(
                    Counter(
                        status
                        for _, status, _ in coverage.values()
                        if not status.startswith("Tested")
                    )
                ),
            },
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, function, paths in (
        ("stage", stage, ("archive", "prior", "work")),
        ("finalize", finalize, ("archive", "work", "output")),
        ("merge", merge, ("archive", "output")),
    ):
        command = commands.add_parser(name)
        command.set_defaults(function=function)
        if name == "stage":
            command.add_argument(
                "--lane", choices=("main", "extra", "diagnostic"), default="main"
            )
            command.add_argument(
                "--diagnostic-inputs", nargs="*", type=Path, default=()
            )
            command.add_argument("--only", nargs="+", type=int, default=())
        for path in paths:
            command.add_argument(path, type=Path)
        if name == "merge":
            command.add_argument("work", nargs="+", type=Path)
    args = vars(parser.parse_args())
    args.pop("command")
    args.pop("function")(**args)
