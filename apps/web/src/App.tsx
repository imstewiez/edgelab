import React, { useEffect, useState } from 'react'
import { Activity, AlertTriangle, BarChart3, CheckCircle2, Database, FlaskConical, Play, ShieldCheck, Upload, XCircle, Zap } from 'lucide-react'
import { api } from './api'

type Tab = 'command' | 'data' | 'discovery' | 'candidates' | 'rejected' | 'risk' | 'jobs'

function Card({children, className=''}: any) { return <div className={`card ${className}`}>{children}</div> }
function Button({children, busy, disabled, className='', ...props}: any) { return <button className={`btn ${className}`} disabled={busy || disabled} {...props}>{busy ? 'Working...' : children}</button> }
function Badge({children, tone='neutral'}: any) { return <span className={`badge ${tone}`}>{children}</span> }
function label(v: string) { return v.replaceAll('_',' ').replace(/\b\w/g, s => s.toUpperCase()) }
function Table({rows, columns}: {rows: any[], columns?: string[]}) {
  const cols = columns || (rows?.length ? Object.keys(rows[0]) : [])
  if (!rows?.length) return <div className="empty">No data yet.</div>
  return <div className="tableWrap"><table><thead><tr>{cols.map(c => <th key={c}>{label(c)}</th>)}</tr></thead><tbody>{rows.slice(0,300).map((r,i)=><tr key={i}>{cols.map(c=><td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody></table></div>
}

export function App() {
  const [tab,setTab] = useState<Tab>('command')
  const [health,setHealth] = useState<any>(null)
  const [catalog,setCatalog] = useState<any>({raw_files:[],datasets:[],features:[],data_health:{datasets:[],summary:{}}})
  const [jobs,setJobs] = useState<any[]>([])
  const [outputs,setOutputs] = useState<any[]>([])
  const [cards,setCards] = useState<any[]>([])
  const [selectedOutput,setSelectedOutput] = useState('')
  const [candidateRows,setCandidateRows] = useState<any[]>([])
  const [rejectedRows,setRejectedRows] = useState<any[]>([])
  const [report,setReport] = useState('')
  const [status,setStatus] = useState('Ready.')
  const [busyAction,setBusyAction] = useState('')
  const [uploadState,setUploadState] = useState('')
  const activeJob = jobs.find(j => ['queued','running'].includes(j.status))

  async function refreshAll(){
    try{setHealth(await api.health())}catch{}
    try{setCatalog(await api.catalog())}catch{}
    try{setJobs(await api.jobs())}catch{}
    try{setOutputs(await api.outputs())}catch{}
    try{setCards(await api.edgeCards())}catch{}
  }
  useEffect(()=>{ refreshAll(); const t=setInterval(refreshAll,2000); return()=>clearInterval(t) },[])
  useEffect(()=>{ if(outputs.length && (!selectedOutput || !outputs.find(o=>o.name===selectedOutput))) setSelectedOutput(outputs[0].name) },[outputs])
  useEffect(()=>{ if(!selectedOutput) return; api.edges(selectedOutput,'candidate').then(r=>setCandidateRows(r.rows||[])).catch(()=>setCandidateRows([])); api.edges(selectedOutput,'rejected').then(r=>setRejectedRows(r.rows||[])).catch(()=>setRejectedRows([])); api.report(selectedOutput).then(r=>setReport(r.markdown||'')).catch(()=>setReport('')) },[selectedOutput])

  async function runAction(name:string, fn:()=>Promise<any>, next?:Tab){
    if(busyAction || activeJob){ setStatus('Another job is already running. Duplicate click ignored.'); return }
    setBusyAction(name); setStatus(`${name} started...`)
    try{ const res=await fn(); setStatus(res?.message || `${name} started. Watch Jobs tab.`); if(next) setTab(next); await refreshAll() } catch(e:any){ setStatus(`Error: ${e.message}`) } finally { setTimeout(()=>setBusyAction(''),900) }
  }

  const healthRows = catalog?.data_health?.datasets || []
  const healthSummary = catalog?.data_health?.summary || {}

  return <div className="app"><aside className="sidebar"><div className="brand"><div className="logo"><FlaskConical size={24}/></div><div><strong>CoreEA EdgeLab</strong><span>Unified Quant Research Lab</span></div></div>
    {[[ 'command', Zap, 'Command Center'],['data',Database,'Data Health'],['discovery',Play,'Edge Discovery'],['candidates',CheckCircle2,'Candidate Edges'],['rejected',XCircle,'Rejected Ideas'],['risk',ShieldCheck,'Risk Lab'],['jobs',Activity,'Jobs & Logs']].map(([id,Icon,txt]:any)=><button key={id} className={tab===id?'nav active':'nav'} onClick={()=>setTab(id)}><Icon size={18}/>{txt}</button>)}
    <div className="sideFooter"><ShieldCheck size={16}/><span>Local-first. No paid DB. No gangsbot production repo.</span></div></aside>
    <main className="main"><header className="topbar"><div><h1>{title(tab)}</h1><p>{subtitle(tab)}</p></div><Button onClick={refreshAll}>Refresh</Button></header>
      <div className={`status ${activeJob?'running':''}`}><strong>{activeJob ? `${label(activeJob.kind)} running` : 'System status'}</strong><span>{activeJob ? `${activeJob.status} · ${activeJob.logs?.at(-1)||''}` : status}</span></div>
      {tab==='command' && <section className="grid"><Metric label="Engine" value={health?.ok?'Online':'Offline'} icon={<Activity/>} tone={health?.ok?'good':'bad'}/><Metric label="Datasets" value={catalog.datasets?.length||0} icon={<Database/>}/><Metric label="Feature Sets" value={catalog.features?.length||0} icon={<FlaskConical/>}/><Metric label="Edge Cards" value={cards?.length||0} icon={<BarChart3/>}/><Card className="wide hero"><h2>Auto Edge Discovery</h2><p>Runs the full pipeline: import data → build features → scan market moves → validate candidates → generate readable edge cards.</p><Button className="primary large" busy={busyAction==='Full Auto Discovery'} disabled={!!activeJob} onClick={()=>runAction('Full Auto Discovery',()=>api.discover({mode:'auto'}),'jobs')}>Discover Edges</Button><Button disabled={!!activeJob} onClick={()=>runAction('Build Features',api.startFeatures,'jobs')}>Build Features Only</Button><Button disabled={!!activeJob} onClick={()=>runAction('Import Data',api.startImport,'jobs')}>Import Only</Button></Card><Card className="wide"><h2>Best Candidate Edges</h2><EdgeCardGrid cards={cards.slice(0,6)}/></Card></section>}
      {tab==='data' && <section className="grid"><Metric label="Good" value={healthSummary.good||0} icon={<CheckCircle2/>} tone="good"/><Metric label="Usable" value={healthSummary.usable||0} icon={<AlertTriangle/>} tone="warn"/><Metric label="Weak" value={healthSummary.weak||0} icon={<XCircle/>} tone="bad"/><Metric label="Raw Files" value={catalog.raw_files?.length||0} icon={<Upload/>}/><Card className="wide"><h2>Upload Market Data</h2><input className="file" type="file" multiple disabled={!!activeJob||!!busyAction} onChange={async e=>{ if(!e.target.files)return; setBusyAction('Upload'); setUploadState('Uploading...'); try{const res=await api.upload(e.target.files); setUploadState(`Uploaded ${res.saved?.length||0} file(s).`); setStatus('Upload complete. Run Auto Discovery.'); await refreshAll()}catch(err:any){setUploadState(`Upload failed: ${err.message}`)}finally{setBusyAction('')}}}/><p>{uploadState}</p></Card><Card className="wide"><h2>Data Health</h2><Table rows={healthRows} columns={['symbol','tf','status','quality_score','rows','start','end','coverage_days','gap_count','duplicate_count','notes']}/></Card></section>}
      {tab==='discovery' && <section className="grid"><Card><h2>Discovery Controls</h2><Button className="primary" disabled={!!activeJob} onClick={()=>runAction('Full Auto Discovery',()=>api.discover({mode:'auto'}),'jobs')}>Run Full Auto Discovery</Button><Button disabled={!!activeJob} onClick={()=>runAction('HTF Discovery',()=>api.scan({mode:'htf'}),'jobs')}>HTF Only</Button><Button disabled={!!activeJob} onClick={()=>runAction('Intraday Discovery',()=>api.scan({mode:'intraday'}),'jobs')}>Intraday Only</Button></Card><Card className="wide"><h2>Latest Report</h2><select value={selectedOutput} onChange={e=>setSelectedOutput(e.target.value)}><option value="">Select run</option>{outputs.map(o=><option key={o.name} value={o.name}>{o.name} — {o.candidate_count} candidates / {o.all_count} tested</option>)}</select><pre className="report">{report || 'No report yet. Run discovery first.'}</pre></Card></section>}
      {tab==='candidates' && <section className="grid"><Card className="wide"><h2>Candidate Edge Cards</h2><EdgeCardGrid cards={cards}/></Card><Card className="wide"><h2>Candidate Table</h2><Table rows={candidateRows} columns={['symbol','tf','concept','grade','score','n','pf','test_pf','expR','maxDD_R','winrate','positive_month_pct','session','rr','sl_mult','verdict']}/></Card></section>}
      {tab==='rejected' && <section className="grid"><Card className="wide"><h2>Rejected Ideas / Needs Work</h2><p className="muted">Rejected means the setup failed v1 checks and needs more evidence, better filters, or better data.</p><Table rows={rejectedRows} columns={['symbol','tf','concept','score','n','pf','test_pf','expR','maxDD_R','positive_month_pct','verdict']}/></Card></section>}
      {tab==='risk' && <section className="grid"><Card className="wide"><h2>Risk Lab v1</h2><p>Before EA export we still need walk-forward, slippage stress, Monte Carlo and portfolio heat tests.</p><div className="riskRules"><div><strong>Risk per module</strong><span>Start 0.10%–0.25% until live forward tests pass.</span></div><div><strong>Daily stop</strong><span>Stop new trades after 1% daily equity loss.</span></div><div><strong>Weekly stop</strong><span>Stop new trades after 3% weekly equity loss.</span></div><div><strong>Kill switch</strong><span>Manual restart required after hard DD threshold.</span></div></div></Card><Card className="wide"><h2>Candidate Risk Snapshot</h2><Table rows={candidateRows} columns={['symbol','tf','concept','grade','n','expR','maxDD_R','max_loss_streak','positive_month_pct','verdict']}/></Card></section>}
      {tab==='jobs' && <section className="grid"><Card><h2>Job Controls</h2><Button disabled={!!activeJob} onClick={async()=>{await api.clearCompletedJobs(); await refreshAll(); setStatus('Completed jobs cleared.')}}>Clear Completed Jobs</Button><Button disabled={!!activeJob} onClick={async()=>{await api.cleanOutputs(); await refreshAll(); setStatus('Outputs cleaned. Data/cache kept.')}}>Clean Outputs</Button></Card><Card className="wide"><h2>Jobs</h2><Table rows={jobs} columns={['id','kind','status','created_at','updated_at','error']}/></Card><Card className="wide"><h2>Latest Job Logs</h2><pre className="logs">{jobs[0]?.logs?.join('\n') || 'No jobs yet.'}</pre></Card></section>}
    </main></div>
}

function Metric({label,value,icon,tone='neutral'}:any){ return <Card><div className={`metric ${tone}`}>{icon}<div><p>{label}</p><strong>{value}</strong></div></div></Card> }
function EdgeCardGrid({cards}:{cards:any[]}){ if(!cards?.length) return <div className="empty">No accepted candidate cards yet. Run Full Auto Discovery.</div>; return <div className="edgeGrid">{cards.map(c=><div className="edgeCard" key={c.id}><div className="edgeTop"><h3>{c.title}</h3><Badge tone={c.grade==='A'?'good':c.grade==='B'?'blue':'warn'}>{c.grade}</Badge></div><p>{c.verdict}</p><div className="edgeMetrics"><span>PF <b>{c.metrics.profit_factor}</b></span><span>Test PF <b>{c.metrics.test_pf}</b></span><span>Trades <b>{c.metrics.trades}</b></span><span>Max DD <b>{c.metrics.max_dd_R}R</b></span><span>Exp <b>{c.metrics.expectancy_R}R</b></span><span>Win <b>{Math.round((c.metrics.winrate||0)*100)}%</b></span></div><div className="setupLine">{c.setup.session} · RR {c.setup.rr} · SL {c.setup.sl_atr} ATR · lookback {c.setup.lookback}</div><div className="nextStep">{c.next_step}</div></div>)}</div> }
function title(tab:Tab){ return {command:'Command Center',data:'Data Health',discovery:'Edge Discovery',candidates:'Candidate Edges',rejected:'Rejected Ideas',risk:'Risk Lab',jobs:'Jobs & Logs'}[tab] }
function subtitle(tab:Tab){ return {command:'One button pipeline for automatic market-edge discovery.',data:'Validate whether your market data is strong enough for research.',discovery:'Run controlled automatic scans for market moves and entry logic.',candidates:'Readable decision cards for setups that passed v1 checks.',rejected:'Rejected setups with reasons, so we avoid curve-fit garbage.',risk:'First-pass risk controls before portfolio and EA export.',jobs:'Transparent logs with anti-spam job locking.'}[tab] }
