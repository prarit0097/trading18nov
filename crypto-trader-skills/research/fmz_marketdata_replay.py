"""Replay portable FMZ Pine source on public Binance USD-M history."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile

from research.delta_pine_compatibility import plain_pine, shell
from research.delta_pine_followup import followup, key_cells, patch
from research.delta_pine_liquid_replay import (
    MARKETS,
    WINDOWS,
    archived_candles,
    prepare_candles,
)
from research.delta_pine_repair import NO_QUOTED
from research.delta_pinets_catalogue import (
    EXTERNAL,
    FMZ_REF,
    aggregate,
    eligibility,
    read,
    source_block,
    write,
)
from research.delta_pinets_migration import (
    VERSION,
    MigrationBlocked,
    arguments,
    keyword,
    tokens,
)
from research.delta_strategy_replay import stamp

FRAMES = {str(x): x * 60 for x in (5, 15, 30, 45, 60, 90, 120, 180, 240, 360, 480, 720)}
FRAMES.update(D=86400, W=604800)
CONFIRMED_OFFSET = re.compile(
    r"(?:open|high|low|close|volume|hl2|hlc3|ohlc4)\[[1-9]\d*\]"
)
EXTRA_UNSUPPORTED = re.compile(
    r"\b(?:varip|timenow|isrealtime|islastconfirmedhistory|renko|kagi|"
    r"linebreak|pointfigure|security_lower_tf|import|financial|quandl|dividends|splits|"
    r"earnings|random)\b|\[\s*-\d"
)


def heikin_bars(bars):
    derived = []
    for bar in bars:
        close = sum(bar[k] for k in ("open", "high", "low", "close")) / 4
        if derived:
            previous = derived[-1]
            opened = (previous["open"] + previous["close"]) / 2
        else:
            opened = (bar["open"] + bar["close"]) / 2
        derived.append(
            {
                **bar,
                "open": opened,
                "close": close,
                "high": max(bar["high"], opened, close),
                "low": min(bar["low"], opened, close),
            }
        )
    return derived


def market_windows(candles, minutes=15, with_heikin=False):
    base, metadata = prepare_candles(candles, minutes)
    windows = {}
    for period, (begin, end) in WINDOWS.items():
        a, b = stamp(begin), stamp(end)
        interval = minutes * 60
        start = ((a + interval - 1) // interval) * interval
        stop = (b // interval) * interval
        result = base[period]
        references, synthetic = {}, {}
        for s in MARKETS:
            frames, heikin = {}, {}
            for label, length in FRAMES.items():
                anchor = 4 * 86400 if label == "W" else 0
                x = ((start - anchor + length - 1) // length) * length + anchor
                y = ((stop - anchor) // length) * length + anchor
                frames[label] = [
                    bar
                    for segment in aggregate(candles[s], x, y, length)
                    for bar in segment
                ]
                if with_heikin:
                    beginning = min(candles[s])
                    first_complete = (
                        (beginning - anchor + length - 1) // length
                    ) * length + anchor
                    history = aggregate(candles[s], first_complete, y, length)
                    heikin[label] = [
                        bar
                        for segment in history
                        for bar in heikin_bars(segment)
                        if x * 1000 <= bar["openTime"] and bar["closeTime"] <= y * 1000
                    ]
            references[s] = frames
            if with_heikin:
                synthetic[s] = heikin
        label = "Binance · " + period
        feeds = {**result["market"], "references": references}
        if with_heikin:
            feeds["heikinAshi"] = synthetic
        windows[label] = {**result, "market": feeds}
    return windows, {"Binance · " + p: m for p, m in metadata.items()}


def request_fields(parts, spans):
    names = ("symbol", "timeframe", "expression", "gaps", "lookahead")
    fields = {}
    for i, span in enumerate(spans):
        key, values = keyword(parts, span)
        key = {"tickerid": "symbol", "resolution": "timeframe"}.get(key, key)
        name = key or (names[i] if i < len(names) else "")
        if name not in names or name in fields:
            raise MigrationBlocked("Request has extra or ambiguous feed arguments")
        fields[name] = ("".join(values), (span[0] + 2, span[1]) if key else span)
    return fields


def checked_requests(code, version, allow_heikin=False):
    parts = tokens(code)
    edits, handled, flags = [], [], 0
    for i, token in enumerate(parts[:-1]):
        if token.group() != "security" or parts[i + 1].group() != "(":
            continue
        qualified = i > 1 and [x.group() for x in parts[i - 2 : i]] == ["request", "."]
        if i and parts[i - 1].group() == "." and not qualified:
            raise MigrationBlocked("Nonstandard security function")
        end, spans = arguments(parts, i + 1)
        values = request_fields(parts, spans)
        symbol, timeframe, expression = (
            values.get(k, ("", None))[0] for k in ("symbol", "timeframe", "expression")
        )
        heikin = allow_heikin and symbol in {
            "heikinashi(syminfo.tickerid)",
            "ticker.heikinashi(syminfo.tickerid)",
            "heikinashi(tickerid)",
            "ticker.heikinashi(tickerid)",
        }
        if (
            (symbol not in {"syminfo.tickerid", "tickerid"} and not heikin)
            or not timeframe
            or not expression
        ):
            raise MigrationBlocked(
                "Request needs another symbol, synthetic series or unavailable configuration"
            )
        if heikin:
            edits.append(
                (
                    *key_cells(parts, values["symbol"][1]),
                    "ticker.heikinashi(syminfo.tickerid)",
                )
            )
        elif symbol == "tickerid":
            edits.append((*key_cells(parts, values["symbol"][1]), "syminfo.tickerid"))
        for key, suffix in (("gaps", "gaps"), ("lookahead", "lookahead")):
            v, span = values.get(key, ("", None))
            if v in {"false", "true"}:
                v = f"barmerge.{suffix}_" + {"false": "off", "true": "on"}[v]
                edits.append((*key_cells(parts, span), v))
            if v and v not in {f"barmerge.{suffix}_off", f"barmerge.{suffix}_on"}:
                raise MigrationBlocked("Request uses a computed alignment flag")
            if (
                key == "lookahead"
                and v.endswith("_on")
                and not CONFIRMED_OFFSET.fullmatch(expression)
                and timeframe != "timeframe.period"
            ):
                raise MigrationBlocked(
                    "Higher-timeframe lookahead can access future data"
                )
        if (
            version < 3
            and "lookahead" not in values
            and timeframe != "timeframe.period"
        ):
            if not CONFIRMED_OFFSET.fullmatch(expression):
                raise MigrationBlocked(
                    "Legacy higher-timeframe request uses future-looking default"
                )
            stop = parts[end].start()
            edits.append((stop, stop, ", lookahead = barmerge.lookahead_on"))
        if not qualified:
            edits.append((token.start(), token.end(), "request.security"))
        a = parts[i - 2].start() if qualified else token.start()
        handled.append((a, parts[end].end(), ""))
        flags += 1
    remaining = NO_QUOTED.sub("", patch(code, handled))
    if EXTERNAL.search(remaining) or re.search(r"\bheikinashi\b", remaining):
        raise MigrationBlocked(
            "Requires an external feed, a library or visible chart state"
        )
    return patch(code, edits), flags


def historical_tick_setting(code):
    """The Pine realtime-only tick flag has no effect on historical calculations."""
    parts = tokens(code)
    for i, token in enumerate(parts[:-1]):
        if token.group() != "strategy" or parts[i + 1].group() != "(":
            continue
        _, spans = arguments(parts, i + 1)
        for span in spans:
            name, values = keyword(parts, span)
            if name == "calc_on_every_tick" and values == ["true"]:
                a, b = key_cells(parts, (span[0] + 2, span[1]))
                return code[:a] + "false" + code[b:], True
    return code, False


def prepare_source(block, *, isolated_literals=False, with_heikin=False):
    code = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    check = NO_QUOTED.sub("", code)
    if EXTRA_UNSUPPORTED.search(check) or (
        not with_heikin and re.search(r"\bheikinashi\b", check)
    ):
        raise MigrationBlocked(
            "Source requires realtime state, external APIs, a synthetic chart or future data"
        )
    if not (version_match := VERSION.search(code)):
        raise MigrationBlocked("Source version is absent")
    version = int(version_match[1])
    if not re.search(r"(?m)^strategy\s*\(", check):
        raise MigrationBlocked("Pine source has no active strategy declaration")
    if re.search(r"(?m)^\s*strategy\.initial_capital\s*(?::=|=(?!=))", check):
        raise MigrationBlocked("Source rewrites the broker wallet")
    code, ticks = historical_tick_setting(code)
    code, n = checked_requests(code, version, allow_heikin=with_heikin)
    changes = {"historical bar-close evaluation": 1} if ticks else {}
    if n:
        changes["confirmed same-symbol timeframe data"] = n
    if with_heikin and "ticker.heikinashi" in code:
        changes["Heikin-Ashi reference series, real chart fills"] = 1
    if version in {2, 3, 4}:
        code, _, _, signals = followup(
            code, verified_requests=bool(n), isolated_literals=isolated_literals
        )
        changes.update(signals)
        # A second scan verifies transformed namespaces and did not introduce other requests.
        code, after = checked_requests(code, version, allow_heikin=with_heikin)
        if after != n:
            raise MigrationBlocked("Migrated data requests differ from source")
    elif problem := eligibility(
        code, verified_requests=bool(n), isolated_literals=isolated_literals
    ):
        raise MigrationBlocked(problem)
    return code.strip(), version, changes


def owned(value):
    if value["source"] != "FMZ":
        return False
    if "untraded candle" in value["reason"] or "untraded fill" in value["reason"]:
        return False
    if value["status"] in {"Pending · FMZ", "Needs execution model"}:
        return True
    if value["reason"].startswith(
        ("External data", "Source requires tick or intrabar")
    ):
        return True
    return value["status"] == "FMZ native replay pending" and value[
        "reason"
    ].startswith(
        ("PineTS could not", "PineTS lacks", "PineTS per-source", "Wall-clock")
    )


def describe_source(document):
    if re.search(r"\b(?:GetDepth|GetOrderBook|GetTrades)\b", document):
        return "Archived FMZ source requires its venue's historic order book or trade events and order simulator"
    if re.search(r"\b(?:exchange\.IO|HttpQuery|WebSocket)\b", document):
        return (
            "Archived FMZ source includes venue-specific endpoints or external services"
        )
    if re.search(
        r"\b(?:GetAccount|GetPosition|exchange\.Buy|exchange\.Sell)\b", document
    ):
        return "Archived FMZ bot needs its deployment defaults, exchange state or FMZ order lifecycle"
    if re.search(r"\bstrategy\s*\(", document):
        return "Archive lacks one identifiable standalone Pine strategy with active order calls"
    return "Archive does not provide a standalone historical trading strategy compatible with these market data"


def script_blocks(document, allow_fmz_shell):
    found = source_block(document)
    if found or not allow_fmz_shell:
        return found
    possible = []
    for block in re.findall(r"(?ms)^\x60{3}[^\n]*\n(.*?)^\x60{3}", document):
        if not VERSION.search(block):
            continue
        try:
            code, changes = shell(plain_pine(block))
        except MigrationBlocked:
            continue
        possible.append((code, changes))
    return possible


def prepare(
    archive,
    target,
    candles,
    work,
    isolated_literals=False,
    heikin_only=False,
    all_specified=False,
):
    backlog = {
        int(k): v
        for k, v in read(target).items()
        if ((heikin_only or all_specified) and v["source"] == "FMZ")
        or owned(v)
        or (
            isolated_literals
            and v["source"] == "FMZ"
            and v["reason"].startswith(
                ("Source outside the isolated Pine", "No single supported Pine")
            )
        )
    }
    market, files = archived_candles(candles)
    work.mkdir(parents=True, exist_ok=True)
    windows, metadata = market_windows(market, with_heikin=heikin_only)
    statuses, entries = [], []
    with ZipFile(archive) as z:
        for i, row in backlog.items():
            rev, path = unquote(row["url"].split("/blob/", 1)[1]).split("/", 1)
            if rev != FMZ_REF:
                raise ValueError(f"Unexpected archive revision: {i}")
            binary = z.read(f"strategies-{rev}/{path}")
            document = binary.decode("utf-8")
            if heikin_only and not re.search(r"\bheikinashi\s*\(", document):
                continue
            codes = script_blocks(document, isolated_literals)
            try:
                if len(codes) != 1:
                    raise MigrationBlocked(describe_source(document))
                block, declared = (
                    (codes[0], {}) if isinstance(codes[0], str) else codes[0]
                )
                code, version, changes = prepare_source(
                    block, isolated_literals=isolated_literals, with_heikin=heikin_only
                )
                changes.update(declared)
            except ValueError as exc:
                statuses.append([i, "Pending · FMZ source or data", str(exc)])
                continue
            archived = re.search(r"(?m)^period:\s*(\S+)", document)
            entries.append(
                {
                    "id": i,
                    "name": row["name"],
                    "code": code,
                    "old_version": version,
                    "source": row["url"],
                    "hash": hashlib.sha256(binary).hexdigest(),
                    "archived": archived[1] if archived else "",
                    "repairs": changes,
                    "migration_sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
            )
    assert heikin_only or len(statuses) + len(entries) == len(backlog)
    write(work / "candidates.json", entries)
    write(work / "candles.json", windows)
    write(
        work / "preflight.json",
        {
            "coverage": statuses,
            "bar_archives": files,
            "windows": metadata,
            "source_revision": FMZ_REF,
            "market": "Binance USD-M perpetual",
            "requires_os_isolation": isolated_literals,
            "heikin_ashi_references": heikin_only,
        },
    )
    print("Market-data scope:", len(statuses) + len(entries), "running:", len(entries))
    print(Counter(r[2] for r in statuses).most_common(20))


def finalize(work, output, prior=None):
    manifest = read(work / "preflight.json")
    if manifest.get("requires_os_isolation", False):
        assurance = read(work / "isolation-probe.json")
        if assurance != {"privateDenied": True, "networkDenied": True}:
            raise ValueError(
                "Cannot load this batch without the no-network sandbox probe"
            )
        manifest["isolation_probe"] = assurance
    candidates = {x["id"]: x for x in read(work / "candidates.json")}
    records = {}
    for line in (work / "out.jsonl").read_text(encoding="utf-8-sig").splitlines():
        result = json.loads(line)
        assert result["id"] not in records
        records[result["id"]] = result
    assert records.keys() == candidates.keys()
    reports = []
    for i, data in sorted(records.items()):
        if "reason" in data:
            manifest["coverage"].append(
                [i, "Pending · FMZ source or data", "Binance 15m: " + data["reason"]]
            )
            continue
        rows, c = data["results"], candidates[i]
        assert len(rows) == 6 and len({(x["period"], x["market"]) for x in rows}) == 6
        for row in rows:
            assert row["id"] == i and row["source_sha256"] == c["hash"]
            row.update(
                group="FMZ Binance market-data",
                quote_currency="USDT",
                pine_source_version=c["old_version"],
                migration_sha256=c["migration_sha256"],
                repairs=c["repairs"],
            )
        reports.extend(rows)
        status = (
            "Tested · FMZ Binance"
            if any(x["trades"] for x in rows)
            else "Tested · FMZ Binance, no closes"
        )
        manifest["coverage"].append(
            [
                i,
                status,
                "Binance USD-M perpetual, 15m"
                + (". " + ", ".join(c["repairs"]) if c["repairs"] else ""),
            ]
        )
    manifest["coverage"].sort()
    manifest["results"] = reports
    manifest["engine"] = "PineTS 0.13.1"
    if prior:
        previous = read(prior)
        assert previous["bar_archives"] == manifest["bar_archives"]
        assert previous["source_revision"] == manifest["source_revision"]
        by_id = {x[0]: x for x in previous["coverage"] + manifest["coverage"]}
        old_ids = {x["id"] for x in previous["results"]}
        assert not old_ids.intersection(i for i, _, _ in manifest["coverage"])
        manifest["coverage"] = sorted(by_id.values())
        manifest["results"] = previous["results"] + manifest["results"]
        manifest["earlier_phase"] = {
            "tested": len(old_ids),
            "rows": len(previous["results"]),
            "requires_os_isolation": previous.get("requires_os_isolation", False),
        }
    write(output, manifest)
    print(
        Counter(s for _, s, _ in manifest["coverage"]), len(manifest["results"]), "rows"
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    steps = cli.add_subparsers(dest="action", required=True)
    for subcommand, fields in (
        ("prepare", ("archive", "target", "candles", "work")),
        ("finalize", ("work", "output")),
    ):
        parser = steps.add_parser(subcommand)
        for field in fields:
            parser.add_argument(field, type=Path)
        if subcommand == "prepare":
            parser.add_argument("--isolated-literals", action="store_true")
            parser.add_argument("--heikin-only", action="store_true")
            parser.add_argument("--all-specified", action="store_true")
        else:
            parser.add_argument("--prior", type=Path)
    options = vars(cli.parse_args())
    action = options.pop("action")
    (prepare if action == "prepare" else finalize)(**options)
