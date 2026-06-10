from __future__ import annotations

# Research map only. This is not a promise that each idea is profitable.
# Concepts are grouped so EdgeLab can progressively test them with the right data type.

STRATEGY_UNIVERSE = {
    "trend": [
        {"id": "ema_trend_continuation", "name": "EMA trend continuation", "data": "ohlc", "status": "active"},
        {"id": "adx_trend_strength", "name": "ADX trend strength filter", "data": "ohlc", "status": "planned"},
        {"id": "higher_high_higher_low", "name": "HH/HL or LH/LL structure trend", "data": "ohlc", "status": "planned"},
        {"id": "multi_timeframe_alignment", "name": "D1/H4/H1 multi-timeframe alignment", "data": "ohlc", "status": "planned"},
    ],
    "breakout": [
        {"id": "range_breakout", "name": "Range breakout", "data": "ohlc", "status": "active"},
        {"id": "volatility_expansion_breakout", "name": "Compression to expansion breakout", "data": "ohlc", "status": "active"},
        {"id": "opening_range_breakout", "name": "Opening range breakout", "data": "ohlc", "status": "planned"},
        {"id": "asian_range_breakout", "name": "Asian range breakout", "data": "ohlc", "status": "active"},
        {"id": "previous_day_high_low_break", "name": "Previous day high/low break", "data": "ohlc", "status": "active"},
    ],
    "pullback": [
        {"id": "ema21_pullback", "name": "EMA21 pullback/reclaim", "data": "ohlc", "status": "active"},
        {"id": "vwap_pullback", "name": "VWAP pullback", "data": "ohlc/tick", "status": "planned"},
        {"id": "atr_pullback", "name": "ATR-normalized pullback", "data": "ohlc", "status": "planned"},
    ],
    "mean_reversion": [
        {"id": "rsi_extreme_reversion", "name": "RSI extreme mean reversion", "data": "ohlc", "status": "planned"},
        {"id": "bollinger_reversion", "name": "Bollinger band reversion", "data": "ohlc", "status": "planned"},
        {"id": "zscore_reversion", "name": "Z-score reversion", "data": "ohlc", "status": "planned"},
        {"id": "session_overextension_reversion", "name": "Session overextension reversion", "data": "ohlc", "status": "planned"},
    ],
    "smc_liquidity": [
        {"id": "liquidity_sweep_reclaim", "name": "Liquidity sweep and reclaim", "data": "ohlc", "status": "active"},
        {"id": "previous_day_sweep", "name": "Previous day high/low sweep", "data": "ohlc", "status": "active"},
        {"id": "equal_high_low_sweep", "name": "Equal highs/lows sweep", "data": "ohlc", "status": "planned"},
        {"id": "break_of_structure", "name": "Break of structure", "data": "ohlc", "status": "planned"},
        {"id": "change_of_character", "name": "Change of character", "data": "ohlc", "status": "planned"},
        {"id": "order_block_retest", "name": "Order block retest", "data": "ohlc", "status": "planned"},
        {"id": "fair_value_gap_rebalance", "name": "Fair value gap / imbalance rebalance", "data": "ohlc", "status": "planned"},
        {"id": "breaker_block", "name": "Breaker block", "data": "ohlc", "status": "planned"},
        {"id": "mitigation_block", "name": "Mitigation block", "data": "ohlc", "status": "planned"},
        {"id": "premium_discount_array", "name": "Premium/discount range filter", "data": "ohlc", "status": "planned"},
    ],
    "session_models": [
        {"id": "london_open", "name": "London open expansion", "data": "ohlc", "status": "planned"},
        {"id": "ny_open", "name": "New York open expansion", "data": "ohlc", "status": "active"},
        {"id": "london_ny_overlap", "name": "London/NY overlap", "data": "ohlc", "status": "active"},
        {"id": "rollover_filter", "name": "Rollover avoidance filter", "data": "ohlc/tick", "status": "planned"},
    ],
    "volatility_regime": [
        {"id": "atr_percentile", "name": "ATR percentile regime", "data": "ohlc", "status": "active"},
        {"id": "range_compression", "name": "Range compression", "data": "ohlc", "status": "active"},
        {"id": "volatility_expansion", "name": "Volatility expansion", "data": "ohlc", "status": "active"},
        {"id": "chop_filter", "name": "Chop/no-trade filter", "data": "ohlc", "status": "planned"},
    ],
    "microstructure_dom": [
        {"id": "book_imbalance", "name": "Order-book bid/ask imbalance", "data": "dom", "status": "requires_dom_recorder"},
        {"id": "depth_slope", "name": "Depth slope / liquidity wall", "data": "dom", "status": "requires_dom_recorder"},
        {"id": "liquidity_pull", "name": "Liquidity pull / cancellation pressure", "data": "dom", "status": "requires_dom_recorder"},
        {"id": "spread_pressure", "name": "Spread pressure", "data": "tick/dom", "status": "requires_tick_or_dom"},
        {"id": "trade_flow_imbalance", "name": "Trade-flow imbalance", "data": "tick", "status": "requires_tick_data"},
        {"id": "absorption", "name": "Absorption at level", "data": "tick/dom", "status": "requires_tick_or_dom"},
    ],
    "risk_management": [
        {"id": "fixed_fractional", "name": "Fixed fractional risk", "data": "backtest", "status": "planned"},
        {"id": "volatility_adjusted_sizing", "name": "Volatility-adjusted sizing", "data": "backtest", "status": "planned"},
        {"id": "equity_kill_switch", "name": "Equity kill switch", "data": "backtest", "status": "planned"},
        {"id": "loss_streak_reduction", "name": "Risk reduction after loss streak", "data": "backtest", "status": "planned"},
        {"id": "portfolio_heat", "name": "Portfolio heat cap", "data": "portfolio", "status": "planned"},
    ],
}


def get_strategy_universe():
    active = 0
    planned = 0
    dom_required = 0
    for group in STRATEGY_UNIVERSE.values():
        for item in group:
            if item["status"] == "active":
                active += 1
            elif "requires" in item["status"]:
                dom_required += 1
            else:
                planned += 1
    return {
        "groups": STRATEGY_UNIVERSE,
        "summary": {
            "groups": len(STRATEGY_UNIVERSE),
            "concepts": sum(len(v) for v in STRATEGY_UNIVERSE.values()),
            "active": active,
            "planned": planned,
            "requires_tick_or_dom": dom_required,
        },
        "warning": "SMC/ICT labels are treated as testable hypotheses, not proof of institutional order flow. DOM/tick ideas require real DOM/tick recordings before they can be validated.",
    }
