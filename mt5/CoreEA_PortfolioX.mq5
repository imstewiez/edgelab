//+------------------------------------------------------------------+
//| CoreEA PortfolioX                                                 |
//| Qualification-mode multi-system systematic portfolio EA for MT5    |
//| v1.200                                                            |
//|                                                                  |
//| Important: this is a research/qualification build. It prioritizes |
//| survival, module isolation, cooldowns and stricter trend filters.  |
//| It does not claim a proven live edge.                              |
//+------------------------------------------------------------------+
#property strict
#property version   "1.200"
#property description "CoreEA PortfolioX - qualification-mode multi-system portfolio EA"

#define MODULE_COUNT 9

enum EModuleId
{
   MOD_TREND_PULLBACK=0,
   MOD_MOMENTUM_BREAKOUT=1,
   MOD_LATE_CYCLE_FAST_MOVE=2,
   MOD_DOWNSIDE_RISK_OFF=3,
   MOD_CORRECTION_REBOUND=4,
   MOD_MTF_TREND_CORE=5,
   MOD_AVWAP_LIQUIDITY=6,
   MOD_VOLATILITY_EXPANSION=7,
   MOD_DEFENSIVE_REGIME=8
};

input group "01. General"
input bool             AllowLiveTrading          = false;
input bool             ExecuteInTester           = true;
input string           InpSymbols                = "XAUUSD,EURUSD,GBPUSD,AUDUSD,NZDUSD,USDCAD,USDCHF,USDJPY,EURJPY,GBPJPY";
input string           ExcludedSymbols           = "";       // optional, e.g. XAUUSD,USDJPY
input ENUM_TIMEFRAMES  EntryTF                   = PERIOD_M15;
input ENUM_TIMEFRAMES  RegimeTF                  = PERIOD_H1;
input ENUM_TIMEFRAMES  CoreTF                    = PERIOD_H4;
input int              MagicBase                 = 996000;
input bool             DebugLogs                 = true;
input string           CsvLogFile                = "CoreEA_PortfolioX.csv";

input group "02. Portfolio Risk - Qualification Defaults"
input double           BaseRiskPercent           = 0.05;
input int              MaxPortfolioPositions     = 2;
input int              MaxPositionsPerSymbol     = 1;
input int              MaxPositionsPerBucket     = 1;
input int              MaxPositionsPerSystem     = 1;
input int              MaxTradesPerSymbolPerDay  = 1;
input int              MaxTradesPerSystemPerDay  = 1;
input double           MaxDailyLossPercent       = 0.60;
input double           EquityStopDDPercent       = 2.50;
input double           RiskCutDD1Percent         = 1.00;
input double           RiskCutDD1Multiplier      = 0.50;
input double           RiskCutDD2Percent         = 1.75;
input double           RiskCutDD2Multiplier      = 0.25;

input group "03. Cooldowns / Anti-Crowding"
input int              MinBarsBetweenSymbolTrades= 24;
input int              MinBarsBetweenModuleTrades= 12;
input int              LossStreakBeforeCooldown  = 2;
input int              SymbolCooldownHours       = 48;
input int              ModuleCooldownHours       = 24;
input bool             BlockNewTradesAfterLossDay= true;

input group "04. Session / Execution Safety"
input int              SessionTimeShiftHours     = 0;
input int              TradeStartHour            = 7;
input int              TradeEndHour              = 17;
input bool             AvoidFridayLate           = true;
input int              FridayCutoffHour          = 14;
input int              ManualMaxSpreadPoints     = 0;
input int              ManualDeviationPoints     = 0;
input bool             OneSignalPerSymbolPerBar  = true;
input int              MinSLModifyStepPoints     = 15;

input group "05. Indicators / Regime"
input int              ATRPeriod                 = 14;
input int              FastEMA                   = 50;
input int              SlowEMA                   = 200;
input int              PullbackEMA               = 21;
input int              ADXPeriod                 = 14;
input double           TrendADXMin               = 25.0;
input double           StrongTrendADX            = 32.0;
input double           RangeADXMax               = 15.0;
input bool             RequireCoreTrendAgreement = true;
input bool             RequireADXIncreasing      = true;

input group "06. Module Enables - Qualification"
input bool             EnableTrendPullback       = true;
input bool             EnableMomentumBreakout    = true;
input bool             EnableLateCycleFastMove   = false;
input bool             EnableDownsideRiskOff     = false;
input bool             EnableCorrectionRebound   = false;
input bool             EnableMTFTrendCore        = false;
input bool             EnableAVWAPLiquidity      = false;
input bool             EnableVolatilityExpansion = false;
input bool             EnableDefensiveRegime     = true;

input group "07. Module Risk Multipliers"
input double           RiskTrendPullback         = 0.65;
input double           RiskMomentumBreakout      = 0.55;
input double           RiskLateCycleFastMove     = 0.35;
input double           RiskDownsideRiskOff       = 0.40;
input double           RiskCorrectionRebound     = 0.15;
input double           RiskMTFTrendCore          = 0.45;
input double           RiskAVWAPLiquidity        = 0.35;
input double           RiskVolatilityExpansion   = 0.45;

input group "08. Module Parameters"
input int              BreakoutLookback          = 64;
input int              SwingLookback             = 12;
input int              AVWAPMaxBars              = 500;
input int              AVWAPLondonAnchorHour     = 7;
input int              AVWAPNewYorkAnchorHour    = 13;
input double           AVWAPBandSD               = 1.60;
input int              RollingLiquidityLookback  = 80;
input double           MinBodyATR                = 0.65;
input double           MomentumBodyATR           = 0.95;
input double           VolExpansionRatio         = 1.50;
input double           RangeDeviationATR         = 1.50;

input group "09. Exits / Trade Management"
input double           DefaultRR                 = 1.85;
input double           MinimumRR                 = 1.50;
input double           StopATRMult               = 1.70;
input bool             MoveToBreakeven           = true;
input double           BreakevenAtR              = 1.10;
input double           BreakevenPlusPoints       = 2.0;
input bool             UseATRTrailing            = true;
input double           TrailStartR               = 1.80;
input double           TrailATRMult              = 1.50;

struct SAssetProfile{string bucket; double riskMultiplier; int maxSpreadPoints; int deviationPoints; double minStopATR; double maxStopATR;};
struct SSymbolState{string symbol; datetime lastBarTime; int hATR; int hATRRegime; int hADX; int hFastEMA; int hSlowEMA; int hPullbackEMA; int hCoreFastEMA; int hCoreSlowEMA;};
struct SSignal{bool valid; string symbol; int moduleId; string moduleName; string bucket; int side; double entry; double sl; double tp; double riskDistance; double rr; double atr; double riskMultiplier; string reason;};

SSymbolState States[];
datetime g_day=0;
double g_dayStartEquity=0.0;
double g_equityPeak=0.0;
int g_dailySymbolTrades[];
int g_dailyModuleTrades[];
int g_dailyLossFlag[];
datetime g_lastSymbolTradeTime[];
datetime g_lastModuleTradeTime[];
datetime g_symbolBlockUntil[];
datetime g_moduleBlockUntil[];
int g_symbolLossStreak[];
int g_moduleLossStreak[];

