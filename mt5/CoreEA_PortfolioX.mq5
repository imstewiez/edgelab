//+------------------------------------------------------------------+
//| CoreEA PortfolioX                                                 |
//| MT5 Expert Advisor                                                |
//|                                                                  |
//| Production-oriented multi-system portfolio EA.                    |
//|                                                                  |
//| Built from the session lessons:                                   |
//| - A single universal liquidity model is fragile.                  |
//| - Pure SMC/liquidity labels over-filter or overtrade.             |
//| - The realistic structure is a portfolio of independent systems.  |
//| - Diversification is conditional; sizing/risk governors matter.    |
//| - Target development metric should be Calmar-like: return/DD.     |
//|                                                                  |
//| Systems included:                                                 |
//|  0 Trend pullback                                                  |
//|  1 Momentum breakout                                               |
//|  2 Late-cycle fast-move trail                                      |
//|  3 Downside/risk-off participation                                 |
//|  4 Correction rebound / reduced exposure                           |
//|  5 Multi-timeframe trend core                                      |
//|  6 AVWAP liquidity reversion                                      |
//|  7 Volatility expansion                                            |
//|  8 Defensive cash/no-trade regime                                  |
//|                                                                  |
//| Live trading is blocked unless AllowLiveTrading=true.              |
//+------------------------------------------------------------------+
#property strict
#property version   "1.000"
#property description "CoreEA PortfolioX - multi-system systematic portfolio EA"

#define MODULE_COUNT 9

//====================================================================
// INPUTS
//====================================================================
input group "01. General"
input bool             AllowLiveTrading          = false;
input bool             ExecuteInTester           = true;
input string           InpSymbols                = "XAUUSD,EURUSD,GBPUSD,AUDUSD,NZDUSD,USDCAD,USDCHF,USDJPY,EURJPY,GBPJPY";
input ENUM_TIMEFRAMES  EntryTF                   = PERIOD_M15;
input ENUM_TIMEFRAMES  RegimeTF                  = PERIOD_H1;
input ENUM_TIMEFRAMES  CoreTF                    = PERIOD_H4;
input int              MagicBase                 = 996000;
input bool             DebugLogs                 = true;
input string           CsvLogFile                = "CoreEA_PortfolioX.csv";

input group "02. Portfolio Risk"
input double           BaseRiskPercent           = 0.18;
input int              MaxPortfolioPositions     = 5;
input int              MaxPositionsPerSymbol     = 1;
input int              MaxPositionsPerBucket     = 2;
input int              MaxPositionsPerSystem     = 2;
input int              MaxTradesPerSymbolPerDay  = 3;
input int              MaxTradesPerSystemPerDay  = 4;
input double           MaxDailyLossPercent       = 2.0;
input double           EquityKillDDPercent       = 8.0;
input double           RiskCutDD1Percent         = 3.0;
input double           RiskCutDD1Multiplier      = 0.50;
input double           RiskCutDD2Percent         = 5.0;
input double           RiskCutDD2Multiplier      = 0.25;

input group "03. Session / Broker Adaptation"
input int              SessionTimeShiftHours     = 0;
input int              TradeStartHour            = 7;
input int              TradeEndHour              = 20;
input bool             AvoidFridayLate           = true;
input int              FridayCutoffHour          = 16;
input int              ManualMaxSpreadPoints     = 0;      // 0 = auto profile
input int              ManualDeviationPoints     = 0;      // 0 = auto profile
input bool             OneSignalPerSymbolPerBar  = true;

input group "04. Indicators / Regime"
input int              ATRPeriod                 = 14;
input int              FastEMA                   = 50;
input int              SlowEMA                   = 200;
input int              PullbackEMA               = 21;
input int              ADXPeriod                 = 14;
input double           TrendADXMin               = 19.0;
input double           StrongTrendADX            = 28.0;
input double           RangeADXMax               = 17.0;

input group "05. Module Enables"
input bool             EnableTrendPullback       = true;
input bool             EnableMomentumBreakout    = true;
input bool             EnableLateCycleFastMove   = true;
input bool             EnableDownsideRiskOff     = true;
input bool             EnableCorrectionRebound   = true;
input bool             EnableMTFTrendCore        = true;
input bool             EnableAVWAPLiquidity      = true;
input bool             EnableVolatilityExpansion = true;
input bool             EnableDefensiveRegime     = true;

input group "06. Module Risk Multipliers"
input double           RiskTrendPullback         = 1.00;
input double           RiskMomentumBreakout      = 0.80;
input double           RiskLateCycleFastMove     = 0.60;
input double           RiskDownsideRiskOff       = 0.80;
input double           RiskCorrectionRebound     = 0.20;
input double           RiskMTFTrendCore          = 0.90;
input double           RiskAVWAPLiquidity        = 0.70;
input double           RiskVolatilityExpansion   = 0.75;

input group "07. Module Parameters"
input int              BreakoutLookback          = 40;
input int              SwingLookback             = 8;
input int              RangeLookback             = 96;
input int              AVWAPMaxBars              = 500;
input int              AVWAPLondonAnchorHour     = 7;
input int              AVWAPNewYorkAnchorHour    = 13;
input double           AVWAPBandSD               = 1.35;
input int              AsiaStartHour             = 0;
input int              AsiaEndHour               = 7;
input int              RollingLiquidityLookback  = 64;
input double           MinBodyATR                = 0.35;
input double           MomentumBodyATR           = 0.55;
input double           VolExpansionRatio         = 1.25;
input double           RangeDeviationATR         = 1.20;

input group "08. Exits / Trade Management"
input double           DefaultRR                 = 1.65;
input double           MinimumRR                 = 1.25;
input double           StopATRMult               = 1.35;
input bool             MoveToBreakeven           = true;
input double           BreakevenAtR              = 0.90;
input double           BreakevenPlusPoints       = 2.0;
input bool             UseATRTrailing            = true;
input double           TrailStartR               = 1.35;
input double           TrailATRMult              = 1.15;

//====================================================================
// ENUMS / STRUCTS
//====================================================================
enum EModuleId
{
   MOD_TREND_PULLBACK = 0,
   MOD_MOMENTUM_BREAKOUT = 1,
   MOD_LATE_CYCLE_FAST_MOVE = 2,
   MOD_DOWNSIDE_RISK_OFF = 3,
   MOD_CORRECTION_REBOUND = 4,
   MOD_MTF_TREND_CORE = 5,
   MOD_AVWAP_LIQUIDITY = 6,
   MOD_VOLATILITY_EXPANSION = 7,
   MOD_DEFENSIVE_REGIME = 8
};

struct SAssetProfile
{
   string bucket;
   double riskMultiplier;
   int maxSpreadPoints;
   int deviationPoints;
   double minStopATR;
   double maxStopATR;
};

struct SSymbolState
{
   string symbol;
   datetime lastBarTime;
   int hATR;
   int hATRRegime;
   int hADX;
   int hFastEMA;
   int hSlowEMA;
   int hPullbackEMA;
   int hCoreFastEMA;
   int hCoreSlowEMA;
};

