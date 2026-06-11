//+------------------------------------------------------------------+
//| CoreEA Microstructure AVWAP Pro                                   |
//| MT5 Expert Advisor                                                |
//|                                                                  |
//| Fully automatic multi-symbol EA based on:                         |
//| - Anchored VWAP value model with dynamic standard deviation bands  |
//| - Structural liquidity sweeps and reclaims                         |
//| - Synthetic CVD / tick-flow divergence                             |
//| - Displacement + Fair Value Gap / liquidity vacuum                 |
//| - Portfolio risk and asset-bucket exposure control                 |
//|                                                                  |
//| Live trading is blocked unless AllowLiveTrading=true.              |
//+------------------------------------------------------------------+
#property strict
#property version   "1.001"
#property description "CoreEA institutional AVWAP liquidity sweep microstructure EA"

//====================================================================
// INPUTS
//====================================================================
input group "01. General / Symbols"
input bool             AllowLiveTrading              = false;
input bool             ExecuteInTester               = true;
input string           InpSymbols                    = "XAUUSD,EURUSD,GBPUSD,AUDUSD,NZDUSD,USDCAD,USDCHF,USDJPY,EURJPY,GBPJPY";
input ENUM_TIMEFRAMES  SignalTF                      = PERIOD_M15;
input int              MagicBase                     = 995000;
input bool             DebugLogs                     = true;
input string           CsvLogFile                    = "CoreEA_MicrostructureAVWAPPro.csv";

input group "02. Anchored VWAP Value Model"
input int              SessionTimeShiftHours         = 0;
input int              LondonAnchorHour              = 7;
input int              NewYorkAnchorHour             = 13;
input int              VwapMaxBars                   = 500;
input double           VwapBand1SD                   = 1.0;
input double           VwapBand2SD                   = 2.0;
input bool             RequireAVWAPExtreme           = true;

input group "03. Liquidity Pools"
input int              AsiaStartHour                 = 0;
input int              AsiaEndHour                   = 7;
input bool             UseAsianLiquidity             = true;
input bool             UsePreviousDayLiquidity       = true;
input bool             UseRollingIntradayLiquidity   = true;
input int              RollingPoolLookbackBars       = 96;
input double           MinSweepATR                   = 0.05;
input double           MinReclaimCloseATR            = 0.00;

input group "04. Synthetic Order Flow / CVD"
input int              CvdLookbackBars               = 3;
input double           CvdSpikeMultiplier            = 1.25;
input bool             RequireSyntheticCvdConfirm    = true;

input group "05. Displacement / Liquidity Vacuum"
input int              ATRPeriod                     = 14;
input double           DisplacementBodyATR           = 1.50;
input int              DisplacementBreakLookback     = 5;
input bool             RequireFVG                    = true;
input bool             PreferLimitAtVacuumMidpoint   = true;
input int              PendingExpiryBars             = 8;

input group "06. Execution / Risk"
input double           RiskPercentPerTrade           = 0.25;
input double           SL_ATR_Padding                = 0.50;
input double           MinimumRR                     = 2.00;
input double           FallbackRR                    = 2.20;
input int              MaxBarsInTrade                = 48;
input bool             MoveToBreakeven               = true;
input double           BreakevenAtR                  = 1.00;
input double           BreakevenPlusPoints           = 2.0;
input bool             UseATRTrailing                = true;
input double           TrailStartR                   = 1.50;
input double           TrailATRMult                  = 1.20;

input group "07. Portfolio Risk Buckets"
input int              MaxPortfolioPositions         = 4;
input int              MaxPositionsPerSymbol         = 1;
input int              MaxPositionsPerBucket         = 1;
input int              MaxTradesPerSymbolPerDay      = 2;
input double           MaxDailyLossPercent           = 2.0;

input group "08. Session / Spread / Broker Adaptation"
input int              TradeStartHour                = 7;
input int              TradeEndHour                  = 20;
input bool             AvoidFridayLate               = true;
input int              FridayCutoffHour              = 16;
input int              ManualMaxSpreadPoints         = 0;
input int              ManualDeviationPoints         = 0;

//====================================================================
// STRUCTS
//====================================================================
struct SAssetProfile
{
   string bucket;
   double riskMultiplier;
   int    maxSpreadPoints;
   int    deviationPoints;
   double minStopATR;
   double maxStopATR;
};

struct SVwapState
{
   bool     valid;
   datetime anchorTime;
   double   vwap;
   double   sd;
   double   upper1;
   double   lower1;
   double   upper2;
   double   lower2;
};

struct SLiquidityPools
{
   bool   valid;
   double asiaHigh;
   double asiaLow;
   double prevDayHigh;
   double prevDayLow;
   double rollingHigh;
   double rollingLow;
};

struct STradeSignal
{
   bool     valid;
   string   symbol;
   int      side;
   string   setup;
   string   bucket;
   double   entryHint;
   double   stopLoss;
   double   takeProfit;
   double   riskDistance;
   double   rr;
   double   atr;
   double   sweptLevel;
   double   sweepExtreme;
   double   fvgMidpoint;
   bool     useLimit;
   string   reason;
};

//====================================================================
// UTILS
//====================================================================
string TrimString(string value)
{
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
}

string UpperString(string value)
{
   StringToUpper(value);
   return value;
}

datetime AdjustedTime(const datetime serverTime)
{
   return serverTime + SessionTimeShiftHours * 3600;
}

datetime UnadjustedTime(const datetime adjustedTime)
{
   return adjustedTime - SessionTimeShiftHours * 3600;
}

datetime DayStart(const datetime t)
{
   MqlDateTime dt;
   TimeToStruct(t, dt);
   dt.hour = 0;
   dt.min = 0;
   dt.sec = 0;
   return StructToTime(dt);
}

datetime CurrentSessionDayKey(const string symbol)
{
   datetime t = iTime(symbol, SignalTF, 1);
   if(t <= 0)
      t = TimeCurrent();
   return DayStart(AdjustedTime(t));
}

