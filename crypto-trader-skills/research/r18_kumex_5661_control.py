"""Run exact archived driver and SDK serialization against a local branch fixture."""

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).absolute().parent
JOB = ROOT / "r17-kumex-5661-control-input.json"
OUT = ROOT / "r17-kumex-5661-control-receipt.json"


class CaseEnd(BaseException):
    pass


class InvalidOrderSize(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run_case(case, source, methods):
    record = {
        "name": case["name"],
        "public_kline_requests": 0,
        "position_reads": 0,
        "order_payloads": [],
    }
    cfg = {
        "api_key": "",
        "api_secret": "",
        "api_passphrase": "",
        "is_sandbox": False,
        "symbol": "XBTUSDTM",
        "resolution": 1,
        "valve": 0.10,
        "leverage": 3,
        "size": 1,
    }
    if case.get("missing"):
        del cfg[case["missing"]]
    time_to = 1_700_000_040
    readings = 0
    max_reads = case.get("reads", 1)

    def now():
        nonlocal readings
        if readings == max_reads:
            raise CaseEnd
        readings += 1
        return time_to + readings * 60

    def get(method, url, *, headers, timeout):
        assert method == "GET" and headers == {} and timeout == 5
        parts = urlsplit(url)
        assert (
            parts.hostname == "kitchen.kumex.com"
            and parts.path == "/kumex-kline/history"
        )
        query = parse_qs(parts.query)
        assert query["symbol"] == ["XBTUSDTM"] and query["resolution"] == ["1"]
        left, right = (int(query[key][0]) for key in ("from", "to"))
        assert right - left == 35 * 60
        record["public_kline_requests"] += 1
        trail = right - 60 if case.get("timestamp") == "preceding bar start" else right
        body = {
            "s": "ok",
            "t": list(range(trail - 30 * 60, trail + 60, 60)),
            "h": [case.get("high", 100)] * 31,
            "l": [90] * 31,
            "c": [case.get("close", 95)] * 31,
        }
        return SimpleNamespace(status_code=200, json=lambda: body)

    def mock_request(self, method, path, *, params):
        if method == "GET":
            assert path == "/api/v1/position" and params == {"symbol": "XBTUSDTM"}
            record["position_reads"] += 1
            return {"currentQty": case.get("qty", 0), "realLeverage": 3}
        assert method == "POST" and path == "/api/v1/orders"
        record["order_payloads"].append(dict(params))
        if not isinstance(params["size"], int) or params["size"] <= 0:
            raise InvalidOrderSize(
                "Classic KuMEX limit order size must be a positive integer"
            )
        return {"orderId": "local-fixture-" + str(len(record["order_payloads"]))}

    sdk_namespace = {}
    # The two audited SDK methods delegate exclusively to mock_request in this offline fixture.
    exec(compile(methods, "pinned-kumex-sdk-methods", "exec"), sdk_namespace)  # noqa: S102
    sdk = type(
        "OfflineKuMEX",
        (),
        {
            "_request": mock_request,
            "return_unique_id": "fixture-only",
            "get_position_details": sdk_namespace["get_position_details"],
            "create_limit_order": sdk_namespace["create_limit_order"],
        },
    )()
    modules = {
        "json": json,
        "time": SimpleNamespace(time=now),
        "requests": SimpleNamespace(request=get),
        "kumex.client": SimpleNamespace(Trade=lambda *args, **kwargs: sdk),
    }

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        return modules[name]

    def config(name, mode):
        assert name == "config.json" and mode == "r"
        return io.StringIO(json.dumps(cfg))

    env = {
        "__name__": "__main__",
        "__builtins__": {
            "__build_class__": __build_class__,
            "__import__": importer,
            "object": object,
            "int": int,
            "float": float,
            "Exception": Exception,
            "ValueError": ValueError,
            "open": config,
            "print": lambda *args: None,
        },
    }
    try:
        # This is the exact hash-checked archive source inside a network-denied AppContainer.
        exec(compile(source, "archived-kucoin-5661", "exec"), env)  # noqa: S102
    except CaseEnd:
        record["ending"] = "bounded branch check"
    except (InvalidOrderSize, KeyError) as exc:
        record["ending"] = f"{type(exc).__name__}: {exc}"
    record["clock_reads"] = readings
    return record


if __name__ == "__main__":
    raw = JOB.read_bytes()
    job = json.loads(raw)
    assert sha(job["source"].encode()) == job["source_sha256"]
    assert sha(job["sdk_methods"].encode()) == job["sdk_methods_sha256"]
    receipts = [run_case(c, job["source"], job["sdk_methods"]) for c in job["cases"]]
    OUT.write_text(
        json.dumps(
            {
                "script_sha256": sha(Path(__file__).read_bytes()),
                "job_sha256": sha(raw),
                "source_sha256": job["source_sha256"],
                "sdk_methods_sha256": job["sdk_methods_sha256"],
                "controls": receipts,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
