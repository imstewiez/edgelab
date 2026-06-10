import React, { useEffect, useMemo, useState } from 'react'
import {
  Activity, Database, Upload, FlaskConical, Play, FileText,
  ShieldCheck, Server, BarChart3, Layers3
} from 'lucide-react'
import {
  getCatalog, getEdges, getHealth, getJobs, getOutputs,
  getReport, startJob, startScan, uploadFiles
} from './api'

type Tab = 'overview' | 'upload' | 'data' | 'research' | 'results' | 'architecture'

function Card({children, className=''}: any) {
  return <div className={`card ${className}`}>{children}</div>
}

function Stat({label, value, icon}: any) {
  return <Card><div className="stat">{icon}<div><p>{label}</p><strong>{value}</strong></div></div></Card>
}

function Table({rows}: {rows: any[]}) {
  const cols = rows?.length ? Object.keys(rows[0]) : []
  return <div className="tableWrap">
    <table>
      <thead><tr>{cols.map(c => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>
        {rows?.slice(0, 200).map((r, i) => (
          <tr key={i}>{cols.map(c => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>
        ))}
      </tbody>
    </table>
  </div>
}

export function App() {
  const [tab, setTab] = useState<Tab>('overview')
  const [health, setHealth] = useState<any>(null)
  const [catalog, setCatalog] = useState<any>({raw_files: [], datasets: [], features: []})
  const [jobs, setJobs] = useState<any[]>([])
  const [outputs, setOutputs] = useState<any[]>([])
  const [selectedOutput, setSelectedOutput] = useState('')
  const [edges, setEdges] = useState<any>({rows: [], columns: []})
  const [report, setReport] = useState('')
  const [uploadState, setUploadState] = useState('')
  const [scanMode, setScanMode] = useState('priority')

  async function refreshAll() {
    try { setHealth(await getHealth()) } catch {}
    try { setCatalog(await getCatalog()) } catch {}
    try { setJobs(await getJobs()) } catch {}
    try {
      const o = await getOutputs()
      setOutputs(o)
      if (!selectedOutput && o?.length) setSelectedOutput(o[0].name)
    } catch {}
  }

  useEffect(() => {
    refreshAll()
    const t = setInterval(refreshAll, 2500)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (!selectedOutput) return
    getEdges(selectedOutput, 'candidate').then(setEdges).catch(() => {})
    getReport(selectedOutput).then(r => setReport(r.markdown || '')).catch(() => setReport(''))
  }, [selectedOutput])

  const latestJob = jobs?.[jobs.length - 1]

  return <div className="app">
    <aside className="sidebar">
      <div className="brand">
        <div className="logo"><FlaskConical size={24}/></div>
        <div>
          <strong>CoreEA EdgeLab</strong>
          <span>Local Quant Research</span>
        </div>
      </div>

      {[
        ['overview', Activity, 'Overview'],
        ['upload', Upload, 'Upload'],
        ['data', Database, 'Data Library'],
        ['research', Play, 'Research Lab'],
        ['results', BarChart3, 'Results'],
        ['architecture', Layers3, 'Architecture'],
      ].map(([id, Icon, label]: any) => (
        <button key={id} className={tab === id ? 'nav active' : 'nav'} onClick={() => setTab(id)}>
          <Icon size={18}/>{label}
        </button>
      ))}

      <div className="sideFooter">
        <ShieldCheck size={16}/>
        <span>Standalone project. No gangsbot production repo.</span>
      </div>
    </aside>

    <main className="main">
      <header className="topbar">
        <div>
          <h1>{tabTitle(tab)}</h1>
          <p>Local-first market-data research platform. No paid DB required.</p>
        </div>
        <button className="btn" onClick={refreshAll}>Refresh</button>
      </header>

      {tab === 'overview' && <section className="grid">
        <Stat label="Engine" value={health?.ok ? 'Online' : 'Offline'} icon={<Server/>}/>
        <Stat label="Raw files" value={catalog.raw_files?.length || 0} icon={<Upload/>}/>
        <Stat label="Datasets" value={catalog.datasets?.length || 0} icon={<Database/>}/>
        <Stat label="Feature sets" value={catalog.features?.length || 0} icon={<FlaskConical/>}/>

        <Card className="wide">
          <h2>Project Guardrails</h2>
          <div className="notice good">
            <strong>Separate from gangsbot-web-44.</strong>
            <span>This dashboard is built as a standalone repo-ready project. Market data stays local under <code>data/</code> and is ignored by Git.</span>
          </div>
          <div className="notice">
            <strong>Confidence model.</strong>
            <span>Strategies are ranked by PF, out-of-sample performance, trade count, drawdown, loss streak and stability.</span>
          </div>
        </Card>

        <Card className="wide">
          <h2>Latest Jobs</h2>
          <Table rows={jobs.slice(-8).reverse()} />
        </Card>
      </section>}

      {tab === 'upload' && <section className="grid">
        <Card className="wide">
          <h2>Upload Market Data</h2>
          <p className="muted">Upload MT5 CSV or ZIP exports. They are saved locally in the engine's <code>data/raw</code> folder.</p>
          <input className="file" type="file" multiple onChange={async e => {
            if (!e.target.files) return
            setUploadState('Uploading...')
            const res = await uploadFiles(e.target.files)
            setUploadState(`Uploaded ${res.saved?.length || 0} file(s)`)
            refreshAll()
          }}/>
          <p>{uploadState}</p>
        </Card>

        <Card>
          <h2>Next steps</h2>
          <button className="btn primary" onClick={async () => { await startJob('import'); refreshAll() }}>Run Import Data</button>
          <button className="btn primary" onClick={async () => { await startJob('features'); refreshAll() }}>Build Features</button>
        </Card>
      </section>}

      {tab === 'data' && <section className="grid">
        <Card className="wide">
          <h2>Raw Files</h2>
          <Table rows={(catalog.raw_files || []).map((f: string) => ({file: f}))} />
        </Card>
        <Card className="wide">
          <h2>Imported Datasets</h2>
          <Table rows={catalog.datasets || []} />
        </Card>
        <Card className="wide">
          <h2>Feature Cache</h2>
          <Table rows={catalog.features || []} />
        </Card>
      </section>}

      {tab === 'research' && <section className="grid">
        <Card>
          <h2>Run Research Scan</h2>
          <label>Mode</label>
          <select value={scanMode} onChange={e => setScanMode(e.target.value)}>
            <option value="priority">Priority symbols</option>
            <option value="htf">HTF H1/H4/D1</option>
            <option value="intraday">Intraday M5/M15/M30</option>
            <option value="all">All cached datasets</option>
          </select>
          <button className="btn primary" onClick={async () => {
            const name = `scan_${scanMode}_${new Date().toISOString().slice(0,16).replace(/[-:T]/g,'')}`
            await startScan({name, mode: scanMode})
            refreshAll()
          }}>Start Scan</button>
        </Card>

        <Card className="wide">
          <h2>Jobs</h2>
          <Table rows={jobs.slice().reverse()} />
        </Card>

        {latestJob && <Card className="wide">
          <h2>Latest Job Logs</h2>
          <pre className="logs">{(latestJob.logs || []).join('\n')}</pre>
        </Card>}
      </section>}

      {tab === 'results' && <section className="grid">
        <Card>
          <h2>Scans</h2>
          <select value={selectedOutput} onChange={e => setSelectedOutput(e.target.value)}>
            <option value="">Select scan</option>
            {outputs.map(o => <option key={o.name} value={o.name}>{o.name} — {o.candidate_count} candidates</option>)}
          </select>
        </Card>

        <Card className="wide">
          <h2>Candidate Edges</h2>
          <Table rows={edges.rows || []} />
        </Card>

        <Card className="wide">
          <h2>Report</h2>
          <pre className="report">{report}</pre>
        </Card>
      </section>}

      {tab === 'architecture' && <section className="grid">
        <Card className="wide">
          <h2>Local-first Architecture</h2>
          <div className="flow">
            <div>CSV / ZIP Upload</div><span>→</span>
            <div>Local raw folder</div><span>→</span>
            <div>Data cache</div><span>→</span>
            <div>Feature cache</div><span>→</span>
            <div>Research outputs</div>
          </div>
        </Card>
        <Card className="wide">
          <h2>Depth of Market / Order Book Plan</h2>
          <p className="muted">Historical DOM normally cannot be reconstructed from candle data. EdgeLab is prepared for DOM imports later, but we need a live MT5 recorder to collect it going forward.</p>
          <ul>
            <li>DOM snapshots: time, symbol, side, price, volume, level</li>
            <li>Derived features: imbalance, liquidity change, depth slope, spread pressure</li>
            <li>Execution history: fills, slippage, spread at entry/exit</li>
          </ul>
        </Card>
      </section>}
    </main>
  </div>
}

function tabTitle(tab: Tab) {
  return {
    overview: 'Overview',
    upload: 'Upload & Import',
    data: 'Data Library',
    research: 'Research Lab',
    results: 'Strategy Results',
    architecture: 'Architecture'
  }[tab]
}