int ParseSymbols(const string src, string &out[])
{
   string parts[];
   int n = StringSplit(src, ',', parts);
   ArrayResize(out, n);
   int k = 0;
   for(int i = 0; i < n; i++)
   {
      string s = TrimString(parts[i]);
      if(s == "")
         continue;
      out[k] = s;
      k++;
   }
   ArrayResize(out, k);
   return k;
}

int HashSymbol(const string symbol)
{
   int h = 0;
   for(int i = 0; i < StringLen(symbol); i++)
      h += StringGetCharacter(symbol, i) * (i + 1);
   return h % 9000;
}

double SymbolPoint(const string symbol)
{
   double p = SymbolInfoDouble(symbol, SYMBOL_POINT);
   return p > 0.0 ? p : 0.00001;
}

double NormalizePrice(const string symbol, const double price)
{
   return NormalizeDouble(price, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS));
}

double HighestHigh(const string symbol, const ENUM_TIMEFRAMES tf, const int startShift, const int count)
{
   double v = -DBL_MAX;
   for(int i = startShift; i < startShift + count; i++)
      v = MathMax(v, iHigh(symbol, tf, i));
   return v;
}

double LowestLow(const string symbol, const ENUM_TIMEFRAMES tf, const int startShift, const int count)
{
   double v = DBL_MAX;
   for(int i = startShift; i < startShift + count; i++)
      v = MathMin(v, iLow(symbol, tf, i));
   return v;
}

bool IsTradeTimeAllowed(const string symbol)
{
   datetime t = iTime(symbol, SignalTF, 1);
   if(t <= 0)
      return false;
   MqlDateTime dt;
   TimeToStruct(AdjustedTime(t), dt);
   if(dt.hour < TradeStartHour || dt.hour >= TradeEndHour)
      return false;
   if(AvoidFridayLate && dt.day_of_week == 5 && dt.hour >= FridayCutoffHour)
      return false;
   return true;
}

//====================================================================
// LOGGER
//====================================================================
class CLogEngine
{
private:
   string m_file;

public:
   void Init(const string fileName)
   {
      m_file = fileName;
      int h = FileOpen(m_file, FILE_READ | FILE_CSV | FILE_ANSI);
      if(h != INVALID_HANDLE)
      {
         FileClose(h);
         return;
      }
      h = FileOpen(m_file, FILE_WRITE | FILE_CSV | FILE_ANSI);
      if(h == INVALID_HANDLE)
         return;
      FileWrite(h, "time", "event", "symbol", "bucket", "setup", "side", "price", "sl", "tp", "rr", "atr", "spread", "retcode", "note");
      FileClose(h);
   }

   void Write(const string eventType,
              const string symbol,
              const string bucket,
              const string setup,
              const string side,
              const double price,
              const double sl,
              const double tp,
              const double rr,
              const double atr,
              const int spread,
              const uint retcode,
              const string note)
   {
      int h = FileOpen(m_file, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI);
      if(h != INVALID_HANDLE)
      {
         FileSeek(h, 0, SEEK_END);
         int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
         FileWrite(h,
                   TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
                   eventType, symbol, bucket, setup, side,
                   DoubleToString(price, digits),
                   DoubleToString(sl, digits),
                   DoubleToString(tp, digits),
                   DoubleToString(rr, 2),
                   DoubleToString(atr, digits),
                   spread, retcode, note);
         FileClose(h);
      }
      if(DebugLogs || eventType == "ORDER_ERROR" || eventType == "SLTP_ERROR" || eventType == "SKIP")
         Print(eventType, " ", symbol, " ", setup, " ", side, " ", note);
   }
};

CLogEngine LOG;

//====================================================================
// BROKER PROFILE ENGINE
//====================================================================
class CBrokerProfileEngine
{
public:
   SAssetProfile Profile(const string symbol)
   {
      SAssetProfile p;
      string s = UpperString(symbol);
      p.bucket = "FX_USD";
      p.riskMultiplier = 1.0;
      p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 25;
      p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 20;
      p.minStopATR = 0.65;
      p.maxStopATR = 4.00;

      if(StringFind(s, "XAU") >= 0 || StringFind(s, "GOLD") >= 0)
      {
         p.bucket = "METALS";
         p.riskMultiplier = 0.70;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 120;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 50;
         p.minStopATR = 0.85;
         p.maxStopATR = 5.00;
      }
      else if(StringFind(s, "BTC") >= 0 || StringFind(s, "ETH") >= 0 || StringFind(s, "CRYPTO") >= 0)
      {
         p.bucket = "CRYPTO";
         p.riskMultiplier = 0.50;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 500;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 100;
         p.minStopATR = 1.00;
         p.maxStopATR = 6.00;
      }
      else if(StringFind(s, "NAS") >= 0 || StringFind(s, "US30") >= 0 || StringFind(s, "SPX") >= 0 || StringFind(s, "GER") >= 0 || StringFind(s, "DAX") >= 0)
      {
         p.bucket = "INDICES";
         p.riskMultiplier = 0.60;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 250;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 80;
         p.minStopATR = 0.90;
         p.maxStopATR = 5.50;
      }
      else if(StringFind(s, "JPY") >= 0)
      {
         p.bucket = "FX_JPY";
         p.riskMultiplier = 0.90;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 40;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 25;
         p.minStopATR = 0.75;
         p.maxStopATR = 4.50;
      }
      else if(StringFind(s, "GBP") >= 0)
      {
         p.bucket = "FX_GBP";
         p.riskMultiplier = 0.85;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 35;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 25;
         p.minStopATR = 0.70;
         p.maxStopATR = 4.50;
      }
      else if(StringFind(s, "AUD") >= 0 || StringFind(s, "NZD") >= 0)
      {
         p.bucket = "FX_AUD_NZD";
         p.riskMultiplier = 1.0;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 32;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 25;
      }
      return p;
   }
};

