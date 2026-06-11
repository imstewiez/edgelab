//+------------------------------------------------------------------+
//| CoreEA Liquidity Engine V3 - Scored                               |
//| MT5 Expert Advisor                                                |
//|                                                                  |
//| Clean liquidity/pricing EA with scored confirmation instead of     |
//| brittle all-or-nothing gates.                                     |
//|                                                                  |
//| Mandatory condition: liquidity raid + reclaim.                    |
//| Score components:                                                  |
//| - HTF bias                                                        |
//| - displacement                                                    |
//| - FVG / imbalance                                                 |
//| - premium/discount location                                       |
//| - strong sweep depth                                              |
//|                                                                  |
//| Goal: avoid the old portfolio overtrading while producing enough   |
//| trades to evaluate a real edge.                                   |
//+------------------------------------------------------------------+
#property strict
#property version   "3.000"
#property description "CoreEA Liquidity Engine V3 Scored - single-symbol liquidity EA"

#include <Trade/Trade.mqh>

input bool   AllowLiveTrading           = false;
input bool   ExecuteInTester            = true;
input string TradeSymbol                = "";          // Empty = chart symbol
input ENUM_TIMEFRAMES SignalTF          = PERIOD_M15;
input ENUM_TIMEFRAMES BiasTF            = PERIOD_H1;
input double BaseRiskPercent            = 0.15;
input int    MagicNumber                = 993000;
input bool   DebugSignals               = true;
input string LogFileName                = "CoreEA_LiquidityEngineV3_Scored.csv";

// Sessions use broker/server time plus SessionTimeShiftHours.
input int    SessionTimeShiftHours      = 0;
input int    AsiaStartHour              = 0;
input int    AsiaEndHour                = 7;
input int    TradeStartHour             = 7;
input int    TradeEndHour               = 18;
input bool   AvoidFridayLate            = true;
input int    FridayCutoffHour           = 16;

// Liquidity pools. Defaults avoid noisy equal-high/low and previous-week spam.
input bool   UseAsianRange              = true;
input bool   UsePreviousDay             = true;
input bool   UsePreviousWeek            = false;
input bool   UseEqualHighLow            = false;
input int    EqualLevelLookback         = 48;
input double EqualToleranceATR          = 0.10;

// Scoring system.
input bool   UseScoredEntry             = true;
input int    MinSignalScore             = 5;
input bool   RequireStructureShift      = true;         // requires displacement OR FVG
input int    ATRPeriod                  = 14;
input int    BiasRangeLookback          = 48;
input int    DisplacementBreakLookback  = 4;
input int    FVGSearchLookback          = 6;
input int    PremiumDiscountLookback    = 96;
input double StrongSweepATR             = 0.22;

// Optional hard filters. In scored mode these are score components unless set as hard filters below.
input bool   HardRequireHTFBias         = false;
input bool   HardRequireDisplacement    = false;
input bool   HardRequireFVG             = false;
input bool   HardRequirePremiumDiscount = false;

// Risk/execution. 0 values use symbol profile.
input int    MaxSpreadPoints            = 0;
input int    MaxPositionsPerSymbol      = 1;
input int    MaxTradesPerSymbolPerDay   = 2;
input double MinSweepATR                = 0.0;
input double MinBodyATR                 = 0.0;
input double SLBufferATR                = 0.0;
input double MinStopATR                 = 0.0;
input double MaxStopATR                 = 0.0;
input double TakeProfitR                = 0.0;
input int    MaxBarsHold                = 0;
input bool   MoveToBreakeven            = true;
input double BreakevenAtR               = 0.85;
input double BreakevenPlusPoints        = 2.0;

CTrade trade;
string Sym;
int atrHandle = INVALID_HANDLE;
datetime lastBarTime = 0;
datetime lastTradeDay = 0;
int tradesToday = 0;
datetime lastPoolTradeDay[6];

struct Profile
{
   string bucket;
   double riskPercent;
   int maxSpreadPoints;
   double minSweepATR;
   double minBodyATR;
   double slBufferATR;
   double minStopATR;
   double maxStopATR;
   double takeProfitR;
   int maxBarsHold;
};

