# Strategy qualification workflow

Use the isolated interpreter from `E:\coding\code\Trade\crypto-trader-skills`.

```powershell
.\.venv\Scripts\python.exe -m crypto_skills.validation download --workspace research\pilot-20261114-60d-v1 --end 2026-11-14T00:00:00Z --days 60
.\.venv\Scripts\python.exe -m crypto_skills.validation evaluate --workspace research\pilot-20261114-60d-v1
.\.venv\Scripts\python.exe run.py report --workspace research\pilot-20261114-60d-v1
```

This is an independent research workspace; never pass the shared manual paper-account workspace. The downloader is resumable and accepts12..60days in multiples of4, pinned at a completed UTC day boundary. A completed identical experiment reuses its recorded result. Code/settings changes under an existing experiment fail; do not rewrite the specification to bypass this.

Artifacts: `trader/experiment_spec.json`, three `history_<symbol>.json` envelopes, `selection.json`, `qualification.json`, raw cached pages under `raw/`, and a shared inspected-period registry in the bundle's `research-registry/`. Each asset gets an independent10000USDT research account. These are not a combined deployable portfolio or the user's actual shared paper positions.

Four fixed variants compare lookback20/40 and RVOL0/1.5. Chronological30/15/15-day train/validation/test windows keep all features and position outcomes inside their split. Each boundary force-settles open inventory with exit costs. Plan stops/targets stay anchored to the signal close; invalid next-open fills are skipped. Trade fills include adverse slip, both fees, steps/ticks, notional/cash/exposure caps and a daily realized-loss cutoff.

The choice is frozen from training before validation/test. Negative training still produces a diagnostic candidate with `training_pass=false`, never a promoted strategy. Validation does not pick a replacement. Different-fingerprint tests overlapping any previously inspected training/validation/test period are marked exploratory and cannot qualify. This registry is local evidence tracking, not a security boundary against someone rewriting files.

Qualification requires positive training/validation evidence, sufficient test trades, improvement over baseline, positive results on at least two assets, bounded drawdown, positive doubled-cost net and a positive lower95%block-bootstrap bound on pooled daily mean PnL. A pass permits only further forward-paper research; it is not an order approval or a calibrated next-trade probability. The ordinary paper execution CLI remains available for explicitly requested execution tests; these research gates are not a global execution kill switch.

The first60-day pilot was **rejected**: every candidate lost money in training, and the frozen diagnostic candidate also lost money on validation/test. See [actual results](E:/coding/code/Trade/crypto-trader-skills/PROFIT-RESEARCH-RESULTS.md). No strategy defaults were promoted. Do not describe smaller losses as proven profitability or silently reuse the final dates for retuning.

Limits: current exchange filters rather than historical rule snapshots;5m bar execution without depth, queues, latency or impact; short time/regime coverage; independently simulated assets; no news alpha or MiroFish calibration. Historical evidence and synthetic stress are separate. Existing manual paper entries remain execution tests and are excluded from strategy qualification.

## Replaying the completed pilot after later runtime changes

The prior calculation source is preserved under `research/pilot-20261114-60d-v1/frozen-code/`, with its original code hash and SHA256 manifest. Later paper-exit changes intentionally invalidate that old code hash in the current package; do not rewrite the old specification. To inspect/replay the unchanged completed result with the frozen version:

```powershell
Set-Location "E:\coding\code\Trade\crypto-trader-skills\research\pilot-20261114-60d-v1\frozen-code"
& "E:\coding\code\Trade\crypto-trader-skills\.venv\Scripts\python.exe" -m crypto_skills.validation evaluate --workspace "E:\coding\code\Trade\crypto-trader-skills\research\pilot-20261114-60d-v1"
```

This reuses the original completed result. Current code belongs in a new research workspace; already inspected dates remain ineligible as fresh tests.