struct SSignal
{
   bool valid;
   string symbol;
   int moduleId;
   string moduleName;
   string bucket;
   int side;
   double entry;
   double sl;
   double tp;
   double riskDistance;
   double rr;
   double atr;
   double riskMultiplier;
   int maxHoldBars;
   string reason;
};

//====================================================================
// GLOBALS
//====================================================================
SSymbolState States[];
datetime g_day = 0;
double g_dayStartEquity = 0.0;
double g_equityPeak = 0.0;
int g_dailySymbolTrades[];
int g_dailyModuleTrades[];

//====================================================================
// BASIC UTILS
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

datetime AdjustedTime(const datetime t)
{
   return t + SessionTimeShiftHours * 3600;
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

datetime CurrentDayKey()
{
   return DayStart(AdjustedTime(TimeCurrent()));
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

long MagicFor(const int moduleId, const string symbol)
{
   return (long)(MagicBase + moduleId * 10000 + HashSymbol(symbol));
}

bool IsOurMagic(const long magic)
{
   return magic >= MagicBase && magic < MagicBase + MODULE_COUNT * 10000 + 9999;
}

int ModuleFromMagic(const long magic)
{
   if(!IsOurMagic(magic))
      return -1;
   int m = (int)((magic - MagicBase) / 10000);
   if(m < 0 || m >= MODULE_COUNT)
      return -1;
   return m;
}

double PointFor(const string symbol)
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

double BodySize(const string symbol, const ENUM_TIMEFRAMES tf, const int shift)
{
   return MathAbs(iClose(symbol, tf, shift) - iOpen(symbol, tf, shift));
}

bool BullishBar(const string symbol, const ENUM_TIMEFRAMES tf, const int shift)
{
   return iClose(symbol, tf, shift) > iOpen(symbol, tf, shift);
}

bool BearishBar(const string symbol, const ENUM_TIMEFRAMES tf, const int shift)
{
   return iClose(symbol, tf, shift) < iOpen(symbol, tf, shift);
}

bool TradeTimeAllowed(const string symbol)
{
   datetime t = iTime(symbol, EntryTF, 1);
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
class CLogger
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
      FileWrite(h, "time", "event", "symbol", "module", "bucket", "side", "price", "sl", "tp", "rr", "atr", "spread", "retcode", "note");
      FileClose(h);
   }

   void Write(const string eventType,
              const string symbol,
              const string moduleName,
              const string bucket,
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
         int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
         FileSeek(h, 0, SEEK_END);
         FileWrite(h,
                   TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
                   eventType,
                   symbol,
                   moduleName,
                   bucket,
                   side,
                   DoubleToString(price, digits),
                   DoubleToString(sl, digits),
                   DoubleToString(tp, digits),
                   DoubleToString(rr, 2),
                   DoubleToString(atr, digits),
                   spread,
                   retcode,
                   note);
         FileClose(h);
      }

      if(DebugLogs || eventType == "ORDER_ERROR" || eventType == "SKIP" || eventType == "CLOSE_ERROR")
         Print(eventType, " ", symbol, " ", moduleName, " ", side, " ", note);
   }
};

CLogger LOG;

//====================================================================
// PROFILE / MODULE CONFIG
//====================================================================
class CProfileEngine
{
public:
   SAssetProfile Profile(const string symbol)
   {
      SAssetProfile p;
      string s = UpperString(symbol);
      p.bucket = "FX_USD";
      p.riskMultiplier = 1.0;
      p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 45;
      p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 25;
      p.minStopATR = 0.55;
      p.maxStopATR = 5.00;

      if(StringFind(s, "XAU") >= 0 || StringFind(s, "GOLD") >= 0)
      {
         p.bucket = "METALS";
         p.riskMultiplier = 0.70;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 150;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 60;
         p.minStopATR = 0.75;
         p.maxStopATR = 6.50;
      }
      else if(StringFind(s, "BTC") >= 0 || StringFind(s, "ETH") >= 0)
      {
         p.bucket = "CRYPTO";
         p.riskMultiplier = 0.45;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 650;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 120;
         p.minStopATR = 0.90;
         p.maxStopATR = 8.00;
      }
      else if(StringFind(s, "NAS") >= 0 || StringFind(s, "US30") >= 0 || StringFind(s, "SPX") >= 0 || StringFind(s, "GER") >= 0 || StringFind(s, "DAX") >= 0)
      {
         p.bucket = "INDICES";
         p.riskMultiplier = 0.60;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 300;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 90;
         p.minStopATR = 0.80;
         p.maxStopATR = 7.00;
      }
      else if(StringFind(s, "JPY") >= 0)
      {
         p.bucket = "FX_JPY";
         p.riskMultiplier = 0.90;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 55;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 30;
         p.minStopATR = 0.60;
         p.maxStopATR = 5.50;
      }
      else if(StringFind(s, "GBP") >= 0)
      {
         p.bucket = "FX_GBP";
         p.riskMultiplier = 0.85;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 50;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 30;
      }
      else if(StringFind(s, "AUD") >= 0 || StringFind(s, "NZD") >= 0)
      {
         p.bucket = "FX_AUD_NZD";
         p.riskMultiplier = 1.0;
         p.maxSpreadPoints = ManualMaxSpreadPoints > 0 ? ManualMaxSpreadPoints : 45;
         p.deviationPoints = ManualDeviationPoints > 0 ? ManualDeviationPoints : 30;
      }
      return p;
   }
};

CProfileEngine PROFILE;

string ModuleName(const int moduleId)
{
   switch(moduleId)
   {
      case MOD_TREND_PULLBACK: return "TrendPullback";
      case MOD_MOMENTUM_BREAKOUT: return "MomentumBreakout";
      case MOD_LATE_CYCLE_FAST_MOVE: return "LateCycleFastMove";
      case MOD_DOWNSIDE_RISK_OFF: return "DownsideRiskOff";
      case MOD_CORRECTION_REBOUND: return "CorrectionRebound";
      case MOD_MTF_TREND_CORE: return "MTFTrendCore";
      case MOD_AVWAP_LIQUIDITY: return "AVWAPLiquidity";
      case MOD_VOLATILITY_EXPANSION: return "VolatilityExpansion";
      case MOD_DEFENSIVE_REGIME: return "DefensiveRegime";
   }
   return "Unknown";
}

bool ModuleEnabled(const int moduleId)
{
   switch(moduleId)
   {
      case MOD_TREND_PULLBACK: return EnableTrendPullback;
      case MOD_MOMENTUM_BREAKOUT: return EnableMomentumBreakout;
      case MOD_LATE_CYCLE_FAST_MOVE: return EnableLateCycleFastMove;
      case MOD_DOWNSIDE_RISK_OFF: return EnableDownsideRiskOff;
      case MOD_CORRECTION_REBOUND: return EnableCorrectionRebound;
      case MOD_MTF_TREND_CORE: return EnableMTFTrendCore;
      case MOD_AVWAP_LIQUIDITY: return EnableAVWAPLiquidity;
      case MOD_VOLATILITY_EXPANSION: return EnableVolatilityExpansion;
      case MOD_DEFENSIVE_REGIME: return EnableDefensiveRegime;
   }
   return false;
}

