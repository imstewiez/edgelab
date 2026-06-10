//+------------------------------------------------------------------+
//| CoreEA Multi-Strategy Portfolio EA                                |
//| MT5 Expert Advisor                                                |
//|                                                                  |
//| Strategies:                                                       |
//| 1) Compression Breakout                                           |
//| 2) EMA Pullback                                                   |
//| 3) Sweep Reclaim                                                  |
//|                                                                  |
//| SAFE DEFAULT: PaperMode=true and AllowLiveTrading=false.          |
//| Switch only on demo first.                                        |
//+------------------------------------------------------------------+
#property strict
#property version   "1.000"
#property description "CoreEA Multi-Strategy Portfolio EA for MT5"

#include <Trade/Trade.mqh>

input bool   PaperMode              = true;
input bool   AllowLiveTrading        = false;
input string TradeSymbol             = "AUDUSD";
input ENUM_TIMEFRAMES SignalTF       = PERIOD_M5;
input double RiskPercent             = 0.50;
input int    MagicBase               = 880000;
input int    MaxSpreadPoints         = 25;
input int    MaxOpenPositionsSymbol  = 1;
input int    SessionStartHour        = 13;
input int    SessionEndHour          = 17;
input bool   UseSessionFilter        = true;
input bool   DebugSignals            = true;
input string LogFileName             = "CoreEA_MultiStrategy_Portfolio.csv";

input bool   EnableCompressionBreakout = true;
input int    CB_LookbackBars           = 48;
input int    CB_ATRPeriod              = 14;
input double CB_StopATRMult            = 2.0;
input double CB_TakeProfitR            = 2.5;
input int    CB_ATRRankBars            = 500;
input int    CB_RangeRankBars          = 200;
input double CB_ATRCompressionRankMax  = 0.35;
input double CB_RangeCompressionRankMax= 0.45;
input int    CB_MaxBarsHold            = 72;

input bool   EnableEMAPullback         = true;
input int    PB_FastEMA                = 21;
input int    PB_SlowEMA                = 55;
input int    PB_ATRPeriod              = 14;
input double PB_StopATRMult            = 1.8;
input double PB_TakeProfitR            = 2.0;
input int    PB_MaxBarsHold            = 60;

input bool   EnableSweepReclaim        = true;
input int    SR_LookbackBars           = 24;
input int    SR_ATRPeriod              = 14;
input double SR_StopATRMult            = 1.7;
input double SR_TakeProfitR            = 2.2;
input int    SR_MaxBarsHold            = 48;

CTrade trade;
datetime lastBarTime = 0;

struct PaperTrade
{
   bool active;
   int strategy;
   int side;
   datetime entry_time;
   datetime entry_bar_time;
   double entry;
   double sl;
   double tp;
   double risk;
};

PaperTrade paper[3];

int cbAtrHandle = INVALID_HANDLE;
int cbEma21Handle = INVALID_HANDLE;
int cbEma55Handle = INVALID_HANDLE;

int pbAtrHandle = INVALID_HANDLE;
int pbFastHandle = INVALID_HANDLE;
int pbSlowHandle = INVALID_HANDLE;

int srAtrHandle = INVALID_HANDLE;

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Symbol != TradeSymbol)
      Print("Warning: chart symbol is ", _Symbol, " but TradeSymbol input is ", TradeSymbol);

   cbAtrHandle = iATR(TradeSymbol, SignalTF, CB_ATRPeriod);
   cbEma21Handle = iMA(TradeSymbol, SignalTF, 21, 0, MODE_EMA, PRICE_CLOSE);
   cbEma55Handle = iMA(TradeSymbol, SignalTF, 55, 0, MODE_EMA, PRICE_CLOSE);

   pbAtrHandle = iATR(TradeSymbol, SignalTF, PB_ATRPeriod);
   pbFastHandle = iMA(TradeSymbol, SignalTF, PB_FastEMA, 0, MODE_EMA, PRICE_CLOSE);
   pbSlowHandle = iMA(TradeSymbol, SignalTF, PB_SlowEMA, 0, MODE_EMA, PRICE_CLOSE);

   srAtrHandle = iATR(TradeSymbol, SignalTF, SR_ATRPeriod);

   if(cbAtrHandle == INVALID_HANDLE || cbEma21Handle == INVALID_HANDLE || cbEma55Handle == INVALID_HANDLE ||
      pbAtrHandle == INVALID_HANDLE || pbFastHandle == INVALID_HANDLE || pbSlowHandle == INVALID_HANDLE ||
      srAtrHandle == INVALID_HANDLE)
   {
      Print("Failed to create one or more indicator handles.");
      return INIT_FAILED;
   }

   for(int i = 0; i < 3; i++)
   {
      paper[i].active = false;
      paper[i].strategy = i + 1;
      paper[i].side = 0;
      paper[i].entry_time = 0;
      paper[i].entry_bar_time = 0;
      paper[i].entry = 0.0;
      paper[i].sl = 0.0;
      paper[i].tp = 0.0;
      paper[i].risk = 0.0;
   }

   EnsureLogHeader();
   Print("CoreEA Multi-Strategy Portfolio initialized. PaperMode=", PaperMode, " AllowLiveTrading=", AllowLiveTrading);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(cbAtrHandle != INVALID_HANDLE) IndicatorRelease(cbAtrHandle);
   if(cbEma21Handle != INVALID_HANDLE) IndicatorRelease(cbEma21Handle);
   if(cbEma55Handle != INVALID_HANDLE) IndicatorRelease(cbEma55Handle);
   if(pbAtrHandle != INVALID_HANDLE) IndicatorRelease(pbAtrHandle);
   if(pbFastHandle != INVALID_HANDLE) IndicatorRelease(pbFastHandle);
   if(pbSlowHandle != INVALID_HANDLE) IndicatorRelease(pbSlowHandle);
   if(srAtrHandle != INVALID_HANDLE) IndicatorRelease(srAtrHandle);
}

