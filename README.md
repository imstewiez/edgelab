# CoreEA EdgeLab v1

Standalone local-first algo/quant research lab for CoreEA.

This repository is intentionally separate from `imstewiez/gangsta-bot-web-44`.

## What v1 does

EdgeLab v1 is a unified research lab that can:

- Upload MT5 CSV/ZIP market data
- Validate data health
- Build feature caches
- Automatically discover strategy candidates
- Rank candidate edges with anti-overfit checks
- Separate accepted/rejected edges with readable reasons
- Show simple dashboard cards instead of raw confusing tables
- Prevent duplicate spam jobs and multiple-click job floods
- Keep all market data local and private
- Run without paid databases

## Important

This is a production-candidate research environment, not a live-trading guarantee. Any edge must still pass walk-forward, slippage/spread stress, Monte Carlo and portfolio tests before becoming an EA module.

## Quick start

```powershell
INSTALL_ALL.bat
START_ENGINE.bat
START_WEB.bat
```

Open:

```text
http://localhost:5173
```

## Workflow

1. Upload market data.
2. Run **Discover Edges**.
3. Review **Candidate Edges** and **Rejected Ideas**.
4. Use Risk Lab before EA export.

## Local data

Everything under `data/` is ignored by Git. Do not commit market data, CSVs, ZIPs, reports, cache files or strategy outputs.
