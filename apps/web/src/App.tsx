import React, { useEffect, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Database, FlaskConical, Layers3, ShieldCheck, Upload, XCircle, Zap } from 'lucide-react'
import { api } from './api'

type Tab = 'run' | 'edges' | 'universe' | 'data' | 'logs'
type Job = { id: string; kind: string; status: string; created_at?: string; updated_at?: string; logs?: string[]; error?: string }

const label = (v: string) => String(v || '').replaceAll('_', ' ').replace(/\b\w/g, s => s.toUpperCase())
const Card = ({ children, className = '' }: any) => <div className={`card ${className}`}>{children}</div>
const Button = ({ children, busy, disabled, className = '', ...props }: any) => <button className={`btn ${className}`} disabled={busy || disabled} {...props}>{busy ? 'Working...' : children}</button>
const Stat = ({ label: l, value, tone = '', icon }: any) => <Card><div className={`metric ${tone}`}>{icon}<div><p>{l}</p><strong>{value}</strong></div></div></Card>

function MiniTable({ rows, columns }: { rows: any[], columns: string[] }) {
  if (!rows?.length) return <div className="empty">Nothing here yet.</div>
  return <div className="tableWrap compact"><table><thead><tr>{columns.map(c => <th key={c}>{label(c)}</th>)}</tr></thead><tbody>{rows.slice(0, 80).map((r, i) => <tr key={i}>{columns.map(c => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody></table></div>
}

export function App() {
  const [tab, setTab] = useState<Tab>('run')
  const [health, setHealth] = useState<any>(null)
  const [catalog, setCatalog] = useState<any>({ raw_files: [], data_health: { datasets: [], summary: {} } })
  const [jobs, setJobs] = useState<Job[]>([])
  const [outputs, setOutputs] = useState<any[]>([])
  const [universe, setUniverse] = useState<any>({ groups: {}, summary: {} })
  const [validation, setValidation] = useState<any>({ top: [] })
  const [walkforward, setWalkforward] = useState<any>({ top: [] })
  const [stress, setStress] = useState<any>({ top: [] })
  const [mc, setMc] = useState<any>({ top: [], ea_ready: 0 })
  const [sensitivity, setSensitivity] = useState<any>({ top: [] })
  const [portfolio, setPortfolio] = useState<any>({ top: [] })
  const [selectedOutput, setSelectedOutput] = useState('')
  const [candidateRows, setCandidateRows] = useState<any[]>([])
  const [rejectedRows, setRejectedRows] = useState<any[]>([])
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('Ready.')
  const [uploadState, setUploadState] = useState('')

  const activeJob = jobs.find(j => ['queued', 'running'].includes(j.status))
  const latestJob = jobs[0]
  const latestRun = outputs[0]
  const currentRunName = selectedOutput || latestRun?.name

  async function refreshAll(runName = currentRunName) {
    try { setHealth(await api.health()) } catch {}
    try { setCatalog(await api.catalog()) } catch {}
    try { setJobs(await api.jobs()) } catch {}
    try { setOutputs(await api.outputs()) } catch {}
    try { setUniverse(await api.strategyUniverse()) } catch {}
    try { setValidation(await api.validation(runName)) } catch {}
    try { setWalkforward(await api.walkforward(runName)) } catch {}
    try { setStress(await api.executionStress(runName)) } catch {}
    try { setMc(await api.monteCarlo(runName)) } catch {}
    try { setSensitivity(await api.sensitivity(runName)) } catch {}
    try { setPortfolio(await api.portfolioRisk(runName)) } catch {}
  }

  useEffect(() => { refreshAll(); const t = setInterval(() => refreshAll(), 2000); return () => clearInterval(t) }, [currentRunName])
  useEffect(() => { if (outputs.length && (!selectedOutput || !outputs.find(o => o.name === selectedOutput))) setSelectedOutput(outputs[0].name) }, [outputs])
  useEffect(() => {
    if (!selectedOutput) return
    api.edges(selectedOutput, 'candidate').then(r => setCandidateRows(r.rows || [])).catch(() => setCandidateRows([]))
    api.edges(selectedOutput, 'rejected').then(r => setRejectedRows(r.rows || [])).catch(() => setRejectedRows([]))
    refreshAll(selectedOutput)
  }, [selectedOutput])

  async function run(name: string, fn: () => Promise<any>, next: Tab = 'logs') {
    if (activeJob || busy) { setNotice('Already running. Extra click ignored.'); return }
    setBusy(name); setNotice(`${name} started.`)
    try { const r = await fn(); setNotice(r?.message || `${name} queued.`); setTab(next); await refreshAll() }
    catch (e: any) { setNotice(`Error: ${e.message}`) }
    finally { setTimeout(() => setBusy(''), 800) }
  }

  const healthSummary = catalog?.data_health?.summary || {}
  const healthRows = catalog?.data_health?.datasets || []
  const cleanOutputs = outputs.map(o => ({ run: o.name, candidates: o.candidate_count, screened: o.all_count, sensitivity: o.has_sensitivity ? 'yes' : 'no', portfolio: o.has_portfolio_risk ? 'yes' : 'no' }))

  return <div className="app"><aside className="sidebar"><div className="brand"><div className="logo"><FlaskConical size={24}/></div><div><strong>CoreEA EdgeLab</strong><span>Quant lab</span></div></div>{[['run', Zap, 'Run'], ['edges', CheckCircle2, 'Edges'], ['universe', Layers3, 'Universe'], ['data', Database, 'Data'], ['logs', Activity, 'Logs']].map(([id, Icon, txt]: any) => <button key={id} className={tab === id ? 'nav active' : 'nav'} onClick={() => setTab(id)}><Icon size={18}/>{txt}</button>)}<div className="sideFooter"><ShieldCheck size={16}/><span>Local data. No paid DB.</span></div></aside><main className="main"><header className="topbar"><div><h1>{pageTitle(tab)}</h1><p>{pageSub(tab)}</p></div><Button onClick={() => refreshAll()}>Refresh</Button></header><div className={`status ${activeJob ? 'running' : ''}`}><strong>{activeJob ? `${label(activeJob.kind)} running` : 'Status'}</strong><span>{activeJob ? (activeJob.logs?.slice(-1)[0] || activeJob.status) : notice}</span></div>
    {tab === 'run' && <section className="grid"><Stat label="Engine" value={health?.ok ? 'Online' : 'Offline'} icon={<Activity/>} tone={health?.ok ? 'good' : 'bad'} /><Stat label="Candidates" value={latestRun?.candidate_count ?? 0} icon={<CheckCircle2/>} tone="good" /><Stat label="Sensitivity Pass" value={sensitivity?.sensitivity_pass ?? 0} icon={<ShieldCheck/>} tone="good" /><Stat label="Portfolio Pass" value={portfolio?.portfolio_pass ?? 0} icon={<ShieldCheck/>} tone="warn" /><Card className="wide primaryPanel"><div><h2>Discovery → Validation → Walk-forward → Stress → Monte Carlo → Sensitivity → Portfolio</h2><p>Phase 1/2 pipeline uses setup IDs, broker-aware costs and full validation handoffs. EA-ready remains locked at 0 until forward paper tracking and broker execution checks pass.</p></div><PipelineButtons run={run} activeJob={activeJob} latestRun={latestRun} currentRunName={currentRunName}/></Card><Card className="wide"><h2>Pipeline status</h2>{latestRun ? <div className="summaryGrid"><div><strong>{latestRun.all_count}</strong><span>Screened</span></div><div><strong>{walkforward?.wf_pass || 0}</strong><span>WF pass</span></div><div><strong>{stress?.stress_pass || 0}</strong><span>Stress pass</span></div><div><strong>{mc?.mc_pass || 0}</strong><span>MC pass</span></div><div><strong>{sensitivity?.sensitivity_pass || 0}</strong><span>Sensitivity pass</span></div><div><strong>{portfolio?.portfolio_pass || 0}</strong><span>Portfolio pass</span></div><div><strong>{portfolio?.portfolio_monthly_dd_R ?? '-'}</strong><span>Portfolio DD R</span></div><div><strong>{portfolio?.avg_pair_corr ?? '-'}</strong><span>Avg pair corr</span></div></div> : <div className="empty">No run yet. Click Discover.</div>}</Card><Card className="wide"><h2>Portfolio leaders</h2><PortfolioList rows={portfolio?.top || []} /></Card><Card className="wide"><h2>Sensitivity leaders</h2><SensitivityList rows={sensitivity?.top || []} /></Card></section>}
    {tab === 'edges' && <section className="grid"><Card className="wide"><h2>Choose run</h2><select value={selectedOutput} onChange={e => setSelectedOutput(e.target.value)}><option value="">Select run</option>{outputs.map(o => <option key={o.name} value={o.name}>{o.name} — {o.candidate_count} candidates / {o.all_count} screened</option>)}</select><PipelineButtons run={run} activeJob={activeJob} latestRun={selectedOutput} currentRunName={selectedOutput}/></Card><Stage title="Stage 7 portfolio/risk heat" summary={portfolio} keys={['candidates_checked','portfolio_pass','portfolio_watchlist','portfolio_monthly_dd_R']} warning={portfolio?.warning}><PortfolioList rows={portfolio?.top || []}/></Stage><Stage title="Stage 6 parameter sensitivity" summary={sensitivity} keys={['candidates_checked','sensitivity_pass','sensitivity_watchlist','sensitivity_fail']} warning={sensitivity?.warning}><SensitivityList rows={sensitivity?.top || []}/></Stage><Stage title="Stage 5 Monte Carlo" summary={mc} keys={['candidates_checked','mc_pass','mc_watchlist','ea_ready']} warning={mc?.warning}><MonteCarloList rows={mc?.top || []}/></Stage><Card className="wide"><h2>Stage 4 execution stress</h2><StressList rows={stress?.top || []}/></Card><Card className="wide"><h2>Stage 3 walk-forward</h2><WalkForwardList rows={walkforward?.top || []}/></Card><Card className="wide"><h2>Stage 2 robustness</h2><ValidationList rows={validation?.top || []}/></Card><Card className="wide"><h2>Candidate ideas</h2><MiniTable rows={candidateRows} columns={['setup_id','symbol','tf','concept','session','lookback','rr','sl_mult','pf','test_pf','expR','maxDD_R','avg_cost_R','verdict']} /></Card><Card className="wide"><h2>Rejected ideas</h2><MiniTable rows={rejectedRows} columns={['symbol','tf','concept','pf','test_pf','expR','maxDD_R','positive_month_pct','verdict']} /></Card></section>}
    {tab === 'universe' && <section className="grid"><Stat label="Concept Groups" value={universe.summary?.groups || 0} icon={<Layers3/>} /><Stat label="Total Concepts" value={universe.summary?.concepts || 0} icon={<FlaskConical/>} /><Stat label="Active Now" value={universe.summary?.active || 0} icon={<CheckCircle2/>} tone="good" /><Stat label="Need Tick/DOM" value={universe.summary?.requires_tick_or_dom || 0} icon={<AlertTriangle/>} tone="warn" /><Card className="wide"><h2>Strategy universe</h2><p>{universe.warning || 'Every concept is treated as a hypothesis until tested.'}</p><UniverseGroups universe={universe}/></Card></section>}
    {tab === 'data' && <section className="grid"><Stat label="Good" value={healthSummary.good || 0} icon={<CheckCircle2/>} tone="good" /><Stat label="Usable" value={healthSummary.usable || 0} icon={<AlertTriangle/>} tone="warn" /><Stat label="Weak" value={healthSummary.weak || 0} icon={<XCircle/>} tone="bad" /><Stat label="Raw files" value={catalog.raw_files?.length || 0} icon={<Upload/>} /><Card className="wide"><h2>Upload data</h2><input className="file" type="file" multiple disabled={!!activeJob || !!busy} onChange={async e => { if (!e.target.files) return; setBusy('Upload'); setUploadState('Uploading...'); try { const r = await api.upload(e.target.files); setUploadState(`Uploaded ${r.saved?.length || 0} file(s).`); await refreshAll() } catch (err: any) { setUploadState(`Upload failed: ${err.message}`) } finally { setBusy('') } }}/><p>{uploadState || 'Upload MT5 CSV/ZIP exports here. Include spread/spread_points columns when possible.'}</p><Button disabled={!!activeJob} onClick={() => run('Import Data', api.startImport)}>Import Only</Button><Button disabled={!!activeJob} onClick={() => run('Build Features', api.startFeatures)}>Build Features Only</Button></Card><Card className="wide"><h2>Data health</h2><MiniTable rows={healthRows} columns={['symbol','tf','status','quality_score','rows','start','end','coverage_days','gap_count','market_closure_gaps','notes']} /></Card></section>}
    {tab === 'logs' && <section className="grid"><Card><h2>Controls</h2><Button disabled={!!activeJob} onClick={async () => { await api.clearCompletedJobs(); await refreshAll(); setNotice('Completed jobs cleared.') }}>Clear completed jobs</Button><Button disabled={!!activeJob} onClick={async () => { await api.cleanOutputs(); await refreshAll(); setNotice('Outputs cleaned. Data/cache kept.') }}>Clean outputs</Button></Card><Card className="wide"><h2>Runs</h2><MiniTable rows={cleanOutputs} columns={['run','candidates','screened','sensitivity','portfolio']} /></Card><Card className="wide"><h2>Jobs</h2><MiniTable rows={jobs} columns={['id','kind','status','created_at','updated_at','error']} /></Card><Card className="wide"><h2>Latest log</h2><pre className="logs">{latestJob?.logs?.join('\n') || 'No jobs yet.'}</pre></Card></section>}
  </main></div>
}

function PipelineButtons({ run, activeJob, latestRun, currentRunName }: any) { return <div><Button className="primary huge" disabled={!!activeJob} onClick={() => run('Discover Edges', () => api.discover({ mode: 'auto' }), 'logs')}>Discover</Button><Button disabled={!!activeJob || !latestRun} onClick={() => run('Validate', () => api.validate({ scan_name: currentRunName }), 'logs')}>Validate</Button><Button disabled={!!activeJob || !latestRun} onClick={() => run('Walk-forward', () => api.runWalkforward({ scan_name: currentRunName }), 'logs')}>Walk-forward</Button><Button disabled={!!activeJob || !latestRun} onClick={() => run('Execution Stress', () => api.runExecutionStress({ scan_name: currentRunName }), 'logs')}>Stress</Button><Button disabled={!!activeJob || !latestRun} onClick={() => run('Monte Carlo', () => api.runMonteCarlo({ scan_name: currentRunName }), 'logs')}>Monte Carlo</Button><Button disabled={!!activeJob || !latestRun} onClick={() => run('Sensitivity', () => api.runSensitivity({ scan_name: currentRunName }), 'logs')}>Sensitivity</Button><Button disabled={!!activeJob || !latestRun} onClick={() => run('Portfolio Risk', () => api.runPortfolioRisk({ scan_name: currentRunName }), 'logs')}>Portfolio Risk</Button></div> }
function Stage({ title, summary, keys, warning, children }: any) { return <Card className="wide"><h2>{title}</h2><div className="summaryGrid">{keys.map((k: string) => <div key={k}><strong>{summary?.[k] ?? 0}</strong><span>{label(k)}</span></div>)}</div><p>{warning}</p>{children}</Card> }
function MonteCarloList({ rows }: { rows: any[] }) { if (!rows?.length) return <div className="empty">No Stage 5 Monte Carlo yet.</div>; return <MiniTable rows={rows} columns={['setup_id','symbol','tf','concept','mc_status','mc_score','profit_probability','p05_totalR','p95_dd_R','p99_dd_R','p95_loss_streak','ruin_probability','verdict']} /> }
function StressList({ rows }: { rows: any[] }) { if (!rows?.length) return <div className="empty">No Stage 4 execution stress yet.</div>; return <MiniTable rows={rows} columns={['setup_id','symbol','tf','concept','stress_status','stress_pass_rate','base_pf','base_test_pf','base_avg_cost_R','worst_test_pf','worst_maxDD_R','verdict']} /> }
function WalkForwardList({ rows }: { rows: any[] }) { if (!rows?.length) return <div className="empty">No Stage 3 walk-forward yet.</div>; return <MiniTable rows={rows} columns={['setup_id','symbol','tf','concept','wf_status','wf_score','wf_pass_rate','wf_median_pf','wf_min_pf','wf_median_expR','wf_verdict']} /> }
function ValidationList({ rows }: { rows: any[] }) { if (!rows?.length) return <div className="empty">No Stage 2 validation yet.</div>; return <MiniTable rows={rows} columns={['setup_id','symbol','tf','concept','robustness_status','robustness_score','trades','pf','test_pf','verdict']} /> }
function SensitivityList({ rows }: { rows: any[] }) { if (!rows?.length) return <div className="empty">No Stage 6 sensitivity yet.</div>; return <MiniTable rows={rows} columns={['setup_id','symbol','tf','concept','sensitivity_status','sensitivity_score','pass_rate','variants_tested','variants_passed','median_pf','min_pf','median_expR','maxDD_R','verdict']} /> }
function PortfolioList({ rows }: { rows: any[] }) { if (!rows?.length) return <div className="empty">No Stage 7 portfolio risk yet.</div>; return <MiniTable rows={rows} columns={['setup_id','symbol','tf','concept','portfolio_status','portfolio_score','avg_abs_corr','standalone_monthly_dd_R','sumR','avg_cost_R','verdict']} /> }
function UniverseGroups({ universe }: { universe: any }) { const entries = Object.entries(universe?.groups || {}); if (!entries.length) return <div className="empty">No strategy universe loaded.</div>; return <div className="universeGrid">{entries.map(([group, concepts]: any) => <div className="universeGroup" key={group}><h3>{label(group)}</h3>{concepts.map((c: any) => <div className="concept" key={c.id}><strong>{c.name}</strong><span>{c.data}</span><em className={`conceptStatus ${c.status.includes('requires') ? 'requires' : c.status}`}>{label(c.status)}</em></div>)}</div>)}</div> }
function pageTitle(tab: Tab) { return { run: 'Run', edges: 'Edges', universe: 'Universe', data: 'Data', logs: 'Logs' }[tab] }
function pageSub(tab: Tab) { return { run: 'Full pipeline through portfolio risk.', edges: 'Candidate ideas through all robustness gates.', universe: 'All concepts EdgeLab knows about.', data: 'Upload files and check whether the data is usable.', logs: 'Only for debugging when something goes wrong.' }[tab] }