//+------------------------------------------------------------------+
void OnTick()
{
   if(_Symbol != TradeSymbol)
      return;

   ManagePaperTrades();

   datetime t = iTime(TradeSymbol, SignalTF, 0);
   if(t == 0)
      return;
   if(t == lastBarTime)
      return;

   lastBarTime = t;
   EvaluateSignals();
}

//+------------------------------------------------------------------+
void EvaluateSignals()
{
   if(Bars(TradeSymbol, SignalTF) < 800)
      return;

   if(UseSessionFilter && !InSession(1))
      return;

   int spread = (int)SymbolInfoInteger(TradeSymbol, SYMBOL_SPREAD);
   if(spread <= 0 || spread > MaxSpreadPoints)
      return;

   if(CountOpenPositionsForSymbol() >= MaxOpenPositionsSymbol)
      return;

   if(EnableCompressionBreakout && !IsStrategyActive(1))
      TryCompressionBreakout(spread);

   if(EnableEMAPullback && CountOpenPositionsForSymbol() < MaxOpenPositionsSymbol && !IsStrategyActive(2))
      TryEMAPullback(spread);

   if(EnableSweepReclaim && CountOpenPositionsForSymbol() < MaxOpenPositionsSymbol && !IsStrategyActive(3))
      TrySweepReclaim(spread);
}

//+------------------------------------------------------------------+
void TryCompressionBreakout(int spread)
{
   int shift = 1;
   double atr = BufferValue(cbAtrHandle, shift);
   double ema21 = BufferValue(cbEma21Handle, shift);
   double ema55 = BufferValue(cbEma55Handle, shift);
   if(atr <= 0 || ema21 <= 0 || ema55 <= 0) return;

   if(!IsCompressed(shift + 1)) return;

   double close = iClose(TradeSymbol, SignalTF, shift);
   double hi = HighestHigh(shift + 1, CB_LookbackBars);
   double lo = LowestLow(shift + 1, CB_LookbackBars);

   int side = 0;
   if(close > hi && ema21 > ema55) side = 1;
   if(close < lo && ema21 < ema55) side = -1;
   if(side == 0) return;

   OpenSignal(1, "compression_breakout", side, atr, CB_StopATRMult, CB_TakeProfitR, CB_MaxBarsHold, spread);
}

//+------------------------------------------------------------------+
void TryEMAPullback(int spread)
{
   int s1 = 1;
   int s2 = 2;
   double atr = BufferValue(pbAtrHandle, s1);
   double fast1 = BufferValue(pbFastHandle, s1);
   double slow1 = BufferValue(pbSlowHandle, s1);
   double fast2 = BufferValue(pbFastHandle, s2);
   double close1 = iClose(TradeSymbol, SignalTF, s1);
   double close2 = iClose(TradeSymbol, SignalTF, s2);
   double low1 = iLow(TradeSymbol, SignalTF, s1);
   double high1 = iHigh(TradeSymbol, SignalTF, s1);
   if(atr <= 0 || fast1 <= 0 || slow1 <= 0 || fast2 <= 0) return;

   int side = 0;
   if(fast1 > slow1 && low1 <= fast1 && close1 > fast1 && close1 > close2) side = 1;
   if(fast1 < slow1 && high1 >= fast1 && close1 < fast1 && close1 < close2) side = -1;
   if(side == 0) return;

   OpenSignal(2, "ema_pullback", side, atr, PB_StopATRMult, PB_TakeProfitR, PB_MaxBarsHold, spread);
}

