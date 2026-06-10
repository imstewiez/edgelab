//+------------------------------------------------------------------+
//| CoreEA Liquidity Portfolio Pro                                    |
//| MT5 Expert Advisor                                                |
//|                                                                  |
//| Multi-symbol liquidity/pricing portfolio engine.                  |
//|                                                                  |
//| Core thesis:                                                      |
//| price seeks liquidity, raids stops, reclaims key levels, then     |
//| delivers through displacement/imbalance.                          |
//|                                                                  |
//| This EA does NOT use generic EMA retail entries.                  |
//| It uses inferred liquidity from OHLC/tick execution data:          |
//| - Asian session range                                             |
//| - Previous day high/low                                           |
//| - Previous week high/low                                          |
//| - Equal highs/lows                                                |
//| - Sweep + reclaim                                                 |
//| - Displacement confirmation                                       |
//| - FVG / imbalance confirmation                                    |
//| - Premium/discount location                                       |
//| - Symbol-class adaptive profiles                                  |
//| - Portfolio risk/correlation buckets                              |
//|                                                                  |
//| Safe defaults: live trading blocked unless explicitly enabled.    |
//| Strategy Tester can place simulated orders via ExecuteInTester.   |
//+------------------------------------------------------------------+
#property strict
#property version   "1.100"
#property description "CoreEA multi-symbol liquidity/pricing portfolio EA"

#include <Trade/Trade.mqh>

input bool   AllowLiveTrading        = false;
input bool   ExecuteInTester         = true;
input string InpSymbols              = "XAUUSD,EURUSD,GBPUSD,AUDUSD,NZDUSD,USDCAD,USDCHF,USDJPY,EURJPY,GBPJPY";
input ENUM_TIMEFRAMES SignalTF       = PERIOD_M15;
input double BaseRiskPercent         = 0.25;
input int    MagicBase               = 991000;
input int    MaxPortfolioPositions   = 3;
input int    MaxPositionsPerSymbol   = 1;
input int    MaxPositionsPerBucket   = 1;
input int    MaxTradesPerSymbolPerDay= 1;
input bool   DebugSignals            = true;
input string LogFileName             = "CoreEA_LiquidityPortfolioPro.csv";

// Sessions use broker/server time plus SessionTimeShiftHours.
// Example: if broker server is GMT+3 but you want the session model to behave like GMT+2, set -1.
input int    SessionTimeShiftHours   = 0;
input int    AsiaStartHour           = 0;
input int    AsiaEndHour             = 7;
input int    LondonStartHour         = 7;
input int    NewYorkEndHour          = 17;
input bool   AvoidFridayLate         = true;
input int    FridayCutoffHour        = 16;

// Liquidity modules.
input bool   UseAsianRange           = true;
input bool   UsePreviousDay          = true;
input bool   UsePreviousWeek         = true;
input bool   UseEqualHighLow         = true;
input int    EqualLevelLookback      = 48;
input double EqualToleranceATR       = 0.12;

// Confirmation modules.
input int    ATRPeriod               = 14;
input int    SwingLookback           = 5;
input bool   RequireDisplacement     = true;
input bool   RequirePremiumDiscount  = true;
input bool   RequireFVG              = true;
input int    FVGSearchLookback       = 6;
input int    PremiumDiscountLookback = 144;

// Generic fallback execution parameters. Symbol profiles override these.
input double DefaultMinSweepATR      = 0.06;
input double DefaultMinBodyATR       = 0.42;
input double DefaultSLBufferATR      = 0.16;
input double DefaultMinStopATR       = 0.55;
input double DefaultMaxStopATR       = 2.80;
input double DefaultTakeProfitR      = 2.0;
input int    DefaultMaxBarsHold      = 60;
input int    DefaultMaxSpreadPoints  = 25;

CTrade trade;
string Symbols[];
datetime LastBarTimes[];
int AtrHandles[];
datetime LastPoolDay[];        // indexed by symbol index * 8 + pool index
datetime LastSymbolTradeDay[];  // hard daily symbol guard

