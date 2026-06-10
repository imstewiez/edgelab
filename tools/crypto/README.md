# Crypto Order Book Collection

Crypto order books are easier than FX/CFD DOM because many exchanges expose public order-book APIs and WebSocket feeds.

## Recommended approach

For production-quality crypto order-book history:

1. Take an initial REST depth snapshot.
2. Subscribe to WebSocket depth updates.
3. Apply updates in sequence.
4. Persist snapshots or deltas locally.
5. Periodically resync if update sequence breaks.

## EdgeLab target schema

### Snapshot rows

```text
time, exchange, symbol, side, price, quantity, level
```

### Delta rows

```text
time, exchange, symbol, first_update_id, final_update_id, side, price, quantity
```

## Important

For crypto, order book is exchange-specific. Binance BTCUSDT order book is not the same as Coinbase BTC-USD order book. EdgeLab should keep exchange in the symbol identity.