//+------------------------------------------------------------------+
void TrySweepReclaim(int spread)
{
   int shift = 1;
   double atr = BufferValue(srAtrHandle, shift);
   if(atr <= 0) return;

   double prevHi = HighestHigh(shift + 1, SR_LookbackBars);
   double prevLo = LowestLow(shift + 1, SR_LookbackBars);
   double high = iHigh(TradeSymbol, SignalTF, shift);
   double low = iLow(TradeSymbol, SignalTF, shift);
   double close = iClose(TradeSymbol, SignalTF, shift);
   double open = iOpen(TradeSymbol, SignalTF, shift);

   int side = 0;
   if(low < prevLo && close > prevLo && close > open) side = 1;
   if(high > prevHi && close < prevHi && close < open) side = -1;
   if(side == 0) return;

   OpenSignal(3, "sweep_reclaim", side, atr, SR_StopATRMult, SR_TakeProfitR, SR_MaxBarsHold, spread);
}

//+------------------------------------------------------------------+
void OpenSignal(int strategy, string strategyName, int side, double atr, double stopMult, double takeProfitR, int maxBarsHold, int spread)
{
   double ask = SymbolInfoDouble(TradeSymbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(TradeSymbol, SYMBOL_BID);
   double entry = side == 1 ? ask : bid;
   double risk = atr * stopMult;
   if(risk <= 0) return;

   double sl = side == 1 ? entry - risk : entry + risk;
   double tp = side == 1 ? entry + risk * takeProfitR : entry - risk * takeProfitR;
   string sideName = side == 1 ? "long" : "short";
   int magic = MagicBase + strategy;

   LogEvent("SIGNAL", strategyName, sideName, entry, sl, tp, atr, spread, 0.0, "signal_detected");

   if(PaperMode || !AllowLiveTrading)
   {
      OpenPaper(strategy, side, entry, sl, tp, risk, strategyName, atr, spread);
      return;
   }

   if(CountOpenPositionsForSymbol() >= MaxOpenPositionsSymbol)
      return;

   trade.SetExpertMagicNumber(magic);
   double lots = CalcLots(risk);
   if(lots <= 0)
   {
      LogEvent("LIVE_SKIP", strategyName, sideName, entry, sl, tp, atr, spread, 0.0, "invalid_lot_size");
      return;
   }

   bool ok = side == 1 ? trade.Buy(lots, TradeSymbol, entry, sl, tp, strategyName)
                       : trade.Sell(lots, TradeSymbol, entry, sl, tp, strategyName);
   LogEvent(ok ? "LIVE_ORDER" : "LIVE_ERROR", strategyName, sideName, entry, sl, tp, atr, spread, 0.0, ok ? "order_sent" : trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
void OpenPaper(int strategy, int side, double entry, double sl, double tp, double risk, string strategyName, double atr, int spread)
{
   int idx = strategy - 1;
   if(idx < 0 || idx >= 3) return;

   paper[idx].active = true;
   paper[idx].strategy = strategy;
   paper[idx].side = side;
   paper[idx].entry_time = TimeCurrent();
   paper[idx].entry_bar_time = iTime(TradeSymbol, SignalTF, 0);
   paper[idx].entry = entry;
   paper[idx].sl = sl;
   paper[idx].tp = tp;
   paper[idx].risk = risk;

   LogEvent("PAPER_OPEN", strategyName, side == 1 ? "long" : "short", entry, sl, tp, atr, spread, 0.0, "paper_trade_opened");
}

//+------------------------------------------------------------------+
void ManagePaperTrades()
{
   for(int i = 0; i < 3; i++)
   {
      if(!paper[i].active) continue;

      string strategyName = StrategyName(paper[i].strategy);
      int maxHold = StrategyMaxBarsHold(paper[i].strategy);
      int barsHeld = BarsHeld(paper[i].entry_bar_time, paper[i].entry_time);
      double bid = SymbolInfoDouble(TradeSymbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(TradeSymbol, SYMBOL_ASK);
      double exitPrice = 0.0;
      string reason = "";

      if(paper[i].side == 1)
      {
         if(bid <= paper[i].sl) { exitPrice = paper[i].sl; reason = "paper_sl"; }
         else if(bid >= paper[i].tp) { exitPrice = paper[i].tp; reason = "paper_tp"; }
         else if(barsHeld >= maxHold) { exitPrice = bid; reason = StringFormat("paper_timeout_%d_bars", barsHeld); }
      }
      else if(paper[i].side == -1)
      {
         if(ask >= paper[i].sl) { exitPrice = paper[i].sl; reason = "paper_sl"; }
         else if(ask <= paper[i].tp) { exitPrice = paper[i].tp; reason = "paper_tp"; }
         else if(barsHeld >= maxHold) { exitPrice = ask; reason = StringFormat("paper_timeout_%d_bars", barsHeld); }
      }

      if(reason == "") continue;

      double r = paper[i].side * (exitPrice - paper[i].entry) / paper[i].risk;
      LogEvent("PAPER_CLOSE", strategyName, paper[i].side == 1 ? "long" : "short", paper[i].entry, paper[i].sl, paper[i].tp, 0.0, (int)SymbolInfoInteger(TradeSymbol, SYMBOL_SPREAD), r, reason);
      paper[i].active = false;
      paper[i].side = 0;
      paper[i].entry_bar_time = 0;
   }
}

//+------------------------------------------------------------------+
bool IsCompressed(int shift)
{
   double atrNow = BufferValue(cbAtrHandle, shift);
   if(atrNow <= 0) return false;

   int atrLess = 0, atrCount = 0;
   for(int i = shift; i < shift + CB_ATRRankBars; i++)
   {
      double v = BufferValue(cbAtrHandle, i);
      if(v <= 0) continue;
      atrCount++;
      if(v <= atrNow) atrLess++;
   }
   if(atrCount < 50) return false;
   double atrRank = (double)atrLess / (double)atrCount;

   double rangeNow = iHigh(TradeSymbol, SignalTF, shift) - iLow(TradeSymbol, SignalTF, shift);
   int rangeLess = 0, rangeCount = 0;
   for(int j = shift; j < shift + CB_RangeRankBars; j++)
   {
      double r = iHigh(TradeSymbol, SignalTF, j) - iLow(TradeSymbol, SignalTF, j);
      if(r <= 0) continue;
      rangeCount++;
      if(r <= rangeNow) rangeLess++;
   }
   if(rangeCount < 50) return false;
   double rangeRank = (double)rangeLess / (double)rangeCount;

   return atrRank < CB_ATRCompressionRankMax && rangeRank < CB_RangeCompressionRankMax;
}

//+------------------------------------------------------------------+
bool InSession(int shift)
{
   MqlDateTime dt;
   TimeToStruct(iTime(TradeSymbol, SignalTF, shift), dt);
   return dt.hour >= SessionStartHour && dt.hour < SessionEndHour;
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
double BufferValue(int handle, int shift)
{
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(handle, 0, shift, 1, buf) != 1)
      return 0.0;
   return buf[0];
}

//+------------------------------------------------------------------+
int CountOpenPositionsForSymbol()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != TradeSymbol) continue;
      long magic = PositionGetInteger(POSITION_MAGIC);
      if(magic >= MagicBase && magic <= MagicBase + 99)
         count++;
   }
   if(PaperMode || !AllowLiveTrading)
   {
      for(int j = 0; j < 3; j++)
         if(paper[j].active) count++;
   }
   return count;
}

//+------------------------------------------------------------------+
bool IsStrategyActive(int strategy)
{
   int idx = strategy - 1;
   if(idx >= 0 && idx < 3 && paper[idx].active)
      return true;

   int magic = MagicBase + strategy;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) == TradeSymbol && PositionGetInteger(POSITION_MAGIC) == magic)
         return true;
   }
   return false;
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
string StrategyName(int strategy)
{
   if(strategy == 1) return "compression_breakout";
   if(strategy == 2) return "ema_pullback";
   if(strategy == 3) return "sweep_reclaim";
   return "unknown";
}