//====================================================================
// ANCHORED VWAP ENGINE
//====================================================================
class CVwapEngine
{
private:
   datetime ActiveAnchorServerTime(const string symbol)
   {
      datetime ref = iTime(symbol, SignalTF, 1);
      if(ref <= 0)
         ref = TimeCurrent();

      datetime adj = AdjustedTime(ref);
      datetime today = DayStart(adj);
      datetime london = today + LondonAnchorHour * 3600;
      datetime ny = today + NewYorkAnchorHour * 3600;
      datetime anchorAdj;

      if(adj >= ny)
         anchorAdj = ny;
      else if(adj >= london)
         anchorAdj = london;
      else
         anchorAdj = DayStart(adj - 86400) + NewYorkAnchorHour * 3600;

      return UnadjustedTime(anchorAdj);
   }

public:
   bool Calculate(const string symbol, SVwapState &state)
   {
      state.valid = false;
      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int copied = CopyRates(symbol, SignalTF, 0, VwapMaxBars, rates);
      if(copied < 50)
         return false;

      datetime anchor = ActiveAnchorServerTime(symbol);
      double sumPV = 0.0;
      double sumV = 0.0;
      int used = 0;

      for(int i = 1; i < copied; i++)
      {
         if(rates[i].time < anchor)
            break;
         double typical = (rates[i].high + rates[i].low + rates[i].close) / 3.0;
         double vol = (double)MathMax((long)1, rates[i].tick_volume);
         sumPV += typical * vol;
         sumV += vol;
         used++;
      }
      if(used < 10 || sumV <= 0.0)
         return false;

      double vwap = sumPV / sumV;
      double variance = 0.0;
      for(int j = 1; j < copied; j++)
      {
         if(rates[j].time < anchor)
            break;
         double typical = (rates[j].high + rates[j].low + rates[j].close) / 3.0;
         double vol = (double)MathMax((long)1, rates[j].tick_volume);
         variance += vol * MathPow(typical - vwap, 2.0);
      }
      variance /= sumV;
      double sd = MathSqrt(MathMax(0.0, variance));

      state.valid = true;
      state.anchorTime = anchor;
      state.vwap = vwap;
      state.sd = sd;
      state.upper1 = vwap + VwapBand1SD * sd;
      state.lower1 = vwap - VwapBand1SD * sd;
      state.upper2 = vwap + VwapBand2SD * sd;
      state.lower2 = vwap - VwapBand2SD * sd;
      return true;
   }
};

//====================================================================
// LIQUIDITY / SYNTHETIC ORDER FLOW ENGINE
//====================================================================
class CLiquidityEngine
{
private:
   double SyntheticDelta(const MqlRates &bar)
   {
      double range = bar.high - bar.low;
      if(range <= 0.0)
         return 0.0;
      double closeLocation = ((bar.close - bar.low) / range - 0.5) * 2.0;
      return (double)MathMax((long)1, bar.tick_volume) * closeLocation;
   }

   double ATRFromRates(const MqlRates &rates[], const int copied, const int shift)
   {
      if(copied < ATRPeriod + shift + 2)
         return 0.0;
      double sum = 0.0;
      for(int i = shift; i < shift + ATRPeriod; i++)
      {
         double prevClose = rates[i + 1].close;
         double tr = MathMax(rates[i].high - rates[i].low,
                             MathMax(MathAbs(rates[i].high - prevClose), MathAbs(rates[i].low - prevClose)));
         sum += tr;
      }
      return sum / (double)ATRPeriod;
   }

   double HighestFromRates(const MqlRates &rates[], const int startShift, const int count)
   {
      double h = -DBL_MAX;
      for(int i = startShift; i < startShift + count; i++)
         h = MathMax(h, rates[i].high);
      return h;
   }

   double LowestFromRates(const MqlRates &rates[], const int startShift, const int count)
   {
      double l = DBL_MAX;
      for(int i = startShift; i < startShift + count; i++)
         l = MathMin(l, rates[i].low);
      return l;
   }

   bool BuildPools(const string symbol, const MqlRates &rates[], const int copied, SLiquidityPools &pools)
   {
      pools.valid = false;
      pools.asiaHigh = -DBL_MAX;
      pools.asiaLow = DBL_MAX;
      pools.prevDayHigh = iHigh(symbol, PERIOD_D1, 1);
      pools.prevDayLow = iLow(symbol, PERIOD_D1, 1);
      pools.rollingHigh = HighestHigh(symbol, SignalTF, 2, RollingPoolLookbackBars);
      pools.rollingLow = LowestLow(symbol, SignalTF, 2, RollingPoolLookbackBars);

      datetime todayStart = DayStart(AdjustedTime(rates[1].time));
      for(int i = 1; i < copied; i++)
      {
         datetime adj = AdjustedTime(rates[i].time);
         if(adj < todayStart)
            break;
         MqlDateTime dt;
         TimeToStruct(adj, dt);
         if(dt.hour >= AsiaStartHour && dt.hour < AsiaEndHour)
         {
            pools.asiaHigh = MathMax(pools.asiaHigh, rates[i].high);
            pools.asiaLow = MathMin(pools.asiaLow, rates[i].low);
         }
      }

      bool has = false;
      if(UseAsianLiquidity && pools.asiaHigh != -DBL_MAX && pools.asiaLow != DBL_MAX)
         has = true;
      if(UsePreviousDayLiquidity && pools.prevDayHigh > 0 && pools.prevDayLow > 0)
         has = true;
      if(UseRollingIntradayLiquidity && pools.rollingHigh > 0 && pools.rollingLow > 0)
         has = true;
      pools.valid = has;
      return has;
   }

   bool BullSweep(const MqlRates &bar, const double level, const double atr, double &extreme, double &depthATR)
   {
      if(level <= 0 || atr <= 0)
         return false;
      double depth = level - bar.low;
      depthATR = depth / atr;
      if(bar.low < level && bar.close > level && depthATR >= MinSweepATR)
      {
         double reclaim = (bar.close - level) / atr;
         if(reclaim >= MinReclaimCloseATR)
         {
            extreme = bar.low;
            return true;
         }
      }
      return false;
   }