string TrimString(string v){StringTrimLeft(v); StringTrimRight(v); return v;}
string UpperString(string v){StringToUpper(v); return v;}
datetime AdjustedTime(datetime t){return t+SessionTimeShiftHours*3600;}
datetime DayStart(datetime t){MqlDateTime d; TimeToStruct(t,d); d.hour=0; d.min=0; d.sec=0; return StructToTime(d);}
datetime CurrentDayKey(){return DayStart(AdjustedTime(TimeCurrent()));}
double PointFor(string s){double p=SymbolInfoDouble(s,SYMBOL_POINT); return p>0?p:0.00001;}
double NormalizePrice(string s,double p){return NormalizeDouble(p,(int)SymbolInfoInteger(s,SYMBOL_DIGITS));}

int ParseSymbols(string src,string &out[])
{
   string parts[]; int n=StringSplit(src,',',parts); ArrayResize(out,n); int k=0;
   for(int i=0;i<n;i++)
   {
      string s=TrimString(parts[i]);
      if(s=="") continue;
      if(ExcludedSymbols!="")
      {
         string ex=","+UpperString(ExcludedSymbols)+",";
         string ss=","+UpperString(s)+",";
         if(StringFind(ex,ss)>=0) continue;
      }
      out[k]=s; k++;
   }
   ArrayResize(out,k); return k;
}

int SymbolIndexByName(string s){for(int i=0;i<ArraySize(States);i++) if(States[i].symbol==s) return i; return -1;}
int HashSymbol(string s){int h=0; for(int i=0;i<StringLen(s);i++) h+=StringGetCharacter(s,i)*(i+1); return h%9000;}
long MagicFor(int moduleId,string symbol){return (long)(MagicBase+moduleId*10000+HashSymbol(symbol));}
bool IsOurMagic(long magic){return magic>=MagicBase && magic<MagicBase+MODULE_COUNT*10000+9999;}
int ModuleFromMagic(long magic){if(!IsOurMagic(magic)) return -1; int m=(int)((magic-MagicBase)/10000); return (m>=0 && m<MODULE_COUNT)?m:-1;}

double HighestHigh(string s,ENUM_TIMEFRAMES tf,int start,int count){double v=-DBL_MAX; for(int i=start;i<start+count;i++) v=MathMax(v,iHigh(s,tf,i)); return v;}
double LowestLow(string s,ENUM_TIMEFRAMES tf,int start,int count){double v=DBL_MAX; for(int i=start;i<start+count;i++) v=MathMin(v,iLow(s,tf,i)); return v;}
double BodySize(string s,ENUM_TIMEFRAMES tf,int shift){return MathAbs(iClose(s,tf,shift)-iOpen(s,tf,shift));}
bool BullishBar(string s,ENUM_TIMEFRAMES tf,int shift){return iClose(s,tf,shift)>iOpen(s,tf,shift);}
bool BearishBar(string s,ENUM_TIMEFRAMES tf,int shift){return iClose(s,tf,shift)<iOpen(s,tf,shift);}

bool TradeTimeAllowed(string s)
{
   datetime t=iTime(s,EntryTF,1); if(t<=0) return false;
   MqlDateTime d; TimeToStruct(AdjustedTime(t),d);
   if(d.hour<TradeStartHour || d.hour>=TradeEndHour) return false;
   if(AvoidFridayLate && d.day_of_week==5 && d.hour>=FridayCutoffHour) return false;
   return true;
}

class CLogger
{
private:string m_file;
public:
   void Init(string fileName)
   {
      m_file=fileName; int h=FileOpen(m_file,FILE_READ|FILE_CSV|FILE_ANSI);
      if(h!=INVALID_HANDLE){FileClose(h); return;}
      h=FileOpen(m_file,FILE_WRITE|FILE_CSV|FILE_ANSI); if(h==INVALID_HANDLE) return;
      FileWrite(h,"time","event","symbol","module","bucket","side","price","sl","tp","rr","atr","spread","retcode","note"); FileClose(h);
   }
   void Write(string ev,string s,string mod,string bucket,string side,double price,double sl,double tp,double rr,double atr,int spread,uint ret,string note)
   {
      int h=FileOpen(m_file,FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI);
      if(h!=INVALID_HANDLE){int digits=(int)SymbolInfoInteger(s,SYMBOL_DIGITS); FileSeek(h,0,SEEK_END); FileWrite(h,TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),ev,s,mod,bucket,side,DoubleToString(price,digits),DoubleToString(sl,digits),DoubleToString(tp,digits),DoubleToString(rr,2),DoubleToString(atr,digits),spread,ret,note); FileClose(h);}
      if(DebugLogs || ev=="ORDER_ERROR" || ev=="SKIP" || ev=="CLOSE_ERROR" || ev=="SLTP_ERROR" || ev=="COOLDOWN") Print(ev," ",s," ",mod," ",side," ",note);
   }
};
CLogger LOG;

class CProfileEngine
{
public:
   SAssetProfile Profile(string symbol)
   {
      SAssetProfile p; string s=UpperString(symbol);
      p.bucket="FX_USD"; p.riskMultiplier=1.0; p.maxSpreadPoints=ManualMaxSpreadPoints>0?ManualMaxSpreadPoints:36; p.deviationPoints=ManualDeviationPoints>0?ManualDeviationPoints:25; p.minStopATR=0.85; p.maxStopATR=5.50;
      if(StringFind(s,"XAU")>=0 || StringFind(s,"GOLD")>=0){p.bucket="METALS"; p.riskMultiplier=0.55; p.maxSpreadPoints=ManualMaxSpreadPoints>0?ManualMaxSpreadPoints:120; p.deviationPoints=ManualDeviationPoints>0?ManualDeviationPoints:60; p.minStopATR=1.00; p.maxStopATR=7.00;}
      else if(StringFind(s,"BTC")>=0 || StringFind(s,"ETH")>=0){p.bucket="CRYPTO"; p.riskMultiplier=0.35; p.maxSpreadPoints=ManualMaxSpreadPoints>0?ManualMaxSpreadPoints:650; p.deviationPoints=ManualDeviationPoints>0?ManualDeviationPoints:120; p.minStopATR=1.10; p.maxStopATR=8.00;}
      else if(StringFind(s,"NAS")>=0 || StringFind(s,"US30")>=0 || StringFind(s,"SPX")>=0 || StringFind(s,"DAX")>=0 || StringFind(s,"GER")>=0){p.bucket="INDICES"; p.riskMultiplier=0.50; p.maxSpreadPoints=ManualMaxSpreadPoints>0?ManualMaxSpreadPoints:250; p.deviationPoints=ManualDeviationPoints>0?ManualDeviationPoints:90; p.minStopATR=1.00; p.maxStopATR=7.00;}
      else if(StringFind(s,"JPY")>=0){p.bucket="FX_JPY"; p.riskMultiplier=0.75; p.maxSpreadPoints=ManualMaxSpreadPoints>0?ManualMaxSpreadPoints:42; p.deviationPoints=ManualDeviationPoints>0?ManualDeviationPoints:30; p.minStopATR=0.90; p.maxStopATR=6.00;}
      else if(StringFind(s,"GBP")>=0){p.bucket="FX_GBP"; p.riskMultiplier=0.80; p.maxSpreadPoints=ManualMaxSpreadPoints>0?ManualMaxSpreadPoints:42; p.deviationPoints=ManualDeviationPoints>0?ManualDeviationPoints:30;}
      else if(StringFind(s,"AUD")>=0 || StringFind(s,"NZD")>=0){p.bucket="FX_AUD_NZD"; p.maxSpreadPoints=ManualMaxSpreadPoints>0?ManualMaxSpreadPoints:36; p.deviationPoints=ManualDeviationPoints>0?ManualDeviationPoints:30;}
      return p;
   }
};
CProfileEngine PROFILE;