double ModuleRiskMultiplier(const int moduleId)
{
   switch(moduleId)
   {
      case MOD_TREND_PULLBACK: return RiskTrendPullback;
      case MOD_MOMENTUM_BREAKOUT: return RiskMomentumBreakout;
      case MOD_LATE_CYCLE_FAST_MOVE: return RiskLateCycleFastMove;
      case MOD_DOWNSIDE_RISK_OFF: return RiskDownsideRiskOff;
      case MOD_CORRECTION_REBOUND: return RiskCorrectionRebound;
      case MOD_MTF_TREND_CORE: return RiskMTFTrendCore;
      case MOD_AVWAP_LIQUIDITY: return RiskAVWAPLiquidity;
      case MOD_VOLATILITY_EXPANSION: return RiskVolatilityExpansion;
   }
   return 0.0;
}

double ModuleRR(const int moduleId)
{
   switch(moduleId)
   {
      case MOD_LATE_CYCLE_FAST_MOVE: return 1.35;
      case MOD_CORRECTION_REBOUND: return 1.85;
      case MOD_MTF_TREND_CORE: return 2.00;
      case MOD_AVWAP_LIQUIDITY: return 1.60;
      case MOD_VOLATILITY_EXPANSION: return 1.75;
      default: return DefaultRR;
   }
}

int ModuleMaxHoldBars(const int moduleId)
{
   switch(moduleId)
   {
      case MOD_LATE_CYCLE_FAST_MOVE: return 18;
      case MOD_CORRECTION_REBOUND: return 240;
      case MOD_MTF_TREND_CORE: return 120;
      case MOD_AVWAP_LIQUIDITY: return 32;
      case MOD_VOLATILITY_EXPANSION: return 28;
      default: return 48;
   }
}

//====================================================================
// INDICATOR HELPERS
//====================================================================
double BufferValue(const int handle, const int buffer, const int shift)
{
   double v[];
   ArraySetAsSeries(v, true);
   if(handle == INVALID_HANDLE)
      return 0.0;
   if(CopyBuffer(handle, buffer, shift, 1, v) != 1)
      return 0.0;
   return v[0];
}

double ATR(const int idx, const int shift=1)
{
   return BufferValue(States[idx].hATR, 0, shift);
}

double ADX(const int idx, const int shift=1)
{
   return BufferValue(States[idx].hADX, 0, shift);
}

double EMAFast(const int idx, const int shift=1)
{
   return BufferValue(States[idx].hFastEMA, 0, shift);
}

double EMASlow(const int idx, const int shift=1)
{
   return BufferValue(States[idx].hSlowEMA, 0, shift);
}

double EMAPullback(const int idx, const int shift=1)
{
   return BufferValue(States[idx].hPullbackEMA, 0, shift);
}

double CoreFast(const int idx, const int shift=1)
{
   return BufferValue(States[idx].hCoreFastEMA, 0, shift);
}

double CoreSlow(const int idx, const int shift=1)
{
   return BufferValue(States[idx].hCoreSlowEMA, 0, shift);
}

int TrendDirection(const int idx)
{
   double fast = EMAFast(idx, 1);
   double slow = EMASlow(idx, 1);
   double fastPrev = EMAFast(idx, 3);
   if(fast <= 0 || slow <= 0 || fastPrev <= 0)
      return 0;
   if(fast > slow && fast >= fastPrev)
      return 1;
   if(fast < slow && fast <= fastPrev)
      return -1;
   return 0;
}

int CoreTrendDirection(const int idx)
{
   double fast = CoreFast(idx, 1);
   double slow = CoreSlow(idx, 1);
   if(fast <= 0 || slow <= 0)
      return 0;
   if(fast > slow)
      return 1;
   if(fast < slow)
      return -1;
   return 0;
}

//====================================================================
// AVWAP / LIQUIDITY HELPERS
//====================================================================
bool CalculateAVWAP(const string symbol, double &vwap, double &sd, double &upper, double &lower)
{
   vwap = 0.0;
   sd = 0.0;
   upper = 0.0;
   lower = 0.0;

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, EntryTF, 0, AVWAPMaxBars, rates);
   if(copied < 20)
      return false;

   datetime ref = rates[1].time;
   datetime adj = AdjustedTime(ref);
   datetime today = DayStart(adj);
   datetime london = today + AVWAPLondonAnchorHour * 3600;
   datetime ny = today + AVWAPNewYorkAnchorHour * 3600;
   datetime anchorAdj = adj >= ny ? ny : (adj >= london ? london : DayStart(adj - 86400) + AVWAPNewYorkAnchorHour * 3600);
   datetime anchor = anchorAdj - SessionTimeShiftHours * 3600;

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

   if(used < 4)
   {
      int fallback = MathMin(48, copied - 1);
      sumPV = 0.0;
      sumV = 0.0;
      used = 0;
      for(int k = 1; k <= fallback; k++)
      {
         double typical = (rates[k].high + rates[k].low + rates[k].close) / 3.0;
         double vol = (double)MathMax((long)1, rates[k].tick_volume);
         sumPV += typical * vol;
         sumV += vol;
         used++;
      }
   }

   if(sumV <= 0.0 || used < 4)
      return false;

   vwap = sumPV / sumV;
   double variance = 0.0;
   for(int j = 1; j <= used; j++)
   {
      double typical = (rates[j].high + rates[j].low + rates[j].close) / 3.0;
      double vol = (double)MathMax((long)1, rates[j].tick_volume);
      variance += vol * MathPow(typical - vwap, 2.0);
   }
   variance /= sumV;
   sd = MathSqrt(MathMax(variance, 0.0));
   if(sd <= 0.0)
      sd = PointFor(symbol) * 10.0;
   upper = vwap + sd * AVWAPBandSD;
   lower = vwap - sd * AVWAPBandSD;
   return true;
}

double SyntheticDelta(const string symbol, const int shift)
{
   double high = iHigh(symbol, EntryTF, shift);
   double low = iLow(symbol, EntryTF, shift);
   double close = iClose(symbol, EntryTF, shift);
   long volume = iVolume(symbol, EntryTF, shift);
   double range = high - low;
   if(range <= 0)
      return 0.0;
   double loc = ((close - low) / range - 0.5) * 2.0;
   return (double)MathMax((long)1, volume) * loc;
}

bool CVDConfirms(const string symbol, const int side)
{
   double d1 = SyntheticDelta(symbol, 1);
   double d2 = SyntheticDelta(symbol, 2);
   double d3 = SyntheticDelta(symbol, 3);
   double d4 = SyntheticDelta(symbol, 4);
   double cvdNow = d1 + d2 + d3;
   double cvdPast = d2 + d3 + d4;
   if(side == 1)
      return (iLow(symbol, EntryTF, 1) < iLow(symbol, EntryTF, 3) && cvdNow > cvdPast) || d1 > MathAbs(d2 + d3) * 0.35;
   if(side == -1)
      return (iHigh(symbol, EntryTF, 1) > iHigh(symbol, EntryTF, 3) && cvdNow < cvdPast) || d1 < -MathAbs(d2 + d3) * 0.35;
   return false;
}

