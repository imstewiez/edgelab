const API = 'http://127.0.0.1:8765'

export async function getHealth() {
  const r = await fetch(`${API}/health`)
  return r.json()
}

export async function uploadFiles(files: FileList) {
  const fd = new FormData()
  Array.from(files).forEach(f => fd.append('files', f))
  const r = await fetch(`${API}/api/upload`, { method: 'POST', body: fd })
  return r.json()
}

export async function getCatalog() {
  const r = await fetch(`${API}/api/catalog`)
  return r.json()
}

export async function startJob(kind: 'import' | 'features') {
  const r = await fetch(`${API}/api/jobs/${kind}`, { method: 'POST' })
  return r.json()
}

export async function startScan(payload: any) {
  const r = await fetch(`${API}/api/jobs/scan`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  })
  return r.json()
}

export async function getJobs() {
  const r = await fetch(`${API}/api/jobs`)
  return r.json()
}

export async function getOutputs() {
  const r = await fetch(`${API}/api/outputs`)
  return r.json()
}

export async function getEdges(scan: string, kind = 'candidate') {
  const r = await fetch(`${API}/api/outputs/${scan}/edges?kind=${kind}&limit=200`)
  return r.json()
}

export async function getReport(scan: string) {
  const r = await fetch(`${API}/api/outputs/${scan}/report`)
  return r.json()
}
