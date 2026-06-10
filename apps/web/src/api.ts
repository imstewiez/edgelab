const API = 'http://127.0.0.1:8765'

async function req(path: string, init?: RequestInit) {
  const r = await fetch(`${API}${path}`, init)
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data?.error || `HTTP ${r.status}`)
  return data
}

export const api = {
  health: () => req('/health'),
  upload: async (files: FileList) => {
    const fd = new FormData()
    Array.from(files).forEach(f => fd.append('files', f))
    return req('/api/upload', { method: 'POST', body: fd })
  },
  catalog: () => req('/api/catalog'),
  strategyUniverse: () => req('/api/strategy-universe'),
  jobs: () => req('/api/jobs'),
  clearCompletedJobs: () => req('/api/jobs/completed', { method: 'DELETE' }),
  startImport: () => req('/api/jobs/import', { method: 'POST' }),
  startFeatures: () => req('/api/jobs/features', { method: 'POST' }),
  discover: (payload: any = {}) => req('/api/jobs/discover', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) }),
  scan: (payload: any = {}) => req('/api/jobs/scan', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) }),
  outputs: () => req('/api/outputs'),
  edgeCards: () => req('/api/edge-cards'),
  dataHealth: () => req('/api/data-health'),
  edges: (scan: string, kind = 'candidate') => req(`/api/outputs/${scan}/edges?kind=${kind}&limit=300`),
  report: (scan: string) => req(`/api/outputs/${scan}/report`),
  cleanOutputs: () => req('/api/outputs', { method: 'DELETE' }),
}
