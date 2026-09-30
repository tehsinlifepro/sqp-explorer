#!/usr/bin/env python3
"""Generic Supabase loader: truncate a table and load a CSV into it (replaces manual CSV import).

Reads the CSV as text (so ints stay ints, no 12.0 casting surprises), turns '' into NULL, and lets
Postgres cast each column to its real type on insert. Column set = the CSV header (must match the
table's columns).

Use as a module:  from sb_load import connect, load_csv
Or CLI:           python3 sb_load.py <table> <csv_path>
"""
import os, sys, csv, psycopg2
from psycopg2.extras import execute_values

def connect():
    return psycopg2.connect(host=os.environ['PGHOST'], port=os.environ.get('PGPORT', '5432'),
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'],
        dbname=os.environ.get('PGDATABASE', 'postgres'), sslmode='require', connect_timeout=40)

def load_csv(cur, table, csv_path, truncate=True, conflict=None):
    """Load a CSV into `table`.
    - default: truncate then insert (snapshot replace).
    - conflict=[pk cols]: UPSERT (insert ... on conflict do update) and DO NOT truncate,
      so rows/months not present in this batch are preserved. Use for month-keyed tables
      fed by a rolling-window source (SellerLabs), turning the load into an accumulator.
    """
    with open(csv_path, newline='') as f:
        r = csv.reader(f)
        cols = next(r)
        rows = [[(v if v != '' else None) for v in row] for row in r]
    collist = ','.join(f'"{c}"' for c in cols)
    if conflict:
        upd = ','.join(f'"{c}"=excluded."{c}"' for c in cols if c not in conflict)
        action = f'do update set {upd}' if upd else 'do nothing'
        sql = f'insert into {table} ({collist}) values %s on conflict ({",".join(conflict)}) {action}'
        if rows:
            execute_values(cur, sql, rows, page_size=5000)
    else:
        if truncate:
            cur.execute(f'truncate {table}')
        if rows:
            execute_values(cur, f'insert into {table} ({collist}) values %s', rows, page_size=5000)
    return len(rows)

if __name__ == '__main__':
    table, path = sys.argv[1], sys.argv[2]
    c = connect(); cur = c.cursor()
    n = load_csv(cur, table, path); c.commit(); c.close()
    print(f'loaded {n:,} rows into {table}')