string ModuleName(int id){switch(id){case MOD_TREND_PULLBACK:return "TrendPullback"; case MOD_MOMENTUM_BREAKOUT:return "MomentumBreakout"; case MOD_LATE_CYCLE_FAST_MOVE:return "LateCycleFastMove"; case MOD_DOWNSIDE_RISK_OFF:return "DownsideRiskOff"; case MOD_CORRECTION_REBOUND:return "CorrectionRebound"; case MOD_MTF_TREND_CORE:return "MTFTrendCore"; case MOD_AVWAP_LIQUIDITY:return "AVWAPLiquidity"; case MOD_VOLATILITY_EXPANSION:return "VolatilityExpansion"; case MOD_DEFENSIVE_REGIME:return "DefensiveRegime";} return "Unknown";}
bool ModuleEnabled(int id){switch(id){case MOD_TREND_PULLBACK:return EnableTrendPullback; case MOD_MOMENTUM_BREAKOUT:return EnableMomentumBreakout; case MOD_LATE_CYCLE_FAST_MOVE:return EnableLateCycleFastMove; case MOD_DOWNSIDE_RISK_OFF:return EnableDownsideRiskOff; case MOD_CORRECTION_REBOUND:return EnableCorrectionRebound; case MOD_MTF_TREND_CORE:return EnableMTFTrendCore; case MOD_AVWAP_LIQUIDITY:return EnableAVWAPLiquidity; case MOD_VOLATILITY_EXPANSION:return EnableVolatilityExpansion;} return false;}
double ModuleRiskMultiplier(int id){switch(id){case MOD_TREND_PULLBACK:return RiskTrendPullback; case MOD_MOMENTUM_BREAKOUT:return RiskMomentumBreakout; case MOD_LATE_CYCLE_FAST_MOVE:return RiskLateCycleFastMove; case MOD_DOWNSIDE_RISK_OFF:return RiskDownsideRiskOff; case MOD_CORRECTION_REBOUND:return RiskCorrectionRebound; case MOD_MTF_TREND_CORE:return RiskMTFTrendCore; case MOD_AVWAP_LIQUIDITY:return RiskAVWAPLiquidity; case MOD_VOLATILITY_EXPANSION:return RiskVolatilityExpansion;} return 0.0;}
double ModuleRR(int id){switch(id){case MOD_LATE_CYCLE_FAST_MOVE:return 1.45; case MOD_CORRECTION_REBOUND:return 2.00; case MOD_MTF_TREND_CORE:return 2.10; case MOD_AVWAP_LIQUIDITY:return 1.80; case MOD_VOLATILITY_EXPANSION:return 1.95; default:return DefaultRR;}}
int ModuleMaxHoldBars(int id){switch(id){case MOD_LATE_CYCLE_FAST_MOVE:return 14; case MOD_CORRECTION_REBOUND:return 120; case MOD_MTF_TREND_CORE:return 80; case MOD_AVWAP_LIQUIDITY:return 28; case MOD_VOLATILITY_EXPANSION:return 20; default:return 36;}}

double BufferValue(int handle,int buffer,int shift){double v[]; ArraySetAsSeries(v,true); if(handle==INVALID_HANDLE) return 0; if(CopyBuffer(handle,buffer,shift,1,v)!=1) return 0; return v[0];}
double ATRv(int idx,int shift=1){return BufferValue(States[idx].hATR,0,shift);} double ADXv(int idx,int shift=1){return BufferValue(States[idx].hADX,0,shift);} double EMAFastv(int idx,int shift=1){return BufferValue(States[idx].hFastEMA,0,shift);} double EMASlowv(int idx,int shift=1){return BufferValue(States[idx].hSlowEMA,0,shift);} double EMAPullbackv(int idx,int shift=1){return BufferValue(States[idx].hPullbackEMA,0,shift);} double CoreFastv(int idx,int shift=1){return BufferValue(States[idx].hCoreFastEMA,0,shift);} double CoreSlowv(int idx,int shift=1){return BufferValue(States[idx].hCoreSlowEMA,0,shift);}

int TrendDirection(int idx){double f=EMAFastv(idx,1),s=EMASlowv(idx,1),fp=EMAFastv(idx,4); if(f<=0||s<=0||fp<=0) return 0; if(f>s&&f>=fp) return 1; if(f<s&&f<=fp) return -1; return 0;}
int CoreTrendDirection(int idx){double f=CoreFastv(idx,1),s=CoreSlowv(idx,1); if(f<=0||s<=0) return 0; if(f>s) return 1; if(f<s) return -1; return 0;}
bool CoreAgrees(int idx,int side){if(!RequireCoreTrendAgreement) return true; return CoreTrendDirection(idx)==side && TrendDirection(idx)==side;}
bool ADXRising(int idx){if(!RequireADXIncreasing) return true; return ADXv(idx,1)>ADXv(idx,4);}

bool CalculateAVWAP(string symbol,double &vwap,double &upper,double &lower)
{
   vwap=0; upper=0; lower=0; MqlRates r[]; ArraySetAsSeries(r,true); int copied=CopyRates(symbol,EntryTF,0,AVWAPMaxBars,r); if(copied<30) return false;
   datetime ref=r[1].time,adj=AdjustedTime(ref),today=DayStart(adj); datetime london=today+AVWAPLondonAnchorHour*3600,ny=today+AVWAPNewYorkAnchorHour*3600; datetime anchorAdj=adj>=ny?ny:(adj>=london?london:DayStart(adj-86400)+AVWAPNewYorkAnchorHour*3600); datetime anchor=anchorAdj-SessionTimeShiftHours*3600;
   double sumPV=0,sumV=0; int used=0; for(int i=1;i<copied;i++){if(r[i].time<anchor) break; double typ=(r[i].high+r[i].low+r[i].close)/3.0,vol=(double)MathMax((long)1,r[i].tick_volume); sumPV+=typ*vol; sumV+=vol; used++;}
   if(used<4){sumPV=0; sumV=0; used=0; int fb=MathMin(48,copied-1); for(int k=1;k<=fb;k++){double typ=(r[k].high+r[k].low+r[k].close)/3.0,vol=(double)MathMax((long)1,r[k].tick_volume); sumPV+=typ*vol; sumV+=vol; used++;}}
   if(sumV<=0||used<4) return false; vwap=sumPV/sumV; double var=0; for(int j=1;j<=used;j++){double typ=(r[j].high+r[j].low+r[j].close)/3.0,vol=(double)MathMax((long)1,r[j].tick_volume); var+=vol*MathPow(typ-vwap,2.0);} var/=sumV; double sd=MathSqrt(MathMax(var,0.0)); if(sd<=0) sd=PointFor(symbol)*10.0; upper=vwap+sd*AVWAPBandSD; lower=vwap-sd*AVWAPBandSD; return true;
}