bool LiquiditySweepReclaim(const string symbol, const int side, double &level, double &extreme)
{
   double asiaHigh = -DBL_MAX;
   double asiaLow = DBL_MAX;
   datetime today = DayStart(AdjustedTime(iTime(symbol, EntryTF, 1)));
   for(int i = 1; i < 300; i++)
   {
      datetime t = iTime(symbol, EntryTF, i);
      if(t <= 0 || AdjustedTime(t) < today)
         break;
      MqlDateTime dt;
      TimeToStruct(AdjustedTime(t), dt);
      if(dt.hour >= AsiaStartHour && dt.hour < AsiaEndHour)
      {
         asiaHigh = MathMax(asiaHigh, iHigh(symbol, EntryTF, i));
         asiaLow = MathMin(asiaLow, iLow(symbol, EntryTF, i));
      }
   }

   double prevHigh = iHigh(symbol, PERIOD_D1, 1);
   double prevLow = iLow(symbol, PERIOD_D1, 1);
   double rollHigh = HighestHigh(symbol, EntryTF, 2, RollingLiquidityLookback);
   double rollLow = LowestLow(symbol, EntryTF, 2, RollingLiquidityLookback);

   double close = iClose(symbol, EntryTF, 1);
   double high = iHigh(symbol, EntryTF, 1);
   double low = iLow(symbol, EntryTF, 1);

   if(side == 1)
   {
      double lows[3];
      lows[0] = asiaLow == DBL_MAX ? 0.0 : asiaLow;
      lows[1] = prevLow;
      lows[2] = rollLow;
      for(int k = 0; k < 3; k++)
      {
         if(lows[k] > 0.0 && low < lows[k] && close > lows[k])
         {
            level = lows[k];
            extreme = low;
            return true;
         }
      }
   }
   if(side == -1)
   {
      double highs[3];
      highs[0] = asiaHigh == -DBL_MAX ? 0.0 : asiaHigh;
      highs[1] = prevHigh;
      highs[2] = rollHigh;
      for(int k = 0; k < 3; k++)
      {
         if(highs[k] > 0.0 && high > highs[k] && close < highs[k])
         {
            level = highs[k];
            extreme = high;
            return true;
         }
      }
   }
   return false;
}

//====================================================================
// DEFENSIVE REGIME
//====================================================================
bool DefensiveRegimeBlocks(const int idx, const SAssetProfile &profile, string &reason)
{
   if(!EnableDefensiveRegime)
      return false;

   string symbol = States[idx].symbol;
   int spread = (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   if(spread > profile.maxSpreadPoints)
   {
      reason = "spread_above_profile";
      return true;
   }

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_equityPeak > 0.0)
   {
      double peakDD = (g_equityPeak - equity) / g_equityPeak * 100.0;
      if(peakDD >= EquityKillDDPercent)
      {
         reason = "equity_kill_dd";
         return true;
      }
   }

   double atr = ATR(idx, 1);
   double price = iClose(symbol, EntryTF, 1);
   if(price > 0.0 && atr / price > 0.018 && profile.bucket != "CRYPTO")
   {
      reason = "abnormal_atr_percent";
      return true;
   }

   reason = "ok";
   return false;
}

//====================================================================
// SIGNAL ENGINE
//====================================================================
class CSignalEngine
{
private:
   bool PrepareSignal(const int idx, const int moduleId, const int side, const string reason, SSignal &sig)
   {
      string symbol = States[idx].symbol;
      SAssetProfile profile = PROFILE.Profile(symbol);
      double atr = ATR(idx, 1);
      if(atr <= 0.0 || side == 0)
         return false;

      double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
      double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
      if(ask <= 0.0 || bid <= 0.0)
         return false;

      double entry = side == 1 ? ask : bid;
      double swingLow = LowestLow(symbol, EntryTF, 1, SwingLookback);
      double swingHigh = HighestHigh(symbol, EntryTF, 1, SwingLookback);
      double sl = side == 1 ? MathMin(swingLow, entry - atr * StopATRMult) : MathMax(swingHigh, entry + atr * StopATRMult);
      double risk = MathAbs(entry - sl);

      if(risk < atr * profile.minStopATR)
      {
         sl = side == 1 ? entry - atr * profile.minStopATR : entry + atr * profile.minStopATR;
         risk = MathAbs(entry - sl);
      }
      if(risk > atr * profile.maxStopATR)
         return false;

      double rr = MathMax(MinimumRR, ModuleRR(moduleId));
      double tp = side == 1 ? entry + risk * rr : entry - risk * rr;

      sig.valid = true;
      sig.symbol = symbol;
      sig.moduleId = moduleId;
      sig.moduleName = ModuleName(moduleId);
      sig.bucket = profile.bucket;
      sig.side = side;
      sig.entry = entry;
      sig.sl = sl;
      sig.tp = tp;
      sig.riskDistance = risk;
      sig.rr = rr;
      sig.atr = atr;
      sig.riskMultiplier = ModuleRiskMultiplier(moduleId) * profile.riskMultiplier;
      sig.maxHoldBars = ModuleMaxHoldBars(moduleId);
      sig.reason = reason;
      return true;
   }

   bool TrendPullback(const int idx, SSignal &sig)
   {
      int dir = TrendDirection(idx);
      if(dir == 0 || ADX(idx, 1) < TrendADXMin)
         return false;

      string symbol = States[idx].symbol;
      double ema = EMAPullback(idx, 1);
      double atr = ATR(idx, 1);
      if(ema <= 0 || atr <= 0)
         return false;

      if(dir == 1)
      {
         bool pull = iLow(symbol, EntryTF, 1) <= ema || iLow(symbol, EntryTF, 2) <= ema;
         bool reclaim = iClose(symbol, EntryTF, 1) > ema && BullishBar(symbol, EntryTF, 1);
         bool impulse = BodySize(symbol, EntryTF, 1) >= atr * MinBodyATR;
         if(pull && reclaim && impulse)
            return PrepareSignal(idx, MOD_TREND_PULLBACK, 1, "trend_pullback_reclaim", sig);
      }
      else if(dir == -1)
      {
         bool pull = iHigh(symbol, EntryTF, 1) >= ema || iHigh(symbol, EntryTF, 2) >= ema;
         bool reclaim = iClose(symbol, EntryTF, 1) < ema && BearishBar(symbol, EntryTF, 1);
         bool impulse = BodySize(symbol, EntryTF, 1) >= atr * MinBodyATR;
         if(pull && reclaim && impulse)
            return PrepareSignal(idx, MOD_TREND_PULLBACK, -1, "trend_pullback_reclaim", sig);
      }
      return false;
   }

