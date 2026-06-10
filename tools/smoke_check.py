from __future__ import annotations

import ast
import compileall
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "apps" / "engine"
WEB = ROOT / "apps" / "web"
STREAMLIT = ROOT / "apps" / "streamlit"

LEGACY_PATTERNS = [
    "TODO", "FIXME", "HACK", "deprecated", "legacy", "old pipeline", "quick automated checks",
]
IGNORE_DIR_NAMES = {
    ".git", ".venv", "venv", "env", "node_modules", "site-packages", "__pycache__",
    ".pytest_cache", ".streamlit", "dist", "build", ".next",
}
REQUIRED_ENGINE = [
    "main.py", "quantlab_core.py", "discovery_fast.py", "pipeline_io.py", "stage_limits.py",
    "robustness.py", "walkforward.py", "execution_stress.py", "monte_carlo.py", "sensitivity.py",
    "portfolio_risk.py", "permutation_test.py", "incubation.py", "event_lab.py", "inefficiency_lab.py",
]
REQUIRED_ROOT = ["START_ALL.bat", "START_STREAMLIT.bat", "INSTALL_ALL.bat", "PROJECT_CONTEXT.md"]
OPTIONAL_BUT_EXPECTED = [WEB / "src" / "App.tsx", WEB / "src" / "api.ts", STREAMLIT / "streamlit_app.py"]


def add(report: dict, name: str, ok: bool, **extra):
    report["checks"].append({"name": name, "ok": bool(ok), **extra})
    return bool(ok)


def should_ignore(path: Path) -> bool:
    return any(part in IGNORE_DIR_NAMES for part in path.parts)


def iter_project_py(base: Path):
    if not base.exists():
        return
    for p in base.rglob("*.py"):
        if should_ignore(p.relative_to(ROOT)):
            continue
        yield p


def py_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def scan_legacy() -> list[dict]:
    hits = []
    allowed_dirs = [ENGINE, WEB / "src", STREAMLIT, ROOT / "tools"]
    for base in allowed_dirs:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if should_ignore(p.relative_to(ROOT)):
                continue
            if not p.is_file() or p.suffix.lower() not in {".py", ".tsx", ".ts", ".css"}:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for pat in LEGACY_PATTERNS:
                if re.search(re.escape(pat), text, re.IGNORECASE):
                    hits.append({"file": str(p.relative_to(ROOT)), "pattern": pat})
    return hits


def main() -> int:
    report = {"root": str(ROOT), "checks": []}
    ok = True

    engine_ok = compileall.compile_dir(str(ENGINE), quiet=1, force=True, rx=re.compile(r"(\\.venv|site-packages|__pycache__)"))
    ok = add(report, "python_compile_engine", engine_ok, path=str(ENGINE)) and ok

    tools_ok = compileall.compile_dir(str(ROOT / "tools"), quiet=1, force=True, rx=re.compile(r"(__pycache__|\\.venv|site-packages)"))
    ok = add(report, "python_compile_tools", tools_ok, path=str(ROOT / "tools")) and ok

    streamlit_ok = compileall.compile_dir(str(STREAMLIT), quiet=1, force=True, rx=re.compile(r"(__pycache__|\\.venv|site-packages)")) if STREAMLIT.exists() else False
    ok = add(report, "python_compile_streamlit", streamlit_ok, path=str(STREAMLIT)) and ok

    missing_engine = [f for f in REQUIRED_ENGINE if not (ENGINE / f).exists()]
    ok = add(report, "required_engine_files", not missing_engine, missing=missing_engine) and ok

    missing_root = [f for f in REQUIRED_ROOT if not (ROOT / f).exists()]
    ok = add(report, "required_root_files", not missing_root, missing=missing_root) and ok

    missing_optional = [str(p.relative_to(ROOT)) for p in OPTIONAL_BUT_EXPECTED if not p.exists()]
    ok = add(report, "expected_ui_files", not missing_optional, missing=missing_optional) and ok

    req_path = ENGINE / "requirements.txt"
    requirements = set(req_path.read_text(encoding="utf-8").split()) if req_path.exists() else set()
    expected_reqs = {"fastapi", "uvicorn", "pandas", "numpy", "python-multipart", "tabulate", "pytest", "streamlit", "plotly"}
    missing_reqs = sorted(expected_reqs - requirements)
    ok = add(report, "requirements_complete", not missing_reqs, missing=missing_reqs) and ok

    imported = set()
    for base in [ENGINE, STREAMLIT, ROOT / "tools"]:
        for p in iter_project_py(base) or []:
            imported |= py_imports(p)
    third_party = {"fastapi", "pandas", "numpy", "streamlit", "plotly", "pytest"}
    imported_third_party = sorted(imported & third_party)
    missing_import_reqs = sorted((set(imported_third_party) - requirements) - {"pytest"})
    ok = add(report, "imported_dependencies_declared", not missing_import_reqs, imported=imported_third_party, missing=missing_import_reqs) and ok

    package_json = WEB / "package.json"
    package_lock = WEB / "package-lock.json"
    ok = add(report, "web_package_json_present", package_json.exists(), path=str(package_json)) and ok
    add(report, "web_lockfile_present", package_lock.exists(), note="Recommended for fully reproducible npm installs; current CI uses npm install so absence is not fatal.")

    legacy_hits = scan_legacy()
    non_fatal_hits = [h for h in legacy_hits if h["pattern"].lower() not in {"quick automated checks"}]
    ok = add(report, "legacy_markers_scan", not non_fatal_hits, hits=non_fatal_hits[:50], note="Vendor folders are ignored. quick automated checks is tolerated only for old-run detection in UI.") and ok

    data_dir_exists = (ROOT / "data").exists()
    add(report, "data_dir_present", data_dir_exists, note="Runtime data may be local-only and not committed.")

    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