//+------------------------------------------------------------------+
struct SymbolProfile
{
   string name;
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
   int tradeStartHour;
   int tradeEndHour;
   bool useAsia;
   bool usePrevDay;
   bool usePrevWeek;
   bool useEqualLevels;
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
   int n = ParseSymbols(InpSymbols, Symbols);
   if(n <= 0)
   {
      Print("No symbols configured.");
      return INIT_FAILED;
   }

   ArrayResize(LastBarTimes, n);
   ArrayResize(AtrHandles, n);
   ArrayResize(LastPoolDay, n * 8);
   ArrayResize(LastSymbolTradeDay, n);

   for(int i = 0; i < n; i++)
   {
      Symbols[i] = Trim(Symbols[i]);
      SymbolSelect(Symbols[i], true);
      LastBarTimes[i] = 0;
      LastSymbolTradeDay[i] = 0;
      AtrHandles[i] = iATR(Symbols[i], SignalTF, ATRPeriod);
      if(AtrHandles[i] == INVALID_HANDLE)
      {
         Print("Failed ATR handle for ", Symbols[i]);
         return INIT_FAILED;
      }
      for(int p = 0; p < 8; p++)
         LastPoolDay[i * 8 + p] = 0;
   }

   trade.SetDeviationInPoints(30);
   EnsureLogHeader();
   Print("CoreEA Liquidity Portfolio Pro initialized. Version=1.100 Symbols=", n,
         " TF=", EnumToString(SignalTF),
         " RequireFVG=", RequireFVG,
         " SessionShift=", SessionTimeShiftHours,
         " AllowLiveTrading=", AllowLiveTrading,
         " ExecuteInTester=", ExecuteInTester,
         " MQL_TESTER=", (bool)MQLInfoInteger(MQL_TESTER));
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   for(int i = 0; i < ArraySize(AtrHandles); i++)
      if(AtrHandles[i] != INVALID_HANDLE)
         IndicatorRelease(AtrHandles[i]);
}

//+------------------------------------------------------------------+
void OnTick()
{
   for(int i = 0; i < ArraySize(Symbols); i++)
   {
      string sym = Symbols[i];
      datetime t = iTime(sym, SignalTF, 0);
      if(t == 0 || t == LastBarTimes[i])
         continue;
      LastBarTimes[i] = t;
      EvaluateSymbol(i);
   }
}

