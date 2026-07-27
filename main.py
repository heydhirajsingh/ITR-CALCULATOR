"""One-command launcher for the fully local ITR preparation application.

Running ``python main.py`` creates a local virtual environment when required, installs
Python and frontend dependencies, builds the React application, starts FastAPI, and
opens the app in the default browser.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
FRONTEND_DIR = ROOT / "frontend"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the local ITR preparation system")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    parser.add_argument("--rebuild", action="store_true", help="Force a frontend rebuild")
    parser.add_argument("--host", default=os.getenv("ITR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ITR_PORT", "8000")))
    return parser.parse_args()


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def bootstrap_python_environment() -> None:
    if os.environ.get("ITR_BOOTSTRAPPED") == "1":
        return
    target_python = venv_python()
    if not target_python.exists():
        print("[setup] Creating local Python virtual environment...")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
    marker = VENV_DIR / ".requirements-installed"
    requirements = ROOT / "requirements.txt"
    needs_install = not marker.exists() or marker.stat().st_mtime < requirements.stat().st_mtime
    if needs_install:
        print("[setup] Installing Python dependencies locally...")
        subprocess.run(
            [str(target_python), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"],
            check=True,
            cwd=ROOT,
        )
        subprocess.run([str(target_python), "-m", "pip", "install", "-r", str(requirements)], check=True, cwd=ROOT)
        marker.touch()
    env = os.environ.copy()
    env["ITR_BOOTSTRAPPED"] = "1"
    os.execve(str(target_python), [str(target_python), str(ROOT / "main.py"), *sys.argv[1:]], env)


def latest_source_mtime(path: Path) -> float:
    latest = 0.0
    for item in path.rglob("*"):
        if item.is_file() and "node_modules" not in item.parts and "dist" not in item.parts:
            latest = max(latest, item.stat().st_mtime)
    return latest


def build_frontend(force: bool = False) -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("Node.js 18+ and npm are required to build the React frontend.")
    node_modules = FRONTEND_DIR / "node_modules"
    tsc_bin = node_modules / ".bin" / ("tsc.cmd" if os.name == "nt" else "tsc")
    if not node_modules.exists() or not tsc_bin.exists():
        print("[setup] Installing frontend dependencies locally...")
        subprocess.run([npm, "install", "--no-package-lock", "--no-audit", "--no-fund", "--legacy-peer-deps"], cwd=FRONTEND_DIR, check=True)
    index = FRONTEND_DIR / "dist" / "index.html"
    needs_build = force or not index.exists() or latest_source_mtime(FRONTEND_DIR / "src") > index.stat().st_mtime
    if needs_build:
        print("[setup] Building the React frontend...")
        subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, check=True)


def open_browser_when_ready(url: str) -> None:
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=0.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)


def main() -> None:
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12 or newer is required.")
    args = parse_args()
    bootstrap_python_environment()
    build_frontend(force=args.rebuild)
    os.chdir(ROOT)
    import uvicorn

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser and os.getenv("ITR_OPEN_BROWSER", "true").lower() not in {"0", "false", "no"}:
        threading.Thread(target=open_browser_when_ready, args=(url,), daemon=True).start()
    print(f"[ready] Local ITR is starting at {url}")
    print("[privacy] All files are processed on this machine. Press Ctrl+C to stop.")
    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
