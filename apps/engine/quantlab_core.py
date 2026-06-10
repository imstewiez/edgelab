from __future__ import annotations

import json, re, shutil, time
from pathlib import Path
from typing import Callable, Optional, Tuple
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STORE = ROOT / 'data'; RAW_DIR = STORE / 'raw'; CACHE_DIR = STORE / 'cache'; FEATURES_DIR = STORE / 'features'; OUTPUTS_DIR = STORE / 'outputs'
CATALOG_PATH = STORE / 'catalog.csv'; FEATURE_CATALOG_PATH = STORE / 'feature_catalog.csv'; HEALTH_PATH = STORE / 'data_health.json'; LATEST_CARDS_PATH = OUTPUTS_DIR / 'latest_edge_cards.json'
TF_MINUTES = {'M1':1,'M5':5,'M15':15,'M30':30,'H1':60,'H4':240,'D1':1440}
PRIORITY_SYMBOLS = {'XAUUSD','NAS100','US30','XTIUSD','GBPJPY','EURUSD','USDJPY','USDCAD','GBPUSD','EURJPY','AUDUSD'}
HORIZON = {'M1':240,'M5':72,'M15':48,'M30':32,'H1':72,'H4':48,'D1':30}

def ensure_store():
    for p in [STORE,RAW_DIR,CACHE_DIR,FEATURES_DIR,OUTPUTS_DIR]: p.mkdir(parents=True, exist_ok=True)

def parse_symbol_tf(path: Path) -> Tuple[Optional[str], Optional[str]]:
    m = re.search(r'([A-Z0-9]+)_(M1|M5|M15|M30|H1|H4|D1)(?:_|\.|-)', path.name.upper())
    return (m.group(1), m.group(2)) if m else (None, None)

def read_csv_flexible(path: Path) -> pd.DataFrame:
    last = None
    for sep in [',',';','\t']:
        try:
            df = pd.read_csv(path, sep=sep)
            df.columns = [str(c).strip().lower().replace('<','').replace('>','') for c in df.columns]
            if 'date' in df.columns and 'time' in df.columns and 'open' in df.columns:
                df['time'] = df['date'].astype(str)+' '+df['time'].astype(str)
            if {'time','open','high','low','close'}.issubset(df.columns): return df
        except Exception as e: last = e
    raise RuntimeError(f'Could not parse {path.name}: {last}')

def market_files(): return sorted([p for p in RAW_DIR.rglob('*') if p.is_file() and parse_symbol_tf(p)[0]])
def cache_path(s,t): return CACHE_DIR / f'{s}_{t}.pkl'
def feature_path(s,t): return FEATURES_DIR / f'{s}_{t}_features.pkl'
def list_catalog(): return [] if not CATALOG_PATH.exists() else pd.read_csv(CATALOG_PATH).replace([np.inf,-np.inf],np.nan).fillna('').to_dict('records')
def list_feature_catalog(): return [] if not FEATURE_CATALOG_PATH.exists() else pd.read_csv(FEATURE_CATALOG_PATH).replace([np.inf,-np.inf],np.nan).fillna('').to_dict('records')
def read_data_health(): return {'datasets': [], 'summary': {'status':'not_available'}} if not HEALTH_PATH.exists() else json.loads(HEALTH_PATH.read_text(encoding='utf-8'))

