import React, { useEffect, useMemo, useState } from 'react'
import { Activity, BarChart3, CheckCircle2, Database, FlaskConical, Play, RefreshCw } from 'lucide-react'
import { api } from './api'

type View = 'pipeline' | 'data' | 'results'
type ResearchMode = 'quick' | 'balanced' | 'deep'
type Job = { id: string; kind: string; status: string; percent?: number; stage?: string; steps?: any[]; created_at?: string; updated_at?: string; logs?: string[]; error?: string; result?: any; payload?: any }

const label = (v: string) => String(v || '').replaceAll('_', ' ').replace(/\b\w/g, s => s.toUpperCase())
const Card = ({ children, className = '' }: any) => <div className={`card ${className}`}>{children}</div>
const Button = ({ children, disabled, className = '', ...props }: any) => <button className={`btn ${className}`} disabled={disabled} {...props}>{children}</button>
const Metric = ({ name, value, tone = '', icon }: any) => <Card><div className={`metric ${tone}`}>{icon}<div><p>{name}</p><strong>{value}</strong></div></div></Card>

const MODE_COPY: Record<ResearchMode, { title: string; body: string; tone: string }> = {
  quick: { title: 'Quick sanity', body: 'Só prova que o sistema corre. Poucos datasets/conceitos. Não usar para tirar conclusões.', tone: 'warn' },
  balanced: { title: 'Balanced research', body: 'Modo recomendado: vários símbolos, timeframes e famílias de ineficiência sem explodir o tempo.', tone: 'good' },
  deep: { title: 'Deep scan', body: 'Mais lento. Usar depois de escolher símbolos/timeframes ou para confirmar uma shortlist.', tone: 'blue' },
}

const nf = (v: any, digits = 2) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  return n.toLocaleString('en-US', { maximumFractionDigits: digits })
}
const money = (v: number) => Number.isFinite(v) ? `€${Math.round(v).toLocaleString('en-US')}` : '-'
const pick = (...vals: any[]) => vals.find(v => v !== undefined && v !== null && v !== '' && Number.isFinite(Number(v)))
const txt = (...vals: any[]) => vals.find(v => v !== undefined && v !== null && String(v).trim() !== '') || ''

