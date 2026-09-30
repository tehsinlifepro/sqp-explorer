-- Sprint 9: user-set monthly targets (editable in the Targets tab). Canada / Vendor Central.
-- scope = 'Account' or a family name; tacos_target stored as a fraction (0.22 = 22%).
create table if not exists targets (
  region text, scope text, month text,
  sales_target numeric, ppc_budget numeric, tacos_target numeric,
  primary key (region, scope, month));
alter table targets enable row level security;
drop policy if exists sel_auth on targets; create policy sel_auth on targets for select to authenticated using (true);
drop policy if exists ins_auth on targets; create policy ins_auth on targets for insert to authenticated with check (true);
drop policy if exists upd_auth on targets; create policy upd_auth on targets for update to authenticated using (true) with check (true);
drop policy if exists del_auth on targets; create policy del_auth on targets for delete to authenticated using (true);
grant select, insert, update, delete on targets to authenticated;
