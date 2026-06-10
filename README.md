# CoreEA EdgeLab

Standalone local quant research dashboard for CoreEA.

This project is intentionally separate from `imstewiez/gangsta-bot-web-44`.

## What this is

EdgeLab is a local-first research platform:

- Web dashboard for uploads, datasets, scans and results
- Local Python research engine
- Local file-based cache, no paid database required
- Market data stays on your PC
- GitHub stores code only, not raw data

## Architecture

```text
coreea-edgelab/
  apps/web/       React dashboard
  apps/engine/    FastAPI local quant engine
  data/           local market data, ignored by Git
  docs/           architecture + data requirements
```

## Local storage

The engine stores data here:

```text
data/
  raw/
  cache/
  features/
  outputs/
```

These folders are ignored by Git.

## Install

### Engine

```powershell
cd apps/engine
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Web

```powershell
cd apps/web
npm install
```

## Run

Open two terminals.

### Terminal 1 — Engine

```powershell
cd apps/engine
.venv\Scripts\activate
uvicorn main:app --host 127.0.0.1 --port 8765 --reload
```

### Terminal 2 — Web

```powershell
cd apps/web
npm run dev
```

Open:

```text
http://localhost:5173
```

## Workflow

1. Upload raw MT5 CSV/ZIP files in the dashboard.
2. Run "Import Data".
3. Run "Build Features".
4. Run "Scan HTF" or "Scan Intraday".
5. Review candidate edges and reports.
6. Export strategy specs for EA development.

## Current research concepts

- H4/D1 breakout trend
- fast breakout
- EMA21 pullback/reclaim
- compression breakout
- sweep/reclaim
- previous-day sweep
- Asian breakout
- NY opening range breakout

## DOM / Order Book

Historical DOM usually cannot be reconstructed from candles. For MT5/CFD/FX, DOM is broker-specific. EdgeLab supports the structure for DOM imports later, but we need a live recorder to collect it going forward.

See `docs/DATA_REQUIREMENTS.md`.

## Important

Do not put market data into GitHub.

The `.gitignore` blocks:

- raw market data
- cached features
- DuckDB/parquet/pickle files
- reports/outputs
- zip/csv data files
