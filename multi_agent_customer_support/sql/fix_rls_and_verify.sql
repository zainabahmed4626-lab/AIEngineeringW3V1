-- ============================================================
-- One-time fix: Row Level Security for anon/API access + verify counts
-- Run in Supabase SQL Editor if tables already exist but the JS/Python
-- client sees 0 rows or insert fails with policy errors.
-- ============================================================

alter table customers enable row level security;
alter table orders enable row level security;
alter table support_tickets enable row level security;

drop policy if exists "dev_api_all_customers" on public.customers;
drop policy if exists "dev_api_all_orders" on public.orders;
drop policy if exists "dev_api_all_support_tickets" on public.support_tickets;

create policy "dev_api_all_customers"
  on public.customers
  for all
  to anon, authenticated
  using (true)
  with check (true);

create policy "dev_api_all_orders"
  on public.orders
  for all
  to anon, authenticated
  using (true)
  with check (true);

create policy "dev_api_all_support_tickets"
  on public.support_tickets
  for all
  to anon, authenticated
  using (true)
  with check (true);

select
  (select count(*)::bigint from customers) as customers,
  (select count(*)::bigint from orders) as orders,
  (select count(*)::bigint from support_tickets) as support_tickets;
