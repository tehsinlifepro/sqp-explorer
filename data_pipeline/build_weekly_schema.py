#!/usr/bin/env python3
"""Generate + apply the weekly (_week) organic SQP tables by mirroring the monthly tables.

For each monthly table it introspects columns + PK from Postgres and creates the _week twin with the
'month' (text) column replaced by 'week' (date), same PK (month->week), RLS + authenticated select grant.
Idempotent (create table if not exists). Part of the weekly SQP lane.
Run: cd ~/Downloads/sqp-explorer && set -a && . .secrets/supabase.env && set +a && \
     PGHOST=aws-0-us-east-1.pooler.supabase.com PGPORT=5432 PGUSER=postgres.vhrzfsceziyqbrwwwhxv \
     python3 data_pipeline/build_weekly_schema.py
"""
import os, psycopg2

PAIRS = {  # monthly source table -> weekly table
    "category_month": "category_week", "asin_month": "asin_week",
    "query_month": "query_week", "query_asin_month": "query_asin_week",
    "family_niche_month": "family_niche_week", "query_summary": "query_summary_week",
    "family_kw_composition": "family_kw_composition_week", "family_top_keywords": "family_top_keywords_week",
}

def conn():
    return psycopg2.connect(host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"), sslmode="require", connect_timeout=40)

c = conn(); c.autocommit = True; cur = c.cursor()
for mtab, wtab in PAIRS.items():
    cur.execute("""select column_name, data_type from information_schema.columns
                   where table_name=%s and table_schema='public' order by ordinal_position""", (mtab,))
    cols = cur.fetchall()
    if not cols:
        print(f"  !! {mtab} not found — skipping {wtab}"); continue
    defs = []
    for name, dtype in cols:
        if name == "month":
            defs.append("week date")
        else:
            defs.append(f'"{name}" {dtype}')
    cur.execute("""select a.attname from pg_index i join pg_attribute a on a.attrelid=i.indrelid and a.attnum=any(i.indkey)
                   where i.indrelid=%s::regclass and i.indisprimary order by array_position(i.indkey,a.attnum)""", (mtab,))
    pk = [("week" if r[0] == "month" else r[0]) for r in cur.fetchall()]
    pk_clause = f", primary key ({','.join(pk)})" if pk else ""
    cur.execute(f"create table if not exists {wtab} ({', '.join(defs)}{pk_clause})")
    cur.execute(f"alter table {wtab} enable row level security")
    cur.execute(f"drop policy if exists sel_auth on {wtab}")
    cur.execute(f"create policy sel_auth on {wtab} for select to authenticated using (true)")
    cur.execute(f"grant select on {wtab} to authenticated")
    print(f"  ✓ {wtab:26} ({len(cols)} cols, pk={pk})")
c.close()
print("✓ weekly organic schema ready")