def score_health(symbol, tf, df, source):
    d = df.sort_values('time'); expected = pd.Timedelta(minutes=TF_MINUTES.get(tf,1)); deltas = d['time'].diff().dropna()
    raw_gaps = int((deltas > expected*3).sum()) if len(deltas) else 0
    suspicious_gaps = 0
    for idx, delta in deltas.items():
        if delta <= expected*3: continue
        prev = d.loc[idx-1, 'time'] if idx-1 in d.index else None
        cur = d.loc[idx, 'time']
        if prev is not None and (prev.weekday() == 4 or cur.weekday() in [6, 0]):
            continue
        suspicious_gaps += 1
    dup = int(d['time'].duplicated().sum())
    days = max(1, (d['time'].max()-d['time'].min()).days)
    score = 100 - min(30,suspicious_gaps*3) - min(20,dup)
    if len(d) < 1000 and tf != 'D1': score -= 20
    if days < 180 and tf in ['M1','M5','M15','M30','H1']: score -= 35
    elif days < 365 and tf in ['M1','M5','M15','M30','H1']: score -= 20
    score = max(0,int(score))
    status = 'good' if score>=75 else ('usable' if score>=55 else 'weak')
    note = ''
    if days < 365 and tf in ['M1','M5','M15']: note = 'Short intraday history; avoid over-trusting results.'
    if suspicious_gaps: note = (note + ' ' if note else '') + 'Possible missing-data gaps.'
    return {'symbol':symbol,'tf':tf,'source':source,'rows':int(len(d)),'start':str(d.time.min()),'end':str(d.time.max()),'coverage_days':int(days),'gap_count':suspicious_gaps,'market_closure_gaps':raw_gaps-suspicious_gaps,'duplicate_count':dup,'quality_score':score,'status':status,'notes':note}

