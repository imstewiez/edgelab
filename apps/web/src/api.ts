const API = 'http://127.0.0.1:8765'

async function req(path: string, init?: RequestInit) {
  const r = await fetch(`${API}${path}`, init)
  const data = await r.json().catch(() => ({}))
  if (!r.ok && r.status !== 207) {
    const details = data?.message || data?.error || (Array.isArray(data?.errors) ? data.errors.map((e: any) => e.error).join(', ') : '')
    throw new Error(details || `HTTP ${r.status}`)
  }
  return data
}

const jsonPost = (path: string, payload: any = {}) => req(path, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) })
const scanQS = (scan?: string) => scan ? `?scan_name=${encodeURIComponent(scan)}` : ''

export const api = {
  health: () => req('/health'),
  upload: async (files: FileList) => {
    const fd = new FormData()
    Array.from(files).forEach(f => fd.append('files', f))
    return req('/api/upload', { method: 'POST', body: fd })
  },
  catalog: () => req('/api/catalog'),
  strategyUniverse: () => req('/api/strategy-universe'),
  eventLab: (scan?: string) => req(`/api/event-lab${scanQS(scan)}`),
  runEventLab: (payload: any = {}) => jsonPost('/api/jobs/event-lab', payload),
  validation: (scan?: string) => req(`/api/validation${scanQS(scan)}`),
  validate: (payload: any = {}) => jsonPost('/api/jobs/validate', payload),
  walkforward: (scan?: string) => req(`/api/walkforward${scanQS(scan)}`),
  runWalkforward: (payload: any = {}) => jsonPost('/api/jobs/walkforward', payload),
  executionStress: (scan?: string) => req(`/api/execution-stress${scanQS(scan)}`),
  runExecutionStress: (payload: any = {}) => jsonPost('/api/jobs/execution-stress', payload),
  monteCarlo: (scan?: string) => req(`/api/monte-carlo${scanQS(scan)}`),
  runMonteCarlo: (payload: any = {}) => jsonPost('/api/jobs/monte-carlo', payload),
  sensitivity: (scan?: string) => req(`/api/sensitivity${scanQS(scan)}`),
  runSensitivity: (payload: any = {}) => jsonPost('/api/jobs/sensitivity', payload),
  portfolioRisk: (scan?: string) => req(`/api/portfolio-risk${scanQS(scan)}`),
  runPortfolioRisk: (payload: any = {}) => jsonPost('/api/jobs/portfolio-risk', payload),
  permutationTest: (scan?: string) => req(`/api/permutation-test${scanQS(scan)}`),
  runPermutationTest: (payload: any = {}) => jsonPost('/api/jobs/permutation-test', payload),
  incubation: (scan?: string) => req(`/api/incubation${scanQS(scan)}`),
  seedIncubation: (payload: any = {}) => jsonPost('/api/jobs/seed-incubation', payload),
  exportEA: (payload: any = {}) => jsonPost('/api/ea/export', payload),
  jobs: () => req('/api/jobs'),
  clearCompletedJobs: () => req('/api/jobs/completed', { method: 'DELETE' }),
  startImport: () => req('/api/jobs/import', { method: 'POST' }),
  startFeatures: () => req('/api/jobs/features', { method: 'POST' }),
  discover: (payload: any = {}) => jsonPost('/api/jobs/discover', payload),
  fullPipeline: (payload: any = {}) => jsonPost('/api/jobs/full-pipeline', payload),
  scan: (payload: any = {}) => jsonPost('/api/jobs/scan', payload),
  outputs: () => req('/api/outputs'),
  edgeCards: () => req('/api/edge-cards'),
  dataHealth: () => req('/api/data-health'),
  edges: (scan: string, kind = 'candidate') => req(`/api/outputs/${encodeURIComponent(scan)}/edges?kind=${encodeURIComponent(kind)}&limit=300`),
  report: (scan: string) => req(`/api/outputs/${encodeURIComponent(scan)}/report`),
  cleanOutputs: () => req('/api/outputs', { method: 'DELETE' }),
}