function MiniTable({ rows, columns, tall = false }: { rows: any[], columns: string[], tall?: boolean }) {
  if (!rows?.length) return <div className="empty">Ainda sem resultados nesta secção.</div>
  return <div className={`tableWrap ${tall ? 'tall' : ''}`}><table><thead><tr>{columns.map(c => <th key={c}>{label(c)}</th>)}</tr></thead><tbody>{rows.slice(0, 160).map((r, i) => <tr key={i}>{columns.map(c => <td key={c} title={String(r[c] ?? '')}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody></table></div>
}

function latestPipelineRun(jobs: Job[]) {
  return jobs.find(j => j.kind === 'full_pipeline' && j.status === 'completed' && j.result?.scan_name)?.result?.scan_name || ''
}

function latestPipelineMode(jobs: Job[]) {
  return jobs.find(j => j.kind === 'full_pipeline' && j.status === 'completed')?.result?.mode || jobs.find(j => j.kind === 'full_pipeline')?.payload?.mode || ''
}

function isQuickEvidence(rows: any[], jobMode: string) {
  if (String(jobMode).toLowerCase() === 'quick') return true
  return rows.some(r => String(r.verdict || '').toLowerCase().includes('quick automated'))
}

function buildSetupLookup(groups: any[][]) {
  const byId: Record<string, any> = {}
  for (const group of groups) {
    for (const r of group || []) {
      const id = String(r?.setup_id || '')
      if (!id) continue
      byId[id] = { ...(byId[id] || {}), ...r }
    }
  }
  return byId
}

function explainMetric(name: string) {
  const map: Record<string, string> = {
    PF: 'Profit Factor. Acima de 1.0 ganha mais do que perde; >1.25 é interessante; >1.5 já é forte, mas pode ser overfit.',
    Score: 'Pontuação interna 0-100 baseada em PF, OOS/test PF, estabilidade mensal, drawdown e loss streak.',
    RealR: 'Resultado em R. 1R = o risco por trade. Se arriscas 1% por trade, 10R ≈ +10% antes de lot sizing dinâmico.',
    DDR: 'Drawdown em R. 7R com risco 1% ≈ -7% na conta; com 0.5% ≈ -3.5%.',
  }
  return map[name] || ''
}

export function App() {
  const [view, setView] = useState<View>('pipeline')
  const [scanMode, setScanMode] = useState<ResearchMode>('balanced')
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
  const completedPipelineRun = latestPipelineRun(jobs)
  const currentMode = latestPipelineMode(jobs)
  const currentRun = selectedRun || completedPipelineRun || outputs[0]?.name || ''
  const quickRun = isQuickEvidence([...candidateRows, ...allRows], currentMode)
  const progress = Math.max(0, Math.min(100, Number(activeJob?.percent ?? (latestJob?.status === 'completed' ? 100 : 0))))
  const lastLog = activeJob?.logs?.slice(-1)[0] || latestJob?.logs?.slice(-1)[0] || notice
  const healthSummary = catalog?.data_health?.summary || {}
  const rawFiles = Array.isArray(catalog?.raw_files) ? catalog.raw_files : []

  async function refresh(runName = currentRun) {
    let nextJobs: Job[] = jobs
    try { setHealth(await api.health()) } catch {}
    try { setCatalog(await api.catalog()) } catch {}
    try { nextJobs = await api.jobs(); setJobs(nextJobs) } catch {}
    try {
      const outs = await api.outputs()
      setOutputs(outs)
      const preferred = latestPipelineRun(nextJobs)
      if (preferred) runName = preferred
      else if (!runName && outs?.[0]?.name) runName = outs[0].name
    } catch {}
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
  useEffect(() => { if (completedPipelineRun && selectedRun !== completedPipelineRun) setSelectedRun(completedPipelineRun) }, [completedPipelineRun, selectedRun])
  useEffect(() => { if (!selectedRun && !completedPipelineRun && outputs?.[0]?.name) setSelectedRun(outputs[0].name) }, [outputs, selectedRun, completedPipelineRun])

  async function startFullPipeline(mode = scanMode) {
    if (activeJob || busy) return
    setBusy(true); setNotice(`A iniciar pipeline completo em modo ${mode}...`)
    try { const r = await api.fullPipeline({ mode }); setNotice(r.message || 'Pipeline iniciado.'); setView('pipeline'); await refresh() }
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
      setNotice('Upload concluído. Agora corre Balanced Research para importar, limpar e testar.')
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
      <section className="hero"><Card><h1>Research unificado: dados → eventos → validação → incubação</h1><p>O objetivo não é aceitar o primeiro backtest bonito. O sistema procura padrões/ineficiências, testa robustez, compara contra aleatório e bloqueia EA-ready até haver forward evidence.</p><ResearchModeBox mode={scanMode} setMode={setScanMode} busy={busy || !!activeJob} startFullPipeline={startFullPipeline}/><div className="actions"><Button disabled={!!activeJob || busy} onClick={() => refresh()}><RefreshCw size={16}/> Refresh</Button></div><div className={`notice ${latestJob?.status === 'failed' ? 'danger' : latestJob?.status === 'completed' ? 'ok' : ''}`}>{latestJob?.error ? `Erro: ${latestJob.error}` : lastLog}</div></Card><ProgressPanel job={activeJob || latestJob} progress={progress}/></section>
      {quickRun && <div className="warningBox"><b>Esta run é Quick/Sanity.</b> Serve para testar o pipeline, não para concluir que só existe edge em XAUUSD/D1. Corre <b>Balanced Research</b> para uma análise minimamente representativa.</div>}
      {view === 'pipeline' && <PipelineView health={health} healthSummary={healthSummary} outputs={outputs} selectedRun={selectedRun} setSelectedRun={setSelectedRun} activeJob={activeJob} runStep={runStep} currentRun={currentRun} eventLab={eventLab} validation={validation} walkforward={walkforward} stress={stress} mc={mc} sensitivity={sensitivity} portfolio={portfolio} permutation={permutation} incubation={incubation} latestJob={latestJob}/>} 
      {view === 'data' && <DataView rawFiles={rawFiles} healthSummary={healthSummary} catalog={catalog} busy={busy || !!activeJob} handleUpload={handleUpload} uploadState={uploadState} runStep={runStep}/>} 
      {view === 'results' && <ResultsView outputs={outputs} selectedRun={selectedRun} setSelectedRun={setSelectedRun} currentRun={currentRun} finalCandidates={finalCandidates} candidateRows={candidateRows} allRows={allRows} quickRun={quickRun} eventLab={eventLab} validation={validation} walkforward={walkforward} stress={stress} mc={mc} sensitivity={sensitivity} portfolio={portfolio} permutation={permutation} incubation={incubation}/>} 
    </main>
  </div>
}

function ResearchModeBox({ mode, setMode, busy, startFullPipeline }: { mode: ResearchMode; setMode: (m: ResearchMode) => void; busy: boolean; startFullPipeline: (m?: ResearchMode) => void }) {
  return <div className="modePanel">
    {(Object.keys(MODE_COPY) as ResearchMode[]).map(m => <button key={m} className={`modeOption ${mode === m ? 'selected' : ''}`} disabled={busy} onClick={() => setMode(m)}><span className={`pill ${MODE_COPY[m].tone}`}>{MODE_COPY[m].title}</span><small>{MODE_COPY[m].body}</small></button>)}
    <Button className="primary big" disabled={busy} onClick={() => startFullPipeline(mode)}><Play size={16}/> Run {MODE_COPY[mode].title}</Button>
  </div>
}

function ProgressPanel({ job, progress }: { job?: Job, progress: number }) {
  const status = job?.status || 'idle'
  const steps = job?.steps || []
  return <div className="progressBox"><div className="progressTop"><div><h2>{job ? label(job.kind) : 'Pipeline status'}</h2><div className="statusLine"><span className={`pill ${status === 'completed' ? 'good' : status === 'failed' ? 'bad' : status === 'running' ? 'blue' : 'warn'}`}>{label(status)}</span><span>{job?.stage || 'À espera de execução'}</span></div></div><strong>{progress}%</strong></div><div className="progressBar"><div className="progressFill" style={{ width: `${progress}%` }}/></div>{steps.length ? <div className="steps">{steps.map((s: any) => <div key={s.id} className={`step ${s.status}`}>{s.label}</div>)}</div> : <div className="steps"><div className="step">Upload</div><div className="step">Event Lab</div><div className="step">Validate</div><div className="step">Permutation</div><div className="step">Incubation</div><div className="step">Results</div></div>}</div>
}

function PipelineView({ health, healthSummary, outputs, selectedRun, setSelectedRun, activeJob, runStep, currentRun, eventLab, validation, walkforward, stress, mc, sensitivity, portfolio, permutation, incubation, latestJob }: any) {
  return <section className="grid"><Metric name="Engine" value={health?.ok ? 'Online' : 'Offline'} tone={health?.ok ? 'good' : 'bad'} icon={<Activity/>}/><Metric name="Datasets bons" value={healthSummary.good || 0} tone="good" icon={<Database/>}/><Metric name="Eventos" value={eventLab?.events || 0} tone="warn" icon={<BarChart3/>}/><Metric name="Incubação" value={incubation?.tracked || 0} tone="good" icon={<CheckCircle2/>}/><Card className="span12"><h2>Run selecionado</h2><p className="muted">Run atual: <b>{currentRun || 'nenhuma'}</b></p><select value={selectedRun} onChange={e => setSelectedRun(e.target.value)}><option value="">Último pipeline completo</option>{outputs.map((o: any) => <option key={o.name} value={o.name}>{o.name} — {o.candidate_count} candidatos / {o.all_count} testados</option>)}</select><div className="actions"><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Event Lab', () => api.runEventLab({ scan_name: currentRun }))}>Event Lab</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Validate', () => api.validate({ scan_name: currentRun }))}>Validate</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Walk-forward', () => api.runWalkforward({ scan_name: currentRun }))}>Walk-forward</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Stress', () => api.runExecutionStress({ scan_name: currentRun }))}>Stress</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Monte Carlo', () => api.runMonteCarlo({ scan_name: currentRun }))}>Monte Carlo</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Sensitivity', () => api.runSensitivity({ scan_name: currentRun }))}>Sensitivity</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Portfolio', () => api.runPortfolioRisk({ scan_name: currentRun }))}>Portfolio</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Permutation', () => api.runPermutationTest({ scan_name: currentRun }))}>Permutation</Button><Button disabled={!!activeJob || !currentRun} onClick={() => runStep('Incubation', () => api.seedIncubation({ scan_name: currentRun }))}>Seed Incubation</Button></div></Card><StageSummary eventLab={eventLab} validation={validation} walkforward={walkforward} stress={stress} mc={mc} sensitivity={sensitivity} portfolio={portfolio} permutation={permutation} incubation={incubation}/><Card className="span12"><h2>Logs e erros</h2><pre className="logs">{latestJob?.logs?.join('\n') || 'Ainda sem logs. Faz upload e corre o pipeline.'}</pre></Card></section>
}