   bool BearSweep(const MqlRates &bar, const double level, const double atr, double &extreme, double &depthATR)
   {
      if(level <= 0 || atr <= 0)
         return false;
      double depth = bar.high - level;
      depthATR = depth / atr;
      if(bar.high > level && bar.close < level && depthATR >= MinSweepATR)
      {
         double reclaim = (level - bar.close) / atr;
         if(reclaim >= MinReclaimCloseATR)
         {
            extreme = bar.high;
            return true;
         }
      }
      return false;
   }

   bool CvdLongConfirm(const MqlRates &rates[], const int copied)
   {
      if(copied < CvdLookbackBars + 5)
         return false;
      double d1 = SyntheticDelta(rates[1]);
      double d2 = SyntheticDelta(rates[2]);
      double d3 = SyntheticDelta(rates[3]);
      double d4 = SyntheticDelta(rates[4]);
      double avgAbs = (MathAbs(d2) + MathAbs(d3) + MathAbs(d4)) / 3.0;
      double cvdNow = d1 + d2 + d3;
      double cvdPast = d2 + d3 + d4;
      bool divergence = rates[1].low < rates[3].low && cvdNow > cvdPast;
      bool spike = d1 > MathMax(avgAbs * CvdSpikeMultiplier, MathAbs(d2 + d3) * 0.50);
      return divergence || spike;
   }

   bool CvdShortConfirm(const MqlRates &rates[], const int copied)
   {
      if(copied < CvdLookbackBars + 5)
         return false;
      double d1 = SyntheticDelta(rates[1]);
      double d2 = SyntheticDelta(rates[2]);
      double d3 = SyntheticDelta(rates[3]);
      double d4 = SyntheticDelta(rates[4]);
      double avgAbs = (MathAbs(d2) + MathAbs(d3) + MathAbs(d4)) / 3.0;
      double cvdNow = d1 + d2 + d3;
      double cvdPast = d2 + d3 + d4;
      bool divergence = rates[1].high > rates[3].high && cvdNow < cvdPast;
      bool spike = d1 < -MathMax(avgAbs * CvdSpikeMultiplier, MathAbs(d2 + d3) * 0.50);
      return divergence || spike;
   }

   bool DisplacementAndFVG(const MqlRates &rates[], const int copied, const int side, const double atr, double &midpoint)
   {
      if(copied < 8 || atr <= 0)
         return false;
      double body = MathAbs(rates[1].close - rates[1].open);
      if(body < atr * DisplacementBodyATR)
         return false;

      if(side == 1)
      {
         if(rates[1].close <= rates[1].open)
            return false;
         if(rates[1].close <= HighestFromRates(rates, 2, DisplacementBreakLookback))
            return false;
         bool fvg = rates[1].low > rates[3].high;
         if(RequireFVG && !fvg)
            return false;
         midpoint = fvg ? (rates[1].low + rates[3].high) / 2.0 : (rates[1].open + rates[1].close) / 2.0;
         return true;
      }
      if(side == -1)
      {
         if(rates[1].close >= rates[1].open)
            return false;
         if(rates[1].close >= LowestFromRates(rates, 2, DisplacementBreakLookback))
            return false;
         bool fvg = rates[1].high < rates[3].low;
         if(RequireFVG && !fvg)
            return false;
         midpoint = fvg ? (rates[1].high + rates[3].low) / 2.0 : (rates[1].open + rates[1].close) / 2.0;
         return true;
      }
      return false;
   }

