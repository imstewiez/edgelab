from __future__ import annotations

import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from quantlab_core import (
    STORE, RAW_DIR, OUTPUTS_DIR, ensure_store, import_raw_data, build_features,
    list_catalog, list_feature_catalog, list_outputs, read_edges_preview, read_report,
    read_edge_cards, read_data_health, clean_outputs,
)
from discovery_fast import discover_edges as run_fast_discovery
from event_lab import read_event_lab, run_event_lab
from execution_stress import read_execution_stress, run_execution_stress
from incubation import export_ea_candidates, read_incubation, seed_incubation
from monte_carlo import read_monte_carlo, run_monte_carlo
from permutation_test import read_permutation_test, run_permutation_test
from portfolio_risk import read_portfolio_risk, run_portfolio_risk
from robustness import read_validation, run_validation
from sensitivity import read_sensitivity, run_sensitivity
from strategy_universe import get_strategy_universe
from walkforward import read_walkforward, run_walkforward

app = FastAPI(title="CoreEA EdgeLab v1 Engine", version="1.2.2-quick-research-lab")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: Dict[str, Dict[str, Any]] = {}
job_locks: Dict[str, str] = {}
jobs_lock = threading.Lock()

PIPELINE_STEPS = [
    ("import", "Import raw data"),
    ("features", "Build feature cache"),
    ("discover", "Quick strategy discovery"),
    ("event_lab", "Event/feature/outcome lab"),
    ("validate", "Robustness validation"),
    ("walkforward", "Walk-forward matrix"),
    ("stress", "Broker-aware execution stress"),
    ("monte_carlo", "Monte Carlo robustness"),
    ("sensitivity", "Parameter sensitivity"),
    ("portfolio", "Portfolio/risk heat"),
    ("permutation", "Permutation/randomization test"),
    ("incubation", "Seed paper incubation"),
]


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _empty_steps():
    return [{"id": sid, "label": label, "status": "pending"} for sid, label in PIPELINE_STEPS]


def _safe_filename(name: str) -> str:
    raw = Path(str(name or "upload.csv")).name.strip()
    raw = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)[:160]
    return raw or f"upload_{int(time.time())}.csv"


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 9999):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{uuid.uuid4().hex[:8]}{suffix}")


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> list[str]:
    extracted: list[str] = []
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            filename = _safe_filename(info.filename)
            if not filename.lower().endswith(".csv"):
                continue
            dest = _dedupe_path(target_dir / filename)
            if not str(dest.resolve()).startswith(str(target_root)):
                raise RuntimeError("Unsafe ZIP path detected.")
            with z.open(info, "r") as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted.append(str(dest.relative_to(RAW_DIR)))
    return extracted


def run_scan_only(name, mode="quick", symbols="", tfs="", logger=print):
    return run_fast_discovery(name=name, mode=mode or "quick", symbols=symbols, tfs=tfs, logger=logger)


def run_auto_discovery(mode="quick", symbols="", tfs="", logger=print):
    logger("Step 1/3: Importing data")
    import_raw_data(logger)
    logger("Step 2/3: Building features")
    build_features(logger)
    logger("Step 3/3: Quick discovery")
    return run_scan_only(f"auto_discovery_{time.strftime('%Y%m%d_%H%M%S')}", mode="quick" if mode in {"auto", "priority", "efficient", ""} else mode, symbols=symbols, tfs=tfs, logger=logger)


def create_or_reuse_job(kind: str, lock_key: str, payload: Optional[dict] = None, steps: Optional[list[dict]] = None):
    with jobs_lock:
        existing = job_locks.get(lock_key)
        if existing and existing in jobs and jobs[existing]["status"] in {"queued", "running"}:
            jobs[existing]["logs"].append(f"[{time.strftime('%H:%M:%S')}] Duplicate click ignored. Existing job is already running.")
            return existing, True
        jid = str(uuid.uuid4())[:8]
        jobs[jid] = {"id": jid, "kind": kind, "lock_key": lock_key, "status": "queued", "created_at": now(), "updated_at": now(), "payload": payload or {}, "logs": [], "result": None, "error": None, "reused": False, "percent": 0, "stage": "Queued", "steps": steps or []}
        job_locks[lock_key] = jid
        return jid, False