double SyntheticDelta(string symbol,int shift){double h=iHigh(symbol,EntryTF,shift),l=iLow(symbol,EntryTF,shift),c=iClose(symbol,EntryTF,shift); long vol=iVolume(symbol,EntryTF,shift); double range=h-l; if(range<=0) return 0; return (double)MathMax((long)1,vol)*(((c-l)/range-0.5)*2.0);}
bool CVDConfirms(string symbol,int side){double d1=SyntheticDelta(symbol,1),d2=SyntheticDelta(symbol,2),d3=SyntheticDelta(symbol,3),d4=SyntheticDelta(symbol,4); double now=d1+d2+d3,past=d2+d3+d4; if(side==1) return (iLow(symbol,EntryTF,1)<iLow(symbol,EntryTF,3)&&now>past)||d1>MathAbs(d2+d3)*0.55; if(side==-1) return (iHigh(symbol,EntryTF,1)>iHigh(symbol,EntryTF,3)&&now<past)||d1<-MathAbs(d2+d3)*0.55; return false;}
bool LiquiditySweepReclaim(string symbol,int side){double ph=iHigh(symbol,PERIOD_D1,1),pl=iLow(symbol,PERIOD_D1,1),rh=HighestHigh(symbol,EntryTF,2,RollingLiquidityLookback),rl=LowestLow(symbol,EntryTF,2,RollingLiquidityLookback); double c=iClose(symbol,EntryTF,1),h=iHigh(symbol,EntryTF,1),l=iLow(symbol,EntryTF,1); if(side==1) return (pl>0&&l<pl&&c>pl)||(rl>0&&l<rl&&c>rl); if(side==-1) return (ph>0&&h>ph&&c<ph)||(rh>0&&h>rh&&c<rh); return false;}

bool DefensiveBlocks(int idx,SAssetProfile &profile,string &reason)
{
   if(!EnableDefensiveRegime) return false; string s=States[idx].symbol; int spread=(int)SymbolInfoInteger(s,SYMBOL_SPREAD); if(spread>profile.maxSpreadPoints){reason="spread_above_profile"; return true;} double eq=AccountInfoDouble(ACCOUNT_EQUITY); if(g_equityPeak>0&&(g_equityPeak-eq)/g_equityPeak*100.0>=EquityStopDDPercent){reason="equity_stop_dd"; return true;} double atr=ATRv(idx,1),price=iClose(s,EntryTF,1); if(price>0&&atr/price>0.018&&profile.bucket!="CRYPTO"){reason="abnormal_atr_percent"; return true;} reason="ok"; return false;
}

class CSignalEngine
{
private:
   bool Prepare(int idx,int moduleId,int side,string reason,SSignal &sig)
   {
      string s=States[idx].symbol; SAssetProfile p=PROFILE.Profile(s); double atr=ATRv(idx,1); if(atr<=0||side==0) return false; double ask=SymbolInfoDouble(s,SYMBOL_ASK),bid=SymbolInfoDouble(s,SYMBOL_BID); if(ask<=0||bid<=0) return false; double entry=side==1?ask:bid;
      double swingLow=LowestLow(s,EntryTF,1,SwingLookback), swingHigh=HighestHigh(s,EntryTF,1,SwingLookback); double sl=side==1?MathMin(swingLow,entry-atr*StopATRMult):MathMax(swingHigh,entry+atr*StopATRMult); double risk=MathAbs(entry-sl); if(risk<atr*p.minStopATR){sl=side==1?entry-atr*p.minStopATR:entry+atr*p.minStopATR; risk=MathAbs(entry-sl);} if(risk>atr*p.maxStopATR) return false;
      double rr=MathMax(MinimumRR,ModuleRR(moduleId)); double tp=side==1?entry+risk*rr:entry-risk*rr; sig.valid=true; sig.symbol=s; sig.moduleId=moduleId; sig.moduleName=ModuleName(moduleId); sig.bucket=p.bucket; sig.side=side; sig.entry=entry; sig.sl=sl; sig.tp=tp; sig.riskDistance=risk; sig.rr=rr; sig.atr=atr; sig.riskMultiplier=ModuleRiskMultiplier(moduleId)*p.riskMultiplier; sig.reason=reason; return true;
   }
   bool TrendPullback(int idx,SSignal &sig){int dir=TrendDirection(idx); if(dir==0||ADXv(idx,1)<TrendADXMin||!CoreAgrees(idx,dir)||!ADXRising(idx)) return false; string s=States[idx].symbol; double ema=EMAPullbackv(idx,1),atr=ATRv(idx,1); if(ema<=0||atr<=0) return false; if(dir==1){bool touched=iLow(s,EntryTF,1)<=ema||iClose(s,EntryTF,2)<=ema; bool reclaim=iClose(s,EntryTF,1)>ema&&BullishBar(s,EntryTF,1); bool impulse=BodySize(s,EntryTF,1)>=atr*MinBodyATR; if(touched&&reclaim&&impulse) return Prepare(idx,MOD_TREND_PULLBACK,1,"qualified_trend_pullback",sig);} if(dir==-1){bool touched=iHigh(s,EntryTF,1)>=ema||iClose(s,EntryTF,2)>=ema; bool reclaim=iClose(s,EntryTF,1)<ema&&BearishBar(s,EntryTF,1); bool impulse=BodySize(s,EntryTF,1)>=atr*MinBodyATR; if(touched&&reclaim&&impulse) return Prepare(idx,MOD_TREND_PULLBACK,-1,"qualified_trend_pullback",sig);} return false;}
   bool MomentumBreakout(int idx,SSignal &sig){if(ADXv(idx,1)<TrendADXMin||!ADXRising(idx)) return false; string s=States[idx].symbol; double atr=ATRv(idx,1); if(atr<=0) return false; double c=iClose(s,EntryTF,1),pc=iClose(s,EntryTF,2),hi=HighestHigh(s,EntryTF,2,BreakoutLookback),lo=LowestLow(s,EntryTF,2,BreakoutLookback),body=BodySize(s,EntryTF,1); if(c>hi&&pc<=hi&&BullishBar(s,EntryTF,1)&&body>=atr*MomentumBodyATR&&CoreAgrees(idx,1)) return Prepare(idx,MOD_MOMENTUM_BREAKOUT,1,"qualified_momentum_breakout",sig); if(c<lo&&pc>=lo&&BearishBar(s,EntryTF,1)&&body>=atr*MomentumBodyATR&&CoreAgrees(idx,-1)) return Prepare(idx,MOD_MOMENTUM_BREAKOUT,-1,"qualified_momentum_breakout",sig); return false;}
   bool LateCycle(int idx,SSignal &sig){int dir=TrendDirection(idx); double adx=ADXv(idx,1),atr=ATRv(idx,1),fast=EMAFastv(idx,1); string s=States[idx].symbol; if(dir==0||adx<StrongTrendADX||atr<=0||fast<=0||!CoreAgrees(idx,dir)) return false; double c=iClose(s,EntryTF,1); if(MathAbs(c-fast)/atr<1.80) return false; if(dir==1&&BullishBar(s,EntryTF,1)&&BodySize(s,EntryTF,1)>=atr*MomentumBodyATR) return Prepare(idx,MOD_LATE_CYCLE_FAST_MOVE,1,"late_cycle_fast_long",sig); if(dir==-1&&BearishBar(s,EntryTF,1)&&BodySize(s,EntryTF,1)>=atr*MomentumBodyATR) return Prepare(idx,MOD_LATE_CYCLE_FAST_MOVE,-1,"late_cycle_fast_short",sig); return false;}
   bool Downside(int idx,SSignal &sig){int dir=TrendDirection(idx); string s=States[idx].symbol; double atr=ATRv(idx,1); if(dir!=-1||CoreTrendDirection(idx)!=-1||ADXv(idx,1)<TrendADXMin||atr<=0||!ADXRising(idx)) return false; double c=iClose(s,EntryTF,1),pc=iClose(s,EntryTF,2),lo=LowestLow(s,EntryTF,2,BreakoutLookback/2); if(c<lo&&pc>=lo&&BearishBar(s,EntryTF,1)&&BodySize(s,EntryTF,1)>=atr*MinBodyATR) return Prepare(idx,MOD_DOWNSIDE_RISK_OFF,-1,"qualified_downside_breakout",sig); return false;}
   bool Correction(int idx,SSignal &sig){string s=States[idx].symbol; double atr=ATRv(idx,1),fast=EMAFastv(idx,1); if(atr<=0||fast<=0||ADXv(idx,1)>RangeADXMax) return false; double c=iClose(s,EntryTF,1); if((fast-c)/atr>=RangeDeviationATR&&BullishBar(s,EntryTF,1)&&CoreTrendDirection(idx)>=0) return Prepare(idx,MOD_CORRECTION_REBOUND,1,"correction_rebound_discount",sig); return false;}
   bool MTFCore(int idx,SSignal &sig){int core=CoreTrendDirection(idx),reg=TrendDirection(idx); if(core==0||core!=reg||ADXv(idx,1)<TrendADXMin||!ADXRising(idx)) return false; string s=States[idx].symbol; if(core==1&&BullishBar(s,EntryTF,1)&&iClose(s,EntryTF,1)>EMAPullbackv(idx,1)) return Prepare(idx,MOD_MTF_TREND_CORE,1,"mtf_trend_core_long",sig); if(core==-1&&BearishBar(s,EntryTF,1)&&iClose(s,EntryTF,1)<EMAPullbackv(idx,1)) return Prepare(idx,MOD_MTF_TREND_CORE,-1,"mtf_trend_core_short",sig); return false;}
   bool AVWAP(int idx,SSignal &sig){string s=States[idx].symbol; double v,u,l; if(!CalculateAVWAP(s,v,u,l)) return false; double c=iClose(s,EntryTF,1); if(c<l&&LiquiditySweepReclaim(s,1)&&CVDConfirms(s,1)) return Prepare(idx,MOD_AVWAP_LIQUIDITY,1,"avwap_discount_liquidity_reclaim",sig); if(c>u&&LiquiditySweepReclaim(s,-1)&&CVDConfirms(s,-1)) return Prepare(idx,MOD_AVWAP_LIQUIDITY,-1,"avwap_premium_liquidity_reclaim",sig); return false;}
   bool VolExpansion(int idx,SSignal &sig){string s=States[idx].symbol; double a=ATRv(idx,1),ar=BufferValue(States[idx].hATRRegime,0,1); if(a<=0||ar<=0||a/ar<VolExpansionRatio) return false; double c=iClose(s,EntryTF,1),pc=iClose(s,EntryTF,2),hi=HighestHigh(s,EntryTF,2,BreakoutLookback/2),lo=LowestLow(s,EntryTF,2,BreakoutLookback/2); if(c>hi&&pc<=hi&&BullishBar(s,EntryTF,1)&&CoreAgrees(idx,1)) return Prepare(idx,MOD_VOLATILITY_EXPANSION,1,"volatility_expansion_breakout",sig); if(c<lo&&pc>=lo&&BearishBar(s,EntryTF,1)&&CoreAgrees(idx,-1)) return Prepare(idx,MOD_VOLATILITY_EXPANSION,-1,"volatility_expansion_breakout",sig); return false;}
public:
   bool Build(int idx,int moduleId,SSignal &sig){sig.valid=false; if(!ModuleEnabled(moduleId)) return false; switch(moduleId){case MOD_TREND_PULLBACK:return TrendPullback(idx,sig); case MOD_MOMENTUM_BREAKOUT:return MomentumBreakout(idx,sig); case MOD_LATE_CYCLE_FAST_MOVE:return LateCycle(idx,sig); case MOD_DOWNSIDE_RISK_OFF:return Downside(idx,sig); case MOD_CORRECTION_REBOUND:return Correction(idx,sig); case MOD_MTF_TREND_CORE:return MTFCore(idx,sig); case MOD_AVWAP_LIQUIDITY:return AVWAP(idx,sig); case MOD_VOLATILITY_EXPANSION:return VolExpansion(idx,sig);} return false;}
};
CSignalEngine SIGNALS;

