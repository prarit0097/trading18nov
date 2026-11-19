# NVDA Time Machine result

Run fetched at 2026-11-16T15:33:20.977698+00:00. Repository commit: 3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd.

## What was simulated

The refreshed current session was **waiting**, with no live ORB entry. This is therefore a **historical triggered-trade replay**, not today's trade and not a fabricated live signal. Searching backward through full sessions, 2026-11-13 had no qualifying entry by 15:30 ET; the latest qualifying session was 2026-11-12.

The repository's own trader-entry selected the 09:55 five-minute candle closing at 10:00 AM ET. The opening range was $148.80-$162.33. trader-exit generated the default midpoint stop and 2R target:

| Input | Value |
|---|---|
| Historical entry | $162.66 |
| Stop | $155.56 |
| Target | $176.86 |
| Risk per share | $7.10 (1R) |
| Exit cutoff | 15:55 ET |
| Replays / seed | 10,000 / 19 |
| Source pool | 57 full sessions, 2026-08-24 through 2026-11-11 |

## Output, unchanged from the tool

```text
NVDA buy, Thursday 2026-11-12: entry 162.66 at 10:00 AM (bar 5), stop 155.56, target 176.86 (2R, risk 7.10 a share).
10,000 replays of the rest of the session, 10:00 AM to 3:55 PM (71 five-minute bars), seed 19.
Each bar is drawn whole from NVDA's own 5-min bars at the same time of day (+-2 bars) over its last 57 full sessions (2026-08-24 to 2026-11-11).

  target first   0.0 %
  stop first     0.4 %
  neither        99.6 %   still open at 3:55 PM
  green          38.0 %   target first, or above the entry at 3:55 PM

  Price at 3:55 PM: median 161.93, 90 % of replays between 158.24 and 165.52.
  Average R: -0.102 (R = the 7.10 risk: +2R at the target, -1R at the stop).

History: the same rule (15-min opening range, stop at the opening-range midpoint, 2R target) on each of those 57 real sessions fired 32 times: 2 target, 16 stop, 14 neither. Average R -0.258.

Strongly toward the stop: at 2R the target has to come first in 33 % of the replays that hit one side; it did in 2 % (target first 0.0 % vs stop first 0.4 %).
99.6 % of the replays hit neither by 3:55 PM; the price at 3:55 PM decides those.

A simulation built from NVDA's own last 57 full sessions. It is not a prediction: earnings, news and halts can do things those sessions never did. Same seed, same numbers. Repeat this run with --seed 19.
```

## How to read this result

Almost all simulations reached the time cutoff without touching either boundary. The tool's stop-lean verdict is conditional on the very small subset that hit a boundary; it does not mean most simulations hit the stop. Its displayed 0.0% target figure is rounded to one decimal, not proof that zero runs reached the target. At 15:55 ET the strategy would exit even when neither boundary had been hit. Average R is negative in both the Monte Carlo and the historical rule replay. No positive edge is established by these outputs.

The four probabilities overlap only in the intended way: target/stop/neither are mutually exclusive; green is an additional measure, not a fourth exclusive outcome. The price distribution describes simulated underlying prices at cutoff, including paths after a simulated stop/target event; it is not the distribution of realized exit prices or dollar profits.

## Evidence and limits

- `NVDA-60d5m.json` is the unmodified Yahoo response downloaded for this run. The CLI's `--offline` flag reuses that captured response for reproducibility; it is not a synthetic fixture. Fetch URL and SHA-256 are in `metadata.json`.
- `commands.json` records the exact exit-plan, Time Machine and saved-chart commands. Raw stdout/stderr are retained. `trader/timemachine.json` contains full results; `03-chart.stdout.txt` contains the tool's fan chart.
- Source code was unchanged. No budget sizing, risk approval, broker order, fill or actual account was used. The example configuration only supplied the existing strategy defaults.
- The pool excludes the selected entry date and every later date. A second 10,000-run verification, with the clock cut back to the historical entry close, produced identical Monte Carlo and history results. Data hash, probability totals, historical outcome totals and absent order artifacts were checked; see `verification.json`.
- This is the tool's last-60-day bootstrap simulation, not a prediction or an independent out-of-sample performance study. Data are unofficial five-minute Yahoo bars, not execution ticks. Commissions, slippage, spread, liquidity and gap-through-stop losses are not fully modeled; the simulator scores a stop as -1R even when a real fill could be worse.
- Recent news was fetched in the preceding live test but its headlines were not independently verified. No external news claim was used to justify this historical simulation.

Source: [repository Time Machine skill](https://github.com/jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/SKILL.md).