def import_raw_data(logger: Callable[[str],None]=print):
    ensure_store(); rows=[]; health=[]; files=market_files(); logger(f'Found {len(files)} market files')
    for i,f in enumerate(files,1):
        sym,tf=parse_symbol_tf(f); logger(f'[{i}/{len(files)}] Importing {sym} {tf}: {f.name}')
        df=read_csv_flexible(f); keep=[c for c in ['time','open','high','low','close','tick_volume','spread_points','real_volume','spread'] if c in df.columns]
        df=df[keep].copy(); df['time']=pd.to_datetime(df['time'], errors='coerce')
        for c in [x for x in keep if x!='time']: df[c]=pd.to_numeric(df[c], errors='coerce')
        if 'spread' in df.columns and 'spread_points' not in df.columns: df=df.rename(columns={'spread':'spread_points'})
        df=df.dropna(subset=['time','open','high','low','close']).sort_values('time').drop_duplicates('time').reset_index(drop=True); df.to_pickle(cache_path(sym,tf))
        rows.append({'symbol':sym,'tf':tf,'rows':int(len(df)),'start':str(df.time.min()),'end':str(df.time.max()),'source':str(f.relative_to(RAW_DIR)),'cache':str(cache_path(sym,tf).relative_to(STORE))})
        health.append(score_health(sym,tf,df,str(f.relative_to(RAW_DIR))))
    pd.DataFrame(rows).to_csv(CATALOG_PATH,index=False)
    summary={'dataset_count':len(health),'good':sum(h['status']=='good' for h in health),'usable':sum(h['status']=='usable' for h in health),'weak':sum(h['status']=='weak' for h in health),'updated_at':time.strftime('%Y-%m-%d %H:%M:%S')}
    HEALTH_PATH.write_text(json.dumps({'summary':summary,'datasets':health},indent=2),encoding='utf-8')
    return {'files':len(files),'datasets':rows,'health':summary}

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def atr(df,n=14):
    pc=df.close.shift(1); tr=pd.concat([(df.high-df.low),(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1); return tr.rolling(n).mean()
def rsi(c,n=14):
    d=c.diff(); up=d.clip(lower=0).rolling(n).mean(); dn=(-d.clip(upper=0)).rolling(n).mean(); return 100-100/(1+up/dn.replace(0,np.nan))

def build_one_features(df,tf):
    df=df.copy(); df['ema21']=ema(df.close,21); df['ema55']=ema(df.close,55); df['ema200']=ema(df.close,200); df['atr14']=atr(df); df['rsi14']=rsi(df.close)
    df['range']=df.high-df.low; df['body']=df.close-df.open; df['body_abs']=df.body.abs(); df['upper_wick']=df.high-df[['open','close']].max(axis=1); df['lower_wick']=df[['open','close']].min(axis=1)-df.low
    df['wick_pressure']=(df.lower_wick-df.upper_wick)/df.range.replace(0,np.nan); df['ema21_slope_atr']=(df.ema21-df.ema21.shift(4 if tf in ['H4','D1'] else 8))/df.atr14.replace(0,np.nan)
    df['atr_rank_500']=df.atr14.rolling(500,min_periods=50).rank(pct=True); df['range_rank_200']=df.range.rolling(200,min_periods=50).rank(pct=True); df['compression']=(df.atr_rank_500<.35)&(df.range_rank_200<.45)
    df['trend_up']=(df.close>df.ema200)&(df.ema21>df.ema55); df['trend_down']=(df.close<df.ema200)&(df.ema21<df.ema55)
    df['impulse_up']=(df.close>df.open)&(df.range>df.atr14*1.2)&(df.body_abs>df.range*0.55)
    df['impulse_down']=(df.close<df.open)&(df.range>df.atr14*1.2)&(df.body_abs>df.range*0.55)
    df['bull_fvg']=df.low>df.high.shift(2); df['bear_fvg']=df.high<df.low.shift(2)
    df['bull_fvg_mid']=((df.low+df.high.shift(2))/2).where(df.bull_fvg)
    df['bear_fvg_mid']=((df.high+df.low.shift(2))/2).where(df.bear_fvg)
    df['bull_ob_high']=df.open.shift(1).where(df.impulse_up & (df.close.shift(1)<df.open.shift(1))).ffill(limit=40)
    df['bull_ob_low']=df.low.shift(1).where(df.impulse_up & (df.close.shift(1)<df.open.shift(1))).ffill(limit=40)
    df['bear_ob_low']=df.open.shift(1).where(df.impulse_down & (df.close.shift(1)>df.open.shift(1))).ffill(limit=40)
    df['bear_ob_high']=df.high.shift(1).where(df.impulse_down & (df.close.shift(1)>df.open.shift(1))).ffill(limit=40)
    t=pd.to_datetime(df.time); df['date']=t.dt.date.astype(str); df['hour']=t.dt.hour; df['weekday']=t.dt.weekday; df['year']=t.dt.year; df['month']=t.dt.month
    daily=df.groupby('date').agg(day_high=('high','max'),day_low=('low','min')); daily['prev_day_high']=daily.day_high.shift(1); daily['prev_day_low']=daily.day_low.shift(1); df=df.merge(daily[['prev_day_high','prev_day_low']],left_on='date',right_index=True,how='left')
    if tf in ['M1','M5','M15','M30','H1']:
        asian=df[(df.hour>=0)&(df.hour<7)].groupby('date').agg(asian_high=('high','max'),asian_low=('low','min')); df=df.merge(asian,left_on='date',right_index=True,how='left')
    else: df['asian_high']=np.nan; df['asian_low']=np.nan
    return df

def build_features(logger: Callable[[str],None]=print):
    if not CATALOG_PATH.exists(): raise RuntimeError('No catalog found. Run Import first.')
    cat=pd.read_csv(CATALOG_PATH); rows=[]; logger(f'Building features for {len(cat)} datasets')
    for i,r in cat.iterrows():
        logger(f'[{i+1}/{len(cat)}] Features {r.symbol} {r.tf}'); fdf=build_one_features(pd.read_pickle(cache_path(r.symbol,r.tf)),r.tf); fdf.to_pickle(feature_path(r.symbol,r.tf)); row=r.to_dict(); row['feature_cache']=str(feature_path(r.symbol,r.tf).relative_to(STORE)); row['feature_rows']=len(fdf); rows.append(row)
    pd.DataFrame(rows).to_csv(FEATURE_CATALOG_PATH,index=False); return {'datasets':len(rows),'features':rows}

def session_mask(df,s):
    if s=='ny': return (df.hour>=13)&(df.hour<21)
    if s=='overlap': return (df.hour>=13)&(df.hour<17)
    if s=='london_ny': return (df.hour>=7)&(df.hour<21)
    if s=='london': return (df.hour>=7)&(df.hour<13)
    return pd.Series(True,index=df.index)

def signals(df,concept,lb):
    c=df.close; hi=df.high.rolling(lb).max().shift(1); lo=df.low.rolling(lb).min().shift(1)
    b=pd.Series(False,index=df.index); s=pd.Series(False,index=df.index)
    if concept=='breakout_trend': b=(c>hi)&df.trend_up&(df.ema21_slope_atr>.03); s=(c<lo)&df.trend_down&(df.ema21_slope_atr<-.03)
    elif concept=='breakout_fast': b=(c>hi)&(df.ema21>df.ema55); s=(c<lo)&(df.ema21<df.ema55)
    elif concept=='pullback_ema21': b=df.trend_up&(c>df.ema21)&(c.shift(1)<df.ema21.shift(1)); s=df.trend_down&(c<df.ema21)&(c.shift(1)>df.ema21.shift(1))
    elif concept=='compression_breakout': b=df.compression.shift(1).fillna(False)&(c>hi)&(df.ema21>df.ema55); s=df.compression.shift(1).fillna(False)&(c<lo)&(df.ema21<df.ema55)
    elif concept=='sweep_reclaim': b=(df.low<lo)&(c>lo)&(df.wick_pressure>.2); s=(df.high>hi)&(c<hi)&(df.wick_pressure<-.2)
    elif concept=='prev_day_sweep': b=(df.low<df.prev_day_low)&(c>df.prev_day_low); s=(df.high>df.prev_day_high)&(c<df.prev_day_high)
    elif concept=='asian_breakout': tw=(df.hour>=7)&(df.hour<13); b=tw&(c>df.asian_high)&(df.ema21>df.ema55); s=tw&(c<df.asian_low)&(df.ema21<df.ema55)
    elif concept=='equal_high_low_sweep':
        tol=df.atr14*0.20; eq_low=(df.low.shift(1)-lo).abs()<=tol; eq_high=(df.high.shift(1)-hi).abs()<=tol
        b=eq_low&(df.low<lo)&(c>lo)&(df.lower_wick>df.upper_wick)
        s=eq_high&(df.high>hi)&(c<hi)&(df.upper_wick>df.lower_wick)
    elif concept=='bos_breakout':
        b=(c>hi)&(c.shift(1)<=hi)&(df.ema21>df.ema55)
        s=(c<lo)&(c.shift(1)>=lo)&(df.ema21<df.ema55)
    elif concept=='choch_reversal':
        b=df.trend_down.shift(1).fillna(False)&(c>hi)&(df.rsi14>50)
        s=df.trend_up.shift(1).fillna(False)&(c<lo)&(df.rsi14<50)
    elif concept=='fvg_rebalance':
        bull_mid=df.bull_fvg_mid.ffill(limit=30).shift(1); bear_mid=df.bear_fvg_mid.ffill(limit=30).shift(1)
        b=df.trend_up&(df.low<=bull_mid)&(c>bull_mid)&(c>df.open)
        s=df.trend_down&(df.high>=bear_mid)&(c<bear_mid)&(c<df.open)
    elif concept=='order_block_retest':
        b=df.trend_up&(df.low<=df.bull_ob_high)&(c>df.bull_ob_high)&(df.bull_ob_high>df.bull_ob_low)
        s=df.trend_down&(df.high>=df.bear_ob_low)&(c<df.bear_ob_low)&(df.bear_ob_high>df.bear_ob_low)
    return b.fillna(False),s.fillna(False)

def backtest(df,buy,sell,rr,slm,horizon,cost=.04):
    trades=[]; i=250; n=len(df)
    while i<n-2:
        side=1 if buy.iloc[i] else (-1 if sell.iloc[i] else 0)
        if not side: i+=1; continue
        ei=i+1; entry=float(df.open.iloc[ei]); a=float(df.atr14.iloc[i])
        if not np.isfinite(a) or a<=0: i+=1; continue
        risk=a*slm; sl=entry-side*risk; tp=entry+side*risk*rr; end=min(ei+horizon,n-1); R=None
        for j in range(ei,end+1):
            hi,lo=float(df.high.iloc[j]),float(df.low.iloc[j]); hit_sl=lo<=sl if side==1 else hi>=sl; hit_tp=hi>=tp if side==1 else lo<=tp
            if hit_sl and hit_tp: R=-1-cost; end=j; break
            if hit_sl: R=-1-cost; end=j; break
            if hit_tp: R=rr-cost; end=j; break
        if R is None: R=side*(float(df.close.iloc[end])-entry)/risk-cost
        trades.append({'R':float(R),'year':int(df.year.iloc[ei]),'month':int(df.month.iloc[ei])}); i=end+1
    return pd.DataFrame(trades)

def st(tr):
    if tr.empty: return None
    R=tr.R.astype(float); gp=R[R>0].sum(); gl=-R[R<=0].sum(); eq=R.cumsum(); dd=(eq.cummax()-eq).max(); streak=cur=0
    for x in R:
        cur=cur+1 if x<=0 else 0; streak=max(streak,cur)
    return {'n':len(R),'sumR':round(R.sum(),3),'expR':round(R.mean(),4),'pf':round(float(gp/gl),3) if gl>0 else 99,'winrate':round(float((R>0).mean()),4),'maxDD_R':round(float(dd),3),'max_loss_streak':int(streak)}

def concepts_for_tf(tf):
    core=['breakout_trend','breakout_fast','pullback_ema21','compression_breakout','sweep_reclaim','prev_day_sweep']
    smc=['equal_high_low_sweep','bos_breakout','choch_reversal','fvg_rebalance','order_block_retest']
    intraday=['asian_breakout'] if tf in ['M5','M15','M30','H1'] else []
    return core + smc + intraday

def discover_edges(name,mode,symbols,tfs,logger):
    if not FEATURE_CATALOG_PATH.exists(): raise RuntimeError('No feature catalog found. Run Build Features first.')
    cat=pd.read_csv(FEATURE_CATALOG_PATH)
    if symbols: cat=cat[cat.symbol.isin({x.strip().upper() for x in symbols.split(',') if x.strip()})]
    if tfs: cat=cat[cat.tf.isin({x.strip().upper() for x in tfs.split(',') if x.strip()})]
    if mode=='priority': cat=cat[cat.symbol.isin(PRIORITY_SYMBOLS)]
    if mode=='htf': cat=cat[cat.tf.isin(['H1','H4','D1'])]
    if mode=='intraday': cat=cat[cat.tf.isin(['M5','M15','M30'])]
    out=OUTPUTS_DIR/name; out.mkdir(parents=True,exist_ok=True); results=[]; datasets=[]; logger(f'Auto discovery started. mode={mode}, datasets={len(cat)}')
    for _,r in cat.iterrows():
        sym,tf=r.symbol,r.tf; fp=feature_path(sym,tf)
        if not fp.exists(): continue
        df=pd.read_pickle(fp); datasets.append({'symbol':sym,'tf':tf,'rows':len(df),'start':str(df.time.min()),'end':str(df.time.max())}); logger(f'Scanning {sym} {tf}: rows={len(df)}')
        concepts=concepts_for_tf(tf); sessions=['all','london_ny','ny','overlap']; lbs=[20,50] if tf in ['H1','H4','D1'] else [12,20,48]; min_tr=25 if tf=='D1' else 35
        for concept in concepts:
            for lb in lbs:
                b0,s0=signals(df,concept,lb)
                if int(b0.sum()+s0.sum()) < min_tr: continue
                for sess in sessions:
                    sm=session_mask(df,sess)
                    for rr in [1.0,1.4,2.0,2.5]:
                        for slm in [1.0,1.4,2.0]:
                            tr=backtest(df,b0&sm,s0&sm,rr,slm,HORIZON.get(tf,48)); base=st(tr)
                            if not base or base['n']<min_tr: continue
                            split=max(1,int(len(tr)*.7)); test=st(tr.iloc[split:]) or {}; mon=tr.groupby(['year','month']).R.sum(); pos=float((mon>0).mean()) if len(mon) else 0
                            rec={'symbol':sym,'tf':tf,'concept':concept,'lookback':lb,'session':sess,'rr':rr,'sl_mult':slm,**base,'test_pf':test.get('pf',''),'test_n':test.get('n',0),'positive_month_pct':round(pos,3)}
                            score=rec['expR']*100+min(rec['pf'],3)*20+(min(float(rec['test_pf']),3)*12 if rec['test_pf']!='' else 0)+pos*20-rec['maxDD_R']*.35-rec['max_loss_streak']*1.5
                            reasons=[]
                            if rec['pf']<1.22: reasons.append('PF below minimum')
                            if rec['test_n']>=10 and rec['test_pf']<1.05: reasons.append('Weak out-of-sample PF')
                            if pos<.48: reasons.append('Low monthly stability')
                            if rec['max_loss_streak']>9: reasons.append('Loss streak too high')
                            if rec['maxDD_R']>16: reasons.append('R drawdown too high')
                            rec['score']=round(score,3); rec['status']='rejected' if reasons else 'candidate'; rec['grade']='A' if not reasons and score>=105 else ('B' if not reasons and score>=80 else ('C' if not reasons else 'Rejected')); rec['verdict']='; '.join(reasons) if reasons else 'Passed v1 automated checks'; results.append(rec)
    res=pd.DataFrame(results).sort_values('score',ascending=False) if results else pd.DataFrame(); cand=res[res.status=='candidate'] if not res.empty else pd.DataFrame(); rej=res[res.status=='rejected'] if not res.empty else pd.DataFrame()
    cards=[edge_card(x) for x in cand.head(25).to_dict('records')] if not cand.empty else []
    pd.DataFrame(datasets).to_csv(out/'datasets_scanned.csv',index=False); res.to_csv(out/'all_edges.csv',index=False); cand.to_csv(out/'candidate_edges.csv',index=False); rej.to_csv(out/'rejected_edges.csv',index=False); (out/'edge_cards.json').write_text(json.dumps(cards,indent=2),encoding='utf-8'); LATEST_CARDS_PATH.write_text(json.dumps(cards,indent=2),encoding='utf-8')
    report=make_report(name,datasets,res,cand,rej,cards); (out/'DISCOVERY_REPORT.md').write_text(report,encoding='utf-8'); (out/'QUANTLAB_REPORT.md').write_text(report,encoding='utf-8')
    return {'scan_name':name,'datasets':len(datasets),'tested_edges':len(res),'candidates':len(cand),'rejected':len(rej),'active_concepts_tested':sorted(set(res.concept)) if not res.empty else []}

def edge_card(r):
    return {'id':f"{r['symbol']}_{r['tf']}_{r['concept']}_{r['session']}_{r['rr']}",'title':f"{r['symbol']} {r['tf']} {r['concept'].replace('_',' ').title()}",'symbol':r['symbol'],'tf':r['tf'],'concept':r['concept'],'grade':r['grade'],'status':r['status'],'score':r['score'],'metrics':{'trades':r['n'],'profit_factor':r['pf'],'test_pf':r.get('test_pf',''),'expectancy_R':r['expR'],'max_dd_R':r['maxDD_R'],'winrate':r['winrate'],'positive_month_pct':r['positive_month_pct'],'loss_streak':r['max_loss_streak']},'setup':{'session':r['session'],'lookback':r['lookback'],'rr':r['rr'],'sl_atr':r['sl_mult']},'verdict':r['verdict'],'next_step':'Run deeper walk-forward + spread/slippage stress before EA export.'}

def make_report(name,datasets,res,cand,rej,cards):
    lines=[f'# EdgeLab Auto Discovery Report — {name}\n\n',f'Datasets scanned: {len(datasets)}\n\n',f'Edges screened: {len(res)}\n\n',f'First-pass candidates: {len(cand)}\n\n',f'Rejected ideas: {len(rej)}\n\n']
    if cards:
        lines.append('## Best Candidate Cards\n\n')
        for c in cards[:10]: lines.append(f"### {c['title']} — Grade {c['grade']}\n- PF: {c['metrics']['profit_factor']}\n- Test PF: {c['metrics']['test_pf']}\n- Trades: {c['metrics']['trades']}\n- Max DD: {c['metrics']['max_dd_R']}R\n- Verdict: {c['verdict']}\n\n")
    cols=['symbol','tf','concept','session','lookback','rr','sl_mult','grade','score','n','pf','test_pf','expR','maxDD_R','winrate','positive_month_pct','verdict']
    if not cand.empty: lines += ['## Candidate Table\n\n', cand.head(100)[[c for c in cols if c in cand.columns]].to_markdown(index=False), '\n\n']
    if not rej.empty: lines += ['## Rejected / Needs Work\n\n', rej.head(100)[[c for c in cols if c in rej.columns]].to_markdown(index=False), '\n\n']
    return ''.join(lines)

def run_auto_discovery(mode='auto',symbols='',tfs='',logger: Callable[[str],None]=print):
    logger('Step 1/3: Importing data'); import_raw_data(logger); logger('Step 2/3: Building features'); build_features(logger); logger('Step 3/3: Discovering edges'); return discover_edges(f"auto_discovery_{time.strftime('%Y%m%d_%H%M%S')}", 'priority' if mode=='auto' else mode, symbols, tfs, logger)
def run_scan_only(name,mode='priority',symbols='',tfs='',logger: Callable[[str],None]=print): return discover_edges(name,mode,symbols,tfs,logger)
def list_outputs():
    if not OUTPUTS_DIR.exists(): return []
    out=[]
    for d in sorted([p for p in OUTPUTS_DIR.iterdir() if p.is_dir()], reverse=True):
        cand=d/'candidate_edges.csv'; allp=d/'all_edges.csv'; out.append({'name':d.name,'candidate_count':len(pd.read_csv(cand)) if cand.exists() else 0,'all_count':len(pd.read_csv(allp)) if allp.exists() else 0,'has_report':(d/'QUANTLAB_REPORT.md').exists()})
    return out

def read_edges_preview(scan_name,kind='candidate',limit=100):
    fn={'candidate':'candidate_edges.csv','all':'all_edges.csv','rejected':'rejected_edges.csv'}.get(kind,'candidate_edges.csv'); p=OUTPUTS_DIR/scan_name/fn
    if not p.exists(): return {'rows':[],'columns':[]}
    df=pd.read_csv(p).replace([np.inf,-np.inf],np.nan).fillna('').head(limit); return {'rows':df.to_dict('records'),'columns':list(df.columns)}
def read_report(scan_name):
    for fn in ['DISCOVERY_REPORT.md','QUANTLAB_REPORT.md']:
        p=OUTPUTS_DIR/scan_name/fn
        if p.exists(): return p.read_text(encoding='utf-8',errors='ignore')
    return None
def read_edge_cards():
    if LATEST_CARDS_PATH.exists(): return json.loads(LATEST_CARDS_PATH.read_text(encoding='utf-8'))
    outs=list_outputs(); p=OUTPUTS_DIR/outs[0]['name']/'edge_cards.json' if outs else None
    return json.loads(p.read_text(encoding='utf-8')) if p and p.exists() else []
def clean_outputs():
    for p in OUTPUTS_DIR.iterdir() if OUTPUTS_DIR.exists() else []:
        if p.is_dir(): shutil.rmtree(p, ignore_errors=True)
        elif p.name=='latest_edge_cards.json': p.unlink(missing_ok=True)
    return {'ok':True,'message':'Outputs cleaned. Raw data/cache/features kept.'}
