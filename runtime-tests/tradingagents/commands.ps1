$ErrorActionPreference = 'Stop'
$repo = 'E:\coding\code\Trade\TradingAgents'
$artifacts = 'E:\coding\code\Trade\runtime-tests\tradingagents'
# Initial setup (already executed): python -m venv "$artifacts\venv"
# Initial install: & "$artifacts\venv\Scripts\python.exe" -m pip install $repo --log "$artifacts\install.log"
# Test source is copied verbatim from tests/test_graph_end_to_end.py at the revision in result.json.
Set-Location -LiteralPath $artifacts
$env:PYTHON_DOTENV_DISABLED = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$python = "$artifacts\venv\Scripts\python.exe"
& $python -m pip check *> "$artifacts\pip-check.log"
$pipCheckExit = $LASTEXITCODE
& $python -m pip freeze --all *> "$artifacts\versions.txt"
& $python -m pytest test_installed_runtime.py test_graph_end_to_end.py -vv -s --strict-markers --basetemp "$artifacts\pytest-data" --junitxml "$artifacts\junit.xml" *> "$artifacts\runtime.log"
$testExit = $LASTEXITCODE
@{pip_check_exit=$pipCheckExit; pytest_exit=$testExit} | ConvertTo-Json | Set-Content -LiteralPath "$artifacts\exit-codes.json"
exit $testExit