function StageSummary({ eventLab, validation, walkforward, stress, mc, sensitivity, portfolio, permutation, incubation }: any) { return <Card className="span12"><h2>Estado por stage</h2><div className="summaryGrid"><div><strong>{eventLab?.event_ready ?? 0}</strong><span>Event-ready</span></div><div><strong>{validation?.robust_candidates ?? 0}</strong><span>Robust pass</span></div><div><strong>{walkforward?.wf_pass ?? 0}</strong><span>Walk-forward pass</span></div><div><strong>{stress?.stress_pass ?? 0}</strong><span>Stress pass</span></div><div><strong>{mc?.mc_pass ?? 0}</strong><span>Monte Carlo pass</span></div><div><strong>{sensitivity?.sensitivity_pass ?? 0}</strong><span>Sensitivity pass</span></div><div><strong>{portfolio?.portfolio_pass ?? 0}</strong><span>Portfolio pass</span></div><div><strong>{permutation?.permutation_pass ?? 0}</strong><span>Permutation pass</span></div><div><strong>{incubation?.paper_incubation ?? 0}</strong><span>Paper incubation</span></div><div><strong>{incubation?.production ?? 0}</strong><span>Production-ready</span></div><div><strong>{portfolio?.portfolio_monthly_dd_R ?? '-'}</strong><span>Portfolio DD R</span></div><div><strong>{portfolio?.avg_pair_corr ?? '-'}</strong><span>Avg correlation</span></div></div></Card> }

