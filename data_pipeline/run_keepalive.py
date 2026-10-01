"""Run a sqp-explorer pipeline script with TCP keepalives injected into every
psycopg2.connect() call, so long selects/pandas gaps survive the proxy+pooler.
Does not modify the pipeline source. Usage: run_keepalive.py <script.py>
"""
import sys, runpy, psycopg2

_orig = psycopg2.connect
def _connect(*a, **kw):
    kw.setdefault("keepalives", 1)
    kw.setdefault("keepalives_idle", 30)
    kw.setdefault("keepalives_interval", 10)
    kw.setdefault("keepalives_count", 5)
    kw.setdefault("options", "-c statement_timeout=0 -c idle_in_transaction_session_timeout=0")
    return _orig(*a, **kw)
psycopg2.connect = _connect

target = sys.argv[1]
sys.argv = [target]
runpy.run_path(target, run_name="__main__")