def log_job(jid: str, msg: str):
    with jobs_lock:
        if jid in jobs:
            jobs[jid]["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
            jobs[jid]["updated_at"] = now()


def update_job(jid: str, **kw):
    with jobs_lock:
        if jid in jobs:
            jobs[jid].update(kw)
            jobs[jid]["updated_at"] = now()


def update_pipeline_step(jid: str, step_id: str, status: str, percent: int, stage: str):
    with jobs_lock:
        if jid not in jobs:
            return
        for step in jobs[jid].get("steps", []):
            if step.get("id") == step_id:
                step["status"] = status
        jobs[jid]["percent"] = max(0, min(100, int(percent)))
        jobs[jid]["stage"] = stage
        jobs[jid]["updated_at"] = now()


def pipeline_logger(jid: str, step_id: str | None = None, base_pct: int | None = None, end_pct: int | None = None):
    def _log(msg: str):
        log_job(jid, msg)
        if step_id == "discover" and base_pct is not None and end_pct is not None:
            m = re.search(r"\[(\d+)/(\d+)\]", msg)
            if m:
                cur, total = int(m.group(1)), max(1, int(m.group(2)))
                pct = base_pct + int((end_pct - base_pct) * min(cur, total) / total)
                update_pipeline_step(jid, step_id, "running", pct, f"Quick discovery {cur}/{total}")
            elif "complete" in msg.lower() or "cap reached" in msg.lower():
                update_pipeline_step(jid, step_id, "running", end_pct, "Quick discovery finishing")
    return _log


def run_job(jid: str, fn, *args, **kwargs):
    update_job(jid, status="running", percent=5, stage="Running")
    lock_key = jobs.get(jid, {}).get("lock_key")
    try:
        res = fn(*args, logger=lambda m: log_job(jid, m), **kwargs)
        update_job(jid, status="completed", result=res, percent=100, stage="Completed")
    except Exception as e:
        update_job(jid, status="failed", error=str(e), stage="Failed")
        log_job(jid, f"ERROR: {e}")
    finally:
        with jobs_lock:
            if lock_key and job_locks.get(lock_key) == jid:
                job_locks.pop(lock_key, None)


def start_locked(kind: str, lock_key: str, fn, payload: Optional[dict] = None, *args, **kwargs):
    jid, reused = create_or_reuse_job(kind, lock_key, payload)
    if reused:
        return {"job_id": jid, "reused": True, "message": "Job already running. Duplicate click ignored."}
    threading.Thread(target=run_job, args=(jid, fn, *args), kwargs=kwargs, daemon=True).start()
    return {"job_id": jid, "reused": False, "message": f"{kind} job started."}


def run_full_pipeline_job(jid: str, payload: dict):
    lock_key = jobs.get(jid, {}).get("lock_key")
    scan_name = payload.get("scan_name") or f"pipeline_{time.strftime('%Y%m%d_%H%M%S')}"
    mode = payload.get("mode", "quick")
    if mode in {"auto", "priority", "efficient", "fast", ""}:
        mode = "quick"
    symbols = payload.get("symbols", "")
    tfs = payload.get("tfs", "")
    try:
        update_job(jid, status="running", percent=1, stage="Starting quick full pipeline")
        steps = [
            ("import", 5,  lambda: import_raw_data(pipeline_logger(jid))),
            ("features", 12, lambda: build_features(pipeline_logger(jid))),
            ("discover", 28, lambda: run_scan_only(scan_name, mode=mode, symbols=symbols, tfs=tfs, logger=pipeline_logger(jid, "discover", 13, 28))),
            ("event_lab", 36, lambda: run_event_lab(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("validate", 45, lambda: run_validation(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("walkforward", 55, lambda: run_walkforward(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("stress", 65, lambda: run_execution_stress(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("monte_carlo", 75, lambda: run_monte_carlo(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("sensitivity", 84, lambda: run_sensitivity(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("portfolio", 92, lambda: run_portfolio_risk(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("permutation", 98, lambda: run_permutation_test(scan_name=scan_name, logger=pipeline_logger(jid))),
            ("incubation", 100, lambda: seed_incubation(scan_name=scan_name, logger=pipeline_logger(jid))),
        ]
        result = {"scan_name": scan_name, "mode": mode}
        for step_id, pct, fn in steps:
            label = next((x["label"] for x in jobs[jid]["steps"] if x["id"] == step_id), step_id)
            update_pipeline_step(jid, step_id, "running", max(1, pct - 5), label)
            log_job(jid, f"Starting: {label}")
            result[step_id] = fn()
            update_pipeline_step(jid, step_id, "completed", pct, label)
            log_job(jid, f"Completed: {label}")
        update_job(jid, status="completed", result=result, percent=100, stage="Completed")
    except Exception as e:
        update_job(jid, status="failed", error=str(e), stage="Failed")
        log_job(jid, f"ERROR: {e}")
    finally:
        with jobs_lock:
            if lock_key and job_locks.get(lock_key) == jid:
                job_locks.pop(lock_key, None)


@app.on_event("startup")
def startup(): ensure_store()


@app.get("/health")
def health():
    ensure_store()
    return {"ok": True, "version": "1.2.2-quick-research-lab", "store": str(STORE.resolve()), "active_locks": job_locks}


@app.get("/api/strategy-universe")
def strategy_universe(): return get_strategy_universe()


@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...)):
    ensure_store(); saved = []; errors = []
    for f in files:
        try:
            filename = _safe_filename(f.filename); suffix = Path(filename).suffix.lower()
            if suffix not in {".csv", ".zip"}:
                errors.append({"filename": f.filename, "error": "Only .csv and .zip files are supported."}); continue
            dest = _dedupe_path(RAW_DIR / filename)
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            item = {"filename": dest.name, "original_filename": f.filename, "relative_path": str(dest.relative_to(RAW_DIR)), "size": dest.stat().st_size, "type": suffix.replace(".", "")}
            if suffix == ".zip":
                extract_dir = RAW_DIR / dest.stem; extract_dir.mkdir(parents=True, exist_ok=True)
                extracted = _safe_extract_zip(dest, extract_dir); item["extracted_to"] = str(extract_dir.relative_to(RAW_DIR)); item["extracted_csv_files"] = extracted
            saved.append(item)
        except Exception as e:
            errors.append({"filename": f.filename, "error": str(e)})
    status = 207 if errors and saved else (400 if errors and not saved else 200)
    return JSONResponse(status_code=status, content={"saved": saved, "errors": errors, "message": f"Saved {len(saved)} file(s), {len(errors)} error(s)."})


@app.get("/api/catalog")
def catalog():
    ensure_store(); raw_files = []
    for p in RAW_DIR.rglob("*"):
        if p.is_file(): raw_files.append({"path": str(p.relative_to(RAW_DIR)), "size": p.stat().st_size, "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))})
    return {"raw_files": raw_files, "datasets": list_catalog(), "features": list_feature_catalog(), "data_health": read_data_health()}


@app.post("/api/jobs/import")
def job_import(): return start_locked("import", "import", import_raw_data)
@app.post("/api/jobs/features")
def job_features(): return start_locked("features", "features", build_features)
@app.post("/api/jobs/discover")
def job_discover(payload: Dict[str, Any] | None = None):
    payload = payload or {}; mode = payload.get("mode", "quick"); symbols = payload.get("symbols", ""); tfs = payload.get("tfs", "")
    return start_locked("auto_discovery", f"discover:{mode}:{symbols}:{tfs}", run_auto_discovery, payload, mode=mode, symbols=symbols, tfs=tfs)
@app.post("/api/jobs/scan")
def job_scan(payload: Dict[str, Any]):
    mode = payload.get("mode", "quick"); name = payload.get("name") or f"scan_{mode}_{time.strftime('%Y%m%d_%H%M%S')}"
    return start_locked("scan", f"scan:{mode}", run_scan_only, payload, name=name, mode=mode, symbols=payload.get("symbols", ""), tfs=payload.get("tfs", ""))
@app.post("/api/jobs/full-pipeline")
def job_full_pipeline(payload: Dict[str, Any] | None = None):
    payload = payload or {}; payload.setdefault("mode", "quick"); jid, reused = create_or_reuse_job("full_pipeline", "full_pipeline", payload, _empty_steps())
    if reused: return {"job_id": jid, "reused": True, "message": "Full pipeline already running."}
    threading.Thread(target=run_full_pipeline_job, args=(jid, payload), daemon=True).start()
    return {"job_id": jid, "reused": False, "message": "Full pipeline started."}
@app.post("/api/jobs/event-lab")
def job_event_lab(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage1b_event_lab", f"event_lab:{scan_name or 'latest'}", run_event_lab, payload, scan_name=scan_name)
@app.post("/api/jobs/validate")
def job_validate(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage2_validation", f"validate:{scan_name or 'latest'}", run_validation, payload, scan_name=scan_name)
@app.post("/api/jobs/walkforward")
def job_walkforward(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage3_walkforward", f"walkforward:{scan_name or 'latest'}", run_walkforward, payload, scan_name=scan_name)
@app.post("/api/jobs/execution-stress")
def job_execution_stress(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage4_execution_stress", f"execution_stress:{scan_name or 'latest'}", run_execution_stress, payload, scan_name=scan_name)
@app.post("/api/jobs/monte-carlo")
def job_monte_carlo(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage5_monte_carlo", f"monte_carlo:{scan_name or 'latest'}", run_monte_carlo, payload, scan_name=scan_name)
@app.post("/api/jobs/sensitivity")
def job_sensitivity(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage6_sensitivity", f"sensitivity:{scan_name or 'latest'}", run_sensitivity, payload, scan_name=scan_name)
@app.post("/api/jobs/portfolio-risk")
def job_portfolio_risk(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage7_portfolio_risk", f"portfolio_risk:{scan_name or 'latest'}", run_portfolio_risk, payload, scan_name=scan_name)
@app.post("/api/jobs/permutation-test")
def job_permutation_test(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage8_permutation_test", f"permutation:{scan_name or 'latest'}", run_permutation_test, payload, scan_name=scan_name)
@app.post("/api/jobs/seed-incubation")
def job_seed_incubation(payload: Dict[str, Any] | None = None):
    payload = payload or {}; scan_name = payload.get("scan_name") or None
    return start_locked("stage9_seed_incubation", f"incubation:{scan_name or 'latest'}", seed_incubation, payload, scan_name=scan_name)


@app.get("/api/jobs")
def get_jobs():
    with jobs_lock: return sorted(jobs.values(), key=lambda x: x["created_at"], reverse=True)
@app.delete("/api/jobs/completed")
def clear_completed_jobs():
    with jobs_lock:
        keep = {k: v for k, v in jobs.items() if v["status"] in {"queued", "running"}}
        removed = len(jobs) - len(keep); jobs.clear(); jobs.update(keep)
    return {"removed": removed, "remaining": len(jobs)}


@app.get("/api/outputs")
def outputs(): return list_outputs()
@app.get("/api/edge-cards")
def edge_cards(): return read_edge_cards()
@app.get("/api/data-health")
def data_health(): return read_data_health()
@app.get("/api/event-lab")
def event_lab(scan_name: str | None = None): return read_event_lab(scan_name)
@app.get("/api/validation")
def validation(scan_name: str | None = None): return read_validation(scan_name)
@app.get("/api/walkforward")
def walkforward(scan_name: str | None = None): return read_walkforward(scan_name)
@app.get("/api/execution-stress")
def execution_stress(scan_name: str | None = None): return read_execution_stress(scan_name)
@app.get("/api/monte-carlo")
def monte_carlo(scan_name: str | None = None): return read_monte_carlo(scan_name)
@app.get("/api/sensitivity")
def sensitivity(scan_name: str | None = None): return read_sensitivity(scan_name)
@app.get("/api/portfolio-risk")
def portfolio_risk(scan_name: str | None = None): return read_portfolio_risk(scan_name)
@app.get("/api/permutation-test")
def permutation_test(scan_name: str | None = None): return read_permutation_test(scan_name)
@app.get("/api/incubation")
def incubation(scan_name: str | None = None): return read_incubation(scan_name)
@app.post("/api/ea/export")
def ea_export(payload: Dict[str, Any] | None = None):
    payload = payload or {}; return export_ea_candidates(payload.get("scan_name") or None)
@app.get("/api/outputs/{scan_name}/edges")
def output_edges(scan_name: str, kind: str = "candidate", limit: int = 100): return read_edges_preview(scan_name, kind, limit)
@app.get("/api/outputs/{scan_name}/report")
def output_report(scan_name: str):
    md = read_report(scan_name)
    if md is None: return JSONResponse(status_code=404, content={"error": "report not found"})
    return {"scan_name": scan_name, "markdown": md}
@app.delete("/api/outputs")
def api_clean_outputs(): return clean_outputs()
@app.get("/api/download/{scan_name}/{filename}")
def download(scan_name: str, filename: str):
    safe_scan = _safe_filename(scan_name); safe_file = _safe_filename(filename); p = OUTPUTS_DIR / safe_scan / safe_file
    if not p.exists(): return JSONResponse(status_code=404, content={"error": "file not found"})
    return FileResponse(str(p), filename=safe_file)
