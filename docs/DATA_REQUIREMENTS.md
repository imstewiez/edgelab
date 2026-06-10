# Data Requirements

## OHLC data

Required columns:

```text
time, open, high, low, close
```

Optional:

```text
tick_volume, spread_points, real_volume
```

Filename convention:

```text
XAUUSD_M15_2020_2026.csv
NAS100_H4_2020_2026.csv
```

Supported timeframes:

```text
M1, M5, M15, M30, H1, H4, D1
```

## Tick data

Useful for:

- spread behavior
- slippage assumptions
- micro-volatility
- session spikes
- realistic scalping viability

Desired columns:

```text
time, bid, ask, last, volume
```

## DOM / Order Book

DOM is not normally available historically from MT5 unless the broker/provider supplies it.

For FX/CFDs:

- there is no single centralized order book
- broker DOM may be synthetic or broker-specific
- still useful as a live microstructure signal if recorded consistently

Desired DOM snapshot format:

```text
time, symbol, side, price, volume, level
```

Derived features:

```text
bid_depth
ask_depth
book_imbalance
top_level_spread
depth_slope
liquidity_change
large_order_presence
```

## Order/back/order-flow data

The user mentioned "Order back data". We should distinguish:

1. Account order history
   - actual executed trades
   - useful for slippage, fill quality, EA behavior

2. Order book/DOM
   - live liquidity levels
   - useful only if recorded or supplied

3. Market tick trades
   - last price/volume where available
   - many CFD brokers provide limited or synthetic volume

## Future recorder

We should add MT5 tools:

- OHLC exporter
- tick exporter
- DOM live recorder EA/script
- strategy report importer
- account execution history importer