struct LiquidityLevels
{
   double asiaHigh;
   double asiaLow;
   double prevDayHigh;
   double prevDayLow;
   double prevWeekHigh;
   double prevWeekLow;
   double equalHigh;
   double equalLow;
};

//+------------------------------------------------------------------+
int OnInit()
{
   Sym = TradeSymbol == "" ? _Symbol : TradeSymbol;
   if(!SymbolSelect(Sym, true))
   {
      Print("Cannot select symbol: ", Sym);
      return INIT_FAILED;
   }

   atrHandle = iATR(Sym, SignalTF, ATRPeriod);
   if(atrHandle == INVALID_HANDLE)
   {
      Print("Failed ATR handle for ", Sym);
      return INIT_FAILED;
   }

   for(int i = 0; i < 6; i++)
      lastPoolTradeDay[i] = 0;

   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   EnsureLogHeader();

   Profile p;
   BuildProfile(Sym, p);
   Print("CoreEA Liquidity Engine V3 initialized. Symbol=", Sym,
         " SignalTF=", EnumToString(SignalTF),
         " BiasTF=", EnumToString(BiasTF),
         " Bucket=", p.bucket,
         " MinScore=", MinSignalScore,
         " MaxTradesPerDay=", MaxTradesPerSymbolPerDay,
         " AllowLiveTrading=", AllowLiveTrading,
         " ExecuteInTester=", ExecuteInTester,
         " MQL_TESTER=", (bool)MQLInfoInteger(MQL_TESTER));
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
   if(TradeSymbol == "" && _Symbol != Sym)
      return;

   ManageOpenPosition();

   datetime t = iTime(Sym, SignalTF, 0);
   if(t == 0 || t == lastBarTime)
      return;
   lastBarTime = t;

   ResetDailyCounterIfNeeded();
   EvaluateNewBar();
}