   bool MomentumBreakout(const int idx, SSignal &sig)
   {
      string symbol = States[idx].symbol;
      double atr = ATR(idx, 1);
      if(atr <= 0 || ADX(idx, 1) < TrendADXMin)
         return false;

      double close = iClose(symbol, EntryTF, 1);
      double hi = HighestHigh(symbol, EntryTF, 2, BreakoutLookback);
      double lo = LowestLow(symbol, EntryTF, 2, BreakoutLookback);
      double body = BodySize(symbol, EntryTF, 1);

      if(close > hi && BullishBar(symbol, EntryTF, 1) && body >= atr * MomentumBodyATR)
         return PrepareSignal(idx, MOD_MOMENTUM_BREAKOUT, 1, "donchian_momentum_breakout", sig);
      if(close < lo && BearishBar(symbol, EntryTF, 1) && body >= atr * MomentumBodyATR)
         return PrepareSignal(idx, MOD_MOMENTUM_BREAKOUT, -1, "donchian_momentum_breakout", sig);
      return false;
   }

   bool LateCycleFastMove(const int idx, SSignal &sig)
   {
      string symbol = States[idx].symbol;
      int dir = TrendDirection(idx);
      double adx = ADX(idx, 1);
      double atr = ATR(idx, 1);
      double fast = EMAFast(idx, 1);
      double close = iClose(symbol, EntryTF, 1);
      if(dir == 0 || adx < StrongTrendADX || atr <= 0 || fast <= 0)
         return false;

      double extension = MathAbs(close - fast) / atr;
      if(extension < 1.25)
         return false;

      if(dir == 1 && BullishBar(symbol, EntryTF, 1) && BodySize(symbol, EntryTF, 1) >= atr * MomentumBodyATR)
         return PrepareSignal(idx, MOD_LATE_CYCLE_FAST_MOVE, 1, "late_cycle_fast_long", sig);
      if(dir == -1 && BearishBar(symbol, EntryTF, 1) && BodySize(symbol, EntryTF, 1) >= atr * MomentumBodyATR)
         return PrepareSignal(idx, MOD_LATE_CYCLE_FAST_MOVE, -1, "late_cycle_fast_short", sig);
      return false;
   }

   bool DownsideRiskOff(const int idx, SSignal &sig)
   {
      string symbol = States[idx].symbol;
      int dir = TrendDirection(idx);
      double atr = ATR(idx, 1);
      if(dir != -1 || atr <= 0 || ADX(idx, 1) < TrendADXMin)
         return false;
      double close = iClose(symbol, EntryTF, 1);
      double lo = LowestLow(symbol, EntryTF, 2, BreakoutLookback / 2);
      if(close < lo && BearishBar(symbol, EntryTF, 1) && BodySize(symbol, EntryTF, 1) >= atr * MinBodyATR)
         return PrepareSignal(idx, MOD_DOWNSIDE_RISK_OFF, -1, "downside_trend_participation", sig);
      return false;
   }

   bool CorrectionRebound(const int idx, SSignal &sig)
   {
      string symbol = States[idx].symbol;
      double atr = ATR(idx, 1);
      double fast = EMAFast(idx, 1);
      if(atr <= 0 || fast <= 0 || ADX(idx, 1) > RangeADXMax + 7.0)
         return false;

      double close = iClose(symbol, EntryTF, 1);
      double deviation = (fast - close) / atr;
      if(deviation >= RangeDeviationATR && BullishBar(symbol, EntryTF, 1))
         return PrepareSignal(idx, MOD_CORRECTION_REBOUND, 1, "correction_rebound_discount", sig);
      return false;
   }

   bool MTFTrendCore(const int idx, SSignal &sig)
   {
      int coreDir = CoreTrendDirection(idx);
      int regimeDir = TrendDirection(idx);
      if(coreDir == 0 || coreDir != regimeDir || ADX(idx, 1) < TrendADXMin)
         return false;

      string symbol = States[idx].symbol;
      double atr = ATR(idx, 1);
      if(atr <= 0)
         return false;

      if(coreDir == 1 && BullishBar(symbol, EntryTF, 1) && iClose(symbol, EntryTF, 1) > EMAPullback(idx, 1))
         return PrepareSignal(idx, MOD_MTF_TREND_CORE, 1, "mtf_trend_core_long", sig);
      if(coreDir == -1 && BearishBar(symbol, EntryTF, 1) && iClose(symbol, EntryTF, 1) < EMAPullback(idx, 1))
         return PrepareSignal(idx, MOD_MTF_TREND_CORE, -1, "mtf_trend_core_short", sig);
      return false;
   }

   bool AVWAPLiquidity(const int idx, SSignal &sig)
   {
      string symbol = States[idx].symbol;
      double vwap, sd, upper, lower;
      if(!CalculateAVWAP(symbol, vwap, sd, upper, lower))
         return false;

      double close = iClose(symbol, EntryTF, 1);
      double level, extreme;
      double atr = ATR(idx, 1);
      if(atr <= 0)
         return false;

      if(close < lower && LiquiditySweepReclaim(symbol, 1, level, extreme) && CVDConfirms(symbol, 1))
         return PrepareSignal(idx, MOD_AVWAP_LIQUIDITY, 1, "avwap_discount_liquidity_reclaim", sig);
      if(close > upper && LiquiditySweepReclaim(symbol, -1, level, extreme) && CVDConfirms(symbol, -1))
         return PrepareSignal(idx, MOD_AVWAP_LIQUIDITY, -1, "avwap_premium_liquidity_reclaim", sig);
      return false;
   }

   bool VolatilityExpansion(const int idx, SSignal &sig)
   {
      string symbol = States[idx].symbol;
      double atrNow = ATR(idx, 1);
      double atrRegime = BufferValue(States[idx].hATRRegime, 0, 1);
      if(atrNow <= 0 || atrRegime <= 0)
         return false;
      double ratio = atrNow / atrRegime;
      if(ratio < VolExpansionRatio)
         return false;

      double close = iClose(symbol, EntryTF, 1);
      double hi = HighestHigh(symbol, EntryTF, 2, BreakoutLookback / 2);
      double lo = LowestLow(symbol, EntryTF, 2, BreakoutLookback / 2);
      if(close > hi && BullishBar(symbol, EntryTF, 1))
         return PrepareSignal(idx, MOD_VOLATILITY_EXPANSION, 1, "volatility_expansion_breakout", sig);
      if(close < lo && BearishBar(symbol, EntryTF, 1))
         return PrepareSignal(idx, MOD_VOLATILITY_EXPANSION, -1, "volatility_expansion_breakout", sig);
      return false;
   }

public:
   bool Build(const int idx, const int moduleId, SSignal &sig)
   {
      sig.valid = false;
      if(!ModuleEnabled(moduleId))
         return false;
      switch(moduleId)
      {
         case MOD_TREND_PULLBACK: return TrendPullback(idx, sig);
         case MOD_MOMENTUM_BREAKOUT: return MomentumBreakout(idx, sig);
         case MOD_LATE_CYCLE_FAST_MOVE: return LateCycleFastMove(idx, sig);
         case MOD_DOWNSIDE_RISK_OFF: return DownsideRiskOff(idx, sig);
         case MOD_CORRECTION_REBOUND: return CorrectionRebound(idx, sig);
         case MOD_MTF_TREND_CORE: return MTFTrendCore(idx, sig);
         case MOD_AVWAP_LIQUIDITY: return AVWAPLiquidity(idx, sig);
         case MOD_VOLATILITY_EXPANSION: return VolatilityExpansion(idx, sig);
      }
      return false;
   }
};