//+------------------------------------------------------------------+
int StrategyMaxBarsHold(int strategy)
{
   if(strategy == 1) return CB_MaxBarsHold;
   if(strategy == 2) return PB_MaxBarsHold;
   if(strategy == 3) return SR_MaxBarsHold;
   return 48;
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
   FileWrite(h, "time", "event", "strategy", "symbol", "tf", "side", "entry", "sl", "tp", "atr", "spread_points", "result_R", "note");
   FileClose(h);
}

//+------------------------------------------------------------------+
void LogEvent(string eventType, string strategyName, string side, double entry, double sl, double tp, double atr, int spread, double resultR, string note)
{
   int h = FileOpen(LogFileName, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileSeek(h, 0, SEEK_END);
      FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS), eventType, strategyName, TradeSymbol, EnumToString(SignalTF), side, DoubleToString(entry, 5), DoubleToString(sl, 5), DoubleToString(tp, 5), DoubleToString(atr, 6), spread, DoubleToString(resultR, 4), note);
      FileClose(h);
   }

   if(DebugSignals || eventType == "LIVE_ERROR")
      Print(eventType, " ", strategyName, " ", side, " ", TradeSymbol, " R=", DoubleToString(resultR, 4), " ", note);
}
//+------------------------------------------------------------------+