   double OpposingTarget(const int side, const double entry, const SLiquidityPools &pools)
   {
      double target = 0.0;
      if(side == 1)
      {
         double candidates[3];
         candidates[0] = pools.asiaHigh;
         candidates[1] = pools.prevDayHigh;
         candidates[2] = pools.rollingHigh;
         for(int i = 0; i < 3; i++)
            if(candidates[i] > entry && (target == 0.0 || candidates[i] < target))
               target = candidates[i];
      }
      else if(side == -1)
      {
         double candidates[3];
         candidates[0] = pools.asiaLow;
         candidates[1] = pools.prevDayLow;
         candidates[2] = pools.rollingLow;
         for(int i = 0; i < 3; i++)
            if(candidates[i] > 0 && candidates[i] < entry && (target == 0.0 || candidates[i] > target))
               target = candidates[i];
      }
      return target;
   }

public:
   bool BuildSignal(const string symbol, const SAssetProfile &profile, const SVwapState &vwap, STradeSignal &sig)
   {
      sig.valid = false;
      sig.symbol = symbol;
      sig.bucket = profile.bucket;
      sig.side = 0;
      sig.reason = "";

      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int needed = MathMax(ATRPeriod + 20, MathMax(RollingPoolLookbackBars + 20, 160));
      int copied = CopyRates(symbol, SignalTF, 0, needed, rates);
      if(copied < needed / 2)
      {
         sig.reason = "not_enough_rates";
         return false;
      }

      double atr = ATRFromRates(rates, copied, 1);
      if(atr <= 0)
      {
         sig.reason = "invalid_atr";
         return false;
      }

      SLiquidityPools pools;
      if(!BuildPools(symbol, rates, copied, pools))
      {
         sig.reason = "no_liquidity_pools";
         return false;
      }

      int side = 0;
      string setup = "";
      double swept = 0.0;
      double extreme = 0.0;
      double depthATR = 0.0;
      MqlRates bar = rates[1];

      if(UseAsianLiquidity)
      {
         if(BullSweep(bar, pools.asiaLow, atr, extreme, depthATR))
         { side = 1; setup = "asia_low_sweep_absorption"; swept = pools.asiaLow; }
         else if(BearSweep(bar, pools.asiaHigh, atr, extreme, depthATR))
         { side = -1; setup = "asia_high_sweep_absorption"; swept = pools.asiaHigh; }
      }
      if(side == 0 && UsePreviousDayLiquidity)
      {
         if(BullSweep(bar, pools.prevDayLow, atr, extreme, depthATR))
         { side = 1; setup = "pdl_sweep_absorption"; swept = pools.prevDayLow; }
         else if(BearSweep(bar, pools.prevDayHigh, atr, extreme, depthATR))
         { side = -1; setup = "pdh_sweep_absorption"; swept = pools.prevDayHigh; }
      }
      if(side == 0 && UseRollingIntradayLiquidity)
      {
         if(BullSweep(bar, pools.rollingLow, atr, extreme, depthATR))
         { side = 1; setup = "rolling_low_sweep_absorption"; swept = pools.rollingLow; }
         else if(BearSweep(bar, pools.rollingHigh, atr, extreme, depthATR))
         { side = -1; setup = "rolling_high_sweep_absorption"; swept = pools.rollingHigh; }
      }
      if(side == 0)
      {
         sig.reason = "no_sweep_reclaim";
         return false;
      }

      if(RequireAVWAPExtreme && vwap.valid)
      {
         if(side == 1 && !(bar.close < vwap.lower2))
         { sig.reason = "long_not_below_avwap_minus2sd"; return false; }
         if(side == -1 && !(bar.close > vwap.upper2))
         { sig.reason = "short_not_above_avwap_plus2sd"; return false; }
      }

      if(RequireSyntheticCvdConfirm)
      {
         bool ok = side == 1 ? CvdLongConfirm(rates, copied) : CvdShortConfirm(rates, copied);
         if(!ok)
         { sig.reason = "synthetic_cvd_no_absorption_divergence"; return false; }
      }

      double fvgMid = 0.0;
      if(!DisplacementAndFVG(rates, copied, side, atr, fvgMid))
      { sig.reason = "no_displacement_or_fvg"; return false; }

      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      if(ask <= 0 || bid <= 0)
      { sig.reason = "invalid_bid_ask"; return false; }

      double entry = side == 1 ? ask : bid;
      double sl = side == 1 ? extreme - atr * SL_ATR_Padding : extreme + atr * SL_ATR_Padding;
      double risk = MathAbs(entry - sl);
      if(risk < atr * profile.minStopATR)
      {
         sl = side == 1 ? entry - atr * profile.minStopATR : entry + atr * profile.minStopATR;
         risk = MathAbs(entry - sl);
      }
      if(risk > atr * profile.maxStopATR)
      { sig.reason = "stop_distance_outside_profile"; return false; }

      double tp = OpposingTarget(side, entry, pools);
      if(tp <= 0.0)
         tp = side == 1 ? entry + risk * FallbackRR : entry - risk * FallbackRR;
      double rr = side == 1 ? (tp - entry) / risk : (entry - tp) / risk;
      if(rr < MinimumRR)
      {
         tp = side == 1 ? entry + risk * MinimumRR : entry - risk * MinimumRR;
         rr = MinimumRR;
      }

      bool useLimit = false;
      if(PreferLimitAtVacuumMidpoint)
      {
         if(side == 1 && fvgMid < ask && fvgMid > sl)
            useLimit = true;
         if(side == -1 && fvgMid > bid && fvgMid < sl)
            useLimit = true;
      }

      sig.valid = true;
      sig.symbol = symbol;
      sig.bucket = profile.bucket;
      sig.side = side;
      sig.setup = setup;
      sig.entryHint = useLimit ? fvgMid : entry;
      sig.stopLoss = sl;
      sig.takeProfit = tp;
      sig.riskDistance = MathAbs(sig.entryHint - sig.stopLoss);
      sig.rr = side == 1 ? (sig.takeProfit - sig.entryHint) / sig.riskDistance : (sig.entryHint - sig.takeProfit) / sig.riskDistance;
      sig.atr = atr;
      sig.sweptLevel = swept;
      sig.sweepExtreme = extreme;
      sig.fvgMidpoint = fvgMid;
      sig.useLimit = useLimit;
      sig.reason = StringFormat("vwap=%.5f sd=%.5f sweepATR=%.2f fvgMid=%.5f", vwap.vwap, vwap.sd, depthATR, fvgMid);
      return true;
   }
};

//====================================================================
// PORTFOLIO RISK MANAGER
//====================================================================
class CPortfolioRiskManager
{
private:
   datetime m_day;
   double   m_dayStartEquity;
   string   m_symbols[];
   datetime m_symbolDay[];
   int      m_symbolTrades[];

public:
   void Init(string &symbols[])
   {
      int n = ArraySize(symbols);
      ArrayResize(m_symbols, n);
      ArrayResize(m_symbolDay, n);
      ArrayResize(m_symbolTrades, n);
      for(int i = 0; i < n; i++)
      {
         m_symbols[i] = symbols[i];
         m_symbolDay[i] = 0;
         m_symbolTrades[i] = 0;
      }
      m_day = DayStart(AdjustedTime(TimeCurrent()));
      m_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   }

   void ResetIfNewDay()
   {
      datetime d = DayStart(AdjustedTime(TimeCurrent()));
      if(d != m_day)
      {
         m_day = d;
         m_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
         for(int i = 0; i < ArraySize(m_symbolTrades); i++)
         {
            m_symbolTrades[i] = 0;
            m_symbolDay[i] = d;
         }
      }
   }

   bool DailyLossExceeded()
   {
      if(MaxDailyLossPercent <= 0 || m_dayStartEquity <= 0)
         return false;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double dd = (m_dayStartEquity - equity) / m_dayStartEquity * 100.0;
      return dd >= MaxDailyLossPercent;
   }

   int SymbolIndex(const string symbol)
   {
      for(int i = 0; i < ArraySize(m_symbols); i++)
         if(m_symbols[i] == symbol)
            return i;
      return -1;
   }

