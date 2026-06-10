from __future__ import annotations

import compileall
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "apps" / "engine"
WEB = ROOT / "apps" / "web"


def main() -> int:
    report = {"root": str(ROOT), "checks": []}
    ok = True

    engine_ok = compileall.compile_dir(str(ENGINE), quiet=1, force=True)
    report["checks"].append({"name": "python_compile_engine", "ok": bool(engine_ok), "path": str(ENGINE)})
    ok = ok and bool(engine_ok)

    required = [
        ENGINE / "main.py",
        ENGINE / "quantlab_core.py",
        ENGINE / "discovery_fast.py",
        ENGINE / "pipeline_io.py",
        ENGINE / "event_lab.py",
        ENGINE / "permutation_test.py",
        ENGINE / "incubation.py",
        WEB / "src" / "App.tsx",
        WEB / "src" / "api.ts",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    report["checks"].append({"name": "required_files", "ok": not missing, "missing": missing})
    ok = ok and not missing

    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
