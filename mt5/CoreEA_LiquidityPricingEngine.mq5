//+------------------------------------------------------------------+
//| CoreEA Liquidity Pricing Engine                                   |
//| MT5 Expert Advisor                                                |
//|                                                                  |
//| Thesis: trade price delivery after liquidity raids, not generic    |
//| retail EMA/breakout entries.                                      |
//|                                                                  |
//| Modules:                                                          |
//| - Asian range liquidity sweep                                     |
//| - Previous day high/low sweep                                     |
//| - Reclaim close                                                   |
//| - Displacement candle filter                                      |
//| - Optional FVG/imbalance confirmation                             |
//| - Premium/discount filter                                         |
//|                                                                  |
//| SAFE DEFAULT: PaperMode=true and AllowLiveTrading=false.          |
//+------------------------------------------------------------------+
#property strict
#property version   "1.000"
#property description "CoreEA liquidity/pricing engine for MT5"

#include <Trade/Trade.mqh>

input bool   PaperMode                 = true;
input bool   AllowLiveTrading           = false;
input string TradeSymbol                = "AUDUSD";
input ENUM_TIMEFRAMES SignalTF          = PERIOD_M5;
input double RiskPercent                = 0.50;
input int    MagicNumber                = 990001;
input int    MaxSpreadPoints            = 25;
input int    MaxOpenPositions           = 1;
input bool   DebugSignals               = true;
input string LogFileName                = "CoreEA_LiquidityPricingEngine.csv";

// Session windows use broker/server time.
input int    AsiaStartHour              = 0;
input int    AsiaEndHour                = 7;
input int    TradeStartHour             = 7;
input int    TradeEndHour               = 17;
input bool   AvoidFridayLate            = true;
input int    FridayCutoffHour           = 16;

// Liquidity sources.
input bool   UseAsianRangeSweep         = true;
input bool   UsePreviousDaySweep        = true;
input int    EqualLevelLookback         = 36;
input double EqualLevelToleranceATR     = 0.12;

// Confirmation.
input int    ATRPeriod                  = 14;
input int    SwingLookback              = 5;
input double MinSweepATR                = 0.08;
input double MinBodyATR                 = 0.45;
input double MaxCloseWickRatio          = 0.55;
input bool   RequireDisplacement        = true;
input bool   RequireFVG                 = false;
input bool   RequirePremiumDiscount     = true;
input int    PremiumDiscountLookback    = 96;

// Execution.
input double SLBufferATR                = 0.18;
input double MinStopATR                 = 0.55;
input double MaxStopATR                 = 2.50;
input double TakeProfitR                = 2.0;
input int    MaxBarsHold                = 48;
input bool   OneTradePerLiquidityPool   = true;

CTrade trade;
int atrHandle = INVALID_HANDLE;
datetime lastBarTime = 0;
datetime lastAsianBullSweepDay = 0;
datetime lastAsianBearSweepDay = 0;
datetime lastPrevBullSweepDay = 0;
datetime lastPrevBearSweepDay = 0;

struct PaperTrade
{
   bool active;
   int side;
   datetime entry_time;
   datetime entry_bar_time;
   string setup;
   double entry;
   double sl;
   double tp;
   double risk;
};

PaperTrade paper;

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Symbol != TradeSymbol)
      Print("Warning: chart symbol is ", _Symbol, " but TradeSymbol input is ", TradeSymbol);

   atrHandle = iATR(TradeSymbol, SignalTF, ATRPeriod);
   if(atrHandle == INVALID_HANDLE)
   {
      Print("Failed to create ATR handle.");
      return INIT_FAILED;
   }

   paper.active = false;
   paper.side = 0;
   paper.entry_time = 0;
   paper.entry_bar_time = 0;
   paper.setup = "";
   paper.entry = 0.0;
   paper.sl = 0.0;
   paper.tp = 0.0;
   paper.risk = 0.0;

   trade.SetExpertMagicNumber(MagicNumber);
   EnsureLogHeader();
   Print("CoreEA Liquidity Pricing Engine initialized. PaperMode=", PaperMode, " AllowLiveTrading=", AllowLiveTrading);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(atrHandle != INVALID_HANDLE)
      IndicatorRelease(atrHandle);
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(_Symbol != TradeSymbol)
      return;

   ManagePaperTrade();

   datetime t = iTime(TradeSymbol, SignalTF, 0);
   if(t == 0 || t == lastBarTime)
      return;
   lastBarTime = t;

   EvaluateLiquiditySetup();
}