function DataView({ rawFiles, healthSummary, catalog, busy, handleUpload, uploadState, runStep }: any) {
  const datasets = catalog?.data_health?.datasets || []
  return <section className="grid"><Card className="span8"><h2>Upload de dados MT5</h2><input className="file" type="file" multiple accept=".csv,.zip" disabled={busy} onChange={e => handleUpload(e.target.files)}/><p>{uploadState || 'Aceita CSV ou ZIP com CSV. Idealmente inclui colunas time, open, high, low, close e spread/spread_points.'}</p><div className="actions"><Button disabled={busy} onClick={() => runStep('Import Data', api.startImport)}>Import / Clean</Button><Button disabled={busy} onClick={() => runStep('Build Features', api.startFeatures)}>Build Features</Button></div></Card><Card className="span4"><h2>Saúde dos dados</h2><div className="summaryGrid"><div><strong>{healthSummary.good || 0}</strong><span>Good</span></div><div><strong>{healthSummary.usable || 0}</strong><span>Usable</span></div><div><strong>{healthSummary.weak || 0}</strong><span>Weak</span></div><div><strong>{rawFiles.length}</strong><span>Raw files</span></div></div></Card><Card className="span6"><h2>Ficheiros registados</h2><div className="rawList">{rawFiles.length ? rawFiles.slice(0,80).map((f: any) => <div className="rawItem" key={f.path || f}><strong>{f.path || f}</strong><span>{f.size ? `${Math.round(f.size/1024)} KB` : ''}</span></div>) : <div className="empty">Nenhum ficheiro encontrado em data/raw.</div>}</div></Card><Card className="span6"><h2>Datasets limpos / lidos</h2><MiniTable rows={datasets} columns={['symbol','tf','status','quality_score','rows','start','end','coverage_days','gap_count','notes']} tall/></Card></section>
}

