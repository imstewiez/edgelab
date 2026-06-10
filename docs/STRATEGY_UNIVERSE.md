# EdgeLab Strategy Universe

This is the research map for EdgeLab. It is deliberately broad, but every concept must eventually become a testable hypothesis.

## Important principle

No concept is accepted because it sounds smart. SMC, ICT, order blocks, fair value gaps, DOM imbalance, liquidity sweeps and classic indicators are all treated the same way:

```text
hypothesis → measurable rule → backtest → robustness validation → paper/live forward test → EA module
```

## Current active OHLC concepts

- EMA trend continuation
- Range breakout
- Compression breakout
- EMA21 pullback/reclaim
- Liquidity sweep/reclaim
- Previous-day high/low sweep
- Asian range breakout
- NY / London-NY session filters
- ATR volatility regime

## Planned OHLC concepts

- Break of structure
- Change of character
- Equal highs/lows sweep
- Order block retest
- Fair value gap rebalance
- Breaker block
- Mitigation block
- Premium/discount range filter
- VWAP pullback
- Bollinger / Z-score reversion
- Opening range breakout
- Chop/no-trade filter

## Tick / DOM concepts

These require actual tick/DOM data. They cannot be reliably reconstructed from candles.

- Order-book bid/ask imbalance
- Liquidity wall / depth slope
- Liquidity pull / cancellation pressure
- Spread pressure
- Trade-flow imbalance
- Absorption at level

## DOM data requirement

For MT5, DOM must be recorded live through MarketBook-style events, because historical candle exports do not contain full depth-of-market history. DOM also depends on the broker and instrument, especially in FX/CFD products.

Target schema:

```text
time, symbol, side, price, volume, level
```

Tick schema:

```text
time, symbol, bid, ask, last, volume
```

## Validation stages

1. Discovery screen
2. Robustness validation
3. Walk-forward matrix
4. Spread/slippage stress
5. Monte Carlo/path perturbation
6. Portfolio correlation and heat
7. Forward paper tracking
8. EA-ready approval
