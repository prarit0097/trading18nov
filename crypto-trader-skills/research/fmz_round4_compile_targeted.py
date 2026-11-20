"""Source-audited transcription and UI input repairs for the last compiler pass."""

import re

from research.delta_pinets_migration import MigrationBlocked

V1_IDS = {228, 2760, 2874, 3194, 4059}
TARGETS = V1_IDS | {
    200,
    596,
    1005,
    1647,
    2471,
    3949,
    4384,
    4730,
    5208,
    5421,
    5552,
    5596,
}


def replace(code, pattern, value, count):
    updated, number = re.subn(pattern, value, code)
    if number != count:
        raise MigrationBlocked(
            "Archived local repair no longer matches the audited source"
        )
    return updated


def amend(code, strategy_id):
    if strategy_id in V1_IDS:
        code = replace(code, r"(?m)^//@version=1$", "//@version=2", 1)
        if strategy_id == 2760:
            code = replace(code, r"(?m)^(Length = input\(21\)),$", r"\1", 1)
        if strategy_id == 2874:
            code = replace(
                code,
                r"default_qty_type = strategy\.percent_of_equity, (?=default_qty_type)",
                "",
                1,
            )
        return code, "Audited v1 legacy syntax"
    if strategy_id == 200:
        code = replace(code, r"(?m)^ (?: {4})?(strategy\.entry\()", r"    \1", 2)
        return code, "Audited indentation around sibling order calls"
    if strategy_id == 2471:
        code = replace(code, r"(?m)^ {3}(if openShort)", r"    \1", 1)
        code = replace(code, r"(?m)^ {6}(strategy\.entry\(\"S\")", r"        \1", 1)
        return code, "Audited indentation around sibling order calls"
    if strategy_id == 4384:
        code = replace(code, r"(?m)^else[ \t]*\nif\(", "else if (", 1)
        code = replace(code, r"(?m)^ {5}(strategy\.close_all\(\))", r"    \1", 2)
        return code, "Audited indentation around sibling order calls"
    if strategy_id == 596:
        return replace(
            code, r"(vcolor=.*\? )red( :)", r"\1color.red\2", 1
        ), "Documented legacy color namespace"
    if strategy_id == 1005:
        code = replace(
            code,
            r"input\((#[A-Fa-f0-9]{6}),0,('(?:Colors)?'),inline='col'\)",
            r"input.color(\1, \2, inline='col')",
            3,
        )
        return code, "Opaque input color with explicit widget signature"
    if strategy_id in {1647, 5421}:
        code = replace(
            code,
            r'(?m)(defval\s*=\s*timestamp\("(?:01 Jan 2021 00:00|31 Dec 2121 23:59) UTC"\).*?type\s*=\s*input\.time),\s*minval\s*=\s*timestamp\("01 Jan 1970 00:00 UTC"\)',
            r"\1",
            2,
        )
        return (
            code,
            "Fixed time defaults preserve original values above the epoch floor",
        )
    if strategy_id == 3949:
        return replace(
            code, r"(?m)^Stochastic[ \t]*$", r"// Stochastic", 1
        ), "Standalone archived section heading"
    if strategy_id == 4730:
        code = replace(
            code,
            r'(?m)^alertcondition\(inDateRange\[1\][^\n]*\n[ \t]+title="Base Buy Alert",\n[ \t]+message=[^\n]*\)\n',
            "",
            1,
        )
        return code, "Offline variant omits the invalid external alert declaration"
    if strategy_id == 5208:
        code = replace(
            code,
            r"input\((9|26|52), (\"(?:Conversion Period|Base Line Period|Lagging Span Period|Displacement)\"), 1, group",
            r"input.int(\1, \2, minval = 1, group",
            4,
        )
        return code, "Fixed positive integer periods with explicit minimum"
    if strategy_id == 5552:
        return replace(
            code, r"(?m)^    [xy] = true[ \t]*$", "    true", 2
        ), "Explicit returned branch value"
    if strategy_id == 5596:
        code = replace(
            code,
            r"(?m)^    bullish_cross = (crossover\(movingaverage_8, movingaverage_50\))",
            r"    \1",
            1,
        )
        return code, "Explicit returned branch value"
    raise ValueError(f"No audited local repair for {strategy_id}")