   int CountPortfolioExposure()
   {
      int c = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0 || !PositionSelectByTicket(t))
            continue;
         long magic = PositionGetInteger(POSITION_MAGIC);
         if(magic >= MagicBase && magic <= MagicBase + 9999)
            c++;
      }
      for(int j = OrdersTotal() - 1; j >= 0; j--)
      {
         ulong t = OrderGetTicket(j);
         if(t == 0 || !OrderSelect(t))
            continue;
         long magic = OrderGetInteger(ORDER_MAGIC);
         if(magic >= MagicBase && magic <= MagicBase + 9999)
            c++;
      }
      return c;
   }

   int CountSymbolExposure(const string symbol)
   {
      int c = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0 || !PositionSelectByTicket(t))
            continue;
         long magic = PositionGetInteger(POSITION_MAGIC);
         if(PositionGetString(POSITION_SYMBOL) == symbol && magic >= MagicBase && magic <= MagicBase + 9999)
            c++;
      }
      for(int j = OrdersTotal() - 1; j >= 0; j--)
      {
         ulong t = OrderGetTicket(j);
         if(t == 0 || !OrderSelect(t))
            continue;
         long magic = OrderGetInteger(ORDER_MAGIC);
         if(OrderGetString(ORDER_SYMBOL) == symbol && magic >= MagicBase && magic <= MagicBase + 9999)
            c++;
      }
      return c;
   }

   int CountBucketExposure(const string bucket, CBrokerProfileEngine &profileEngine)
   {
      int c = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0 || !PositionSelectByTicket(t))
            continue;
         long magic = PositionGetInteger(POSITION_MAGIC);
         if(magic < MagicBase || magic > MagicBase + 9999)
            continue;
         SAssetProfile p = profileEngine.Profile(PositionGetString(POSITION_SYMBOL));
         if(p.bucket == bucket)
            c++;
      }
      for(int j = OrdersTotal() - 1; j >= 0; j--)
      {
         ulong t = OrderGetTicket(j);
         if(t == 0 || !OrderSelect(t))
            continue;
         long magic = OrderGetInteger(ORDER_MAGIC);
         if(magic < MagicBase || magic > MagicBase + 9999)
            continue;
         SAssetProfile p = profileEngine.Profile(OrderGetString(ORDER_SYMBOL));
         if(p.bucket == bucket)
            c++;
      }
      return c;
   }

   bool CanOpen(const string symbol, const string bucket, CBrokerProfileEngine &profileEngine, string &reason)
   {
      ResetIfNewDay();
      if(DailyLossExceeded())
      { reason = "max_daily_loss_reached"; return false; }
      if(CountPortfolioExposure() >= MaxPortfolioPositions)
      { reason = "max_portfolio_positions"; return false; }
      if(CountSymbolExposure(symbol) >= MaxPositionsPerSymbol)
      { reason = "max_positions_per_symbol"; return false; }
      if(CountBucketExposure(bucket, profileEngine) >= MaxPositionsPerBucket)
      { reason = "max_positions_per_bucket"; return false; }

      int idx = SymbolIndex(symbol);
      if(idx >= 0)
      {
         datetime d = CurrentSessionDayKey(symbol);
         if(m_symbolDay[idx] != d)
         {
            m_symbolDay[idx] = d;
            m_symbolTrades[idx] = 0;
         }
         if(m_symbolTrades[idx] >= MaxTradesPerSymbolPerDay)
         { reason = "max_trades_per_symbol_day"; return false; }
      }
      reason = "ok";
      return true;
   }

   void RegisterTrade(const string symbol)
   {
      int idx = SymbolIndex(symbol);
      if(idx < 0)
         return;
      datetime d = CurrentSessionDayKey(symbol);
      if(m_symbolDay[idx] != d)
      {
         m_symbolDay[idx] = d;
         m_symbolTrades[idx] = 0;
      }
      m_symbolTrades[idx]++;
   }

   double CalculateLots(const string symbol, const double stopDistance, const double profileRiskMultiplier)
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double riskMoney = equity * (RiskPercentPerTrade * profileRiskMultiplier) / 100.0;
      double tickValue = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      if(riskMoney <= 0 || tickValue <= 0 || tickSize <= 0 || stopDistance <= 0)
         return 0.0;
      double lossPerLot = stopDistance / tickSize * tickValue;
      if(lossPerLot <= 0)
         return 0.0;

      double lots = riskMoney / lossPerLot;
      double minLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double maxLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      if(step <= 0)
         return 0.0;
      lots = MathMax(minLot, MathMin(maxLot, lots));
      lots = MathFloor(lots / step) * step;
      return NormalizeDouble(lots, 2);
   }
};

//====================================================================
// EXECUTION ENGINE
//====================================================================
class CExecutionEngine
{
private:
   bool CanExecuteNow()
   {
      bool tester = (bool)MQLInfoInteger(MQL_TESTER);
      return (tester && ExecuteInTester) || AllowLiveTrading;
   }

   bool RetcodeOK(const uint retcode)
   {
      return retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_PLACED || retcode == TRADE_RETCODE_DONE_PARTIAL;
   }

   void LogSltpResult(const bool ok, const MqlTradeRequest &req, const MqlTradeResult &res, const string symbol, const string label)
   {
      if(!ok || !RetcodeOK(res.retcode))
      {
         LOG.Write("SLTP_ERROR", symbol, "", label, "", 0, req.sl, req.tp, 0, 0,
                   (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD), res.retcode, res.comment);
      }
      else if(DebugLogs)
      {
         LOG.Write("SLTP_OK", symbol, "", label, "", 0, req.sl, req.tp, 0, 0,
                   (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD), res.retcode, "modified");
      }
   }