function ResultsView({ outputs, selectedRun, setSelectedRun, currentRun, finalCandidates, candidateRows, allRows, quickRun, eventLab, validation, walkforward, stress, mc, sensitivity, portfolio, permutation, incubation }: any) {
  const lookup = buildSetupLookup([allRows, candidateRows, validation?.top || [], walkforward?.top || [], stress?.top || [], mc?.top || [], sensitivity?.top || [], portfolio?.top || [], permutation?.top || []])
  return <section className="grid"><Card className="span12"><h2>Shortlist da run</h2><p className="muted">Run analisada: <b>{currentRun || selectedRun || 'nenhuma'}</b>. Isto é research shortlist, não EA-ready. Para ficar EA-ready precisa de incubação/paper-forward.</p><div className="explainer"><b>Como ler isto:</b> PF = Profit Factor; R = unidade de risco por trade; DD R = drawdown em R. Exemplo: com conta de €10k e risco de 1% por trade, 1R ≈ €100.</div>{quickRun && <div className="warningInline"><b>Run Quick:</b> estes resultados são demasiado estreitos para avaliar mercado. Corre Balanced Research antes de julgar a estratégia.</div>}<select value={selectedRun} onChange={e => setSelectedRun(e.target.value)}><option value="">Último pipeline completo</option>{outputs.map((o: any) => <option key={o.name} value={o.name}>{o.name} — {o.candidate_count} candidatos / {o.all_count} testados</option>)}</select><ResultCards rows={finalCandidates} lookup={lookup}/></Card><StageSummary eventLab={eventLab} validation={validation} walkforward={walkforward} stress={stress} mc={mc} sensitivity={sensitivity} portfolio={portfolio} permutation={permutation} incubation={incubation}/><Card className="span12"><h2>Candidatos descobertos</h2><MiniTable rows={candidateRows} columns={['setup_id','symbol','tf','concept','session','lookback','rr','sl_mult','pf','test_pf','expR','maxDD_R','score','avg_cost_R','verdict']} tall/></Card><Card className="span12"><h2>Research details</h2><div className="twoCols"><div><h3>Event Lab</h3><MiniTable rows={eventLab?.top || []} columns={['setup_id','event_status','events','tp_first_pct','mean_forward_R','mean_mfe_R','mean_mae_R','verdict']}/></div><div><h3>Validation</h3><MiniTable rows={validation?.top || []} columns={['setup_id','robustness_status','robustness_score','pf','test_pf','expR','maxDD_R','verdict']}/></div><div><h3>Walk-forward</h3><MiniTable rows={walkforward?.top || []} columns={['setup_id','wf_status','wf_score','wf_pass_rate','wf_median_pf','wf_min_pf','wf_verdict']}/></div><div><h3>Stress</h3><MiniTable rows={stress?.top || []} columns={['setup_id','stress_status','stress_pass_rate','worst_test_pf','worst_maxDD_R','verdict']}/></div><div><h3>Monte Carlo</h3><MiniTable rows={mc?.top || []} columns={['setup_id','mc_status','mc_score','profit_probability','p05_totalR','p95_dd_R','ruin_probability','verdict']}/></div><div><h3>Sensitivity</h3><MiniTable rows={sensitivity?.top || []} columns={['setup_id','sensitivity_status','sensitivity_score','pass_rate','median_pf','min_pf','verdict']}/></div><div><h3>Portfolio</h3><MiniTable rows={portfolio?.top || []} columns={['setup_id','portfolio_status','portfolio_score','avg_abs_corr','standalone_monthly_dd_R','sumR','verdict']}/></div><div><h3>Permutation</h3><MiniTable rows={permutation?.top || []} columns={['setup_id','permutation_status','permutation_score','real_sumR','random_median_sumR','sumR_percentile','verdict']}/></div><div><h3>Incubation</h3><MiniTable rows={incubation?.top || []} columns={['setup_id','incubation_status','paper_days','paper_trades','paper_sumR','paper_maxDD_R','promotion_rule']}/></div></div></Card><Card className="span12"><h2>Todos os testes brutos</h2><MiniTable rows={allRows} columns={['setup_id','symbol','tf','concept','session','lookback','rr','sl_mult','status','pf','test_pf','expR','maxDD_R','score','verdict']} tall/></Card></section>
}

