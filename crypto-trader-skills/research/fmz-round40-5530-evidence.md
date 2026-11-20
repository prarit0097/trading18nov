# FMZ #5530 Inverse Fisher RSI compatibility evidence

The archived daily BTC USD-M strategy runs from 14 November 2022 to 20 November 2023, end exclusive. It combines a five-period RSI with a one-period WMA and an inverse Fisher transform. It opens a long on a crossover above 0.8. The short expression instead passes the Boolean result of a comparison to the numeric `crossunder` operand. [FMZ source](https://www.fmz.com/strategy/432783)

Strict Pine Compat rejects the mixed v4/v5 function spelling and bare color constants. Restoring matching v4 vocabulary exposes two remaining type diagnostics. FMZ specifies numeric operands for this function, and TradingView's legacy automatic casts travel from `int` to `float` to `bool`. Neither source documents the reverse Boolean-to-numeric conversion used in one diagnostic. [FMZ language reference](https://www.fmz.com/doc/9293) [TradingView legacy type system](https://www.tradingview.com/pine-script-docs/v5/language/type-system/)

Two diagnostic variants test an explicit 1/0 conversion and a -0.8 short threshold using 371 checksummed chart days per market. On these BTC inputs they submit the same 68 entries. On ETH the 1/0 conversion adds a short condition on 3 December 2022 and the variants submit 78 versus 76 entries. The 1440-minute and daily feed spellings agree in both numeric variants. Neither numeric substitute appears in the authored call. [Binance public archive](https://github.com/binance/binance-public-data)

Both Piner backends fail the literal source because of the bare color constants. With vocabulary repaired, the RSI request stays undefined and both entry plots stay zero, yet each backend records 739 synthetic closes on the 371-day BTC input. Binding the requested daily-equivalent feed still produces that anomaly. The equivalent explicit `if` guards and separate false-order controls all produce zero. Those traces diagnose the runtime, and the catalogue retains a Pending disposition without any performance rows.

## Reproduce

1. Place the pinned archive document into the Windows AppContainer scratch directory as `source-5530.md`. Use the Binance USD-M source archive receipts listed in the report.
2. Run `python -m research.fmz_round40_5530_stage HOURLY_ARCHIVES APP_CONTAINER_ROOT` from the project root.
3. Copy `fmz_round40_5530_runner.py` into the approved AppContainer scratch directory with the pinned compatibility runtime and existing `probe_1216` and `replay_2864` support. Execute via the isolated launcher.
4. Copy `5530-piner-input.json` and `fmz_round40_5530_alternate.mjs` into the pinned Piner AppContainer and execute the script. Retain both isolation receipts.
5. Run `python -m research.fmz_round40_5530 APP_CONTAINER_ROOT PINER_ROOT OUTPUT_JSON`. Repeating the finalizer yields identical bytes.