CSignalEngine SIGNALS;

//====================================================================
// PORTFOLIO RISK MANAGER
//====================================================================
class CPortfolioRiskManager
{
public:
   void Init()
   {
      g_day = CurrentDayKey();
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      g_equityPeak = MathMax(g_equityPeak, g_dayStartEquity);
      ArrayResize(g_dailySymbolTrades, ArraySize(States));
      ArrayResize(g_dailyModuleTrades, MODULE_COUNT);
      ArrayInitialize(g_dailySymbolTrades, 0);
      ArrayInitialize(g_dailyModuleTrades, 0);
   }

   void ResetIfNewDay()
   {
      datetime d = CurrentDayKey();
      if(d != g_day)
      {
         g_day = d;
         g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
         ArrayInitialize(g_dailySymbolTrades, 0);
         ArrayInitialize(g_dailyModuleTrades, 0);
      }
      g_equityPeak = MathMax(g_equityPeak, AccountInfoDouble(ACCOUNT_EQUITY));
   }

   double DrawdownFromPeakPercent()
   {
      if(g_equityPeak <= 0)
         return 0.0;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      return MathMax(0.0, (g_equityPeak - equity) / g_equityPeak * 100.0);
   }

   double DailyLossPercent()
   {
      if(g_dayStartEquity <= 0)
         return 0.0;
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      return MathMax(0.0, (g_dayStartEquity - equity) / g_dayStartEquity * 100.0);
   }

   double RiskGovernorMultiplier()
   {
      double dd = DrawdownFromPeakPercent();
      if(dd >= RiskCutDD2Percent)
         return RiskCutDD2Multiplier;
      if(dd >= RiskCutDD1Percent)
         return RiskCutDD1Multiplier;
      return 1.0;
   }

   int CountPortfolioPositions()
   {
      int c = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket))
            continue;
         if(IsOurMagic(PositionGetInteger(POSITION_MAGIC)))
            c++;
      }
      return c;
   }

   int CountSymbolPositions(const string symbol)
   {
      int c = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket))
            continue;
         if(PositionGetString(POSITION_SYMBOL) == symbol && IsOurMagic(PositionGetInteger(POSITION_MAGIC)))
            c++;
      }
      return c;
   }

   int CountModulePositions(const int moduleId)
   {
      int c = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket))
            continue;
         if(ModuleFromMagic(PositionGetInteger(POSITION_MAGIC)) == moduleId)
            c++;
      }
      return c;
   }

   int CountBucketPositions(const string bucket)
   {
      int c = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket))
            continue;
         if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC)))
            continue;
         SAssetProfile p = PROFILE.Profile(PositionGetString(POSITION_SYMBOL));
         if(p.bucket == bucket)
            c++;
      }
      return c;
   }

   bool CanOpen(const int symbolIndex, const SSignal &sig, string &reason)
   {
      ResetIfNewDay();
      if(DailyLossPercent() >= MaxDailyLossPercent)
      { reason = "daily_loss_limit"; return false; }
      if(DrawdownFromPeakPercent() >= EquityKillDDPercent)
      { reason = "equity_kill_switch"; return false; }
      if(CountPortfolioPositions() >= MaxPortfolioPositions)
      { reason = "max_portfolio_positions"; return false; }
      if(CountSymbolPositions(sig.symbol) >= MaxPositionsPerSymbol)
      { reason = "max_symbol_positions"; return false; }
      if(CountBucketPositions(sig.bucket) >= MaxPositionsPerBucket)
      { reason = "max_bucket_positions"; return false; }
      if(CountModulePositions(sig.moduleId) >= MaxPositionsPerSystem)
      { reason = "max_system_positions"; return false; }
      if(g_dailySymbolTrades[symbolIndex] >= MaxTradesPerSymbolPerDay)
      { reason = "max_symbol_trades_day"; return false; }
      if(g_dailyModuleTrades[sig.moduleId] >= MaxTradesPerSystemPerDay)
      { reason = "max_system_trades_day"; return false; }
      reason = "ok";
      return true;
   }

   void RegisterTrade(const int symbolIndex, const int moduleId)
   {
      if(symbolIndex >= 0 && symbolIndex < ArraySize(g_dailySymbolTrades))
         g_dailySymbolTrades[symbolIndex]++;
      if(moduleId >= 0 && moduleId < MODULE_COUNT)
         g_dailyModuleTrades[moduleId]++;
   }

   double CalculateLots(const SSignal &sig)
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double riskPct = BaseRiskPercent * sig.riskMultiplier * RiskGovernorMultiplier();
      double riskMoney = equity * riskPct / 100.0;
      double tickValue = SymbolInfoDouble(sig.symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize = SymbolInfoDouble(sig.symbol, SYMBOL_TRADE_TICK_SIZE);
      if(equity <= 0 || riskMoney <= 0 || tickValue <= 0 || tickSize <= 0 || sig.riskDistance <= 0)
         return 0.0;
      double lossPerLot = sig.riskDistance / tickSize * tickValue;
      if(lossPerLot <= 0)
         return 0.0;
      double lots = riskMoney / lossPerLot;
      double minLot = SymbolInfoDouble(sig.symbol, SYMBOL_VOLUME_MIN);
      double maxLot = SymbolInfoDouble(sig.symbol, SYMBOL_VOLUME_MAX);
      double step = SymbolInfoDouble(sig.symbol, SYMBOL_VOLUME_STEP);
      if(step <= 0)
         return 0.0;
      lots = MathMax(minLot, MathMin(maxLot, lots));
      lots = MathFloor(lots / step) * step;
      return NormalizeDouble(lots, 2);
   }
};

CPortfolioRiskManager RISK;

