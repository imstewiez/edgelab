# FX Trading Bot

Research-first systematic trading system for FX markets via MetaTrader 5.

## Setup

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Ensure MetaTrader 5 is installed and you have a live/demo account with DPrime.

3. Discover exact symbol names on your broker:
   ```bash
   python src/discover_symbols.py --search NAS
   python src/discover_symbols.py --search XAU
   ```

4. Edit `config/settings.json` with correct `mt5_name` values for your broker.

5. Run data ingestion:
   ```bash
   python src/main.py --ingest
   ```

## Project Structure

```
fx-trading-bot/
├── config/
│   └── settings.json          # Symbols, timeframes, risk parameters
├── data/
│   ├── raw/                   # Parquet files from MT5
│   ├── processed/             # Cleaned/feature-engineered datasets
│   └── market_data.db         # SQLite catalog of available data
├── src/
│   ├── main.py                # Entry point
│   ├── data_ingestion.py      # MT5 data pipeline
│   ├── database.py            # Data catalog & tracking
│   ├── discover_symbols.py    # MT5 symbol discovery
│   └── logger.py              # Logging utilities
└── notebooks/                 # Jupyter notebooks for research
```

## Philosophy

- **Edge first, execution second.** We prove alpha exists in data before risking capital.
- **Broker-specific data.** We ingest from the same MT5 terminal we trade on.
- **Risk by design.** Kill switches, position limits, and drawdown circuit breakers are core infrastructure, not afterthoughts.