//+------------------------------------------------------------------+
void EvaluateSymbol(int idx)
{
   string sym = Symbols[idx];
   if(Bars(sym, SignalTF) < 1500)
      return;

   SymbolProfile profile;
   BuildProfile(sym, profile);

   if(!InTradeWindow(sym, profile, 1))
      return;

   int spread = (int)SymbolInfoInteger(sym, SYMBOL_SPREAD);
   if(spread <= 0 || spread > profile.maxSpreadPoints)
      return;

   if(CountPortfolioPositions() >= MaxPortfolioPositions)
      return;
   if(CountSymbolPositions(sym) >= MaxPositionsPerSymbol)
      return;
   if(CountBucketPositions(profile.bucket) >= MaxPositionsPerBucket)
      return;
   if(SymbolTradesToday(idx) >= MaxTradesPerSymbolPerDay)
      return;

   double atr = ATR(idx, 1);
   if(atr <= 0)
      return;

   LiquidityLevels lv;
   if(!BuildLiquidityLevels(idx, profile, lv))
      return;

   int side = 0;
   int poolId = -1;
   string setup = "";
   double sweptLevel = 0.0;
   double sweepExtreme = 0.0;

   if(profile.useAsia)
   {
      if(DetectBullishSweep(sym, lv.asiaLow, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 0))
      {
         side = 1; poolId = 0; setup = "asia_low_raid_reclaim"; sweptLevel = lv.asiaLow;
      }
      else if(DetectBearishSweep(sym, lv.asiaHigh, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 1))
      {
         side = -1; poolId = 1; setup = "asia_high_raid_reclaim"; sweptLevel = lv.asiaHigh;
      }
   }

   if(side == 0 && profile.usePrevDay)
   {
      if(DetectBullishSweep(sym, lv.prevDayLow, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 2))
      {
         side = 1; poolId = 2; setup = "prev_day_low_raid_reclaim"; sweptLevel = lv.prevDayLow;
      }
      else if(DetectBearishSweep(sym, lv.prevDayHigh, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 3))
      {
         side = -1; poolId = 3; setup = "prev_day_high_raid_reclaim"; sweptLevel = lv.prevDayHigh;
      }
   }

   if(side == 0 && profile.usePrevWeek)
   {
      if(DetectBullishSweep(sym, lv.prevWeekLow, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 4))
      {
         side = 1; poolId = 4; setup = "prev_week_low_raid_reclaim"; sweptLevel = lv.prevWeekLow;
      }
      else if(DetectBearishSweep(sym, lv.prevWeekHigh, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 5))
      {
         side = -1; poolId = 5; setup = "prev_week_high_raid_reclaim"; sweptLevel = lv.prevWeekHigh;
      }
   }

   if(side == 0 && profile.useEqualLevels)
   {
      if(DetectBullishSweep(sym, lv.equalLow, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 6))
      {
         side = 1; poolId = 6; setup = "equal_lows_raid_reclaim"; sweptLevel = lv.equalLow;
      }
      else if(DetectBearishSweep(sym, lv.equalHigh, atr, profile, sweepExtreme) && !PoolTradedToday(idx, 7))
      {
         side = -1; poolId = 7; setup = "equal_highs_raid_reclaim"; sweptLevel = lv.equalHigh;
      }
   }

   if(side == 0)
      return;

   if(RequireDisplacement && !HasDisplacement(sym, side, atr, profile))
   {
      Reject(sym, setup, side, "no_displacement");
      return;
   }

   if(RequirePremiumDiscount && !PassesPremiumDiscount(sym, side))
   {
      Reject(sym, setup, side, "bad_premium_discount_location");
      return;
   }

   if(RequireFVG && !HasFVG(sym, side))
   {
      Reject(sym, setup, side, "no_fvg");
      return;
   }

   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   if(ask <= 0 || bid <= 0)
      return;

   double entry = side == 1 ? ask : bid;
   double sl = side == 1 ? sweepExtreme - atr * profile.slBufferATR : sweepExtreme + atr * profile.slBufferATR;
   double risk = MathAbs(entry - sl);

   if(risk < atr * profile.minStopATR)
   {
      sl = side == 1 ? entry - atr * profile.minStopATR : entry + atr * profile.minStopATR;
      risk = MathAbs(entry - sl);
   }

   if(risk > atr * profile.maxStopATR)
   {
      Reject(sym, setup, side, "stop_too_wide");
      return;
   }

   double tp = side == 1 ? entry + risk * profile.takeProfitR : entry - risk * profile.takeProfitR;

   LastPoolDay[idx * 8 + poolId] = CurrentSessionDayKey(sym);
   LastSymbolTradeDay[idx] = CurrentSessionDayKey(sym);
   SendOrder(sym, setup, side, entry, sl, tp, risk, atr, spread, profile, sweptLevel, sweepExtreme);
}

