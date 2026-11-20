from research.fmz_native_round7 import legacy_python, retry_worker_text


def test_legacy_syntax_updates_keep_the_archived_test_and_catch_body():
    source = "try:\n    ok = type(r) == types.ListType\nexcept Exception,ex:\n    observed = str(ex)\n"
    result = legacy_python(source)
    assert "type(r) == list" in result
    assert "except Exception as ex:" in result
    assert "observed = str(ex)" in result


def test_retry_worker_keeps_the_broker_and_uses_its_own_receipt_namespace():
    worker = (
        'source = "round7-native-python-jobs.json"\n'
        'report = "round7-native-python-" + case_id\n'
        "venue.Sell(-1, num)\n"
    )
    replay = retry_worker_text(worker, "round7-native-python", 2519)
    assert '"round7-native-python-retry-2519-jobs.json"' in replay
    assert '"round7-native-python-retry-2519-"' in replay
    assert replay.splitlines()[-1] == worker.splitlines()[-1]
