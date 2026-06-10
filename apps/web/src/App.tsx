import React, { useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, CheckCircle2, Database, FlaskConical, Play, RefreshCw } from 'lucide-react'
import { api } from './api'

type View = 'pipeline' | 'data' | 'results'
type Job = { id: string; kind: string; status: string; percent?: number; stage?: string; steps?: any[]; created_at?: string; updated_at?: string; logs?: string[]; error?: string; result?: any }

const label = (v: string) => String(v || '').replaceAll('_', ' ').replace(/\b\w/g, s => s.toUpperCase())
const Card = ({ children, className = '' }: any) => <div className={`card ${className}`}>{children}</div>
const Button = ({ children, disabled, className = '', ...props }: any) => <button className={`btn ${className}`} disabled={disabled} {...props}>{children}</button>
const Metric = ({ name, value, tone = '', icon }: any) => <Card><div className={`metric ${tone}`}>{icon}<div><p>{name}</p><strong>{value}</strong></div></div></Card>

function MiniTable({ rows, columns, tall = false }: { rows: any[], columns: string[], tall?: boolean }) {
  if (!rows?.length) return <div className="empty">Ainda sem resultados nesta secção.</div>
  return <div className={`tableWrap ${tall ? 'tall' : ''}`}><table><thead><tr>{columns.map(c => <th key={c}>{label(c)}</th>)}</tr></thead><tbody>{rows.slice(0, 120).map((r, i) => <tr key={i}>{columns.map(c => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody></table></div>
}

export function App() {
  const [view, setView] = useState<View>('pipeline')
  const [health, setHealth] = useState<any>(null)
  const [catalog, setCatalog] = useState<any>({ raw_files: [], data_health: { datasets: [], summary: {} } })
  const [jobs, setJobs] = useState<Job[]>([])
  const [outputs, setOutputs] = useState<any[]>([])
  const [selectedRun, setSelectedRun] = useState('')
  const [eventLab, setEventLab] = useState<any>({ top: [] })
  const [validation, setValidation] = useState<any>({ top: [] })
  const [walkforward, setWalkforward] = useState<any>({ top: [] })
  const [stress, setStress] = useState<any>({ top: [] })
  const [mc, setMc] = useState<any>({ top: [] })
  const [sensitivity, setSensitivity] = useState<any>({ top: [] })
  const [portfolio, setPortfolio] = useState<any>({ top: [] })
  const [permutation, setPermutation] = useState<any>({ top: [] })
  const [incubation, setIncubation] = useState<any>({ top: [] })
  const [candidateRows, setCandidateRows] = useState<any[]>([])
  const [allRows, setAllRows] = useState<any[]>([])
  const [notice, setNotice] = useState('Pronto.')
  const [uploadState, setUploadState] = useState('')
  const [busy, setBusy] = useState(false)

  const activeJob = jobs.find(j => ['queued', 'running'].includes(j.status))
  const latestJob = jobs[0]
  const currentRun = selectedRun || outputs[0]?.name || activeJob?.result?.scan_name || ''
  const progress = Math.max(0, Math.min(100, Number(activeJob?.percent ?? (latestJob?.status === 'completed' ? 100 : 0))))
  const lastLog = activeJob?.logs?.slice(-1)[0] || latestJob?.logs?.slice(-1)[0] || notice
  const healthSummary = catalog?.data_health?.summary || {}
  const rawFiles = Array.isArray(catalog?.raw_files) ? catalog.raw_files : []

  async function refresh(runName = currentRun) {
    try { setHealth(await api.health()) } catch {}
    try { setCatalog(await api.catalog()) } catch {}
    try { setJobs(await api.jobs()) } catch {}
    try { const outs = await api.outputs(); setOutputs(outs); if (!selectedRun && outs?.[0]?.name) runName = outs[0].name } catch {}
    if (runName) {
      await Promise.allSettled([
        api.eventLab(runName).then(setEventLab),
        api.validation(runName).then(setValidation),
        api.walkforward(runName).then(setWalkforward),
        api.executionStress(runName).then(setStress),
        api.monteCarlo(runName).then(setMc),
        api.sensitivity(runName).then(setSensitivity),
        api.portfolioRisk(runName).then(setPortfolio),
        api.permutationTest(runName).then(setPermutation),
        api.incubation(runName).then(setIncubation),
        api.edges(runName, 'candidate').then(r => setCandidateRows(r.rows || [])),
        api.edges(runName, 'all').then(r => setAllRows(r.rows || [])),
      ])
    }
  }

  useEffect(() => { refresh(); const t = setInterval(() => refresh(), 1500); return () => clearInterval(t) }, [selectedRun])
  useEffect(() => { if (!selectedRun && outputs?.[0]?.name) setSelectedRun(outputs[0].name) }, [outputs, selectedRun])

  async function startFullPipeline() {
    if (activeJob || busy) return
    setBusy(true); setNotice('A iniciar pipeline completo...')
    try { const r = await api.fullPipeline({ mode: 'priority' }); setNotice(r.message || 'Pipeline iniciado.'); setView('pipeline'); await refresh() }
    catch (e: any) { setNotice(`Erro: ${e.message}`) }
    finally { setBusy(false) }
  }

  async function runStep(name: string, fn: () => Promise<any>) {
    if (activeJob || busy) return
    setBusy(true); setNotice(`${name} iniciado...`)
    try { const r = await fn(); setNotice(r.message || `${name} em execução.`); await refresh() }
    catch (e: any) { setNotice(`Erro: ${e.message}`) }
    finally { setBusy(false) }
  }

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return
    setBusy(true); setUploadState('A enviar ficheiros...')
    try {
      const r = await api.upload(files)
      const err = r.errors?.length ? ` Erros: ${r.errors.map((x: any) => `${x.filename}: ${x.error}`).join(' | ')}` : ''
      setUploadState(`${r.message || 'Upload concluído.'}${err}`)
      setNotice('Upload concluído. Agora corre o pipeline completo para importar, limpar e testar.')
      await refresh()
    } catch (e: any) {
      setUploadState(`Upload falhou: ${e.message}`)
      setNotice(`Upload falhou: ${e.message}`)
    } finally { setBusy(false) }
  }

  const finalCandidates = useMemo(() => incubation?.top?.length ? incubation.top : permutation?.top?.length ? permutation.top : portfolio?.top?.length ? portfolio.top : sensitivity?.top?.length ? sensitivity.top : mc?.top?.length ? mc.top : stress?.top?.length ? stress.top : walkforward?.top?.length ? walkforward.top : validation?.top || [], [incubation, permutation, portfolio, sensitivity, mc, stress, walkforward, validation])

  return <div className="app">
    <header className="topShell"><div className="topRow"><div className="brand"><div className="logo"><FlaskConical size={22}/></div><div><strong>CoreEA EdgeLab</strong><span>Research pipeline compacto</span></div></div><nav className="nav"><button className={view === 'pipeline' ? 'active' : ''} onClick={() => setView('pipeline')}>Pipeline</button><button className={view === 'data' ? 'active' : ''} onClick={() => setView('data')}>Dados</button><button className={view === 'results' ? 'active' : ''} onClick={() => setView('results')}>Resultados</button></nav></div></header>
    <main className="main">
      <section className="hero"><Card><h1>Research unificado: dados → eventos → validação → incubação</h1><p>Um fluxo simples. O sistema importa dados, cria features, descobre eventos/setups, testa robustez, compara contra aleatório e só depois coloca candidatos em incubação. EA-ready continua bloqueado até haver forward evidence.</p><div className="actions"><Button className="primary big" disabled={!!activeJob || busy} onClick={startFullPipeline}><Play size={16}/> Run Full Pipeline</Button><Button disabled={!!activeJob || busy} onClick={() => refresh()}><RefreshCw size={16}/> Refresh</Button></div><div className={`notice ${latestJob?.status === 'failed' ? 'danger' : latestJob?.status === 'completed' ? 'ok' : ''}`}>{latestJob?.error ? `Erro: ${latestJob.error}` : lastLog}</div></Card><ProgressPanel job={activeJob || latestJob} progress={progress}/></section>
      {view === 'pipeline' && <PipelineView health={health} healthSummary={healthSummary} outputs={outputs} selectedRun={selectedRun} setSelectedRun={setSelectedRun} activeJob={activeJob} runStep={runStep} currentRun={currentRun} eventLab={eventLab} validation={validation} walkforward={walkforward} stress={stress} mc={mc} sensitivity={sensitivity} portfolio={portfolio} permutation={permutation} incubation={incubation} latestJob={latestJob}/>} 
      {view === 'data' && <DataView rawFiles={rawFiles} healthSummary={healthSummary} catalog={catalog} busy={busy || !!activeJob} handleUpload={handleUpload} uploadState={uploadState} runStep={runStep}/>} 
      {view === 'results' && <ResultsView outputs={outputs} selectedRun={selectedRun} setSelectedRun={setSelectedRun} finalCandidates={finalCandidates} candidateRows={candidateRows} allRows={allRows} eventLab={eventLab} validation={validation} walkforward={walkforward} stress={stress} mc={mc} sensitivity={sensitivity} portfolio={portfolio} permutation={permutation} incubation={incubation}/>} 
    </main>
  </div>
}

function ProgressPanel({ job, progress }: { job?: Job, progress: number }) {
  const status = job?.status || 'idle'
  const steps = job?.steps || []
  return <div className="progressBox"><div className="progressTop"><div><h2>{job ? label(job.kind) : 'Pipeline status'}</h2><div className="statusLine"><span className={`pill ${status === 'completed' ? 'good' : status === 'failed' ? 'bad' : status === 'running' ? 'blue' : 'warn'}`}>{label(status)}</span><span>{job?.stage || 'À espera de execução'}</span></div></div><strong>{progress}%</strong></div><div className="progressBar"><div className="progressFill" style={{ width: `${progress}%` }}/></div>{steps.length ? <div className="steps">{steps.map((s: any) => <div key={s.id} className={`step ${s.status}`}>{s.label}</div>)}</div> : <div className="steps"><div className="step">Upload</div><div className="step">Event Lab</div><div className="step">Validate</div><div className="step">Permutation</div><div className="step">Incubation</div><div className="step">Results</div></div>}</div>
}

function PipelineView({ health, healthSummary, outputs, selectedRun, setSelectedRun, activeJob, runStep, currentRun, eventLab, validation, walkforward, stress, mc, sensitivity, portfolio, permutation, incubation, latestJob }: any) {
  return <section className="grid"><Metric name="Engine" value={health?.ok ? 'Online' : 'Offline'} tone={health?.ok ? 'good' : 'bad'} icon={<Activity/>}/><Metric name="Datasets bons" value={healthSummary.good || 0} tone="good" icon={<Database/>}/><Metric name="Eventos" value={eventLab?.events || 0} tone="warn" icon={<BarChart3/>}/><Metric name="Incubação" value={incubation?.tracked || 0} tone="good" icon={<CheckCircle2/>}/><Card className="span12"><h2>Run selecionado</h2><select value={selectedRun} onChange={e => setSelectedRun(e.target.value)}><option value="">Último run</option>{outputs.map((o: any) => <option key={o.name} value={o.name}>{o.name} — {o.candidate_count} candidatos / {o.all_count} testados</option>)}</select><div className="actions"><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Event Lab', () => api.runEventLab({ scan_name: currentRun }))}>Event Lab</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Validate', () => api.validate({ scan_name: currentRun }))}>Validate</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Walk-forward', () => api.runWalkforward({ scan_name: currentRun }))}>Walk-forward</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Stress', () => api.runExecutionStress({ scan_name: currentRun }))}>Stress</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Monte Carlo', () => api.runMonteCarlo({ scan_name: currentRun }))}>Monte Carlo</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Sensitivity', () => api.runSensitivity({ scan_name: currentRun }))}>Sensitivity</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Portfolio', () => api.runPortfolioRisk({ scan_name: currentRun }))}>Portfolio</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Permutation', () => api.runPermutationTest({ scan_name: currentRun }))}>Permutation</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Incubation', () => api.seedIncubation({ scan_name: currentRun }))}>Seed Incubation</Button></div></Card><StageSummary eventLab={eventLab} validation={validation} walkforward={walkforward} stress={stress} mc={mc} sensitivity={sensitivity} portfolio={portfolio} permutation={permutation} incubation={incubation}/><Card className="span12"><h2>Logs e erros</h2><pre className="logs">{latestJob?.logs?.join('\n') || 'Ainda sem logs. Faz upload e corre o pipeline.'}</pre></Card></section>
}