//====================================================================
// EXECUTION / MANAGEMENT
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

   ENUM_ORDER_TYPE_FILLING FillingMode(const string symbol)
   {
      long mode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
      if((mode & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
         return ORDER_FILLING_FOK;
      if((mode & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
         return ORDER_FILLING_IOC;
      return ORDER_FILLING_RETURN;
   }

public:
   bool SendMarket(const int symbolIndex, const SSignal &sig)
   {
      int spread = (int)SymbolInfoInteger(sig.symbol, SYMBOL_SPREAD);
      string sideName = sig.side == 1 ? "long" : "short";
      LOG.Write("SIGNAL", sig.symbol, sig.moduleName, sig.bucket, sideName, sig.entry, sig.sl, sig.tp, sig.rr, sig.atr, spread, 0, sig.reason);

      if(!CanExecuteNow())
      {
         LOG.Write("BLOCKED", sig.symbol, sig.moduleName, sig.bucket, sideName, sig.entry, sig.sl, sig.tp, sig.rr, sig.atr, spread, 0, "trading_disabled");
         return false;
      }

      string riskReason;
      if(!RISK.CanOpen(symbolIndex, sig, riskReason))
      {
         LOG.Write("SKIP", sig.symbol, sig.moduleName, sig.bucket, sideName, sig.entry, sig.sl, sig.tp, sig.rr, sig.atr, spread, 0, riskReason);
         return false;
      }

      double lots = RISK.CalculateLots(sig);
      if(lots <= 0.0)
      {
         LOG.Write("SKIP", sig.symbol, sig.moduleName, sig.bucket, sideName, sig.entry, sig.sl, sig.tp, sig.rr, sig.atr, spread, 0, "invalid_lots");
         return false;
      }

      SAssetProfile profile = PROFILE.Profile(sig.symbol);
      MqlTradeRequest req;
      MqlTradeResult res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_DEAL;
      req.symbol = sig.symbol;
      req.magic = MagicFor(sig.moduleId, sig.symbol);
      req.volume = lots;
      req.type = sig.side == 1 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      req.price = NormalizePrice(sig.symbol, sig.side == 1 ? SymbolInfoDouble(sig.symbol, SYMBOL_ASK) : SymbolInfoDouble(sig.symbol, SYMBOL_BID));
      req.sl = NormalizePrice(sig.symbol, sig.sl);
      req.tp = NormalizePrice(sig.symbol, sig.tp);
      req.deviation = profile.deviationPoints;
      req.type_filling = FillingMode(sig.symbol);
      req.type_time = ORDER_TIME_GTC;
      req.comment = sig.moduleName;

      bool ok = OrderSend(req, res);
      if(!ok || !RetcodeOK(res.retcode))
      {
         LOG.Write("ORDER_ERROR", sig.symbol, sig.moduleName, sig.bucket, sideName, req.price, req.sl, req.tp, sig.rr, sig.atr, spread, res.retcode, res.comment);
         return false;
      }

      RISK.RegisterTrade(symbolIndex, sig.moduleId);
      LOG.Write("MARKET_FILLED", sig.symbol, sig.moduleName, sig.bucket, sideName, req.price, req.sl, req.tp, sig.rr, sig.atr, spread, res.retcode, sig.reason);
      return true;
   }

   void ManageOpenPositions()
   {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || !PositionSelectByTicket(ticket))
            continue;
         long magic = PositionGetInteger(POSITION_MAGIC);
         if(!IsOurMagic(magic))
            continue;

         string symbol = PositionGetString(POSITION_SYMBOL);
         int moduleId = ModuleFromMagic(magic);
         int maxHold = ModuleMaxHoldBars(moduleId);
         datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);
         int barsHeld = iBarShift(symbol, EntryTF, openTime, false);
         if(barsHeld >= maxHold)
         {
            ClosePosition(ticket, symbol, moduleId, "max_hold_bars");
            continue;
         }

         if(MoveToBreakeven)
            TryMoveBreakeven(ticket, symbol, moduleId);
         if(UseATRTrailing)
            TryTrailing(ticket, symbol, moduleId);
      }
   }

   bool ClosePosition(const ulong ticket, const string symbol, const int moduleId, const string reason)
   {
      if(!PositionSelectByTicket(ticket))
         return false;
      int type = (int)PositionGetInteger(POSITION_TYPE);
      double volume = PositionGetDouble(POSITION_VOLUME);
      double price = type == POSITION_TYPE_BUY ? SymbolInfoDouble(symbol, SYMBOL_BID) : SymbolInfoDouble(symbol, SYMBOL_ASK);
      SAssetProfile profile = PROFILE.Profile(symbol);

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
      req.deviation = profile.deviationPoints;
      req.type_filling = FillingMode(symbol);
      req.magic = MagicFor(moduleId, symbol);
      req.comment = reason;

      bool ok = OrderSend(req, res);
      LOG.Write(ok && RetcodeOK(res.retcode) ? "CLOSE_SENT" : "CLOSE_ERROR", symbol, ModuleName(moduleId), profile.bucket, "", req.price, 0, 0, 0, 0, (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD), res.retcode, res.comment);
      return ok && RetcodeOK(res.retcode);
   }

   double LocalATR(const string symbol)
   {
      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      if(CopyRates(symbol, EntryTF, 0, ATRPeriod + 5, rates) < ATRPeriod + 2)
         return 0.0;
      double sum = 0.0;
      for(int i = 1; i <= ATRPeriod; i++)
      {
         double tr = MathMax(rates[i].high - rates[i].low,
                             MathMax(MathAbs(rates[i].high - rates[i+1].close), MathAbs(rates[i].low - rates[i+1].close)));
         sum += tr;
      }
      return sum / (double)ATRPeriod;
   }

   void ModifySLTP(const ulong ticket, const string symbol, const int moduleId, const double newSL, const double tp, const string label)
   {
      MqlTradeRequest req;
      MqlTradeResult res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_SLTP;
      req.position = ticket;
      req.symbol = symbol;
      req.sl = NormalizePrice(symbol, newSL);
      req.tp = tp;
      req.magic = MagicFor(moduleId, symbol);
      bool ok = OrderSend(req, res);
      if(!ok || !RetcodeOK(res.retcode))
      {
         SAssetProfile p = PROFILE.Profile(symbol);
         LOG.Write("SLTP_ERROR", symbol, ModuleName(moduleId), p.bucket, "", 0, req.sl, req.tp, 0, 0, (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD), res.retcode, res.comment + " " + label);
      }
   }

   void TryMoveBreakeven(const ulong ticket, const string symbol, const int moduleId)
   {
      if(!PositionSelectByTicket(ticket))
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
      double point = PointFor(symbol);
      double newSL = sl;

      if(type == POSITION_TYPE_BUY)
      {
         double rNow = (bid - open) / risk;
         if(rNow >= BreakevenAtR && sl < open)
            newSL = open + BreakevenPlusPoints * point;
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double rNow = (open - ask) / risk;
         if(rNow >= BreakevenAtR && sl > open)
            newSL = open - BreakevenPlusPoints * point;
      }

      if(newSL != sl)
         ModifySLTP(ticket, symbol, moduleId, newSL, tp, "breakeven");
   }

   void TryTrailing(const ulong ticket, const string symbol, const int moduleId)
   {
      if(!PositionSelectByTicket(ticket))
         return;
      double atr = LocalATR(symbol);
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
      double trailMult = moduleId == MOD_LATE_CYCLE_FAST_MOVE ? 0.85 : TrailATRMult;
      double trailStart = moduleId == MOD_LATE_CYCLE_FAST_MOVE ? 0.95 : TrailStartR;
      double newSL = sl;

      if(type == POSITION_TYPE_BUY)
      {
         double rNow = (bid - open) / risk;
         double proposed = bid - atr * trailMult;
         if(rNow >= trailStart && proposed > sl && proposed < bid)
            newSL = proposed;
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double rNow = (open - ask) / risk;
         double proposed = ask + atr * trailMult;
         if(rNow >= trailStart && proposed < sl && proposed > ask)
            newSL = proposed;
      }

      if(newSL != sl)
         ModifySLTP(ticket, symbol, moduleId, newSL, tp, "atr_trailing");
   }
};