class CRiskManager
{
public:
   void Init(){g_day=CurrentDayKey(); g_dayStartEquity=AccountInfoDouble(ACCOUNT_EQUITY); g_equityPeak=MathMax(g_equityPeak,g_dayStartEquity); int n=ArraySize(States); ArrayResize(g_dailySymbolTrades,n); ArrayResize(g_dailyLossFlag,n); ArrayResize(g_lastSymbolTradeTime,n); ArrayResize(g_symbolBlockUntil,n); ArrayResize(g_symbolLossStreak,n); ArrayResize(g_dailyModuleTrades,MODULE_COUNT); ArrayResize(g_lastModuleTradeTime,MODULE_COUNT); ArrayResize(g_moduleBlockUntil,MODULE_COUNT); ArrayResize(g_moduleLossStreak,MODULE_COUNT); ArrayInitialize(g_dailySymbolTrades,0); ArrayInitialize(g_dailyLossFlag,0); ArrayInitialize(g_lastSymbolTradeTime,0); ArrayInitialize(g_symbolBlockUntil,0); ArrayInitialize(g_symbolLossStreak,0); ArrayInitialize(g_dailyModuleTrades,0); ArrayInitialize(g_lastModuleTradeTime,0); ArrayInitialize(g_moduleBlockUntil,0); ArrayInitialize(g_moduleLossStreak,0);}
   void ResetIfNewDay(){datetime d=CurrentDayKey(); if(d!=g_day){g_day=d; g_dayStartEquity=AccountInfoDouble(ACCOUNT_EQUITY); ArrayInitialize(g_dailySymbolTrades,0); ArrayInitialize(g_dailyModuleTrades,0); ArrayInitialize(g_dailyLossFlag,0);} g_equityPeak=MathMax(g_equityPeak,AccountInfoDouble(ACCOUNT_EQUITY));}
   double PeakDD(){if(g_equityPeak<=0) return 0; double eq=AccountInfoDouble(ACCOUNT_EQUITY); return MathMax(0.0,(g_equityPeak-eq)/g_equityPeak*100.0);} double DailyLoss(){if(g_dayStartEquity<=0) return 0; double eq=AccountInfoDouble(ACCOUNT_EQUITY); return MathMax(0.0,(g_dayStartEquity-eq)/g_dayStartEquity*100.0);} double RiskGov(){double dd=PeakDD(); if(dd>=RiskCutDD2Percent) return RiskCutDD2Multiplier; if(dd>=RiskCutDD1Percent) return RiskCutDD1Multiplier; return 1.0;}
   int CountPortfolio(){int c=0; for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t)) continue; if(IsOurMagic(PositionGetInteger(POSITION_MAGIC))) c++;} return c;} int CountSymbol(string s){int c=0; for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t)) continue; if(PositionGetString(POSITION_SYMBOL)==s&&IsOurMagic(PositionGetInteger(POSITION_MAGIC))) c++;} return c;} int CountModule(int m){int c=0; for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t)) continue; if(ModuleFromMagic(PositionGetInteger(POSITION_MAGIC))==m) c++;} return c;} int CountBucket(string bucket){int c=0; for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t)) continue; if(!IsOurMagic(PositionGetInteger(POSITION_MAGIC))) continue; if(PROFILE.Profile(PositionGetString(POSITION_SYMBOL)).bucket==bucket) c++;} return c;}
   bool CooldownOK(int symbolIndex,SSignal &sig,string &reason){datetime now=TimeCurrent(); if(g_symbolBlockUntil[symbolIndex]>now){reason="symbol_cooldown"; return false;} if(g_moduleBlockUntil[sig.moduleId]>now){reason="module_cooldown"; return false;} if(BlockNewTradesAfterLossDay && g_dailyLossFlag[symbolIndex]>0){reason="symbol_loss_day_lock"; return false;} if(g_lastSymbolTradeTime[symbolIndex]>0){int bars=(int)((now-g_lastSymbolTradeTime[symbolIndex])/PeriodSeconds(EntryTF)); if(bars<MinBarsBetweenSymbolTrades){reason="symbol_trade_spacing"; return false;}} if(g_lastModuleTradeTime[sig.moduleId]>0){int mbars=(int)((now-g_lastModuleTradeTime[sig.moduleId])/PeriodSeconds(EntryTF)); if(mbars<MinBarsBetweenModuleTrades){reason="module_trade_spacing"; return false;}} reason="ok"; return true;}
   bool CanOpen(int symbolIndex,SSignal &sig,string &reason){ResetIfNewDay(); if(DailyLoss()>=MaxDailyLossPercent){reason="daily_loss_limit"; return false;} if(PeakDD()>=EquityStopDDPercent){reason="equity_stop_dd"; return false;} if(!CooldownOK(symbolIndex,sig,reason)) return false; if(CountPortfolio()>=MaxPortfolioPositions){reason="max_portfolio_positions"; return false;} if(CountSymbol(sig.symbol)>=MaxPositionsPerSymbol){reason="max_symbol_positions"; return false;} if(CountBucket(sig.bucket)>=MaxPositionsPerBucket){reason="max_bucket_positions"; return false;} if(CountModule(sig.moduleId)>=MaxPositionsPerSystem){reason="max_system_positions"; return false;} if(g_dailySymbolTrades[symbolIndex]>=MaxTradesPerSymbolPerDay){reason="max_symbol_trades_day"; return false;} if(g_dailyModuleTrades[sig.moduleId]>=MaxTradesPerSystemPerDay){reason="max_system_trades_day"; return false;} reason="ok"; return true;}
   void RegisterTrade(int symbolIndex,int moduleId){datetime now=TimeCurrent(); if(symbolIndex>=0&&symbolIndex<ArraySize(g_dailySymbolTrades)){g_dailySymbolTrades[symbolIndex]++; g_lastSymbolTradeTime[symbolIndex]=now;} if(moduleId>=0&&moduleId<MODULE_COUNT){g_dailyModuleTrades[moduleId]++; g_lastModuleTradeTime[moduleId]=now;}}
   void RegisterClosedDeal(string symbol,int moduleId,double profit){int idx=SymbolIndexByName(symbol); datetime now=TimeCurrent(); if(profit<0){if(idx>=0){g_symbolLossStreak[idx]++; g_dailyLossFlag[idx]=1; if(g_symbolLossStreak[idx]>=LossStreakBeforeCooldown) g_symbolBlockUntil[idx]=now+SymbolCooldownHours*3600;} if(moduleId>=0&&moduleId<MODULE_COUNT){g_moduleLossStreak[moduleId]++; if(g_moduleLossStreak[moduleId]>=LossStreakBeforeCooldown) g_moduleBlockUntil[moduleId]=now+ModuleCooldownHours*3600;}} else if(profit>0){if(idx>=0) g_symbolLossStreak[idx]=0; if(moduleId>=0&&moduleId<MODULE_COUNT) g_moduleLossStreak[moduleId]=0;}}
   double Lots(SSignal &sig){double eq=AccountInfoDouble(ACCOUNT_EQUITY),riskPct=BaseRiskPercent*sig.riskMultiplier*RiskGov(),riskMoney=eq*riskPct/100.0,tv=SymbolInfoDouble(sig.symbol,SYMBOL_TRADE_TICK_VALUE),ts=SymbolInfoDouble(sig.symbol,SYMBOL_TRADE_TICK_SIZE); if(eq<=0||riskMoney<=0||tv<=0||ts<=0||sig.riskDistance<=0) return 0; double lossPerLot=sig.riskDistance/ts*tv; if(lossPerLot<=0) return 0; double lots=riskMoney/lossPerLot,minLot=SymbolInfoDouble(sig.symbol,SYMBOL_VOLUME_MIN),maxLot=SymbolInfoDouble(sig.symbol,SYMBOL_VOLUME_MAX),step=SymbolInfoDouble(sig.symbol,SYMBOL_VOLUME_STEP); if(step<=0) return 0; lots=MathMax(minLot,MathMin(maxLot,lots)); lots=MathFloor(lots/step)*step; return NormalizeDouble(lots,2);}
};
CRiskManager RISK;