function StageSummary({ eventLab, validation, walkforward, stress, mc, sensitivity, portfolio, permutation, incubation }: any) { return <Card className="span12"><h2>Estado por stage</h2><div className="summaryGrid"><div><strong>{eventLab?.event_ready ?? 0}</strong><span>Event-ready</span></div><div><strong>{validation?.robust_candidates ?? 0}</strong><span>Robust pass</span></div><div><strong>{walkforward?.wf_pass ?? 0}</strong><span>Walk-forward pass</span></div><div><strong>{stress?.stress_pass ?? 0}</strong><span>Stress pass</span></div><div><strong>{mc?.mc_pass ?? 0}</strong><span>Monte Carlo pass</span></div><div><strong>{sensitivity?.sensitivity_pass ?? 0}</strong><span>Sensitivity pass</span></div><div><strong>{portfolio?.portfolio_pass ?? 0}</strong><span>Portfolio pass</span></div><div><strong>{permutation?.permutation_pass ?? 0}</strong><span>Permutation pass</span></div><div><strong>{incubation?.paper_incubation ?? 0}</strong><span>Paper incubation</span></div><div><strong>{incubation?.production ?? 0}</strong><span>Production-ready</span></div><div><strong>{portfolio?.portfolio_monthly_dd_R ?? '-'}</strong><span>Portfolio DD R</span></div><div><strong>{portfolio?.avg_pair_corr ?? '-'}</strong><span>Avg correlation</span></div></div></Card> }

