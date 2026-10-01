#!/usr/bin/env python3
"""Apply a .sql file to Supabase (pooler env). Idempotent DDL runner for the schema files.
Usage: python3 data_pipeline/apply_sql.py data_pipeline/<file>.sql
Env: PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE (refresh_db.sh exports the pooler overrides)."""
import os, sys, psycopg2
if len(sys.argv) != 2:
    sys.exit("usage: apply_sql.py <path.sql>")
sql = open(sys.argv[1]).read()
cn = psycopg2.connect(host=os.environ['PGHOST'], port=os.environ.get('PGPORT', '5432'),
    user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
    dbname=os.environ.get('PGDATABASE', 'postgres'), sslmode='require', connect_timeout=40)
cn.autocommit = True
cn.cursor().execute(sql)
print("applied:", sys.argv[1])
cn.close()