   bool ValidateStops(const STradeSignal &sig, string &reason)
   {
      double point = SymbolPoint(sig.symbol);
      int stops = (int)SymbolInfoInteger(sig.symbol, SYMBOL_TRADE_STOPS_LEVEL);
      double minDistance = (double)MathMax(0, stops) * point;
      if(minDistance <= 0)
      { reason = "ok"; return true; }

      double ask = SymbolInfoDouble(sig.symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(sig.symbol, SYMBOL_BID);
      double ref = sig.side == 1 ? ask : bid;
      if(MathAbs(ref - sig.stopLoss) < minDistance || MathAbs(sig.takeProfit - ref) < minDistance)
      { reason = "broker_min_stop_distance"; return false; }

      reason = "ok";
      return true;
   }

public:
   bool Send(const STradeSignal &sig, const SAssetProfile &profile, CPortfolioRiskManager &risk)
   {
      int spread = (int)SymbolInfoInteger(sig.symbol, SYMBOL_SPREAD);
      string sideName = sig.side == 1 ? "long" : "short";

      if(!CanExecuteNow())
      {
         LOG.Write("BLOCKED", sig.symbol, sig.bucket, sig.setup, sideName, sig.entryHint, sig.stopLoss, sig.takeProfit, sig.rr, sig.atr, spread, 0, "trading_disabled " + sig.reason);
         return false;
      }

      string stopReason;
      if(!ValidateStops(sig, stopReason))
      {
         LOG.Write("SKIP", sig.symbol, sig.bucket, sig.setup, sideName, sig.entryHint, sig.stopLoss, sig.takeProfit, sig.rr, sig.atr, spread, 0, stopReason);
         return false;
      }

      double lots = risk.CalculateLots(sig.symbol, MathAbs(sig.entryHint - sig.stopLoss), profile.riskMultiplier);
      if(lots <= 0.0)
      {
         LOG.Write("SKIP", sig.symbol, sig.bucket, sig.setup, sideName, sig.entryHint, sig.stopLoss, sig.takeProfit, sig.rr, sig.atr, spread, 0, "invalid_lot_size");
         return false;
      }

      MqlTradeRequest req;
      MqlTradeResult  res;
      ZeroMemory(req);
      ZeroMemory(res);

      req.symbol = sig.symbol;
      req.magic = MagicBase + HashSymbol(sig.symbol);
      req.volume = lots;
      req.sl = NormalizePrice(sig.symbol, sig.stopLoss);
      req.tp = NormalizePrice(sig.symbol, sig.takeProfit);
      req.deviation = profile.deviationPoints;
      req.comment = sig.setup;

      if(sig.useLimit)
      {
         req.action = TRADE_ACTION_PENDING;
         req.type = sig.side == 1 ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
         req.price = NormalizePrice(sig.symbol, sig.entryHint);
         req.type_time = ORDER_TIME_SPECIFIED;
         req.expiration = TimeCurrent() + PendingExpiryBars * PeriodSeconds(SignalTF);
      }
      else
      {
         req.action = TRADE_ACTION_DEAL;
         req.type = sig.side == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
         req.price = NormalizePrice(sig.symbol, sig.side == 1 ? SymbolInfoDouble(sig.symbol, SYMBOL_ASK) : SymbolInfoDouble(sig.symbol, SYMBOL_BID));
         req.type_time = ORDER_TIME_GTC;
      }

      bool ok = OrderSend(req, res);
      if(!ok || !RetcodeOK(res.retcode))
      {
         LOG.Write("ORDER_ERROR", sig.symbol, sig.bucket, sig.setup, sideName, req.price, req.sl, req.tp, sig.rr, sig.atr, spread, res.retcode, res.comment);
         return false;
      }

      risk.RegisterTrade(sig.symbol);
      LOG.Write(sig.useLimit ? "LIMIT_PLACED" : "MARKET_FILLED", sig.symbol, sig.bucket, sig.setup, sideName, req.price, req.sl, req.tp, sig.rr, sig.atr, spread, res.retcode, sig.reason);
      return true;
   }

   void ManageOpenPositions()
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket))
            continue;

         string sym = PositionGetString(POSITION_SYMBOL);
         long magic = PositionGetInteger(POSITION_MAGIC);
         if(magic < MagicBase || magic > MagicBase + 9999)
            continue;

         datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);
         int barsHeld = iBarShift(sym, SignalTF, openTime, false);
         if(barsHeld >= MaxBarsInTrade)
         {
            ClosePosition(ticket, sym, "max_bars_in_trade");
            continue;
         }

         if(MoveToBreakeven)
            TryMoveBreakeven(ticket, sym);
         if(UseATRTrailing)
            TryATRTrailing(ticket, sym);
      }
   }

   bool ClosePosition(const ulong ticket, const string symbol, const string reason)
   {
      if(!PositionSelectByTicket(ticket))
         return false;

      int type = (int)PositionGetInteger(POSITION_TYPE);
      double volume = PositionGetDouble(POSITION_VOLUME);
      double price = type == POSITION_TYPE_BUY ? SymbolInfoDouble(symbol, SYMBOL_BID) : SymbolInfoDouble(symbol, SYMBOL_ASK);

      MqlTradeRequest req;
      MqlTradeResult res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_DEAL;
      req.position = ticket;
      req.symbol = symbol;
      req.volume = volume;
      req.type = type == POSITION_TYPE_BUY ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.price = NormalizePrice(symbol, price);
      req.deviation = ManualDeviationPoints > 0 ? ManualDeviationPoints : 30;
      req.magic = MagicBase + HashSymbol(symbol);
      req.comment = reason;

      bool ok = OrderSend(req, res);
      LOG.Write(ok && RetcodeOK(res.retcode) ? "CLOSE_SENT" : "CLOSE_ERROR", symbol, "", reason, "", req.price, 0, 0, 0, 0, (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD), res.retcode, res.comment);
      return ok && RetcodeOK(res.retcode);
   }

   void TryMoveBreakeven(const ulong ticket, const string symbol)
   {
      if(!PositionSelectByTicket(ticket))
         return;
      int type = (int)PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(sl <= 0)
         return;

      double point = SymbolPoint(symbol);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double risk = MathAbs(open - sl);
      if(risk <= 0)
         return;

      double newSL = sl;
      if(type == POSITION_TYPE_BUY)
      {
         double rNow = (bid - open) / risk;
         if(rNow >= BreakevenAtR && sl < open)
            newSL = NormalizePrice(symbol, open + BreakevenPlusPoints * point);
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double rNow = (open - ask) / risk;
         if(rNow >= BreakevenAtR && sl > open)
            newSL = NormalizePrice(symbol, open - BreakevenPlusPoints * point);
      }

      if(newSL == sl)
         return;

      MqlTradeRequest req;
      MqlTradeResult res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_SLTP;
      req.position = ticket;
      req.symbol = symbol;
      req.sl = newSL;
      req.tp = tp;
      req.magic = MagicBase + HashSymbol(symbol);

      bool ok = OrderSend(req, res);
      LogSltpResult(ok, req, res, symbol, "breakeven_modify");
   }

   void TryATRTrailing(const ulong ticket, const string symbol)
   {
      if(!PositionSelectByTicket(ticket))
         return;

      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      if(CopyRates(symbol, SignalTF, 0, ATRPeriod + 5, rates) < ATRPeriod + 2)
         return;

      double atr = 0.0;
      for(int i = 1; i <= ATRPeriod; i++)
      {
         double tr = MathMax(rates[i].high - rates[i].low,
                             MathMax(MathAbs(rates[i].high - rates[i + 1].close), MathAbs(rates[i].low - rates[i + 1].close)));
         atr += tr;
      }
      atr /= (double)ATRPeriod;
      if(atr <= 0)
         return;

      int type = (int)PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      if(sl <= 0)
         return;
      double risk = MathAbs(open - sl);
      if(risk <= 0)
         return;

      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double newSL = sl;

      if(type == POSITION_TYPE_BUY)
      {
         double rNow = (bid - open) / risk;
         double proposed = bid - atr * TrailATRMult;
         if(rNow >= TrailStartR && proposed > sl && proposed < bid)
            newSL = NormalizePrice(symbol, proposed);
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double rNow = (open - ask) / risk;
         double proposed = ask + atr * TrailATRMult;
         if(rNow >= TrailStartR && proposed < sl && proposed > ask)
            newSL = NormalizePrice(symbol, proposed);
      }

      if(newSL == sl)
         return;

      MqlTradeRequest req;
      MqlTradeResult res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_SLTP;
      req.position = ticket;
      req.symbol = symbol;
      req.sl = newSL;
      req.tp = tp;
      req.magic = MagicBase + HashSymbol(symbol);

      bool ok = OrderSend(req, res);
      LogSltpResult(ok, req, res, symbol, "atr_trailing_modify");
   }
};

