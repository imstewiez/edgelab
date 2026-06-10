# EdgeLab Architecture

## Rule

This project is completely separate from the gangsbot/Ballas production app.

## No-cost design

EdgeLab uses:

- local FastAPI backend
- local file cache
- pandas pickle cache for speed
- React dashboard
- no paid database
- no cloud storage requirement

## Data flow

```text
Upload CSV/ZIP
  ↓
data/raw
  ↓
Import
  ↓
data/cache/*.pkl + data/catalog.csv
  ↓
Feature build
  ↓
data/features/*_features.pkl
  ↓
Research scans
  ↓
data/outputs/<scan_id>/
```

## Why local backend instead of browser-only

Browser-only research would be limited by memory and slow file parsing.

The local engine lets us:

- import large MT5 exports
- build cached features once
- run scans repeatedly
- later add tick/DOM/order book processing
- keep all data private/local