function DataView({ rawFiles, healthSummary, catalog, busy, handleUpload, uploadState, runStep }: any) {
  const datasets = catalog?.data_health?.datasets || []
  return <section className="grid"><Card className="span8"><h2>Upload de dados MT5</h2><input className="file" type="file" multiple accept=".csv,.zip" disabled={busy} onChange={e => handleUpload(e.target.files)}/><p>{uploadState || 'Aceita CSV ou ZIP com CSV. Idealmente inclui colunas time, open, high, low, close e spread/spread_points.'}</p><div className="actions"><Button disabled={busy} onClick={() => runStep('Import Data', api.startImport)}>Import / Clean</Button><Button disabled={busy} onClick={() => runStep('Build Features', api.startFeatures)}>Build Features</Button></div></Card><Card className="span4"><h2>Saúde dos dados</h2><div className="summaryGrid"><div><strong>{healthSummary.good || 0}</strong><span>Good</span></div><div><strong>{healthSummary.usable || 0}</strong><span>Usable</span></div><div><strong>{healthSummary.weak || 0}</strong><span>Weak</span></div><div><strong>{rawFiles.length}</strong><span>Raw files</span></div></div></Card><Card className="span6"><h2>Ficheiros registados</h2><div className="rawList">{rawFiles.length ? rawFiles.slice(0,80).map((f: any) => <div className="rawItem" key={f.path || f}><strong>{f.path || f}</strong><span>{f.size ? `${Math.round(f.size/1024)} KB` : ''}</span></div>) : <div className="empty">Nenhum ficheiro encontrado em data/raw.</div>}</div></Card><Card className="span6"><h2>Datasets limpos / lidos</h2><MiniTable rows={datasets} columns={['symbol','tf','status','quality_score','rows','start','end','coverage_days','gap_count','notes']} tall/></Card></section>
}

