-- Raise the PostgREST API row cap. Default is 1000, which SILENTLY truncates any table the app
-- reads whole via fetchAll (e.g. rank_family_day US = 1830 rows → the Organic Ranks family list
-- was cut off alphabetically around "PowerFlow Plus", dropping Waver; also per-family rows in
-- v_ad_term_enriched). Run once. Persists in the DB role. (Also settable in Supabase dashboard →
-- Project Settings → API → Max rows.)
alter role authenticator set pgrst.db_max_rows = '100000';
notify pgrst, 'reload config';
