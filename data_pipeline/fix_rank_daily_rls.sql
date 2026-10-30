-- Close the one RLS gap flagged by Supabase (rls_disabled_in_public) on public.rank_daily.
-- rank_daily is the durable ranks accumulator, created elsewhere with "create table if not exists"
-- and never given RLS. It is written only by the pipeline (direct postgres connection, bypasses RLS)
-- and is NOT read by the client, so enabling RLS is safe. Policy mirrors the project convention
-- (sel_auth: SELECT to authenticated), matching every other read-only data table.
alter table public.rank_daily enable row level security;
drop policy if exists sel_auth on public.rank_daily;
create policy sel_auth on public.rank_daily for select to authenticated using (true);