CExecutionEngine EXECUTION;

//====================================================================
// LIFECYCLE
//====================================================================
int OnInit()
{
   string symbols[];
   int n = ParseSymbols(InpSymbols, symbols);
   if(n <= 0)
   {
      Print("No symbols configured.");
      return INIT_FAILED;
   }

   ArrayResize(States, n);
   for(int i = 0; i < n; i++)
   {
      States[i].symbol = symbols[i];
      States[i].lastBarTime = 0;
      SymbolSelect(States[i].symbol, true);
      States[i].hATR = iATR(States[i].symbol, EntryTF, ATRPeriod);
      States[i].hATRRegime = iATR(States[i].symbol, RegimeTF, ATRPeriod);
      States[i].hADX = iADX(States[i].symbol, RegimeTF, ADXPeriod);
      States[i].hFastEMA = iMA(States[i].symbol, RegimeTF, FastEMA, 0, MODE_EMA, PRICE_CLOSE);
      States[i].hSlowEMA = iMA(States[i].symbol, RegimeTF, SlowEMA, 0, MODE_EMA, PRICE_CLOSE);
      States[i].hPullbackEMA = iMA(States[i].symbol, EntryTF, PullbackEMA, 0, MODE_EMA, PRICE_CLOSE);
      States[i].hCoreFastEMA = iMA(States[i].symbol, CoreTF, FastEMA, 0, MODE_EMA, PRICE_CLOSE);
      States[i].hCoreSlowEMA = iMA(States[i].symbol, CoreTF, SlowEMA, 0, MODE_EMA, PRICE_CLOSE);

      if(States[i].hATR == INVALID_HANDLE || States[i].hADX == INVALID_HANDLE || States[i].hFastEMA == INVALID_HANDLE ||
         States[i].hSlowEMA == INVALID_HANDLE || States[i].hPullbackEMA == INVALID_HANDLE ||
         States[i].hCoreFastEMA == INVALID_HANDLE || States[i].hCoreSlowEMA == INVALID_HANDLE)
      {
         Print("Failed indicator handle for ", States[i].symbol);
         return INIT_FAILED;
      }
   }

   LOG.Init(CsvLogFile);
   RISK.Init();
   LOG.Write("INIT", "PORTFOLIO", "CoreEA_PortfolioX", "", "", 0, 0, 0, 0, 0, 0, 0,
             StringFormat("version=1.000 symbols=%d entryTF=%s regimeTF=%s coreTF=%s", n, EnumToString(EntryTF), EnumToString(RegimeTF), EnumToString(CoreTF)));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   for(int i = 0; i < ArraySize(States); i++)
   {
      if(States[i].hATR != INVALID_HANDLE) IndicatorRelease(States[i].hATR);
      if(States[i].hATRRegime != INVALID_HANDLE) IndicatorRelease(States[i].hATRRegime);
      if(States[i].hADX != INVALID_HANDLE) IndicatorRelease(States[i].hADX);
      if(States[i].hFastEMA != INVALID_HANDLE) IndicatorRelease(States[i].hFastEMA);
      if(States[i].hSlowEMA != INVALID_HANDLE) IndicatorRelease(States[i].hSlowEMA);
      if(States[i].hPullbackEMA != INVALID_HANDLE) IndicatorRelease(States[i].hPullbackEMA);
      if(States[i].hCoreFastEMA != INVALID_HANDLE) IndicatorRelease(States[i].hCoreFastEMA);
      if(States[i].hCoreSlowEMA != INVALID_HANDLE) IndicatorRelease(States[i].hCoreSlowEMA);
   }
   LOG.Write("DEINIT", "PORTFOLIO", "CoreEA_PortfolioX", "", "", 0, 0, 0, 0, 0, 0, 0, IntegerToString(reason));
}

void OnTick()
{
   RISK.ResetIfNewDay();
   EXECUTION.ManageOpenPositions();

   for(int i = 0; i < ArraySize(States); i++)
   {
      string symbol = States[i].symbol;
      datetime t = iTime(symbol, EntryTF, 0);
      if(t <= 0 || t == States[i].lastBarTime)
         continue;
      States[i].lastBarTime = t;
      ProcessSymbol(i);
   }
}

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;
   ulong deal = trans.deal;
   if(deal == 0 || !HistoryDealSelect(deal))
      return;
   long magic = HistoryDealGetInteger(deal, DEAL_MAGIC);
   if(!IsOurMagic(magic))
      return;
   long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT)
      return;
   string symbol = HistoryDealGetString(deal, DEAL_SYMBOL);
   int moduleId = ModuleFromMagic(magic);
   SAssetProfile p = PROFILE.Profile(symbol);
   double profit = HistoryDealGetDouble(deal, DEAL_PROFIT) + HistoryDealGetDouble(deal, DEAL_SWAP) + HistoryDealGetDouble(deal, DEAL_COMMISSION);
   LOG.Write("DEAL_CLOSED", symbol, ModuleName(moduleId), p.bucket, "", HistoryDealGetDouble(deal, DEAL_PRICE), 0, 0, 0, 0, (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD), 0, DoubleToString(profit, 2));
}

//====================================================================
// MAIN PIPELINE
//====================================================================
void ProcessSymbol(const int idx)
{
   string symbol = States[idx].symbol;
   if(!TradeTimeAllowed(symbol))
      return;

   SAssetProfile profile = PROFILE.Profile(symbol);
   string blockReason;
   if(DefensiveRegimeBlocks(idx, profile, blockReason))
   {
      LOG.Write("SKIP", symbol, ModuleName(MOD_DEFENSIVE_REGIME), profile.bucket, "", 0, 0, 0, 0, ATR(idx, 1), (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD), 0, blockReason);
      return;
   }

   int spread = (int)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   if(spread <= 0 || spread > profile.maxSpreadPoints)
   {
      LOG.Write("SKIP", symbol, "SpreadFilter", profile.bucket, "", 0, 0, 0, 0, ATR(idx, 1), spread, 0, "spread_rejected");
      return;
   }

   for(int moduleId = 0; moduleId < MODULE_COUNT - 1; moduleId++)
   {
      SSignal sig;
      sig.valid = false;
      if(!SIGNALS.Build(idx, moduleId, sig))
         continue;

      EXECUTION.SendMarket(idx, sig);
      if(OneSignalPerSymbolPerBar)
         break;
   }
}
//+------------------------------------------------------------------+