//+------------------------------------------------------------------+
void EvaluateNewBar()
{
   if(Bars(Sym, SignalTF) < 1000 || Bars(Sym, BiasTF) < 200)
      return;

   Profile p;
   BuildProfile(Sym, p);

   if(!InTradeWindow(1))
      return;

   int spread = (int)SymbolInfoInteger(Sym, SYMBOL_SPREAD);
   if(spread <= 0 || spread > p.maxSpreadPoints)
      return;

   if(CountOpenPositions() >= MaxPositionsPerSymbol)
      return;

   if(tradesToday >= MaxTradesPerSymbolPerDay)
      return;

   double atr = ATR(1);
   if(atr <= 0)
      return;

   LiquidityLevels lv;
   if(!BuildLiquidityLevels(lv))
      return;

   int side = 0;
   int poolId = -1;
   string setup = "";
   double sweptLevel = 0.0;
   double extreme = 0.0;
   double sweepDepthATR = 0.0;

   if(UseAsianRange)
   {
      if(DetectBullishSweep(lv.asiaLow, atr, p, extreme, sweepDepthATR) && !PoolTradedToday(0))
      {
         side = 1; poolId = 0; setup = "asia_low_raid_reclaim"; sweptLevel = lv.asiaLow;
      }
      else if(DetectBearishSweep(lv.asiaHigh, atr, p, extreme, sweepDepthATR) && !PoolTradedToday(1))
      {
         side = -1; poolId = 1; setup = "asia_high_raid_reclaim"; sweptLevel = lv.asiaHigh;
      }
   }

   if(side == 0 && UsePreviousDay)
   {
      if(DetectBullishSweep(lv.prevDayLow, atr, p, extreme, sweepDepthATR) && !PoolTradedToday(2))
      {
         side = 1; poolId = 2; setup = "prev_day_low_raid_reclaim"; sweptLevel = lv.prevDayLow;
      }
      else if(DetectBearishSweep(lv.prevDayHigh, atr, p, extreme, sweepDepthATR) && !PoolTradedToday(3))
      {
         side = -1; poolId = 3; setup = "prev_day_high_raid_reclaim"; sweptLevel = lv.prevDayHigh;
      }
   }

   if(side == 0 && UsePreviousWeek)
   {
      if(DetectBullishSweep(lv.prevWeekLow, atr, p, extreme, sweepDepthATR) && !PoolTradedToday(4))
      {
         side = 1; poolId = 4; setup = "prev_week_low_raid_reclaim"; sweptLevel = lv.prevWeekLow;
      }
      else if(DetectBearishSweep(lv.prevWeekHigh, atr, p, extreme, sweepDepthATR) && !PoolTradedToday(5))
      {
         side = -1; poolId = 5; setup = "prev_week_high_raid_reclaim"; sweptLevel = lv.prevWeekHigh;
      }
   }

   if(side == 0 && UseEqualHighLow)
   {
      if(DetectBullishSweep(lv.equalLow, atr, p, extreme, sweepDepthATR))
      {
         side = 1; poolId = 0; setup = "equal_lows_raid_reclaim"; sweptLevel = lv.equalLow;
      }
      else if(DetectBearishSweep(lv.equalHigh, atr, p, extreme, sweepDepthATR))
      {
         side = -1; poolId = 1; setup = "equal_highs_raid_reclaim"; sweptLevel = lv.equalHigh;
      }
   }

   if(side == 0)
      return;

   bool htf = PassesHTFBias(side);
   bool disp = HasDisplacement(side, atr, p);
   bool fvg = HasFVG(side);
   bool pd = PassesPremiumDiscount(side);
   bool strongSweep = sweepDepthATR >= StrongSweepATR;

   if(HardRequireHTFBias && !htf) { Reject(setup, side, "hard_htf_bias_fail"); return; }
   if(HardRequireDisplacement && !disp) { Reject(setup, side, "hard_no_displacement"); return; }
   if(HardRequireFVG && !fvg) { Reject(setup, side, "hard_no_fvg"); return; }
   if(HardRequirePremiumDiscount && !pd) { Reject(setup, side, "hard_bad_premium_discount"); return; }
   if(RequireStructureShift && !disp && !fvg) { Reject(setup, side, "no_structure_shift"); return; }

   int score = 0;
   if(htf) score += 2;
   if(disp) score += 2;
   if(fvg) score += 2;
   if(pd) score += 1;
   if(strongSweep) score += 1;

   if(UseScoredEntry && score < MinSignalScore)
   {
      Reject(setup, side, StringFormat("score_too_low_%d", score));
      return;
   }

   double ask = SymbolInfoDouble(Sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(Sym, SYMBOL_BID);
   if(ask <= 0 || bid <= 0)
      return;

   double entry = side == 1 ? ask : bid;
   double sl = side == 1 ? extreme - atr * p.slBufferATR : extreme + atr * p.slBufferATR;
   double risk = MathAbs(entry - sl);

   if(risk < atr * p.minStopATR)
   {
      sl = side == 1 ? entry - atr * p.minStopATR : entry + atr * p.minStopATR;
      risk = MathAbs(entry - sl);
   }

   if(risk > atr * p.maxStopATR)
   {
      Reject(setup, side, "stop_too_wide");
      return;
   }

   double tp = side == 1 ? entry + risk * p.takeProfitR : entry - risk * p.takeProfitR;

   if(poolId >= 0 && poolId < 6)
      lastPoolTradeDay[poolId] = CurrentDayKey();
   lastTradeDay = CurrentDayKey();
   tradesToday++;

   string note = StringFormat("score=%d htf=%d disp=%d fvg=%d pd=%d strong=%d sweepATR=%.2f",
                              score, htf, disp, fvg, pd, strongSweep, sweepDepthATR);
   SendOrder(setup, side, entry, sl, tp, risk, atr, spread, p, note);
}

//+------------------------------------------------------------------+
void BuildProfile(string sym, Profile &p)
{
   string s = ToUpper(sym);
   p.bucket = "majors_fx";
   p.riskPercent = BaseRiskPercent;
   p.maxSpreadPoints = MaxSpreadPoints > 0 ? MaxSpreadPoints : 25;
   p.minSweepATR = MinSweepATR > 0 ? MinSweepATR : 0.05;
   p.minBodyATR = MinBodyATR > 0 ? MinBodyATR : 0.44;
   p.slBufferATR = SLBufferATR > 0 ? SLBufferATR : 0.18;
   p.minStopATR = MinStopATR > 0 ? MinStopATR : 0.60;
   p.maxStopATR = MaxStopATR > 0 ? MaxStopATR : 2.80;
   p.takeProfitR = TakeProfitR > 0 ? TakeProfitR : 1.65;
   p.maxBarsHold = MaxBarsHold > 0 ? MaxBarsHold : 36;

   if(StringFind(s, "XAU") >= 0 || StringFind(s, "GOLD") >= 0)
   {
      p.bucket = "metals";
      p.riskPercent = BaseRiskPercent * 0.70;
      p.maxSpreadPoints = MaxSpreadPoints > 0 ? MaxSpreadPoints : 90;
      p.minSweepATR = MinSweepATR > 0 ? MinSweepATR : 0.05;
      p.minBodyATR = MinBodyATR > 0 ? MinBodyATR : 0.52;
      p.slBufferATR = SLBufferATR > 0 ? SLBufferATR : 0.24;
      p.minStopATR = MinStopATR > 0 ? MinStopATR : 0.80;
      p.maxStopATR = MaxStopATR > 0 ? MaxStopATR : 3.40;
      p.takeProfitR = TakeProfitR > 0 ? TakeProfitR : 1.80;
      p.maxBarsHold = MaxBarsHold > 0 ? MaxBarsHold : 44;
   }
   else if(StringFind(s, "JPY") >= 0)
   {
      p.bucket = "jpy_fx";
      p.maxSpreadPoints = MaxSpreadPoints > 0 ? MaxSpreadPoints : 38;
      p.minBodyATR = MinBodyATR > 0 ? MinBodyATR : 0.48;
      p.maxStopATR = MaxStopATR > 0 ? MaxStopATR : 3.00;
      p.takeProfitR = TakeProfitR > 0 ? TakeProfitR : 1.70;
      p.maxBarsHold = MaxBarsHold > 0 ? MaxBarsHold : 40;
   }
   else if(StringFind(s, "GBP") >= 0)
   {
      p.bucket = "gbp_fx";
      p.riskPercent = BaseRiskPercent * 0.85;
      p.maxSpreadPoints = MaxSpreadPoints > 0 ? MaxSpreadPoints : 32;
      p.minBodyATR = MinBodyATR > 0 ? MinBodyATR : 0.48;
      p.maxStopATR = MaxStopATR > 0 ? MaxStopATR : 3.00;
      p.takeProfitR = TakeProfitR > 0 ? TakeProfitR : 1.75;
   }
   else if(StringFind(s, "AUD") >= 0 || StringFind(s, "NZD") >= 0)
   {
      p.bucket = "aud_nzd_fx";
      p.maxSpreadPoints = MaxSpreadPoints > 0 ? MaxSpreadPoints : 30;
      p.takeProfitR = TakeProfitR > 0 ? TakeProfitR : 1.65;
   }
}

//+------------------------------------------------------------------+
bool BuildLiquidityLevels(LiquidityLevels &lv)
{
   lv.asiaHigh = -DBL_MAX;
   lv.asiaLow = DBL_MAX;
   lv.prevDayHigh = iHigh(Sym, PERIOD_D1, 1);
   lv.prevDayLow = iLow(Sym, PERIOD_D1, 1);
   lv.prevWeekHigh = iHigh(Sym, PERIOD_W1, 1);
   lv.prevWeekLow = iLow(Sym, PERIOD_W1, 1);
   lv.equalHigh = UseEqualHighLow ? FindEqualHigh() : 0.0;
   lv.equalLow = UseEqualHighLow ? FindEqualLow() : 0.0;

   datetime todayStart = DayStart(AdjustedTime(iTime(Sym, SignalTF, 1)));
   for(int i = 1; i < 300; i++)
   {
      datetime bt = iTime(Sym, SignalTF, i);
      if(bt <= 0 || AdjustedTime(bt) < todayStart)
         break;
      MqlDateTime dt;
      TimeToStruct(AdjustedTime(bt), dt);
      if(dt.hour >= AsiaStartHour && dt.hour < AsiaEndHour)
      {
         lv.asiaHigh = MathMax(lv.asiaHigh, iHigh(Sym, SignalTF, i));
         lv.asiaLow = MathMin(lv.asiaLow, iLow(Sym, SignalTF, i));
      }
   }

   if(UseAsianRange && (lv.asiaHigh == -DBL_MAX || lv.asiaLow == DBL_MAX))
      return false;
   if(UsePreviousDay && (lv.prevDayHigh <= 0 || lv.prevDayLow <= 0))
      return false;
   if(UsePreviousWeek && (lv.prevWeekHigh <= 0 || lv.prevWeekLow <= 0))
      return false;
   return true;
}

//+------------------------------------------------------------------+
bool DetectBullishSweep(double level, double atr, Profile &p, double &extreme, double &sweepDepthATR)
{
   if(level <= 0 || atr <= 0) return false;
   int s = 1;
   double low = iLow(Sym, SignalTF, s);
   double high = iHigh(Sym, SignalTF, s);
   double open = iOpen(Sym, SignalTF, s);
   double close = iClose(Sym, SignalTF, s);
   double range = high - low;
   if(range <= 0) return false;
   double sweepDepth = level - low;
   double lowerWick = MathMin(open, close) - low;
   sweepDepthATR = sweepDepth / atr;
   if(low < level && close > level && sweepDepthATR >= p.minSweepATR && lowerWick / range >= 0.22)
   {
      extreme = low;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool DetectBearishSweep(double level, double atr, Profile &p, double &extreme, double &sweepDepthATR)
{
   if(level <= 0 || atr <= 0) return false;
   int s = 1;
   double low = iLow(Sym, SignalTF, s);
   double high = iHigh(Sym, SignalTF, s);
   double open = iOpen(Sym, SignalTF, s);
   double close = iClose(Sym, SignalTF, s);
   double range = high - low;
   if(range <= 0) return false;
   double sweepDepth = high - level;
   double upperWick = high - MathMax(open, close);
   sweepDepthATR = sweepDepth / atr;
   if(high > level && close < level && sweepDepthATR >= p.minSweepATR && upperWick / range >= 0.22)
   {
      extreme = high;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool PassesHTFBias(int side)
{
   double hi = -DBL_MAX;
   double lo = DBL_MAX;
   for(int i = 1; i <= BiasRangeLookback; i++)
   {
      hi = MathMax(hi, iHigh(Sym, BiasTF, i));
      lo = MathMin(lo, iLow(Sym, BiasTF, i));
   }
   double close = iClose(Sym, BiasTF, 1);
   if(hi <= lo || close <= 0) return false;
   double mid = (hi + lo) / 2.0;
   if(side == 1) return close >= mid;
   if(side == -1) return close <= mid;
   return false;
}

//+------------------------------------------------------------------+
bool HasDisplacement(int side, double atr, Profile &p)
{
   int s = 1;
   double open = iOpen(Sym, SignalTF, s);
   double close = iClose(Sym, SignalTF, s);
   double high = iHigh(Sym, SignalTF, s);
   double low = iLow(Sym, SignalTF, s);
   double body = MathAbs(close - open);
   double range = high - low;
   if(range <= 0 || atr <= 0) return false;
   if(body < atr * p.minBodyATR) return false;
   if(body / range < 0.42) return false;
   if(side == 1 && close <= open) return false;
   if(side == -1 && close >= open) return false;
   if(side == 1) return close > HighestHigh(2, DisplacementBreakLookback);
   return close < LowestLow(2, DisplacementBreakLookback);
}

//+------------------------------------------------------------------+
bool HasFVG(int side)
{
   int maxLookback = MathMax(3, FVGSearchLookback);
   for(int s = 1; s <= maxLookback; s++)
   {
      int far = s + 2;
      double highFar = iHigh(Sym, SignalTF, far);
      double lowFar = iLow(Sym, SignalTF, far);
      double highRecent = iHigh(Sym, SignalTF, s);
      double lowRecent = iLow(Sym, SignalTF, s);
      if(side == 1 && lowRecent > highFar)
         return true;
      if(side == -1 && highRecent < lowFar)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool PassesPremiumDiscount(int side)
{
   double hi = HighestHigh(1, PremiumDiscountLookback);
   double lo = LowestLow(1, PremiumDiscountLookback);
   double close = iClose(Sym, SignalTF, 1);
   if(hi <= lo || close <= 0) return false;
   double mid = (hi + lo) / 2.0;
   if(side == 1) return close <= mid;
   if(side == -1) return close >= mid;
   return false;
}

//+------------------------------------------------------------------+
void SendOrder(string setup, int side, double entry, double sl, double tp, double risk, double atr, int spread, Profile &p, string note)
{
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   bool canTrade = (tester && ExecuteInTester) || AllowLiveTrading;
   string sideName = side == 1 ? "long" : "short";

   LogEvent("SIGNAL", setup, sideName, entry, sl, tp, atr, spread, 0.0, note);
   if(!canTrade)
   {
      LogEvent("BLOCKED", setup, sideName, entry, sl, tp, atr, spread, 0.0, "trading_blocked " + note);
      return;
   }

   double lots = CalcLots(risk, p.riskPercent);
   if(lots <= 0)
   {
      LogEvent("ORDER_SKIP", setup, sideName, entry, sl, tp, atr, spread, 0.0, "invalid_lots " + note);
      return;
   }

   trade.SetExpertMagicNumber(MagicNumber);
   bool ok = side == 1 ? trade.Buy(lots, Sym, 0.0, sl, tp, setup)
                       : trade.Sell(lots, Sym, 0.0, sl, tp, setup);
   LogEvent(ok ? "ORDER_SENT" : "ORDER_ERROR", setup, sideName, entry, sl, tp, atr, spread, 0.0, ok ? "order_sent " + note : trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
void ManageOpenPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != Sym) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;

      datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);
      int barsHeld = iBarShift(Sym, SignalTF, openTime, false);
      Profile p;
      BuildProfile(Sym, p);
      if(barsHeld >= p.maxBarsHold)
      {
         trade.PositionClose(ticket);
         LogEvent("EXIT_TIMEOUT", "managed_position", "", 0, 0, 0, ATR(1), (int)SymbolInfoInteger(Sym, SYMBOL_SPREAD), 0.0, "max_bars_hold");
         continue;
      }

      if(MoveToBreakeven)
         TryMoveBreakeven(ticket);
   }
}

//+------------------------------------------------------------------+
void TryMoveBreakeven(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return;
   int type = (int)PositionGetInteger(POSITION_TYPE);
   double open = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl = PositionGetDouble(POSITION_SL);
   double tp = PositionGetDouble(POSITION_TP);
   double bid = SymbolInfoDouble(Sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(Sym, SYMBOL_ASK);
   double point = SymbolInfoDouble(Sym, SYMBOL_POINT);
   if(point <= 0 || sl <= 0) return;
   double initialRisk = MathAbs(open - sl);
   if(initialRisk <= 0) return;

   if(type == POSITION_TYPE_BUY)
   {
      double rNow = (bid - open) / initialRisk;
      double be = open + BreakevenPlusPoints * point;
      if(rNow >= BreakevenAtR && sl < open)
         trade.PositionModify(ticket, be, tp);
   }
   else if(type == POSITION_TYPE_SELL)
   {
      double rNow = (open - ask) / initialRisk;
      double be = open - BreakevenPlusPoints * point;
      if(rNow >= BreakevenAtR && sl > open)
         trade.PositionModify(ticket, be, tp);
   }
}

//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) == Sym && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         c++;
   }
   return c;
}

//+------------------------------------------------------------------+
void ResetDailyCounterIfNeeded()
{
   datetime d = CurrentDayKey();
   if(lastTradeDay != d && tradesToday > 0)
      tradesToday = 0;
}

//+------------------------------------------------------------------+
bool PoolTradedToday(int pool)
{
   if(pool < 0 || pool >= 6) return false;
   return lastPoolTradeDay[pool] == CurrentDayKey();
}

//+------------------------------------------------------------------+
bool InTradeWindow(int shift)
{
   datetime t = AdjustedTime(iTime(Sym, SignalTF, shift));
   MqlDateTime dt;
   TimeToStruct(t, dt);
   if(dt.hour < TradeStartHour || dt.hour >= TradeEndHour) return false;
   if(AvoidFridayLate && dt.day_of_week == 5 && dt.hour >= FridayCutoffHour) return false;
   return true;
}

//+------------------------------------------------------------------+
datetime AdjustedTime(datetime t)
{
   return t + SessionTimeShiftHours * 3600;
}

//+------------------------------------------------------------------+
datetime CurrentDayKey()
{
   return DayStart(AdjustedTime(iTime(Sym, SignalTF, 1)));
}

//+------------------------------------------------------------------+
datetime DayStart(datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
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
      v = MathMax(v, iHigh(Sym, SignalTF, i));
   return v;
}

//+------------------------------------------------------------------+
double LowestLow(int startShift, int count)
{
   double v = DBL_MAX;
   for(int i = startShift; i < startShift + count; i++)
      v = MathMin(v, iLow(Sym, SignalTF, i));
   return v;
}

//+------------------------------------------------------------------+
double FindEqualHigh()
{
   double atr = ATR(1);
   if(atr <= 0) return 0.0;
   double tol = atr * EqualToleranceATR;
   for(int i = 2; i < EqualLevelLookback; i++)
   {
      double h1 = iHigh(Sym, SignalTF, i);
      for(int j = i + 2; j < EqualLevelLookback + 5; j++)
      {
         double h2 = iHigh(Sym, SignalTF, j);
         if(MathAbs(h1 - h2) <= tol)
            return MathMax(h1, h2);
      }
   }
   return 0.0;
}

//+------------------------------------------------------------------+
double FindEqualLow()
{
   double atr = ATR(1);
   if(atr <= 0) return 0.0;
   double tol = atr * EqualToleranceATR;
   for(int i = 2; i < EqualLevelLookback; i++)
   {
      double l1 = iLow(Sym, SignalTF, i);
      for(int j = i + 2; j < EqualLevelLookback + 5; j++)
      {
         double l2 = iLow(Sym, SignalTF, j);
         if(MathAbs(l1 - l2) <= tol)
            return MathMin(l1, l2);
      }
   }
   return 0.0;
}

//+------------------------------------------------------------------+
double CalcLots(double riskPrice, double riskPercent)
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = equity * riskPercent / 100.0;
   double tickValue = SymbolInfoDouble(Sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(Sym, SYMBOL_TRADE_TICK_SIZE);
   if(riskMoney <= 0 || tickValue <= 0 || tickSize <= 0 || riskPrice <= 0) return 0.0;

   double lossPerLot = riskPrice / tickSize * tickValue;
   if(lossPerLot <= 0) return 0.0;

   double lots = riskMoney / lossPerLot;
   double minLot = SymbolInfoDouble(Sym, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(Sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(Sym, SYMBOL_VOLUME_STEP);
   if(step <= 0) return 0.0;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   lots = MathFloor(lots / step) * step;
   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
string ToUpper(string s)
{
   StringToUpper(s);
   return s;
}

//+------------------------------------------------------------------+
void Reject(string setup, int side, string reason)
{
   if(!DebugSignals) return;
   LogEvent("REJECT", setup, side == 1 ? "long" : "short", 0, 0, 0, ATR(1), (int)SymbolInfoInteger(Sym, SYMBOL_SPREAD), 0.0, reason);
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
   FileWrite(h, "time", "event", "symbol", "setup", "tf", "side", "entry", "sl", "tp", "atr", "spread", "result_R", "note");
   FileClose(h);
}

//+------------------------------------------------------------------+
void LogEvent(string eventType, string setup, string side, double entry, double sl, double tp, double atr, int spread, double resultR, string note)
{
   int h = FileOpen(LogFileName, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileSeek(h, 0, SEEK_END);
      FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS), eventType, Sym, setup, EnumToString(SignalTF), side, DoubleToString(entry, 5), DoubleToString(sl, 5), DoubleToString(tp, 5), DoubleToString(atr, 6), spread, DoubleToString(resultR, 4), note);
      FileClose(h);
   }
   if(DebugSignals || eventType == "ORDER_ERROR")
      Print(eventType, " ", Sym, " ", setup, " ", side, " ", note);
}
//+------------------------------------------------------------------+
