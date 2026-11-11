# Day Trader Skill — Taiwan integration (phase 1)

Upstream: https://github.com/Jakeschincariol/day-trader-skill (MIT license).
This is an independent, Taiwan-market adaptation of the scanner/entry/risk concepts,
not a drop-in import of the upstream US-market tools.

## Included
- Pure, deterministic OHLCV signal evaluator: 20-bar breakout/breakdown with volume confirmation.
- Incomplete or malformed data rejected; no network calls or broker dependencies.
- Research-only output: `tradable: false` always.
- Unit tests for breakout, neutral, missing and invalid bars.

## Excluded / next steps
- No US ticker universe, Nasdaq sessions, SEC news or Alpaca broker integration.
- No connection to live quote feeds or current multifactor ranking yet.
- No day-trading order placement, auto-trading, or brokerage authorization.
- Add Taiwan-specific historical intraday feed, market calendar, backtest and
  fee-aware signal validation before enabling any paper order suggestion.
- Existing LINE recommendations and fundamental filters remain unchanged.