//+------------------------------------------------------------------+
void BuildProfile(string sym, SymbolProfile &p)
{
   p.name = sym;
   p.bucket = BucketFor(sym);
   p.riskPercent = BaseRiskPercent;
   p.maxSpreadPoints = DefaultMaxSpreadPoints;
   p.minSweepATR = DefaultMinSweepATR;
   p.minBodyATR = DefaultMinBodyATR;
   p.slBufferATR = DefaultSLBufferATR;
   p.minStopATR = DefaultMinStopATR;
   p.maxStopATR = DefaultMaxStopATR;
   p.takeProfitR = DefaultTakeProfitR;
   p.maxBarsHold = DefaultMaxBarsHold;
   p.tradeStartHour = LondonStartHour;
   p.tradeEndHour = NewYorkEndHour;
   p.useAsia = UseAsianRange;
   p.usePrevDay = UsePreviousDay;
   p.usePrevWeek = UsePreviousWeek;
   p.useEqualLevels = UseEqualHighLow;

   string s = ToUpper(sym);
   if(StringFind(s, "XAU") >= 0 || StringFind(s, "GOLD") >= 0)
   {
      p.bucket = "metals";
      p.riskPercent = BaseRiskPercent * 0.70;
      p.maxSpreadPoints = 80;
      p.minSweepATR = 0.05;
      p.minBodyATR = 0.55;
      p.slBufferATR = 0.22;
      p.minStopATR = 0.70;
      p.maxStopATR = 3.50;
      p.takeProfitR = 2.2;
      p.maxBarsHold = 72;
      p.tradeStartHour = 7;
      p.tradeEndHour = 20;
   }
   else if(StringFind(s, "JPY") >= 0)
   {
      p.bucket = "jpy_fx";
      p.maxSpreadPoints = 35;
      p.minSweepATR = 0.07;
      p.minBodyATR = 0.45;
      p.slBufferATR = 0.18;
      p.minStopATR = 0.60;
      p.maxStopATR = 3.00;
      p.takeProfitR = 2.0;
      p.maxBarsHold = 72;
   }
   else if(StringFind(s, "GBP") >= 0)
   {
      p.bucket = "gbp_fx";
      p.riskPercent = BaseRiskPercent * 0.85;
      p.maxSpreadPoints = 30;
      p.minSweepATR = 0.06;
      p.minBodyATR = 0.45;
      p.slBufferATR = 0.18;
      p.maxStopATR = 3.00;
      p.takeProfitR = 2.1;
   }
   else if(StringFind(s, "AUD") >= 0 || StringFind(s, "NZD") >= 0)
   {
      p.bucket = "aud_nzd_fx";
      p.maxSpreadPoints = 28;
      p.minSweepATR = 0.06;
      p.minBodyATR = 0.42;
      p.slBufferATR = 0.16;
      p.takeProfitR = 2.0;
   }
   else if(StringFind(s, "EUR") >= 0 || StringFind(s, "USD") >= 0 || StringFind(s, "CAD") >= 0 || StringFind(s, "CHF") >= 0)
   {
      p.bucket = "majors_fx";
      p.maxSpreadPoints = 25;
      p.minSweepATR = 0.06;
      p.minBodyATR = 0.42;
      p.slBufferATR = 0.16;
      p.takeProfitR = 2.0;
   }
}

//+------------------------------------------------------------------+
string BucketFor(string sym)
{
   string s = ToUpper(sym);
   if(StringFind(s, "XAU") >= 0 || StringFind(s, "GOLD") >= 0) return "metals";
   if(StringFind(s, "JPY") >= 0) return "jpy_fx";
   if(StringFind(s, "GBP") >= 0) return "gbp_fx";
   if(StringFind(s, "AUD") >= 0 || StringFind(s, "NZD") >= 0) return "aud_nzd_fx";
   return "majors_fx";
}

//+------------------------------------------------------------------+
bool BuildLiquidityLevels(int idx, SymbolProfile &p, LiquidityLevels &lv)
{
   string sym = Symbols[idx];
   lv.asiaHigh = -DBL_MAX;
   lv.asiaLow = DBL_MAX;
   lv.prevDayHigh = iHigh(sym, PERIOD_D1, 1);
   lv.prevDayLow = iLow(sym, PERIOD_D1, 1);
   lv.prevWeekHigh = iHigh(sym, PERIOD_W1, 1);
   lv.prevWeekLow = iLow(sym, PERIOD_W1, 1);
   lv.equalHigh = FindEqualHigh(sym, idx);
   lv.equalLow = FindEqualLow(sym, idx);

   datetime todayStart = DayStart(AdjustedTime(iTime(sym, SignalTF, 1)));
   for(int i = 1; i < 600; i++)
   {
      datetime bt = iTime(sym, SignalTF, i);
      if(bt <= 0 || AdjustedTime(bt) < todayStart)
         break;
      MqlDateTime dt;
      TimeToStruct(AdjustedTime(bt), dt);
      if(dt.hour >= AsiaStartHour && dt.hour < AsiaEndHour)
      {
         lv.asiaHigh = MathMax(lv.asiaHigh, iHigh(sym, SignalTF, i));
         lv.asiaLow = MathMin(lv.asiaLow, iLow(sym, SignalTF, i));
      }
   }

   if(lv.prevDayHigh <= 0 || lv.prevDayLow <= 0)
      return false;
   if(p.usePrevWeek && (lv.prevWeekHigh <= 0 || lv.prevWeekLow <= 0))
      return false;
   if(p.useAsia && (lv.asiaHigh == -DBL_MAX || lv.asiaLow == DBL_MAX))
      return false;
   return true;
}