//+------------------------------------------------------------------+
void EvaluateLiquiditySetup()
{
   if(Bars(TradeSymbol, SignalTF) < 1000)
      return;

   if(!InTradingWindow(1))
      return;

   int spread = (int)SymbolInfoInteger(TradeSymbol, SYMBOL_SPREAD);
   if(spread <= 0 || spread > MaxSpreadPoints)
      return;

   if(HasOpenPositionOrPaper())
      return;

   double atr = ATR(1);
   if(atr <= 0)
      return;

   LiquidityLevels levels;
   if(!BuildLiquidityLevels(levels))
      return;

   int side = 0;
   string setup = "";
   double sweptLevel = 0.0;
   double sweepExtreme = 0.0;

   if(UseAsianRangeSweep)
   {
      if(DetectBullishSweep(levels.asiaLow, atr, sweepExtreme) && !AlreadyTradedPool("asia_bull"))
      {
         side = 1;
         setup = "asia_low_sweep_reclaim";
         sweptLevel = levels.asiaLow;
      }
      else if(DetectBearishSweep(levels.asiaHigh, atr, sweepExtreme) && !AlreadyTradedPool("asia_bear"))
      {
         side = -1;
         setup = "asia_high_sweep_reclaim";
         sweptLevel = levels.asiaHigh;
      }
   }

   if(side == 0 && UsePreviousDaySweep)
   {
      if(DetectBullishSweep(levels.prevDayLow, atr, sweepExtreme) && !AlreadyTradedPool("prev_bull"))
      {
         side = 1;
         setup = "prev_day_low_sweep_reclaim";
         sweptLevel = levels.prevDayLow;
      }
      else if(DetectBearishSweep(levels.prevDayHigh, atr, sweepExtreme) && !AlreadyTradedPool("prev_bear"))
      {
         side = -1;
         setup = "prev_day_high_sweep_reclaim";
         sweptLevel = levels.prevDayHigh;
      }
   }

   if(side == 0)
      return;

   if(RequireDisplacement && !HasDisplacement(side, atr))
   {
      Reject(setup, side, "no_displacement");
      return;
   }

   if(RequireFVG && !HasFVG(side))
   {
      Reject(setup, side, "no_fvg");
      return;
   }

   if(RequirePremiumDiscount && !PassesPremiumDiscount(side))
   {
      Reject(setup, side, "bad_premium_discount_location");
      return;
   }

   double ask = SymbolInfoDouble(TradeSymbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(TradeSymbol, SYMBOL_BID);
   double entry = side == 1 ? ask : bid;
   double buffer = atr * SLBufferATR;
   double sl = side == 1 ? sweepExtreme - buffer : sweepExtreme + buffer;
   double risk = MathAbs(entry - sl);

   if(risk < atr * MinStopATR)
   {
      sl = side == 1 ? entry - atr * MinStopATR : entry + atr * MinStopATR;
      risk = MathAbs(entry - sl);
   }

   if(risk > atr * MaxStopATR)
   {
      Reject(setup, side, "stop_too_wide");
      return;
   }

   double tp = side == 1 ? entry + risk * TakeProfitR : entry - risk * TakeProfitR;

   MarkPoolTraded(setup);
   OpenTradeOrPaper(setup, side, entry, sl, tp, risk, atr, spread, sweptLevel, sweepExtreme);
}

//+------------------------------------------------------------------+
struct LiquidityLevels
{
   double asiaHigh;
   double asiaLow;
   double prevDayHigh;
   double prevDayLow;
};

//+------------------------------------------------------------------+
bool BuildLiquidityLevels(LiquidityLevels &levels)
{
   levels.asiaHigh = -DBL_MAX;
   levels.asiaLow = DBL_MAX;
   levels.prevDayHigh = iHigh(TradeSymbol, PERIOD_D1, 1);
   levels.prevDayLow = iLow(TradeSymbol, PERIOD_D1, 1);

   datetime todayStart = DayStart(iTime(TradeSymbol, SignalTF, 1));
   for(int i = 1; i < 500; i++)
   {
      datetime bt = iTime(TradeSymbol, SignalTF, i);
      if(bt < todayStart)
         break;
      MqlDateTime dt;
      TimeToStruct(bt, dt);
      if(dt.hour >= AsiaStartHour && dt.hour < AsiaEndHour)
      {
         levels.asiaHigh = MathMax(levels.asiaHigh, iHigh(TradeSymbol, SignalTF, i));
         levels.asiaLow = MathMin(levels.asiaLow, iLow(TradeSymbol, SignalTF, i));
      }
   }

   if(levels.prevDayHigh <= 0 || levels.prevDayLow <= 0)
      return false;
   if(levels.asiaHigh == -DBL_MAX || levels.asiaLow == DBL_MAX)
      return false;
   return true;
}

//+------------------------------------------------------------------+
bool DetectBullishSweep(double level, double atr, double &sweepExtreme)
{
   int s = 1;
   double low = iLow(TradeSymbol, SignalTF, s);
   double close = iClose(TradeSymbol, SignalTF, s);
   double open = iOpen(TradeSymbol, SignalTF, s);
   double high = iHigh(TradeSymbol, SignalTF, s);
   if(level <= 0) return false;

   double sweepDepth = level - low;
   if(low < level && close > level && sweepDepth >= atr * MinSweepATR)
   {
      double range = high - low;
      double lowerWick = MathMin(open, close) - low;
      if(range <= 0) return false;
      if(lowerWick / range < 0.25) return false;
      sweepExtreme = low;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool DetectBearishSweep(double level, double atr, double &sweepExtreme)
{
   int s = 1;
   double high = iHigh(TradeSymbol, SignalTF, s);
   double low = iLow(TradeSymbol, SignalTF, s);
   double close = iClose(TradeSymbol, SignalTF, s);
   double open = iOpen(TradeSymbol, SignalTF, s);
   if(level <= 0) return false;

   double sweepDepth = high - level;
   if(high > level && close < level && sweepDepth >= atr * MinSweepATR)
   {
      double range = high - low;
      double upperWick = high - MathMax(open, close);
      if(range <= 0) return false;
      if(upperWick / range < 0.25) return false;
      sweepExtreme = high;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool HasDisplacement(int side, double atr)
{
   int s = 1;
   double open = iOpen(TradeSymbol, SignalTF, s);
   double close = iClose(TradeSymbol, SignalTF, s);
   double high = iHigh(TradeSymbol, SignalTF, s);
   double low = iLow(TradeSymbol, SignalTF, s);
   double body = MathAbs(close - open);
   double range = high - low;
   if(range <= 0 || atr <= 0) return false;
   if(body < atr * MinBodyATR) return false;
   if(body / range < (1.0 - MaxCloseWickRatio)) return false;
   if(side == 1 && close <= open) return false;
   if(side == -1 && close >= open) return false;

   if(side == 1)
      return close > HighestHigh(2, SwingLookback);
   return close < LowestLow(2, SwingLookback);
}

//+------------------------------------------------------------------+
bool HasFVG(int side)
{
   // Uses three closed candles: shifts 3,2,1.
   // Bullish imbalance: low of recent candle is above high two candles back.
   // Bearish imbalance: high of recent candle is below low two candles back.
   double high3 = iHigh(TradeSymbol, SignalTF, 3);
   double low3 = iLow(TradeSymbol, SignalTF, 3);
   double high1 = iHigh(TradeSymbol, SignalTF, 1);
   double low1 = iLow(TradeSymbol, SignalTF, 1);
   if(side == 1)
      return low1 > high3;
   if(side == -1)
      return high1 < low3;
   return false;
}

//+------------------------------------------------------------------+
bool PassesPremiumDiscount(int side)
{
   double hi = HighestHigh(1, PremiumDiscountLookback);
   double lo = LowestLow(1, PremiumDiscountLookback);
   double close = iClose(TradeSymbol, SignalTF, 1);
   if(hi <= lo) return false;
   double mid = (hi + lo) / 2.0;
   if(side == 1)
      return close <= mid;
   if(side == -1)
      return close >= mid;
   return false;
}

//+------------------------------------------------------------------+
void OpenTradeOrPaper(string setup, int side, double entry, double sl, double tp, double risk, double atr, int spread, double sweptLevel, double sweepExtreme)
{
   string sideName = side == 1 ? "long" : "short";
   string note = StringFormat("swept=%.5f extreme=%.5f", sweptLevel, sweepExtreme);
   LogEvent("SIGNAL", setup, sideName, entry, sl, tp, atr, spread, 0.0, note);

   if(PaperMode || !AllowLiveTrading)
   {
      paper.active = true;
      paper.side = side;
      paper.entry_time = TimeCurrent();
      paper.entry_bar_time = iTime(TradeSymbol, SignalTF, 0);
      paper.setup = setup;
      paper.entry = entry;
      paper.sl = sl;
      paper.tp = tp;
      paper.risk = risk;
      LogEvent("PAPER_OPEN", setup, sideName, entry, sl, tp, atr, spread, 0.0, "paper_liquidity_trade_opened");
      return;
   }

   trade.SetExpertMagicNumber(MagicNumber);
   double lots = CalcLots(risk);
   if(lots <= 0)
   {
      LogEvent("LIVE_SKIP", setup, sideName, entry, sl, tp, atr, spread, 0.0, "invalid_lot_size");
      return;
   }

   bool ok = side == 1 ? trade.Buy(lots, TradeSymbol, entry, sl, tp, setup)
                       : trade.Sell(lots, TradeSymbol, entry, sl, tp, setup);
   LogEvent(ok ? "LIVE_ORDER" : "LIVE_ERROR", setup, sideName, entry, sl, tp, atr, spread, 0.0, ok ? "order_sent" : trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
void ManagePaperTrade()
{
   if(!paper.active)
      return;

   double bid = SymbolInfoDouble(TradeSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(TradeSymbol, SYMBOL_ASK);
   double exitPrice = 0.0;
   string reason = "";
   int barsHeld = BarsHeld(paper.entry_bar_time, paper.entry_time);

   if(paper.side == 1)
   {
      if(bid <= paper.sl) { exitPrice = paper.sl; reason = "paper_sl"; }
      else if(bid >= paper.tp) { exitPrice = paper.tp; reason = "paper_tp"; }
      else if(barsHeld >= MaxBarsHold) { exitPrice = bid; reason = StringFormat("paper_timeout_%d_bars", barsHeld); }
   }
   else if(paper.side == -1)
   {
      if(ask >= paper.sl) { exitPrice = paper.sl; reason = "paper_sl"; }
      else if(ask <= paper.tp) { exitPrice = paper.tp; reason = "paper_tp"; }
      else if(barsHeld >= MaxBarsHold) { exitPrice = ask; reason = StringFormat("paper_timeout_%d_bars", barsHeld); }
   }

   if(reason == "")
      return;

   double r = paper.side * (exitPrice - paper.entry) / paper.risk;
   LogEvent("PAPER_CLOSE", paper.setup, paper.side == 1 ? "long" : "short", paper.entry, paper.sl, paper.tp, ATR(1), (int)SymbolInfoInteger(TradeSymbol, SYMBOL_SPREAD), r, reason);
   paper.active = false;
   paper.side = 0;
   paper.setup = "";
}

//+------------------------------------------------------------------+
bool HasOpenPositionOrPaper()
{
   if(paper.active)
      return true;

   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) == TradeSymbol && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         count++;
   }
   return count >= MaxOpenPositions;
}

//+------------------------------------------------------------------+
bool InTradingWindow(int shift)
{
   datetime t = iTime(TradeSymbol, SignalTF, shift);
   MqlDateTime dt;
   TimeToStruct(t, dt);
   if(dt.hour < TradeStartHour || dt.hour >= TradeEndHour)
      return false;
   if(AvoidFridayLate && dt.day_of_week == 5 && dt.hour >= FridayCutoffHour)
      return false;
   return true;
}

//+------------------------------------------------------------------+
datetime DayStart(datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   dt.hour = 0;
   dt.min = 0;
   dt.sec = 0;
   return StructToTime(dt);
}

//+------------------------------------------------------------------+
datetime CurrentDayKey()
{
   return DayStart(iTime(TradeSymbol, SignalTF, 1));
}

//+------------------------------------------------------------------+
bool AlreadyTradedPool(string pool)
{
   if(!OneTradePerLiquidityPool)
      return false;
   datetime d = CurrentDayKey();
   if(pool == "asia_bull") return lastAsianBullSweepDay == d;
   if(pool == "asia_bear") return lastAsianBearSweepDay == d;
   if(pool == "prev_bull") return lastPrevBullSweepDay == d;
   if(pool == "prev_bear") return lastPrevBearSweepDay == d;
   return false;
}

//+------------------------------------------------------------------+
void MarkPoolTraded(string setup)
{
   if(!OneTradePerLiquidityPool)
      return;
   datetime d = CurrentDayKey();
   if(setup == "asia_low_sweep_reclaim") lastAsianBullSweepDay = d;
   if(setup == "asia_high_sweep_reclaim") lastAsianBearSweepDay = d;
   if(setup == "prev_day_low_sweep_reclaim") lastPrevBullSweepDay = d;
   if(setup == "prev_day_high_sweep_reclaim") lastPrevBearSweepDay = d;
}

//+------------------------------------------------------------------+
void Reject(string setup, int side, string reason)
{
   if(!DebugSignals) return;
   LogEvent("REJECT", setup, side == 1 ? "long" : "short", 0, 0, 0, ATR(1), (int)SymbolInfoInteger(TradeSymbol, SYMBOL_SPREAD), 0.0, reason);
}

//+------------------------------------------------------------------+
double ATR(int shift)
{
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(atrHandle, 0, shift, 1, buf) != 1)
      return 0.0;
   return buf[0];
}

//+------------------------------------------------------------------+
double HighestHigh(int startShift, int count)
{
   double v = -DBL_MAX;
   for(int i = startShift; i < startShift + count; i++)
      v = MathMax(v, iHigh(TradeSymbol, SignalTF, i));
   return v;
}

//+------------------------------------------------------------------+
double LowestLow(int startShift, int count)
{
   double v = DBL_MAX;
   for(int i = startShift; i < startShift + count; i++)
      v = MathMin(v, iLow(TradeSymbol, SignalTF, i));
   return v;
}

//+------------------------------------------------------------------+
int BarsHeld(datetime entryBarTime, datetime entryTime)
{
   if(entryBarTime > 0)
   {
      int shift = iBarShift(TradeSymbol, SignalTF, entryBarTime, false);
      if(shift >= 0)
         return shift;
   }
   int seconds = PeriodSeconds(SignalTF);
   if(seconds <= 0) seconds = 300;
   return (int)((TimeCurrent() - entryTime) / seconds);
}

//+------------------------------------------------------------------+
double CalcLots(double riskPrice)
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = equity * RiskPercent / 100.0;
   double tickValue = SymbolInfoDouble(TradeSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(TradeSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(riskMoney <= 0 || tickValue <= 0 || tickSize <= 0 || riskPrice <= 0)
      return 0.0;

   double lossPerLot = riskPrice / tickSize * tickValue;
   if(lossPerLot <= 0) return 0.0;

   double lots = riskMoney / lossPerLot;
   double minLot = SymbolInfoDouble(TradeSymbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(TradeSymbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(TradeSymbol, SYMBOL_VOLUME_STEP);
   lots = MathMax(minLot, MathMin(maxLot, lots));
   lots = MathFloor(lots / step) * step;
   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
void EnsureLogHeader()
{
   int h = FileOpen(LogFileName, FILE_READ | FILE_CSV | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileClose(h);
      return;
   }
   h = FileOpen(LogFileName, FILE_WRITE | FILE_CSV | FILE_ANSI);
   if(h == INVALID_HANDLE) return;
   FileWrite(h, "time", "event", "setup", "symbol", "tf", "side", "entry", "sl", "tp", "atr", "spread_points", "result_R", "note");
   FileClose(h);
}

//+------------------------------------------------------------------+
void LogEvent(string eventType, string setup, string side, double entry, double sl, double tp, double atr, int spread, double resultR, string note)
{
   int h = FileOpen(LogFileName, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileSeek(h, 0, SEEK_END);
      FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS), eventType, setup, TradeSymbol, EnumToString(SignalTF), side, DoubleToString(entry, 5), DoubleToString(sl, 5), DoubleToString(tp, 5), DoubleToString(atr, 6), spread, DoubleToString(resultR, 4), note);
      FileClose(h);
   }

   if(DebugSignals || eventType == "LIVE_ERROR")
      Print(eventType, " ", setup, " ", side, " ", TradeSymbol, " R=", DoubleToString(resultR, 4), " ", note);
}
//+------------------------------------------------------------------+
