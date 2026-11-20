"""Recover publicly displayed FMZ parameter settings tied to archived source previews."""

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

from research.delta_pinets_catalogue import read, write


class StrategyPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_pre = 0
        self.preview = ""
        self.previews = []
        self.field = None
        self.values = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "pre":
            self.in_pre += 1
        if tag == "label":
            field = attrs.get("for", "")
            self.field = field.removeprefix("scriptArgList_") if field.startswith("scriptArgList_") else None
        if not self.field:
            return
        value = None
        if tag == "input" and attrs.get("role") == "spinbutton" and attrs.get("value"):
            try:
                value = json.loads(attrs["value"])
            except json.JSONDecodeError:
                pass
        elif tag == "input" and attrs.get("type") == "text" and "value" in attrs:
            value = attrs["value"]
        elif tag == "button" and attrs.get("role") == "switch" and attrs.get("aria-checked") in ("true", "false"):
            value = attrs["aria-checked"] == "true"
        if value is not None:
            self.values[self.field] = value
            self.field = None

    def handle_endtag(self, tag):
        if tag == "pre" and self.in_pre:
            self.in_pre -= 1
            if not self.in_pre:
                self.previews.append(self.preview)
                self.preview = ""

    def handle_data(self, data):
        if self.in_pre:
            self.preview += data


def normalized(text):
    return re.sub(r"\s+", " ", text).strip()


def recover(item, missing, cache):
    url = item["parameter_page"]
    if not re.fullmatch(r"https://www\.fmz\.com/strategy/\d+", url):
        return {"id": item["id"], "reason": "No pinned public strategy link for parameter verification"}
    location = cache / (url.rsplit("/", 1)[1] + ".html")
    try:
        if not location.exists():
            downloaded = subprocess.run(
                ["curl.exe", "-fsSL", "--max-time", "20", "--max-filesize", "3000000", url],
                capture_output=True, check=True,
            )
            location.write_bytes(downloaded.stdout)
        body = location.read_bytes()
        page = StrategyPage()
        page.feed(body.decode("utf-8"))
    except (OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        return {"id": item["id"], "url": url, "reason": f"Public parameter page unavailable: {type(exc).__name__}"}
    pinned = normalized(item["code"])
    matched = max((len(p) for text in page.previews if len(p := normalized(text)) >= 70 and pinned.startswith(p)), default=0)
    evidence = {"id": item["id"], "url": url, "sha256": hashlib.sha256(body).hexdigest(), "preview_chars": matched}
    if not matched:
        return {**evidence, "reason": "Public source preview does not match pinned source prefix"}
    defaults = {key: value for key, value in page.values.items()
                if re.fullmatch(r"[A-Za-z_$][\w$]*", key) and key not in item["args"]}
    return {**evidence, "args": defaults, "still_missing": sorted(missing - defaults.keys())}


def run(work):
    items = read(work / "native-source-candidates.json")
    candidates = {x["id"]: x for x in items}
    screen = read(work / "native-screen.json")
    jobs = []
    for row in screen:
        reason = row.get("reason") or ""
        if reason.startswith("Public defaults or declarations missing for "):
            jobs.append((candidates[row["id"]], set(reason.removeprefix("Public defaults or declarations missing for ").split(", "))))
    cache = work / "public-parameter-pages"
    cache.mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=5) as pool:
        records = list(pool.map(lambda args: recover(*args, cache), jobs))
    for record in records:
        item = candidates[record["id"]]
        item["args"] = {**item["args"], **record.get("args", {})}
    write(work / "native-public-parameters.json", records)
    write(work / "native-enriched-candidates.json", items)
    print(f"{len(records)} public parameter checks. {sum(bool(x.get('args')) for x in records)} supplied values.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    run(parser.parse_args().work)
