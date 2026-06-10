import React, { useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Database, FlaskConical, Layers3, ShieldCheck, Upload, XCircle, Zap } from 'lucide-react'
import { api } from './api'

type Tab = 'run' | 'edges' | 'universe' | 'data' | 'logs'
type Job = { id: string; kind: string; status: string; created_at?: string; updated_at?: string; logs?: string[]; error?: string; result?: any }

function label(v: string) { return String(v || '').replaceAll('_', ' ').replace(/\b\w/g, s => s.toUpperCase()) }
function Card({ children, className = '' }: any) { return <div className={`card ${className}`}>{children}</div> }
function Button({ children, busy, disabled, className = '', ...props }: any) { return <button className={`btn ${className}`} disabled={busy || disabled} {...props}>{busy ? 'Working...' : children}</button> }
function Stat({ label: l, value, tone = '', icon }: any) { return <Card><div className={`metric ${tone}`}>{icon}<div><p>{l}</p><strong>{value}</strong></div></div></Card> }
function MiniTable({ rows, columns }: { rows: any[], columns: string[] }) {
  if (!rows?.length) return <div className="empty">Nothing here yet.</div>
  return <div className="tableWrap compact"><table><thead><tr>{columns.map(c => <th key={c}>{label(c)}</th>)}</tr></thead><tbody>{rows.slice(0, 80).map((r, i) => <tr key={i}>{columns.map(c => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody></table></div>
}

export function App() {
  const [tab, setTab] = useState<Tab>('run')
  const [health, setHealth] = useState<any>(null)
  const [catalog, setCatalog] = useState<any>({ raw_files: [], datasets: [], features: [], data_health: { datasets: [], summary: {} } })
  const [jobs, setJobs] = useState<Job[]>([])
  const [outputs, setOutputs] = useState<any[]>([])
  const [cards, setCards] = useState<any[]>([])
  const [universe, setUniverse] = useState<any>({ groups: {}, summary: {} })
  const [validation, setValidation] = useState<any>({ robust_candidates: 0, watchlist: 0, not_robust: 0, ea_ready: 0, top: [] })
  const [selectedOutput, setSelectedOutput] = useState('')
  const [candidateRows, setCandidateRows] = useState<any[]>([])
  const [rejectedRows, setRejectedRows] = useState<any[]>([])
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('Ready.')
  const [uploadState, setUploadState] = useState('')

  const activeJob = jobs.find(j => ['queued', 'running'].includes(j.status))
  const latestJob = jobs[0]
  const latestRun = outputs[0]

  async function refreshAll() {
    try { setHealth(await api.health()) } catch {}
    try { setCatalog(await api.catalog()) } catch {}
    try { setJobs(await api.jobs()) } catch {}
    try { setOutputs(await api.outputs()) } catch {}
    try { setCards(await api.edgeCards()) } catch {}
    try { setUniverse(await api.strategyUniverse()) } catch {}
    try { setValidation(await api.validation()) } catch {}
  }

  useEffect(() => { refreshAll(); const t = setInterval(refreshAll, 2000); return () => clearInterval(t) }, [])
  useEffect(() => { if (outputs.length && (!selectedOutput || !outputs.find(o => o.name === selectedOutput))) setSelectedOutput(outputs[0].name) }, [outputs])
  useEffect(() => {
    if (!selectedOutput) return
    api.edges(selectedOutput, 'candidate').then(r => setCandidateRows(r.rows || [])).catch(() => setCandidateRows([]))
    api.edges(selectedOutput, 'rejected').then(r => setRejectedRows(r.rows || [])).catch(() => setRejectedRows([]))
    api.validation(selectedOutput).then(setValidation).catch(() => {})
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
  const topCandidates = useMemo(() => candidateRows.slice(0, 8), [candidateRows])
  const bestCards = cards?.length ? cards : topCandidates.map(edgeRowToCard)
  const cleanOutputs = outputs.map(o => ({ run: o.name, candidates: o.candidate_count, screened: o.all_count }))

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><div className="logo"><FlaskConical size={24}/></div><div><strong>CoreEA EdgeLab</strong><span>Quant lab</span></div></div>
      {[
        ['run', Zap, 'Run'], ['edges', CheckCircle2, 'Edges'], ['universe', Layers3, 'Universe'], ['data', Database, 'Data'], ['logs', Activity, 'Logs'],
      ].map(([id, Icon, txt]: any) => <button key={id} className={tab === id ? 'nav active' : 'nav'} onClick={() => setTab(id)}><Icon size={18}/>{txt}</button>)}
      <div className="sideFooter"><ShieldCheck size={16}/><span>Local data. No paid DB.</span></div>
    </aside>

    <main className="main">
      <header className="topbar"><div><h1>{pageTitle(tab)}</h1><p>{pageSub(tab)}</p></div><Button onClick={refreshAll}>Refresh</Button></header>
      <div className={`status ${activeJob ? 'running' : ''}`}><strong>{activeJob ? `${label(activeJob.kind)} running` : 'Status'}</strong><span>{activeJob ? (activeJob.logs?.slice(-1)[0] || activeJob.status) : notice}</span></div>

      {tab === 'run' && <section className="grid">
        <Stat label="Engine" value={health?.ok ? 'Online' : 'Offline'} icon={<Activity/>} tone={health?.ok ? 'good' : 'bad'} />
        <Stat label="Datasets" value={catalog.datasets?.length || 0} icon={<Database/>} />
        <Stat label="Candidates" value={latestRun?.candidate_count ?? candidateRows.length ?? 0} icon={<CheckCircle2/>} tone="good" />
        <Stat label="EA Ready" value={validation?.ea_ready ?? 0} icon={<ShieldCheck/>} tone="warn" />
        <Card className="wide primaryPanel"><div><h2>Find market edges automatically</h2><p>Discovery screens ideas. Stage 2 checks robustness. EA-ready remains 0 until deeper walk-forward, Monte Carlo and live-forward validation exist.</p></div><div><Button className="primary huge" busy={busy === 'Discover Edges'} disabled={!!activeJob} onClick={() => run('Discover Edges', () => api.discover({ mode: 'auto' }), 'logs')}>Discover Edges</Button><Button busy={busy === 'Validate'} disabled={!!activeJob || !latestRun} onClick={() => run('Validate', () => api.validate({ scan_name: selectedOutput || latestRun?.name }), 'logs')}>Validate Candidates</Button></div></Card>
        <Card className="wide"><h2>Pipeline status</h2>{latestRun ? <div className="summaryGrid"><div><strong>{latestRun.all_count}</strong><span>Screened ideas</span></div><div><strong>{latestRun.candidate_count}</strong><span>First-pass candidates</span></div><div><strong>{validation?.robust_candidates || 0}</strong><span>Robust candidates</span></div><div><strong>{validation?.ea_ready || 0}</strong><span>EA-ready</span></div></div> : <div className="empty">No run yet. Click Discover Edges.</div>}</Card>
        <Card className="wide"><h2>Best robust candidates</h2><ValidationList rows={validation?.top || []} /></Card>
        <Card className="wide"><h2>Best discovery edges</h2><EdgeList cards={bestCards.slice(0, 5)} /></Card>
      </section>}

      {tab === 'edges' && <section className="grid">
        <Card className="wide"><h2>Choose run</h2><select value={selectedOutput} onChange={e => setSelectedOutput(e.target.value)}><option value="">Select run</option>{outputs.map(o => <option key={o.name} value={o.name}>{o.name} — {o.candidate_count} candidates / {o.all_count} screened</option>)}</select><Button disabled={!!activeJob || !selectedOutput} onClick={() => run('Validate', () => api.validate({ scan_name: selectedOutput }), 'logs')}>Validate This Run</Button></Card>
        <Card className="wide"><h2>Stage 2 robustness</h2><div className="summaryGrid"><div><strong>{validation?.candidates_checked || 0}</strong><span>Checked</span></div><div><strong>{validation?.robust_candidates || 0}</strong><span>Robust</span></div><div><strong>{validation?.watchlist || 0}</strong><span>Watchlist</span></div><div><strong>{validation?.ea_ready || 0}</strong><span>EA-ready</span></div></div><p>{validation?.warning}</p><ValidationList rows={validation?.top || []} /></Card>
        <Card className="wide"><h2>Accepted candidate edges</h2><EdgeList cards={bestCards} /></Card>
        <Card className="wide"><h2>Rejected ideas, with reason</h2><MiniTable rows={rejectedRows} columns={['symbol','tf','concept','pf','test_pf','expR','maxDD_R','positive_month_pct','verdict']} /></Card>
      </section>}

      {tab === 'universe' && <section className="grid">
        <Stat label="Concept Groups" value={universe.summary?.groups || 0} icon={<Layers3/>} /><Stat label="Total Concepts" value={universe.summary?.concepts || 0} icon={<FlaskConical/>} /><Stat label="Active Now" value={universe.summary?.active || 0} icon={<CheckCircle2/>} tone="good" /><Stat label="Need Tick/DOM" value={universe.summary?.requires_tick_or_dom || 0} icon={<AlertTriangle/>} tone="warn" />
        <Card className="wide"><h2>Strategy universe</h2><p>{universe.warning || 'Every concept is treated as a hypothesis until tested.'}</p><UniverseGroups universe={universe}/></Card>
      </section>}

      {tab === 'data' && <section className="grid">
        <Stat label="Good" value={healthSummary.good || 0} icon={<CheckCircle2/>} tone="good" /><Stat label="Usable" value={healthSummary.usable || 0} icon={<AlertTriangle/>} tone="warn" /><Stat label="Weak" value={healthSummary.weak || 0} icon={<XCircle/>} tone="bad" /><Stat label="Raw files" value={catalog.raw_files?.length || 0} icon={<Upload/>} />
        <Card className="wide"><h2>Upload data</h2><input className="file" type="file" multiple disabled={!!activeJob || !!busy} onChange={async e => { if (!e.target.files) return; setBusy('Upload'); setUploadState('Uploading...'); try { const r = await api.upload(e.target.files); setUploadState(`Uploaded ${r.saved?.length || 0} file(s).`); await refreshAll() } catch (err: any) { setUploadState(`Upload failed: ${err.message}`) } finally { setBusy('') } }}/><p>{uploadState || 'Upload MT5 CSV/ZIP exports here.'}</p><Button disabled={!!activeJob} onClick={() => run('Import Data', api.startImport)}>Import Only</Button><Button disabled={!!activeJob} onClick={() => run('Build Features', api.startFeatures)}>Build Features Only</Button></Card>
        <Card className="wide"><h2>Data health</h2><MiniTable rows={healthRows} columns={['symbol','tf','status','quality_score','rows','start','end','coverage_days','gap_count','market_closure_gaps','notes']} /></Card>
      </section>}

      {tab === 'logs' && <section className="grid"><Card><h2>Controls</h2><Button disabled={!!activeJob} onClick={async () => { await api.clearCompletedJobs(); await refreshAll(); setNotice('Completed jobs cleared.') }}>Clear completed jobs</Button><Button disabled={!!activeJob} onClick={async () => { await api.cleanOutputs(); await refreshAll(); setNotice('Outputs cleaned. Data/cache kept.') }}>Clean outputs</Button></Card><Card className="wide"><h2>Runs</h2><MiniTable rows={cleanOutputs} columns={['run','candidates','screened']} /></Card><Card className="wide"><h2>Jobs</h2><MiniTable rows={jobs} columns={['id','kind','status','created_at','updated_at','error']} /></Card><Card className="wide"><h2>Latest log</h2><pre className="logs">{latestJob?.logs?.join('\n') || 'No jobs yet.'}</pre></Card></section>}
    </main>
  </div>
}

function ValidationList({ rows }: { rows: any[] }) {
  if (!rows?.length) return <div className="empty">No Stage 2 validation yet. Run Validate Candidates after discovery.</div>
  return <MiniTable rows={rows} columns={['symbol','tf','concept','robustness_status','robustness_score','trades','pf','test_pf','stress_test_pf','stress_maxDD_R','verdict']} />
}
function UniverseGroups({ universe }: { universe: any }) { const groups = universe?.groups || {}; const entries = Object.entries(groups); if (!entries.length) return <div className="empty">No strategy universe loaded.</div>; return <div className="universeGrid">{entries.map(([group, concepts]: any) => <div className="universeGroup" key={group}><h3>{label(group)}</h3>{concepts.map((c: any) => <div className="concept" key={c.id}><strong>{c.name}</strong><span>{c.data}</span><em className={`conceptStatus ${c.status.includes('requires') ? 'requires' : c.status}`}>{label(c.status)}</em></div>)}</div>)}</div> }
function EdgeList({ cards }: { cards: any[] }) { if (!cards?.length) return <div className="empty">No accepted candidates yet.</div>; return <div className="ideaList">{cards.map((c, i) => <div className="idea" key={c.id || i}><div className="rank">#{i + 1}</div><div className="ideaMain"><div className="ideaTitle"><strong>{c.title}</strong><span className={`pill ${gradeTone(c.grade)}`}>{c.grade}</span></div><p>{c.verdict || 'Passed first filter.'}</p><div className="metricsLine"><span>PF <b>{c.metrics?.profit_factor}</b></span><span>Test PF <b>{c.metrics?.test_pf || '-'}</b></span><span>Trades <b>{c.metrics?.trades}</b></span><span>DD <b>{c.metrics?.max_dd_R}R</b></span><span>Exp <b>{c.metrics?.expectancy_R}R</b></span></div></div></div>)}</div> }
function edgeRowToCard(r: any) { return { id: `${r.symbol}_${r.tf}_${r.concept}_${r.session}_${r.rr}`, title: `${r.symbol} ${r.tf} ${label(r.concept)}`, grade: r.grade || 'Candidate', verdict: r.verdict, metrics: { profit_factor: r.pf, test_pf: r.test_pf, trades: r.n, max_dd_R: r.maxDD_R, expectancy_R: r.expR } } }
function gradeTone(g: string) { if (g === 'A') return 'good'; if (g === 'B') return 'blue'; return 'warn' }
function pageTitle(tab: Tab) { return { run: 'Run', edges: 'Edges', universe: 'Universe', data: 'Data', logs: 'Logs' }[tab] }
function pageSub(tab: Tab) { return { run: 'Discovery + validation pipeline.', edges: 'Candidate ideas, robustness status, and rejected ideas.', universe: 'All concepts EdgeLab knows about, including SMC and DOM roadmap.', data: 'Upload files and check whether the data is usable.', logs: 'Only for debugging when something goes wrong.' }[tab] }
