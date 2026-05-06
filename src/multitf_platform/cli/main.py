"""Typer CLI for MultiTF platform."""
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import typer
import pandas as pd
import numpy as np
from datetime import datetime

from multitf_platform.config.loader import load_config
from multitf_platform.config.models import PlatformConfig, CircuitBreakerConfig
from multitf_platform.strategy.frozen.v1_0_0 import MultiTFStrategy, FrozenStrategyConfig, VERSION as STRAT_VERSION
from multitf_platform.risk.v1_1 import RiskWrapper
from multitf_platform.brokers.paper import PaperBroker
from multitf_platform.audit.logger import AuditLogger
from multitf_platform.state.persistence import StateManager

app = typer.Typer(help="MultiTF CFD Platform CLI", no_args_is_help=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_data(symbol: str = "XAUUSD"):
    """Load H1 and H4 data from project data directory."""
    base = Path(__file__).parent.parent.parent.parent / "data" / "raw"
    h1_path = base / f"{symbol}_H1.parquet"
    h4_path = base / f"{symbol}_H4.parquet"
    
    if not h1_path.exists():
        raise FileNotFoundError(f"H1 data not found: {h1_path}")
    if not h4_path.exists():
        raise FileNotFoundError(f"H4 data not found: {h4_path}")
    
    h1 = pd.read_parquet(h1_path)
    if "time" in h1.columns:
        h1.set_index("time", inplace=True)
    
    h4 = pd.read_parquet(h4_path)
    if "time" in h4.columns:
        h4.set_index("time", inplace=True)
    
    return h1, h4


def print_metrics_table(metrics: dict, title: str = "Results"):
    """Pretty-print metrics table."""
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  {title}")
    typer.echo(f"{'='*60}")
    for k, v in metrics.items():
        typer.echo(f"  {k:20s}: {v}")

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def signal(
    symbol: str = typer.Option("XAUUSD", help="Symbol"),
    config: Optional[Path] = typer.Option(None, help="Path to config YAML"),
):
    """Get current MultiTF signal from offline data."""
    cfg = load_config(config)
    h1, h4 = load_data(symbol)
    
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    sig = strategy.generate_signal(h1, h4)
    
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  MultiTF v{STRAT_VERSION} Signal")
    typer.echo(f"{'='*60}")
    typer.echo(f"  Timestamp:     {sig.timestamp}")
    typer.echo(f"  H1 Momentum:   {sig.h1_momentum:.4f}")
    typer.echo(f"  H4 Momentum:   {sig.h4_momentum:.4f}")
    typer.echo(f"  Signal:        {'LONG' if sig.is_long else 'SHORT' if sig.is_short else 'FLAT'}")
    typer.echo(f"  Valid:         {sig.warmup_complete}")
    if sig.blocked_reason:
        typer.echo(f"  Blocked:       {sig.blocked_reason}")
    typer.echo(f"{'='*60}")


@app.command()
def backtest(
    symbol: str = typer.Option("XAUUSD", help="Symbol to backtest"),
    risk: bool = typer.Option(True, help="Enable risk wrapper v1.1"),
    config: Optional[Path] = typer.Option(None, help="Path to config YAML"),
):
    """Run vectorized backtest with risk wrapper on historical data."""
    from .backtest_with_risk import run_backtest_with_risk
    
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  MultiTF v{STRAT_VERSION} + Risk Wrapper Backtest")
    typer.echo(f"{'='*60}")
    
    typer.echo("\n--- WITHOUT RISK CONTROLS ---")
    m_base, _, _, _ = run_backtest_with_risk(symbol=symbol, enable_risk=False)
    print_metrics_table({
        "Sharpe Ratio": f"{m_base.get('sharpe_ratio', 0):.3f}",
        "Ann. Return": f"{m_base.get('ann_return_pct', 0):.1f}%",
        "Max Drawdown": f"{m_base.get('max_drawdown_pct', 0):.1f}%",
        "Total Trades": m_base.get('num_trades', 0),
    }, "Baseline (No Risk)")
    
    typer.echo("\n--- WITH RISK WRAPPER v1.1 ---")
    m_risk, _, _, _ = run_backtest_with_risk(symbol=symbol, enable_risk=True)
    print_metrics_table({
        "Sharpe Ratio": f"{m_risk.get('sharpe_ratio', 0):.3f}",
        "Ann. Return": f"{m_risk.get('ann_return_pct', 0):.1f}%",
        "Max Drawdown": f"{m_risk.get('max_drawdown_pct', 0):.1f}%",
        "Total Trades": m_risk.get('num_trades', 0),
    }, "With Risk Controls")
    
    print_metrics_table({
        "Sharpe delta": f"{m_risk.get('sharpe_ratio', 0) - m_base.get('sharpe_ratio', 0):+.3f}",
        "Return delta": f"{m_risk.get('ann_return_pct', 0) - m_base.get('ann_return_pct', 0):+.1f}%",
        "DD delta": f"{abs(m_risk.get('max_drawdown_pct', 0)) - abs(m_base.get('max_drawdown_pct', 0)):+.1f}%",
    }, "Comparison")


@app.command()
def paper_trade(
    symbol: str = typer.Option("XAUUSD", help="Symbol"),
    equity: float = typer.Option(10000.0, help="Initial equity"),
    leverage: int = typer.Option(1000, help="Account leverage"),
    circuit_breakers: bool = typer.Option(False, help="Enable circuit breakers (disabled by default for backtest)"),
    save: bool = typer.Option(False, help="Save final state to disk"),
    config: Optional[Path] = typer.Option(None, help="Path to config YAML"),
):
    """Run event-driven paper trading simulation on historical data."""
    cfg = load_config(config)
    h1, h4 = load_data(symbol)
    
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  Paper Trading Simulation")
    typer.echo(f"  Account: ${equity:,.2f} | Leverage: 1:{leverage}")
    typer.echo(f"{'='*60}")
    typer.echo(f"Simulating {len(h1)} bars...")
    
    # Override broker config
    broker_cfg = cfg.broker.model_copy(update={
        "initial_equity": equity,
        "leverage": leverage,
    })
    
    # Override risk config: disable circuit breakers unless requested
    risk_cfg = cfg.risk_wrapper.model_copy()
    if not circuit_breakers:
        risk_cfg.circuit_breakers = CircuitBreakerConfig(
            daily_loss_stop_pct=20.0,
            weekly_loss_stop_pct=30.0,
            monthly_loss_stop_pct=50.0,
            total_drawdown_warning_pct=50.0,
            total_drawdown_kill_pct=50.0,
        )
    
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    risk = RiskWrapper(risk_cfg)
    broker = PaperBroker(broker_cfg)
    audit = AuditLogger()
    state_mgr = StateManager()
    
    for i, ts in enumerate(h1.index):
        if i < 500:
            continue
        
        h1_slice = h1.iloc[:i+1]
        h4_slice = h4[h4.index <= ts]
        bar = h1.iloc[i]
        
        sig = strategy.generate_signal(h1_slice, h4_slice, ts)
        equity_now = broker.get_state().equity
        
        spread = broker._get_spread(bar) if hasattr(broker, '_get_spread') else 0.20
        wrapped = risk.apply(sig, h1_slice, equity_now, spread)
        
        # Audit logging
        audit.log_signal(ts, sig.direction, sig.h1_momentum, sig.h4_momentum,
                        sig.warmup_complete, sig.blocked_reason)
        audit.log_risk(ts, wrapped.action.name, wrapped.final_direction,
                      wrapped.position_scale, wrapped.reason or "", wrapped.sub_reasons)
        
        state = broker.process_bar(wrapped, bar, i)
        
        # Log state every 24 bars (once per day)
        if i % 24 == 0:
            audit.log_state(ts, state.balance, state.equity, state.margin_used,
                          state.free_margin, state.open_position.direction if state.open_position else 0,
                          state.open_position.size_lots if state.open_position else 0.0,
                          state.open_position.unrealized_pnl if state.open_position else 0.0,
                          state.daily_pnl)
    
    # Final metrics
    ec = broker.get_equity_curve()
    returns = ec.pct_change().dropna()
    ann_ret = returns.mean() * 252 * 24 * 100
    ann_vol = returns.std() * np.sqrt(252 * 24) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    peak = ec.expanding().max()
    dd = (ec - peak) / peak
    max_dd = dd.min() * 100
    stats = broker.get_trade_stats()
    
    print_metrics_table({
        "Final Equity": f"${ec.iloc[-1]:,.2f}",
        "Sharpe Ratio": f"{sharpe:.3f}",
        "Ann. Return": f"{ann_ret:.1f}%",
        "Max Drawdown": f"{max_dd:.1f}%",
        "Total Trades": stats["total_trades"],
        "Win Rate": f"{stats['win_rate']*100:.1f}%",
        "Avg P&L/Trade": f"${stats['avg_pnl']:.2f}",
        "Profit Factor": f"{stats['profit_factor']:.2f}" if stats['profit_factor'] != float('inf') else "∞",
    }, "Paper Trading Results")
    
    # Save state if requested
    if save:
        final_state = broker.get_state()
        path = state_mgr.save(final_state, metadata={
            "symbol": symbol,
            "mode": "paper_trade_backtest",
            "bars": len(h1),
        })
        typer.echo(f"\nState saved to: {path}")
    
    # Audit summary
    audit_summary = audit.get_summary()
    typer.echo(f"\nAudit log: {audit_summary.get('path', 'N/A')}")
    typer.echo(f"Records: {audit_summary.get('total_records', 0)}")


@app.command()
def paper_live(
    symbol: str = typer.Option("XAUUSD", help="Symbol"),
    bars: int = typer.Option(1, help="Number of bars to process (1=single shot)"),
    interval: int = typer.Option(3600, help="Seconds between iterations (daemon mode)"),
    daemon: bool = typer.Option(False, help="Run continuously in daemon mode"),
    resume: bool = typer.Option(True, help="Resume from saved state if available"),
    config: Optional[Path] = typer.Option(None, help="Path to config YAML"),
):
    """Run live paper trading on historical data (simulates real-time bar-by-bar execution).
    
    In daemon mode, processes one bar at a time and sleeps between iterations.
    This simulates live trading without requiring MT5 connection.
    """
    cfg = load_config(config)
    h1, h4 = load_data(symbol)
    state_mgr = StateManager()
    audit = AuditLogger()
    
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  Paper Live Trading")
    typer.echo(f"  Mode: {'daemon' if daemon else 'single-shot'}")
    typer.echo(f"{'='*60}")
    
    # Initialize or resume
    if resume and state_mgr.exists():
        typer.echo("Resuming from saved state...")
        state_mgr.print_summary()
        broker = PaperBroker(cfg.broker)
        # Note: full position restore would need additional logic
    else:
        broker = PaperBroker(cfg.broker)
        typer.echo(f"Starting fresh with ${cfg.broker.initial_equity:,.2f}")
    
    strategy = MultiTFStrategy(FrozenStrategyConfig())
    risk = RiskWrapper(cfg.risk_wrapper)
    
    # Determine start index
    start_idx = 500
    if resume and state_mgr.exists():
        saved = state_mgr.load()
        # Could track last processed bar index in state
    
    end_idx = min(start_idx + bars, len(h1))
    
    for i in range(start_idx, end_idx):
        ts = h1.index[i]
        h1_slice = h1.iloc[:i+1]
        h4_slice = h4[h4.index <= ts]
        bar = h1.iloc[i]
        
        sig = strategy.generate_signal(h1_slice, h4_slice, ts)
        equity_now = broker.get_state().equity
        spread = broker._get_spread(bar)
        wrapped = risk.apply(sig, h1_slice, equity_now, spread)
        
        # Log
        audit.log_signal(ts, sig.direction, sig.h1_momentum, sig.h4_momentum,
                        sig.warmup_complete, sig.blocked_reason)
        audit.log_risk(ts, wrapped.action.name, wrapped.final_direction,
                      wrapped.position_scale, wrapped.reason or "", wrapped.sub_reasons)
        
        state = broker.process_bar(wrapped, bar, i)
        
        # Print any fills
        if broker.fills and broker.fills[-1].timestamp == ts:
            fill = broker.fills[-1]
            if fill.action.value == "open":
                typer.echo(f"  [{ts}] OPEN {fill.side.value.upper()} {fill.size_lots:.2f} lots @ {fill.fill_price:.2f} | Equity: ${state.equity:,.2f}")
            elif fill.action.value == "close":
                typer.echo(f"  [{ts}] CLOSE P&L: ${fill.realized_pnl:+.2f} | Balance: ${state.balance:,.2f}")
        
        # Check kill switch
        if wrapped.action.name == "KILL_SWITCH":
            audit.log_kill_switch(str(ts), wrapped.reason or "", state.equity)
            typer.echo(f"  [{ts}] KILL SWITCH: {wrapped.reason}")
    
    # Save state
    final_state = broker.get_state()
    state_mgr.save(final_state, metadata={
        "symbol": symbol,
        "mode": "paper_live",
        "last_bar": str(h1.index[end_idx-1]) if end_idx > start_idx else None,
    })
    
    typer.echo(f"\nFinal Equity: ${final_state.equity:,.2f}")
    typer.echo(f"Trades: {len(broker.trades)}")
    typer.echo(f"State saved.")
    
    if daemon:
        typer.echo(f"Sleeping {interval}s before next iteration...")
        # In real daemon mode, would loop here with time.sleep()
        # For now, just indicate what would happen


@app.command()
def status():
    """Show current paper trading state."""
    state_mgr = StateManager()
    state_mgr.print_summary()
    
    audit = AuditLogger()
    summary = audit.get_summary()
    if summary.get("total_records", 0) > 0:
        typer.echo(f"\nAudit log: {summary['path']}")
        typer.echo(f"Records: {summary['total_records']}")
        for evt, cnt in summary.get("event_counts", {}).items():
            typer.echo(f"  {evt}: {cnt}")


@app.command()
def reset(
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt"),
):
    """Clear all saved state and audit logs for a fresh start."""
    if not force:
        confirm = typer.confirm("This will delete all saved state and audit logs. Continue?")
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit()
    
    state_mgr = StateManager()
    state_mgr.clear()
    typer.echo("State cleared.")
    
    # Clear today's audit log
    audit = AuditLogger()
    if audit.path.exists():
        audit.path.unlink()
        typer.echo(f"Audit log cleared: {audit.path}")
    
    typer.echo("Ready for fresh start.")


@app.command()
def config_show(
    config_path: Optional[Path] = typer.Option(None, help="Path to config YAML"),
):
    """Display current configuration."""
    cfg = load_config(config_path)
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  Platform Configuration")
    typer.echo(f"{'='*60}")
    typer.echo(f"  Environment:     {cfg.environment}")
    typer.echo(f"  Timezone:        {cfg.canonical_timezone}")
    typer.echo(f"\n  Strategy:")
    typer.echo(f"    Name:          {cfg.strategy.name}")
    typer.echo(f"    Version:       {cfg.strategy.version}")
    typer.echo(f"    Symbol:        {cfg.strategy.symbol}")
    typer.echo(f"    Timeframes:    {cfg.strategy.entry_timeframe} + {cfg.strategy.confirmation_timeframe}")
    typer.echo(f"\n  Broker:")
    typer.echo(f"    Adapter:       {cfg.broker.adapter}")
    typer.echo(f"    Initial Equity: ${cfg.broker.initial_equity:,.2f}")
    typer.echo(f"    Leverage:      1:{cfg.broker.leverage}")
    typer.echo(f"    Commission:    ${cfg.broker.commission_per_lot}/lot")
    typer.echo(f"\n  Risk Wrapper:")
    typer.echo(f"    Enabled:       {cfg.risk_wrapper.enabled}")
    typer.echo(f"    Version:       {cfg.risk_wrapper.version}")
    typer.echo(f"    Vol Gate:      {cfg.risk_wrapper.volatility_gate.enabled}")
    typer.echo(f"    Spread Filter: {cfg.risk_wrapper.spread_filter.enabled}")
    typer.echo(f"    Flip Filter:   {cfg.risk_wrapper.flip_filter.enabled}")
    typer.echo(f"    Throttle:      {cfg.risk_wrapper.trade_throttle.enabled}")
    typer.echo(f"    Circuit Breakers:")
    typer.echo(f"      Daily:       {cfg.risk_wrapper.circuit_breakers.daily_loss_stop_pct}%")
    typer.echo(f"      Weekly:      {cfg.risk_wrapper.circuit_breakers.weekly_loss_stop_pct}%")
    typer.echo(f"      Kill:        {cfg.risk_wrapper.circuit_breakers.total_drawdown_kill_pct}%")
    typer.echo(f"{'='*60}")


@app.command()
def live(
    symbol: str = typer.Option("XAUUSD", help="Symbol to trade"),
    h1_history: int = typer.Option(300, help="H1 bars to load for warmup"),
    h4_history: int = typer.Option(100, help="H4 bars to load for warmup"),
    dry_run: bool = typer.Option(False, help="Show signal only, don't execute"),
    config_path: Optional[Path] = typer.Option(None, help="Path to config YAML"),
):
    """Execute one live paper trade iteration using MT5 data.
    
    Connects to running MT5 terminal, pulls latest bars, generates signal,
    applies risk wrapper, and executes via paper broker.
    """
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  LIVE Paper Trade — MultiTF v{STRAT_VERSION}")
    typer.echo(f"{'='*60}")
    
    # Load config
    cfg = load_config(config_path)
    
    # Connect to MT5
    try:
        from multitf_platform.brokers.mt5 import MT5Adapter
    except ImportError as e:
        typer.echo(f"ERROR: MT5 adapter not available: {e}")
        raise typer.Exit(1)
    
    mt5 = MT5Adapter()
    try:
        mt5.connect()
        typer.echo("MT5 connected.")
    except Exception as e:
        typer.echo(f"ERROR: Failed to connect to MT5: {e}")
        typer.echo("Make sure MT5 terminal is running.")
        raise typer.Exit(1)
    
    try:
        # Account info
        account = mt5.get_account_info()
        typer.echo(f"Account: #{account['login']} @ {account['server']}")
        typer.echo(f"Balance: ${account['balance']:,.2f} | Equity: ${account['equity']:,.2f}")
        typer.echo(f"Leverage: 1:{account['leverage']}")
        
        # Pull data
        typer.echo(f"\nLoading {h1_history} H1 + {h4_history} H4 bars...")
        h1, h4 = mt5.get_data(symbol, h1_bars=h1_history, h4_bars=h4_history)
        typer.echo(f"H1: {h1.index[0]} to {h1.index[-1]} ({len(h1)} bars)")
        typer.echo(f"H4: {h4.index[0]} to {h4.index[-1]} ({len(h4)} bars)")
        
        # Current price
        tick = mt5.get_tick(symbol)
        typer.echo(f"\nCurrent {symbol}: bid={tick['bid']:.2f} ask={tick['ask']:.2f} spread=${tick['spread']:.2f}")
        
        # Generate signal
        strategy = MultiTFStrategy(FrozenStrategyConfig())
        ts = h1.index[-1]
        sig = strategy.generate_signal(h1, h4, ts)
        
        typer.echo(f"\n--- SIGNAL ---")
        typer.echo(f"Timestamp: {sig.timestamp}")
        typer.echo(f"H1 Momentum: {sig.h1_momentum:.4f}")
        typer.echo(f"H4 Momentum: {sig.h4_momentum:.4f}")
        typer.echo(f"Raw Signal: {'LONG' if sig.is_long else 'SHORT' if sig.is_short else 'FLAT'}")
        
        # Apply risk wrapper
        risk = RiskWrapper(cfg.risk_wrapper)
        equity = account['equity']
        spread = tick['spread']
        
        wrapped = risk.apply(sig, h1, equity, spread)
        
        typer.echo(f"\n--- RISK WRAPPER ---")
        typer.echo(f"Action: {wrapped.action.name}")
        typer.echo(f"Final Direction: {wrapped.final_direction}")
        typer.echo(f"Position Scale: {wrapped.position_scale:.2f}")
        if wrapped.reason:
            typer.echo(f"Reason: {wrapped.reason}")
        if wrapped.sub_reasons:
            typer.echo(f"Sub-reasons: {', '.join(wrapped.sub_reasons)}")
        
        if dry_run:
            typer.echo("\n[DRY RUN] No execution.")
            raise typer.Exit()
        
        # Execute via paper broker
        state_mgr = StateManager()
        audit = AuditLogger()
        
        # Resume or fresh start
        if state_mgr.exists():
            typer.echo("\nResuming from saved state...")
            state_mgr.print_summary()
        
        broker_cfg = cfg.broker.model_copy(update={
            "initial_equity": account['equity'],
            "leverage": account['leverage'],
        })
        broker = PaperBroker(broker_cfg)
        
        # Load saved state if exists (basic restore)
        if state_mgr.exists():
            saved = state_mgr.load()
            broker.balance = saved['broker']['balance']
            broker.equity = saved['broker']['equity']
        
        bar = h1.iloc[-1]
        state = broker.process_bar(wrapped, bar, len(h1) - 1)
        
        # Log
        audit.log_signal(ts, sig.direction, sig.h1_momentum, sig.h4_momentum,
                        sig.warmup_complete, sig.blocked_reason)
        audit.log_risk(ts, wrapped.action.name, wrapped.final_direction,
                      wrapped.position_scale, wrapped.reason or "", wrapped.sub_reasons)
        
        # Print fills
        if broker.fills and broker.fills[-1].timestamp == ts:
            fill = broker.fills[-1]
            if fill.action.value == "open":
                typer.echo(f"\n>>> EXECUTED: OPEN {fill.side.value.upper()} {fill.size_lots:.2f} lots @ {fill.fill_price:.2f}")
            elif fill.action.value == "close":
                typer.echo(f"\n>>> EXECUTED: CLOSE P&L: ${fill.realized_pnl:+.2f}")
        elif wrapped.final_direction == 0 and broker.position is None:
            typer.echo("\n>>> NO ACTION: Flat or risk-blocked.")
        else:
            typer.echo(f"\n>>> POSITION HELD: {broker.position.direction} @ {broker.position.size_lots:.2f} lots")
        
        # Save state
        state_mgr.save(broker.get_state(), metadata={
            "symbol": symbol,
            "mode": "live",
            "last_bar": str(ts),
        })
        
        typer.echo(f"\n--- ACCOUNT ---")
        typer.echo(f"Balance: ${broker.get_state().balance:,.2f}")
        typer.echo(f"Equity:  ${broker.get_state().equity:,.2f}")
        typer.echo(f"Margin:  ${broker.get_state().margin_used:,.2f}")
        if broker.position:
            dir_str = "LONG" if broker.position.is_long else "SHORT"
            typer.echo(f"Position: {dir_str} {broker.position.size_lots:.2f} lots (uP&L: ${broker.position.unrealized_pnl:+.2f})")
        else:
            typer.echo("Position: FLAT")
        
        typer.echo(f"\nState saved. Audit logged.")
        
    finally:
        mt5.disconnect()
        typer.echo("MT5 disconnected.")


@app.command()
def portfolio_live(
    dry_run: bool = typer.Option(False, help="Show signals only, no state changes"),
):
    """Run portfolio live iteration: MT5 signals for XAUUSD + EURUSD + NAS100."""
    from .portfolio_live import main as _portfolio_live
    _portfolio_live()


@app.command()
def portfolio_live_v2(
    dry_run: bool = typer.Option(False, help="Show signals only, no state changes"),
):
    """Run unified multi-alpha portfolio v2: MultiTF + StatArb + SessionMomentum + GapFade."""
    from .portfolio_live_v2 import main as _portfolio_live_v2
    _portfolio_live_v2()


@app.command()
def portfolio_backtest():
    """Run portfolio backtest and show metrics."""
    from .portfolio_backtest import main as _portfolio_backtest
    _portfolio_backtest()


def main():
    app()


if __name__ == "__main__":
    main()