//====================================================================
// GLOBALS
//====================================================================
string Symbols[];
datetime LastBarTimes[];
CBrokerProfileEngine PROFILE;
CVwapEngine VWAP;
CLiquidityEngine LIQUIDITY;
CPortfolioRiskManager RISK;
CExecutionEngine EXECUTION;

//====================================================================
// LIFECYCLE
//====================================================================
int OnInit()
{
   int n = ParseSymbols(InpSymbols, Symbols);
   if(n <= 0)
   {
      Print("No symbols configured.");
      return INIT_FAILED;
   }

   ArrayResize(LastBarTimes, n);
   for(int i = 0; i < n; i++)
   {
      if(!SymbolSelect(Symbols[i], true))
         Print("Warning: could not select symbol ", Symbols[i]);
      LastBarTimes[i] = 0;
   }

   LOG.Init(CsvLogFile);
   RISK.Init(Symbols);
   LOG.Write("INIT", "PORTFOLIO", "", "CoreEA_MicrostructureAVWAPPro", "", 0, 0, 0, 0, 0, 0, 0,
             StringFormat("version=1.001 symbols=%d tf=%s live=%d tester=%d", n, EnumToString(SignalTF), AllowLiveTrading, ExecuteInTester));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   LOG.Write("DEINIT", "PORTFOLIO", "", "CoreEA_MicrostructureAVWAPPro", "", 0, 0, 0, 0, 0, 0, 0, IntegerToString(reason));
}

void OnTick()
{
   RISK.ResetIfNewDay();
   EXECUTION.ManageOpenPositions();

   for(int i = 0; i < ArraySize(Symbols); i++)
   {
      string sym = Symbols[i];
      datetime barTime = iTime(sym, SignalTF, 0);
      if(barTime <= 0 || barTime == LastBarTimes[i])
         continue;
      LastBarTimes[i] = barTime;
      ProcessSymbol(sym);
   }
}

//====================================================================
// MAIN PIPELINE
//====================================================================
void ProcessSymbol(const string symbol)
{
   if(!IsTradeTimeAllowed(symbol))
      return;

   SAssetProfile profile = PROFILE.Profile(symbol);
   int spread = (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   if(spread <= 0 || spread > profile.maxSpreadPoints)
   {
      LOG.Write("SKIP", symbol, profile.bucket, "spread_filter", "", 0, 0, 0, 0, 0, spread, 0, "spread_rejected");
      return;
   }

   string riskReason;
   if(!RISK.CanOpen(symbol, profile.bucket, PROFILE, riskReason))
   {
      LOG.Write("SKIP", symbol, profile.bucket, "portfolio_risk", "", 0, 0, 0, 0, 0, spread, 0, riskReason);
      return;
   }

   SVwapState vwap;
   if(!VWAP.Calculate(symbol, vwap))
   {
      LOG.Write("SKIP", symbol, profile.bucket, "avwap", "", 0, 0, 0, 0, 0, spread, 0, "vwap_invalid");
      return;
   }

   STradeSignal sig;
   if(!LIQUIDITY.BuildSignal(symbol, profile, vwap, sig))
   {
      LOG.Write("SKIP", symbol, profile.bucket, "liquidity_engine", "", 0, 0, 0, 0, 0, spread, 0, sig.reason);
      return;
   }

   if(sig.rr < MinimumRR)
   {
      LOG.Write("SKIP", symbol, profile.bucket, sig.setup, sig.side == 1 ? "long" : "short", sig.entryHint, sig.stopLoss, sig.takeProfit, sig.rr, sig.atr, spread, 0, "rr_below_minimum");
      return;
   }

   EXECUTION.Send(sig, profile, RISK);
}
//+------------------------------------------------------------------+