//+------------------------------------------------------------------+
double FindEqualHigh(string sym, int idx)
{
   double atr = ATR(idx, 1);
   if(atr <= 0) return 0.0;
   double tol = atr * EqualToleranceATR;
   for(int i = 2; i < EqualLevelLookback; i++)
   {
      double h1 = iHigh(sym, SignalTF, i);
      for(int j = i + 2; j < EqualLevelLookback + 5; j++)
      {
         double h2 = iHigh(sym, SignalTF, j);
         if(MathAbs(h1 - h2) <= tol)
            return MathMax(h1, h2);
      }
   }
   return 0.0;
}

//+------------------------------------------------------------------+
double FindEqualLow(string sym, int idx)
{
   double atr = ATR(idx, 1);
   if(atr <= 0) return 0.0;
   double tol = atr * EqualToleranceATR;
   for(int i = 2; i < EqualLevelLookback; i++)
   {
      double l1 = iLow(sym, SignalTF, i);
      for(int j = i + 2; j < EqualLevelLookback + 5; j++)
      {
         double l2 = iLow(sym, SignalTF, j);
         if(MathAbs(l1 - l2) <= tol)
            return MathMin(l1, l2);
      }
   }
   return 0.0;
}

//+------------------------------------------------------------------+
bool DetectBullishSweep(string sym, double level, double atr, SymbolProfile &p, double &extreme)
{
   if(level <= 0 || atr <= 0) return false;
   int s = 1;
   double low = iLow(sym, SignalTF, s);
   double high = iHigh(sym, SignalTF, s);
   double open = iOpen(sym, SignalTF, s);
   double close = iClose(sym, SignalTF, s);
   double range = high - low;
   if(range <= 0) return false;
   double sweepDepth = level - low;
   double lowerWick = MathMin(open, close) - low;
   if(low < level && close > level && sweepDepth >= atr * p.minSweepATR && lowerWick / range >= 0.20)
   {
      extreme = low;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool DetectBearishSweep(string sym, double level, double atr, SymbolProfile &p, double &extreme)
{
   if(level <= 0 || atr <= 0) return false;
   int s = 1;
   double low = iLow(sym, SignalTF, s);
   double high = iHigh(sym, SignalTF, s);
   double open = iOpen(sym, SignalTF, s);
   double close = iClose(sym, SignalTF, s);
   double range = high - low;
   if(range <= 0) return false;
   double sweepDepth = high - level;
   double upperWick = high - MathMax(open, close);
   if(high > level && close < level && sweepDepth >= atr * p.minSweepATR && upperWick / range >= 0.20)
   {
      extreme = high;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
bool HasDisplacement(string sym, int side, double atr, SymbolProfile &p)
{
   int s = 1;
   double open = iOpen(sym, SignalTF, s);
   double close = iClose(sym, SignalTF, s);
   double high = iHigh(sym, SignalTF, s);
   double low = iLow(sym, SignalTF, s);
   double body = MathAbs(close - open);
   double range = high - low;
   if(range <= 0 || atr <= 0) return false;
   if(body < atr * p.minBodyATR) return false;
   if(side == 1 && close <= open) return false;
   if(side == -1 && close >= open) return false;
   if(side == 1) return close > HighestHigh(sym, 2, SwingLookback);
   return close < LowestLow(sym, 2, SwingLookback);
}

//+------------------------------------------------------------------+
bool PassesPremiumDiscount(string sym, int side)
{
   double hi = HighestHigh(sym, 1, PremiumDiscountLookback);
   double lo = LowestLow(sym, 1, PremiumDiscountLookback);
   double close = iClose(sym, SignalTF, 1);
   if(hi <= lo) return false;
   double mid = (hi + lo) / 2.0;
   if(side == 1) return close <= mid;
   if(side == -1) return close >= mid;
   return false;
}

//+------------------------------------------------------------------+
bool HasFVG(string sym, int side)
{
   int maxLookback = MathMax(3, FVGSearchLookback);
   for(int s = 1; s <= maxLookback; s++)
   {
      int far = s + 2;
      double highFar = iHigh(sym, SignalTF, far);
      double lowFar = iLow(sym, SignalTF, far);
      double highRecent = iHigh(sym, SignalTF, s);
      double lowRecent = iLow(sym, SignalTF, s);
      if(side == 1 && lowRecent > highFar)
         return true;
      if(side == -1 && highRecent < lowFar)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
void SendOrder(string sym, string setup, int side, double entry, double sl, double tp, double risk, double atr, int spread, SymbolProfile &p, double sweptLevel, double extreme)
{
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   bool canTrade = (tester && ExecuteInTester) || AllowLiveTrading;
   string sideName = side == 1 ? "long" : "short";
   string note = StringFormat("bucket=%s swept=%.5f extreme=%.5f", p.bucket, sweptLevel, extreme);

   LogEvent("SIGNAL", sym, setup, sideName, entry, sl, tp, atr, spread, 0.0, note);
   if(!canTrade)
   {
      LogEvent("BLOCKED", sym, setup, sideName, entry, sl, tp, atr, spread, 0.0, "live_trading_blocked");
      return;
   }

   double lots = CalcLots(sym, risk, p.riskPercent);
   if(lots <= 0)
   {
      LogEvent("ORDER_SKIP", sym, setup, sideName, entry, sl, tp, atr, spread, 0.0, "invalid_lots");
      return;
   }

   trade.SetExpertMagicNumber(MagicBase + SymbolIndexHash(sym));
   bool ok = side == 1 ? trade.Buy(lots, sym, 0.0, sl, tp, setup)
                       : trade.Sell(lots, sym, 0.0, sl, tp, setup);
   LogEvent(ok ? "ORDER_SENT" : "ORDER_ERROR", sym, setup, sideName, entry, sl, tp, atr, spread, 0.0, ok ? "order_sent" : trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
bool PoolTradedToday(int idx, int pool)
{
   return LastPoolDay[idx * 8 + pool] == CurrentSessionDayKey(Symbols[idx]);
}

//+------------------------------------------------------------------+
int SymbolTradesToday(int idx)
{
   if(MaxTradesPerSymbolPerDay <= 0)
      return 0;
   return LastSymbolTradeDay[idx] == CurrentSessionDayKey(Symbols[idx]) ? 1 : 0;
}

//+------------------------------------------------------------------+
int CountPortfolioPositions()
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      long magic = PositionGetInteger(POSITION_MAGIC);
      if(magic >= MagicBase && magic <= MagicBase + 9999)
         c++;
   }
   return c;
}

//+------------------------------------------------------------------+
int CountSymbolPositions(string sym)
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      long magic = PositionGetInteger(POSITION_MAGIC);
      if(PositionGetString(POSITION_SYMBOL) == sym && magic >= MagicBase && magic <= MagicBase + 9999)
         c++;
   }
   return c;
}

//+------------------------------------------------------------------+
int CountBucketPositions(string bucket)
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      long magic = PositionGetInteger(POSITION_MAGIC);
      if(magic < MagicBase || magic > MagicBase + 9999) continue;
      string psym = PositionGetString(POSITION_SYMBOL);
      if(BucketFor(psym) == bucket)
         c++;
   }
   return c;
}

//+------------------------------------------------------------------+
bool InTradeWindow(string sym, SymbolProfile &p, int shift)
{
   datetime t = AdjustedTime(iTime(sym, SignalTF, shift));
   MqlDateTime dt;
   TimeToStruct(t, dt);
   if(dt.hour < p.tradeStartHour || dt.hour >= p.tradeEndHour) return false;
   if(AvoidFridayLate && dt.day_of_week == 5 && dt.hour >= FridayCutoffHour) return false;
   return true;
}

//+------------------------------------------------------------------+
datetime AdjustedTime(datetime t)
{
   return t + SessionTimeShiftHours * 3600;
}

//+------------------------------------------------------------------+
datetime CurrentSessionDayKey(string sym)
{
   return DayStart(AdjustedTime(iTime(sym, SignalTF, 1)));
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
double ATR(int idx, int shift)
{
   double buf[];
   ArraySetAsSeries(buf, true);
   if(CopyBuffer(AtrHandles[idx], 0, shift, 1, buf) != 1)
      return 0.0;
   return buf[0];
}

//+------------------------------------------------------------------+
double HighestHigh(string sym, int startShift, int count)
{
   double v = -DBL_MAX;
   for(int i = startShift; i < startShift + count; i++)
      v = MathMax(v, iHigh(sym, SignalTF, i));
   return v;
}

//+------------------------------------------------------------------+
double LowestLow(string sym, int startShift, int count)
{
   double v = DBL_MAX;
   for(int i = startShift; i < startShift + count; i++)
      v = MathMin(v, iLow(sym, SignalTF, i));
   return v;
}

//+------------------------------------------------------------------+
double CalcLots(string sym, double riskPrice, double riskPercent)
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = equity * riskPercent / 100.0;
   double tickValue = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(riskMoney <= 0 || tickValue <= 0 || tickSize <= 0 || riskPrice <= 0) return 0.0;

   double lossPerLot = riskPrice / tickSize * tickValue;
   if(lossPerLot <= 0) return 0.0;

   double lots = riskMoney / lossPerLot;
   double minLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(step <= 0) return 0.0;
   lots = MathMax(minLot, MathMin(maxLot, lots));
   lots = MathFloor(lots / step) * step;
   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
int SymbolIndexHash(string sym)
{
   int h = 0;
   for(int i = 0; i < StringLen(sym); i++)
      h += StringGetCharacter(sym, i) * (i + 1);
   return h % 9000;
}

//+------------------------------------------------------------------+
int ParseSymbols(string src, string &out[])
{
   string parts[];
   int n = StringSplit(src, ',', parts);
   ArrayResize(out, n);
   int k = 0;
   for(int i = 0; i < n; i++)
   {
      string s = Trim(parts[i]);
      if(s == "") continue;
      out[k] = s;
      k++;
   }
   ArrayResize(out, k);
   return k;
}

//+------------------------------------------------------------------+
string Trim(string s)
{
   StringTrimLeft(s);
   StringTrimRight(s);
   return s;
}

//+------------------------------------------------------------------+
string ToUpper(string s)
{
   StringToUpper(s);
   return s;
}

//+------------------------------------------------------------------+
void Reject(string sym, string setup, int side, string reason)
{
   if(!DebugSignals) return;
   LogEvent("REJECT", sym, setup, side == 1 ? "long" : "short", 0, 0, 0, 0, (int)SymbolInfoInteger(sym, SYMBOL_SPREAD), 0.0, reason);
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
void LogEvent(string eventType, string sym, string setup, string side, double entry, double sl, double tp, double atr, int spread, double resultR, string note)
{
   int h = FileOpen(LogFileName, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileSeek(h, 0, SEEK_END);
      FileWrite(h, TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS), eventType, sym, setup, EnumToString(SignalTF), side, DoubleToString(entry, 5), DoubleToString(sl, 5), DoubleToString(tp, 5), DoubleToString(atr, 6), spread, DoubleToString(resultR, 4), note);
      FileClose(h);
   }
   if(DebugSignals || eventType == "ORDER_ERROR")
      Print(eventType, " ", sym, " ", setup, " ", side, " ", note);
}
//+------------------------------------------------------------------+
