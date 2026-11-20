import json
import re
import sys
from importlib import import_module
from pathlib import Path

w = Path(__file__).parent
sys.path.insert(0, str(w / "priced-runtime"))
pine = import_module("pine_compat")
cases = []
for ident in (4497, 5772):
    raw = (w / f"r33-source-{ident}.pine").read_text(encoding="utf8")
    normalized = raw.replace("\u00a0", " ")
    moved = re.sub(
        r"(?m)^ +if useMartin\n((?://[^\n]*\n)?)^if ([^\n]+)$",
        r"\1if useMartin and \2",
        normalized,
    )
    assert moved.count("if useMartin and ") == 2
    for label, source in (
        ("archive bytes", raw),
        ("whitespace only", normalized),
        ("joined nested guard diagnostic", moved),
    ):
        try:
            program = pine.compile_script(source)
            notes = {"error": None}
        except ValueError as e:
            notes = {"error": str(e)}
        cases.append({"id": ident, "mode": label, **notes})
(w / "r33-martingale-source-diagnostics.json").write_text(
    json.dumps(cases, ensure_ascii=False, separators=(",", ":")),
    encoding="utf8",
    newline="\n",
)
