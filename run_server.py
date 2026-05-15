from pathlib import Path
import sys

import uvicorn

BASE_DIR = Path(__file__).resolve().parent
out_log = open(BASE_DIR / "server.out.log", "a", encoding="utf-8", buffering=1)
err_log = open(BASE_DIR / "server.err.log", "a", encoding="utf-8", buffering=1)
sys.stdout = out_log
sys.stderr = err_log

uvicorn.run("app.main:app", host="127.0.0.1", port=9999, log_level="info")