class CExecutionEngine
{
private:
   bool CanExecuteNow(){bool tester=(bool)MQLInfoInteger(MQL_TESTER); return (tester&&ExecuteInTester)||AllowLiveTrading;} bool RetcodeOK(uint r){return r==TRADE_RETCODE_DONE||r==TRADE_RETCODE_PLACED||r==TRADE_RETCODE_DONE_PARTIAL;}
   ENUM_ORDER_TYPE_FILLING FillingMode(string s){long m=SymbolInfoInteger(s,SYMBOL_FILLING_MODE); if((m&SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK) return ORDER_FILLING_FOK; if((m&SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC) return ORDER_FILLING_IOC; return ORDER_FILLING_RETURN;}
   bool ModifyAllowed(string s,int type,double oldSL,double newSL){double point=PointFor(s),bid=SymbolInfoDouble(s,SYMBOL_BID),ask=SymbolInfoDouble(s,SYMBOL_ASK); int stops=(int)SymbolInfoInteger(s,SYMBOL_TRADE_STOPS_LEVEL),freeze=(int)SymbolInfoInteger(s,SYMBOL_TRADE_FREEZE_LEVEL); double minDist=(double)MathMax(stops,freeze)*point+2.0*point,minStep=MathMax((double)MinSLModifyStepPoints*point,2.0*point); double n=NormalizePrice(s,newSL),o=NormalizePrice(s,oldSL); if(MathAbs(n-o)<minStep) return false; if(type==POSITION_TYPE_BUY){if(n<=o) return false; if(n>=bid-minDist) return false;} if(type==POSITION_TYPE_SELL){if(n>=o) return false; if(n<=ask+minDist) return false;} return true;}
public:
   bool SendMarket(int symbolIndex,SSignal &sig)
   {
      int spread=(int)SymbolInfoInteger(sig.symbol,SYMBOL_SPREAD); string sideName=sig.side==1?"long":"short"; LOG.Write("SIGNAL",sig.symbol,sig.moduleName,sig.bucket,sideName,sig.entry,sig.sl,sig.tp,sig.rr,sig.atr,spread,0,sig.reason); if(!CanExecuteNow()){LOG.Write("BLOCKED",sig.symbol,sig.moduleName,sig.bucket,sideName,sig.entry,sig.sl,sig.tp,sig.rr,sig.atr,spread,0,"trading_disabled"); return false;} string reason; if(!RISK.CanOpen(symbolIndex,sig,reason)){LOG.Write("SKIP",sig.symbol,sig.moduleName,sig.bucket,sideName,sig.entry,sig.sl,sig.tp,sig.rr,sig.atr,spread,0,reason); return false;} double lots=RISK.Lots(sig); if(lots<=0){LOG.Write("SKIP",sig.symbol,sig.moduleName,sig.bucket,sideName,sig.entry,sig.sl,sig.tp,sig.rr,sig.atr,spread,0,"invalid_lots"); return false;} SAssetProfile p=PROFILE.Profile(sig.symbol); MqlTradeRequest req; MqlTradeResult res; ZeroMemory(req); ZeroMemory(res); req.action=TRADE_ACTION_DEAL; req.symbol=sig.symbol; req.magic=MagicFor(sig.moduleId,sig.symbol); req.volume=lots; req.type=sig.side==1?ORDER_TYPE_BUY:ORDER_TYPE_SELL; req.price=NormalizePrice(sig.symbol,sig.side==1?SymbolInfoDouble(sig.symbol,SYMBOL_ASK):SymbolInfoDouble(sig.symbol,SYMBOL_BID)); req.sl=NormalizePrice(sig.symbol,sig.sl); req.tp=NormalizePrice(sig.symbol,sig.tp); req.deviation=p.deviationPoints; req.type_filling=FillingMode(sig.symbol); req.type_time=ORDER_TIME_GTC; req.comment=sig.moduleName; bool ok=OrderSend(req,res); if(!ok||!RetcodeOK(res.retcode)){LOG.Write("ORDER_ERROR",sig.symbol,sig.moduleName,sig.bucket,sideName,req.price,req.sl,req.tp,sig.rr,sig.atr,spread,res.retcode,res.comment); return false;} RISK.RegisterTrade(symbolIndex,sig.moduleId); LOG.Write("MARKET_FILLED",sig.symbol,sig.moduleName,sig.bucket,sideName,req.price,req.sl,req.tp,sig.rr,sig.atr,spread,res.retcode,sig.reason); return true;
   }
   double LocalATR(string s){MqlRates r[]; ArraySetAsSeries(r,true); if(CopyRates(s,EntryTF,0,ATRPeriod+5,r)<ATRPeriod+2) return 0; double sum=0; for(int i=1;i<=ATRPeriod;i++){double tr=MathMax(r[i].high-r[i].low,MathMax(MathAbs(r[i].high-r[i+1].close),MathAbs(r[i].low-r[i+1].close))); sum+=tr;} return sum/(double)ATRPeriod;}
   void ManageSymbolPositions(string s){for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i); if(t==0||!PositionSelectByTicket(t)) continue; if(PositionGetString(POSITION_SYMBOL)!=s) continue; long magic=PositionGetInteger(POSITION_MAGIC); if(!IsOurMagic(magic)) continue; int moduleId=ModuleFromMagic(magic); datetime openTime=(datetime)PositionGetInteger(POSITION_TIME); int barsHeld=iBarShift(s,EntryTF,openTime,false); if(barsHeld>=ModuleMaxHoldBars(moduleId)){ClosePosition(t,s,moduleId,"max_hold_bars"); continue;} if(MoveToBreakeven) TryBreakeven(t,s,moduleId); if(UseATRTrailing) TryTrail(t,s,moduleId);}}
   bool ClosePosition(ulong ticket,string s,int moduleId,string reason){if(!PositionSelectByTicket(ticket)) return false; int type=(int)PositionGetInteger(POSITION_TYPE); double vol=PositionGetDouble(POSITION_VOLUME),price=type==POSITION_TYPE_BUY?SymbolInfoDouble(s,SYMBOL_BID):SymbolInfoDouble(s,SYMBOL_ASK); SAssetProfile p=PROFILE.Profile(s); MqlTradeRequest req; MqlTradeResult res; ZeroMemory(req); ZeroMemory(res); req.action=TRADE_ACTION_DEAL; req.position=ticket; req.symbol=s; req.volume=vol; req.type=type==POSITION_TYPE_BUY?ORDER_TYPE_SELL:ORDER_TYPE_BUY; req.price=NormalizePrice(s,price); req.deviation=p.deviationPoints; req.type_filling=FillingMode(s); req.magic=MagicFor(moduleId,s); req.comment=reason; bool ok=OrderSend(req,res); LOG.Write(ok&&RetcodeOK(res.retcode)?"CLOSE_SENT":"CLOSE_ERROR",s,ModuleName(moduleId),p.bucket,"",req.price,0,0,0,0,(int)SymbolInfoInteger(s,SYMBOL_SPREAD),res.retcode,res.comment); return ok&&RetcodeOK(res.retcode);}
   void ModifySLTP(ulong ticket,string s,int moduleId,double newSL,double tp,string label){if(!PositionSelectByTicket(ticket)) return; int type=(int)PositionGetInteger(POSITION_TYPE); double oldSL=PositionGetDouble(POSITION_SL); if(oldSL<=0) return; if(!ModifyAllowed(s,type,oldSL,newSL)) return; MqlTradeRequest req; MqlTradeResult res; ZeroMemory(req); ZeroMemory(res); req.action=TRADE_ACTION_SLTP; req.position=ticket; req.symbol=s; req.sl=NormalizePrice(s,newSL); req.tp=NormalizePrice(s,tp); req.magic=MagicFor(moduleId,s); bool ok=OrderSend(req,res); if(!ok||!RetcodeOK(res.retcode)){SAssetProfile p=PROFILE.Profile(s); LOG.Write("SLTP_ERROR",s,ModuleName(moduleId),p.bucket,"",0,req.sl,req.tp,0,0,(int)SymbolInfoInteger(s,SYMBOL_SPREAD),res.retcode,res.comment+" "+label);}}
   void TryBreakeven(ulong ticket,string s,int moduleId){if(!PositionSelectByTicket(ticket)) return; int type=(int)PositionGetInteger(POSITION_TYPE); double open=PositionGetDouble(POSITION_PRICE_OPEN),sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP); if(sl<=0) return; double risk=MathAbs(open-sl); if(risk<=0) return; double bid=SymbolInfoDouble(s,SYMBOL_BID),ask=SymbolInfoDouble(s,SYMBOL_ASK),point=PointFor(s),newSL=sl; if(type==POSITION_TYPE_BUY){double rNow=(bid-open)/risk; if(rNow>=BreakevenAtR&&sl<open) newSL=open+BreakevenPlusPoints*point;} else if(type==POSITION_TYPE_SELL){double rNow=(open-ask)/risk; if(rNow>=BreakevenAtR&&sl>open) newSL=open-BreakevenPlusPoints*point;} if(newSL!=sl) ModifySLTP(ticket,s,moduleId,newSL,tp,"breakeven");}
   void TryTrail(ulong ticket,string s,int moduleId){if(!PositionSelectByTicket(ticket)) return; double atr=LocalATR(s); if(atr<=0) return; int type=(int)PositionGetInteger(POSITION_TYPE); double open=PositionGetDouble(POSITION_PRICE_OPEN),sl=PositionGetDouble(POSITION_SL),tp=PositionGetDouble(POSITION_TP); if(sl<=0) return; double risk=MathAbs(open-sl); if(risk<=0) return; double bid=SymbolInfoDouble(s,SYMBOL_BID),ask=SymbolInfoDouble(s,SYMBOL_ASK),trailMult=moduleId==MOD_LATE_CYCLE_FAST_MOVE?1.15:TrailATRMult,trailStart=moduleId==MOD_LATE_CYCLE_FAST_MOVE?1.25:TrailStartR,newSL=sl; if(type==POSITION_TYPE_BUY){double rNow=(bid-open)/risk,prop=bid-atr*trailMult; if(rNow>=trailStart&&prop>sl&&prop<bid) newSL=prop;} else if(type==POSITION_TYPE_SELL){double rNow=(open-ask)/risk,prop=ask+atr*trailMult; if(rNow>=trailStart&&prop<sl&&prop>ask) newSL=prop;} if(newSL!=sl) ModifySLTP(ticket,s,moduleId,newSL,tp,"atr_trailing");}
};
CExecutionEngine EXECUTION;

