# Local installation

Installed on 2026-11-17 for this Windows machine.

- Bundle: `E:\coding\code\Trade\crypto-trader-skills`.
- Existing Python: 3.13.5, reused without changing other Python installations or PATH.
- Isolated interpreter: `E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe`.
- Bundled pip: 25.1.1. Runtime third-party dependencies: **none**. No paid subscription, API key, Docker, Node, exchange SDK or OpenAI API key is needed.
- All 12 local skills are registered at the documented user discovery root `C:\Users\hp\.agents\skills\crypto-*`, using NTFS directory junctions to this bundle. Earlier Codex-home junctions remain as compatibility links. On recheck the missing user-root registrations were corrected. No app restart or selector refresh was performed; if skills do not appear, restart Codex.

Keep the bundle in place. Moving/deleting it will break these installed links. Skill instructions contain local absolute paths so documentation and runtime resolve correctly through the registered locations. Existing unrelated skills were preserved. This setup targets local Codex with its existing file and shell tools.

## Run without activating the environment

```powershell
Set-Location 'E:\coding\code\Trade\crypto-trader-skills'
& '.\.venv\Scripts\python.exe' run.py --help
& '.\.venv\Scripts\python.exe' run.py status --workspace ./verification/setup-demo
```

The setup verification demo is synthetic, with a simulated clock and fictional limits. To make a fresh demo, use a NEW workspace name:

```powershell
& '.\.venv\Scripts\python.exe' run.py demo --workspace ./my-new-demo
```

For Codex, request a skill such as `$crypto-workflow`, `$crypto-market` or `$crypto-backtest` on the next turn. These are local instruction/script skills; the caller uses the existing file and Python execution tools.

## Verification

Latest discovery-path correction and code verification: [RECHECK.md](RECHECK.md), with 67 passing tests. Earlier setup files below preserve the initial installation evidence.

See [installation evidence](verification/installation.json) and [setup test output](verification/setup-unit-tests.txt). The tests run through the isolated interpreter, and registered wrappers are exercised from a different working directory to prove that the junctions reach the shared runtime. A fresh 10,000-replay/10,000-participant synthetic demo runs through the installed workflow wrapper.

The standalone engine remains paper/research mode. This installation adds no live order connector or persistent background trading process. An explicit bounded paper watch command is available; see PAPER-EXIT-RESULTS.md. Optional development-only skill validation uses the already installed global PyYAML; it is not a runtime requirement.
