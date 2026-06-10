from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from quantlab_core import (
    STORE,
    RAW_DIR,
    OUTPUTS_DIR,
    ensure_store,
    import_raw_data,
    build_features,
    run_scan,
    list_catalog,
    list_feature_catalog,
    list_outputs,
    read_edges_preview,
)

app = FastAPI(title="CoreEA EdgeLab Engine", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()


def create_job(kind: str, payload: Optional[dict] = None) -> str:
    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "payload": payload or {},
            "logs": [],
            "result": None,
            "error": None,
        }
    return job_id


def log_job(job_id: str, message: str):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["logs"].append(f"[{time.strftime('%H:%M:%S')}] {message}")
            jobs[job_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


def update_job(job_id: str, **kwargs):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)
            jobs[job_id]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


def run_job(job_id: str, fn, *args, **kwargs):
    update_job(job_id, status="running")
    try:
        result = fn(*args, logger=lambda m: log_job(job_id, m), **kwargs)
        update_job(job_id, status="completed", result=result)
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))
        log_job(job_id, f"ERROR: {e}")


@app.on_event("startup")
def startup():
    ensure_store()


@app.get("/health")
def health():
    return {
        "ok": True,
        "store": str(STORE.resolve()),
        "raw_dir": str(RAW_DIR.resolve()),
        "outputs_dir": str(OUTPUTS_DIR.resolve()),
    }


@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...)):
    ensure_store()
    saved = []
    for f in files:
        dest = RAW_DIR / f.filename
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append({"filename": f.filename, "path": str(dest), "size": dest.stat().st_size})

        if dest.suffix.lower() == ".zip":
            extract_dir = RAW_DIR / dest.stem
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(dest, "r") as z:
                z.extractall(extract_dir)
            saved[-1]["extracted_to"] = str(extract_dir)

    return {"saved": saved}


@app.get("/api/catalog")
def catalog():
    return {
        "raw_files": [str(p.relative_to(RAW_DIR)) for p in RAW_DIR.rglob("*") if p.is_file()],
        "datasets": list_catalog(),
        "features": list_feature_catalog(),
    }


@app.post("/api/jobs/import")
def job_import():
    job_id = create_job("import")
    threading.Thread(target=run_job, args=(job_id, import_raw_data), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/jobs/features")
def job_features():
    job_id = create_job("features")
    threading.Thread(target=run_job, args=(job_id, build_features), daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/jobs/scan")
def job_scan(payload: Dict[str, Any]):
    name = payload.get("name") or f"scan_{time.strftime('%Y%m%d_%H%M%S')}"
    mode = payload.get("mode", "priority")
    symbols = payload.get("symbols") or ""
    tfs = payload.get("tfs") or ""
    min_trades = int(payload.get("min_trades", 40))
    min_pf = float(payload.get("min_pf", 1.22))
    min_test_pf = float(payload.get("min_test_pf", 1.08))

    job_id = create_job("scan", payload)
    threading.Thread(
        target=run_job,
        args=(job_id, run_scan),
        kwargs={
            "name": name,
            "mode": mode,
            "symbols": symbols,
            "tfs": tfs,
            "min_trades": min_trades,
            "min_pf": min_pf,
            "min_test_pf": min_test_pf,
        },
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs")
def get_jobs():
    with jobs_lock:
        return list(jobs.values())


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with jobs_lock:
        return jobs.get(job_id) or JSONResponse(status_code=404, content={"error": "job not found"})


@app.get("/api/outputs")
def outputs():
    return list_outputs()


@app.get("/api/outputs/{scan_name}/edges")
def output_edges(scan_name: str, kind: str = "candidate", limit: int = 100):
    return read_edges_preview(scan_name, kind=kind, limit=limit)


@app.get("/api/outputs/{scan_name}/report")
def output_report(scan_name: str):
    p = OUTPUTS_DIR / scan_name / "QUANTLAB_REPORT.md"
    if not p.exists():
        return JSONResponse(status_code=404, content={"error": "report not found"})
    return {"scan_name": scan_name, "markdown": p.read_text(encoding="utf-8", errors="ignore")}


@app.get("/api/download/{scan_name}/{filename}")
def download(scan_name: str, filename: str):
    p = OUTPUTS_DIR / scan_name / filename
    if not p.exists():
        return JSONResponse(status_code=404, content={"error": "file not found"})
    return FileResponse(str(p), filename=filename)