int OnInit()
{
   string symbols[]; int n=ParseSymbols(InpSymbols,symbols); if(n<=0){Print("No symbols configured."); return INIT_FAILED;} ArrayResize(States,n);
   for(int i=0;i<n;i++){States[i].symbol=symbols[i]; States[i].lastBarTime=0; SymbolSelect(States[i].symbol,true); States[i].hATR=iATR(States[i].symbol,EntryTF,ATRPeriod); States[i].hATRRegime=iATR(States[i].symbol,RegimeTF,ATRPeriod); States[i].hADX=iADX(States[i].symbol,RegimeTF,ADXPeriod); States[i].hFastEMA=iMA(States[i].symbol,RegimeTF,FastEMA,0,MODE_EMA,PRICE_CLOSE); States[i].hSlowEMA=iMA(States[i].symbol,RegimeTF,SlowEMA,0,MODE_EMA,PRICE_CLOSE); States[i].hPullbackEMA=iMA(States[i].symbol,EntryTF,PullbackEMA,0,MODE_EMA,PRICE_CLOSE); States[i].hCoreFastEMA=iMA(States[i].symbol,CoreTF,FastEMA,0,MODE_EMA,PRICE_CLOSE); States[i].hCoreSlowEMA=iMA(States[i].symbol,CoreTF,SlowEMA,0,MODE_EMA,PRICE_CLOSE); if(States[i].hATR==INVALID_HANDLE||States[i].hATRRegime==INVALID_HANDLE||States[i].hADX==INVALID_HANDLE||States[i].hFastEMA==INVALID_HANDLE||States[i].hSlowEMA==INVALID_HANDLE||States[i].hPullbackEMA==INVALID_HANDLE||States[i].hCoreFastEMA==INVALID_HANDLE||States[i].hCoreSlowEMA==INVALID_HANDLE){Print("Failed indicator handle for ",States[i].symbol); return INIT_FAILED;}}
   LOG.Init(CsvLogFile); RISK.Init(); LOG.Write("INIT","PORTFOLIO","CoreEA_PortfolioX","","",0,0,0,0,0,0,0,StringFormat("version=1.200 symbols=%d entryTF=%s qualification=true",n,EnumToString(EntryTF))); return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){for(int i=0;i<ArraySize(States);i++){if(States[i].hATR!=INVALID_HANDLE) IndicatorRelease(States[i].hATR); if(States[i].hATRRegime!=INVALID_HANDLE) IndicatorRelease(States[i].hATRRegime); if(States[i].hADX!=INVALID_HANDLE) IndicatorRelease(States[i].hADX); if(States[i].hFastEMA!=INVALID_HANDLE) IndicatorRelease(States[i].hFastEMA); if(States[i].hSlowEMA!=INVALID_HANDLE) IndicatorRelease(States[i].hSlowEMA); if(States[i].hPullbackEMA!=INVALID_HANDLE) IndicatorRelease(States[i].hPullbackEMA); if(States[i].hCoreFastEMA!=INVALID_HANDLE) IndicatorRelease(States[i].hCoreFastEMA); if(States[i].hCoreSlowEMA!=INVALID_HANDLE) IndicatorRelease(States[i].hCoreSlowEMA);} LOG.Write("DEINIT","PORTFOLIO","CoreEA_PortfolioX","","",0,0,0,0,0,0,0,IntegerToString(reason));}