function ResultCards({ rows, lookup = {} }: { rows: any[], lookup?: Record<string, any> }) {
  if (!rows?.length) return <div className="empty">Ainda não há shortlist nesta run. Vê os logs ou corre o pipeline completo.</div>
  return <div className="resultList">{rows.slice(0, 15).map((raw, i) => {
    const id = String(raw.setup_id || '')
    const r = { ...(lookup[id] || {}), ...raw }
    const pf = pick(r.pf, r.base_pf, r.median_pf, r.real_pf)
    const score = pick(r.permutation_score, r.portfolio_score, r.sensitivity_score, r.mc_score, r.wf_score, r.robustness_score, r.score)
    const realR = pick(r.real_sumR, r.paper_sumR, r.sumR, r.median_totalR)
    const ddR = pick(r.maxDD_R, r.standalone_monthly_dd_R, r.p95_dd_R, r.paper_maxDD_R, r.wf_maxDD_R)
    const risk05Profit = Number(realR) * 50
    const risk1Profit = Number(realR) * 100
    const risk05DD = Number(ddR) * 50
    const risk1DD = Number(ddR) * 100
    const status = txt(r.incubation_status, r.permutation_status, r.portfolio_status, r.sensitivity_status, r.mc_status, r.stress_status, r.wf_status, r.robustness_status, 'candidate')
    const verdict = txt(r.verdict, r.paper_notes, r.wf_verdict, r.promotion_rule, 'Sem nota técnica disponível.')
    return <div className="result readable" key={id || i}>
      <div><strong>{r.symbol} {r.tf} — {label(r.concept)}</strong><br/><small>{id || `${r.session} / ${r.lookback} / RR ${r.rr}`}</small></div>
      <span className={`pill ${String(status).includes('pass') || String(status).includes('paper') ? 'good' : 'warn'}`}>{label(status)}</span>
      <div className="metricGrid">
        <div title={explainMetric('PF')}><b>{nf(pf)}</b><span>PF</span></div>
        <div title={explainMetric('Score')}><b>{nf(score, 0)}</b><span>Score</span></div>
        <div title={explainMetric('RealR')}><b>{nf(realR)}R</b><span>Resultado</span></div>
        <div title={explainMetric('DDR')}><b>{nf(ddR)}R</b><span>Max DD</span></div>
        <div><b>{nf(r.test_pf)}</b><span>Test PF/OOS</span></div>
        <div><b>{nf(r.positive_month_pct ? Number(r.positive_month_pct) * 100 : '', 0)}%</b><span>Meses +</span></div>
      </div>
      <div className="plainNote"><b>Leitura:</b> {verdict}</div>
      <div className="riskExample"><b>Exemplo conta €10k:</b> com 0.5% risco/trade → resultado ≈ {money(risk05Profit)}, DD ≈ {money(risk05DD)}. Com 1% risco/trade → resultado ≈ {money(risk1Profit)}, DD ≈ {money(risk1DD)}. Isto é backtest/research, não promessa de lucro.</div>
    </div>
  })}</div>
}
