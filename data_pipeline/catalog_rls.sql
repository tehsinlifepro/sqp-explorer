-- Make the `catalog` table editable from the app (Catalog tab): authenticated users can
-- read + insert + update + delete rows. PK is (region, asin). Idempotent.
alter table catalog enable row level security;
drop policy if exists "read for authenticated" on catalog;
create policy "read for authenticated" on catalog for select to authenticated using (true);
drop policy if exists ins_auth on catalog;
create policy ins_auth on catalog for insert to authenticated with check (true);
drop policy if exists upd_auth on catalog;
create policy upd_auth on catalog for update to authenticated using (true) with check (true);
drop policy if exists del_auth on catalog;
create policy del_auth on catalog for delete to authenticated using (true);
grant select, insert, update, delete on catalog to authenticated;