void OnTick()
{
   RISK.ResetIfNewDay();
   for(int i=0;i<ArraySize(States);i++)
   {
      string s=States[i].symbol; datetime t=iTime(s,EntryTF,0); if(t<=0||t==States[i].lastBarTime) continue;
      States[i].lastBarTime=t;
      EXECUTION.ManageSymbolPositions(s);
      ProcessSymbol(i);
   }
}

void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return; ulong deal=trans.deal; if(deal==0||!HistoryDealSelect(deal)) return; long magic=HistoryDealGetInteger(deal,DEAL_MAGIC); if(!IsOurMagic(magic)) return; long entry=HistoryDealGetInteger(deal,DEAL_ENTRY); if(entry!=DEAL_ENTRY_OUT&&entry!=DEAL_ENTRY_INOUT) return; string s=HistoryDealGetString(deal,DEAL_SYMBOL); int moduleId=ModuleFromMagic(magic); SAssetProfile p=PROFILE.Profile(s); double profit=HistoryDealGetDouble(deal,DEAL_PROFIT)+HistoryDealGetDouble(deal,DEAL_SWAP)+HistoryDealGetDouble(deal,DEAL_COMMISSION); RISK.RegisterClosedDeal(s,moduleId,profit); LOG.Write("DEAL_CLOSED",s,ModuleName(moduleId),p.bucket,"",HistoryDealGetDouble(deal,DEAL_PRICE),0,0,0,0,(int)SymbolInfoInteger(s,SYMBOL_SPREAD),0,DoubleToString(profit,2));
}

void ProcessSymbol(const int idx)
{
   string s=States[idx].symbol; if(!TradeTimeAllowed(s)) return; SAssetProfile p=PROFILE.Profile(s); string reason; if(DefensiveBlocks(idx,p,reason)){LOG.Write("SKIP",s,ModuleName(MOD_DEFENSIVE_REGIME),p.bucket,"",0,0,0,0,ATRv(idx,1),(int)SymbolInfoInteger(s,SYMBOL_SPREAD),0,reason); return;} int spread=(int)SymbolInfoInteger(s,SYMBOL_SPREAD); if(spread<=0||spread>p.maxSpreadPoints){LOG.Write("SKIP",s,"SpreadFilter",p.bucket,"",0,0,0,0,ATRv(idx,1),spread,0,"spread_rejected"); return;}
   for(int moduleId=0;moduleId<MODULE_COUNT-1;moduleId++){SSignal sig; sig.valid=false; if(!SIGNALS.Build(idx,moduleId,sig)) continue; EXECUTION.SendMarket(idx,sig); if(OneSignalPerSymbolPerBar) break;}
}
//+------------------------------------------------------------------+