function ResultsView({ outputs, selectedRun, setSelectedRun, finalCandidates, candidateRows, allRows, eventLab, portfolio, permutation, incubation }: any) {
  return <section className="grid"><Card className="span12"><h2>Resultados finais</h2><select value={selectedRun} onChange={e => setSelectedRun(e.target.value)}><option value="">Selecionar run</option>{outputs.map((o: any) => <option key={o.name} value={o.name}>{o.name}</option>)}</select><ResultCards rows={finalCandidates}/></Card><Card className="span12"><h2>Todos os candidatos</h2><MiniTable rows={candidateRows} columns={['setup_id','symbol','tf','concept','session','lookback','rr','sl_mult','pf','test_pf','expR','maxDD_R','avg_cost_R','verdict']} tall/></Card><Card className="span12"><h2>Research details</h2><div className="twoCols"><div><h3>Event Lab</h3><MiniTable rows={eventLab?.top || []} columns={['setup_id','event_status','events','tp_first_pct','mean_forward_R','mean_mfe_R','mean_mae_R','verdict']}/></div><div><h3>Permutation</h3><MiniTable rows={permutation?.top || []} columns={['setup_id','permutation_status','permutation_score','real_sumR','random_median_sumR','sumR_percentile','verdict']}/></div><div><h3>Portfolio</h3><MiniTable rows={portfolio?.top || []} columns={['setup_id','portfolio_status','portfolio_score','avg_abs_corr','standalone_monthly_dd_R','sumR','verdict']}/></div><div><h3>Incubation</h3><MiniTable rows={incubation?.top || []} columns={['setup_id','incubation_status','paper_days','paper_trades','paper_sumR','paper_maxDD_R','promotion_rule']}/></div></div></Card><Card className="span12"><h2>Todos os testes brutos</h2><MiniTable rows={allRows} columns={['setup_id','symbol','tf','concept','session','lookback','rr','sl_mult','status','pf','test_pf','expR','maxDD_R','score','verdict']} tall/></Card></section>
}

