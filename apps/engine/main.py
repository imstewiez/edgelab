from __future__ import annotations

import shutil, threading, time, uuid, zipfile
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from quantlab_core import (
    STORE, RAW_DIR, OUTPUTS_DIR, ensure_store, import_raw_data, build_features,
    run_auto_discovery, run_scan_only, list_catalog, list_feature_catalog,
    list_outputs, read_edges_preview, read_report, read_edge_cards, read_data_health, clean_outputs
)
from robustness import read_validation, run_validation
from strategy_universe import get_strategy_universe

app = FastAPI(title='CoreEA EdgeLab v1 Engine', version='1.0.0-production-candidate')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

jobs: Dict[str, Dict[str, Any]] = {}
job_locks: Dict[str, str] = {}
jobs_lock = threading.Lock()

def now(): return time.strftime('%Y-%m-%d %H:%M:%S')

def create_or_reuse_job(kind: str, lock_key: str, payload: Optional[dict] = None):
    with jobs_lock:
        existing = job_locks.get(lock_key)
        if existing and existing in jobs and jobs[existing]['status'] in {'queued','running'}:
            jobs[existing]['logs'].append(f"[{time.strftime('%H:%M:%S')}] Duplicate click ignored. Existing job is already running.")
            return existing, True
        jid = str(uuid.uuid4())[:8]
        jobs[jid] = {'id': jid, 'kind': kind, 'lock_key': lock_key, 'status': 'queued', 'created_at': now(), 'updated_at': now(), 'payload': payload or {}, 'logs': [], 'result': None, 'error': None, 'reused': False}
        job_locks[lock_key] = jid
        return jid, False

def log_job(jid: str, msg: str):
    with jobs_lock:
        if jid in jobs:
            jobs[jid]['logs'].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            jobs[jid]['updated_at'] = now()

def update_job(jid: str, **kw):
    with jobs_lock:
        if jid in jobs:
            jobs[jid].update(kw); jobs[jid]['updated_at'] = now()

def run_job(jid: str, fn, *args, **kwargs):
    update_job(jid, status='running')
    lock_key = jobs.get(jid, {}).get('lock_key')
    try:
        res = fn(*args, logger=lambda m: log_job(jid, m), **kwargs)
        update_job(jid, status='completed', result=res)
    except Exception as e:
        update_job(jid, status='failed', error=str(e)); log_job(jid, f'ERROR: {e}')
    finally:
        with jobs_lock:
            if lock_key and job_locks.get(lock_key) == jid: job_locks.pop(lock_key, None)

def start_locked(kind: str, lock_key: str, fn, payload: Optional[dict] = None, *args, **kwargs):
    jid, reused = create_or_reuse_job(kind, lock_key, payload)
    if reused: return {'job_id': jid, 'reused': True, 'message': 'Job already running. Duplicate click ignored.'}
    threading.Thread(target=run_job, args=(jid, fn, *args), kwargs=kwargs, daemon=True).start()
    return {'job_id': jid, 'reused': False, 'message': f'{kind} job started.'}

@app.on_event('startup')
def startup(): ensure_store()

@app.get('/health')
def health():
    ensure_store()
    return {'ok': True, 'version': '1.0.0-production-candidate', 'store': str(STORE.resolve()), 'active_locks': job_locks}

@app.get('/api/strategy-universe')
def strategy_universe(): return get_strategy_universe()

@app.post('/api/upload')
async def upload(files: List[UploadFile] = File(...)):
    ensure_store(); saved = []
    for f in files:
        dest = RAW_DIR / f.filename
        with dest.open('wb') as out: shutil.copyfileobj(f.file, out)
        item = {'filename': f.filename, 'path': str(dest), 'size': dest.stat().st_size}
        if dest.suffix.lower() == '.zip':
            ex = RAW_DIR / dest.stem; ex.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dest, 'r') as z: z.extractall(ex)
            item['extracted_to'] = str(ex)
        saved.append(item)
    return {'saved': saved}

@app.get('/api/catalog')
def catalog():
    ensure_store()
    return {'raw_files': [str(p.relative_to(RAW_DIR)) for p in RAW_DIR.rglob('*') if p.is_file()], 'datasets': list_catalog(), 'features': list_feature_catalog(), 'data_health': read_data_health()}

@app.post('/api/jobs/import')
def job_import(): return start_locked('import', 'import', import_raw_data)

@app.post('/api/jobs/features')
def job_features(): return start_locked('features', 'features', build_features)

@app.post('/api/jobs/discover')
def job_discover(payload: Dict[str, Any] | None = None):
    payload = payload or {}; mode = payload.get('mode', 'auto'); symbols = payload.get('symbols', ''); tfs = payload.get('tfs', '')
    return start_locked('auto_discovery', f'discover:{mode}:{symbols}:{tfs}', run_auto_discovery, payload, mode=mode, symbols=symbols, tfs=tfs)

@app.post('/api/jobs/scan')
def job_scan(payload: Dict[str, Any]):
    mode = payload.get('mode','priority'); name = payload.get('name') or f"scan_{mode}_{time.strftime('%Y%m%d_%H%M%S')}"
    return start_locked('scan', f'scan:{mode}', run_scan_only, payload, name=name, mode=mode, symbols=payload.get('symbols',''), tfs=payload.get('tfs',''))

@app.post('/api/jobs/validate')
def job_validate(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get('scan_name') or None
    return start_locked('stage2_validation', f'validate:{scan_name or "latest"}', run_validation, payload, scan_name=scan_name)

@app.get('/api/jobs')
def get_jobs():
    with jobs_lock: return sorted(jobs.values(), key=lambda x: x['created_at'], reverse=True)

@app.delete('/api/jobs/completed')
def clear_completed_jobs():
    with jobs_lock:
        keep = {k:v for k,v in jobs.items() if v['status'] in {'queued','running'}}; removed = len(jobs)-len(keep); jobs.clear(); jobs.update(keep)
    return {'removed': removed, 'remaining': len(jobs)}

@app.get('/api/outputs')
def outputs(): return list_outputs()
@app.get('/api/edge-cards')
def edge_cards(): return read_edge_cards()
@app.get('/api/data-health')
def data_health(): return read_data_health()
@app.get('/api/validation')
def validation(scan_name: str | None = None): return read_validation(scan_name)
@app.get('/api/outputs/{scan_name}/edges')
def output_edges(scan_name: str, kind: str='candidate', limit: int=100): return read_edges_preview(scan_name, kind, limit)
@app.get('/api/outputs/{scan_name}/report')
def output_report(scan_name: str):
    md = read_report(scan_name)
    if md is None: return JSONResponse(status_code=404, content={'error':'report not found'})
    return {'scan_name': scan_name, 'markdown': md}
@app.delete('/api/outputs')
def api_clean_outputs(): return clean_outputs()
@app.get('/api/download/{scan_name}/{filename}')
def download(scan_name: str, filename: str):
    p = OUTPUTS_DIR / scan_name / filename
    if not p.exists(): return JSONResponse(status_code=404, content={'error':'file not found'})
    return FileResponse(str(p), filename=filename)