function ResultCards({ rows }: { rows: any[] }) {
  if (!rows?.length) return <div className="empty">Ainda não há edge final. Corre o pipeline completo ou vê os logs para perceber onde parou.</div>
  return <div className="resultList">{rows.slice(0, 15).map((r, i) => <div className="result" key={r.setup_id || i}><div><strong>{r.symbol} {r.tf} — {label(r.concept)}</strong><br/><small>{r.setup_id || `${r.session} / ${r.lookback} / RR ${r.rr}`}</small></div><span className={`pill ${String(r.incubation_status || r.permutation_status || r.portfolio_status || r.sensitivity_status || r.mc_status || r.stress_status || '').includes('pass') || String(r.incubation_status || '').includes('paper') ? 'good' : 'warn'}`}>{label(r.incubation_status || r.permutation_status || r.portfolio_status || r.sensitivity_status || r.mc_status || r.stress_status || r.wf_status || r.robustness_status || 'candidate')}</span><div className="metricsLine"><span>PF <b>{r.pf || r.base_pf || r.median_pf || '-'}</b></span><span>Score <b>{r.permutation_score || r.portfolio_score || r.sensitivity_score || r.mc_score || r.wf_score || r.robustness_score || '-'}</b></span><span>Real R <b>{r.real_sumR || r.paper_sumR || r.sumR || '-'}</b></span><span>DD R <b>{r.maxDD_R || r.standalone_monthly_dd_R || r.p95_dd_R || r.paper_maxDD_R || '-'}</b></span><span>{r.verdict || r.paper_notes || 'No verdict'}</span></div></div>)}</div>
}
