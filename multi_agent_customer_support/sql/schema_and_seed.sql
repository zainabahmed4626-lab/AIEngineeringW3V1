-- ============================================================
-- Multi-Agent Customer Support - Schema + Seed (Supabase Postgres)
-- Paste into: Supabase Dashboard → SQL Editor → Run
-- ============================================================

create extension if not exists pgcrypto;

-- Optional: clean slate (remove if you already have production data!)
drop table if exists support_tickets cascade;
drop table if exists orders cascade;
drop table if exists customers cascade;

-- =====================
-- 1) TABLE DEFINITIONS
-- =====================

create table customers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null unique,
  created_at timestamptz not null default now()
);

create table orders (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers(id),
  order_number text not null unique,
  total_amount numeric not null,
  status text not null,
  created_at timestamptz not null default now()
);

create table support_tickets (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid not null references customers(id),
  order_id uuid references orders(id),
  category text not null,
  status text not null,
  description text not null,
  created_at timestamptz not null default now()
);

create index idx_orders_customer_id on orders(customer_id);
create index idx_tickets_customer_id on support_tickets(customer_id);
create index idx_tickets_order_id on support_tickets(order_id);
create index idx_tickets_category_status on support_tickets(category, status);

-- =================
-- 2) SEEDING DATA
-- =================

insert into customers (id, name, email, created_at) values
('11111111-1111-1111-1111-111111111101', 'Ava Thompson',   'ava.thompson@example.com',   now() - interval '90 days'),
('11111111-1111-1111-1111-111111111102', 'Liam Carter',    'liam.carter@example.com',    now() - interval '88 days'),
('11111111-1111-1111-1111-111111111103', 'Noah Bennett',   'noah.bennett@example.com',   now() - interval '76 days'),
('11111111-1111-1111-1111-111111111104', 'Emma Rodriguez', 'emma.rodriguez@example.com', now() - interval '73 days'),
('11111111-1111-1111-1111-111111111105', 'Sophia Nguyen',  'sophia.nguyen@example.com',  now() - interval '69 days'),
('11111111-1111-1111-1111-111111111106', 'Mason Patel',    'mason.patel@example.com',    now() - interval '62 days'),
('11111111-1111-1111-1111-111111111107', 'Isabella Kim',   'isabella.kim@example.com',   now() - interval '55 days'),
('11111111-1111-1111-1111-111111111108', 'Ethan Brooks',   'ethan.brooks@example.com',   now() - interval '49 days'),
('11111111-1111-1111-1111-111111111109', 'Olivia Davis',   'olivia.davis@example.com',   now() - interval '35 days'),
('11111111-1111-1111-1111-111111111110', 'Lucas Garcia',   'lucas.garcia@example.com',   now() - interval '21 days');

insert into orders (id, customer_id, order_number, total_amount, status, created_at) values
('22222222-2222-2222-2222-222222222201', '11111111-1111-1111-1111-111111111101', 'ORD-2026-0001', 129.99, 'paid',     now() - interval '40 days'),
('22222222-2222-2222-2222-222222222202', '11111111-1111-1111-1111-111111111102', 'ORD-2026-0002',  79.50, 'shipped',  now() - interval '38 days'),
('22222222-2222-2222-2222-222222222203', '11111111-1111-1111-1111-111111111103', 'ORD-2026-0003', 249.00, 'paid',     now() - interval '36 days'),
('22222222-2222-2222-2222-222222222204', '11111111-1111-1111-1111-111111111104', 'ORD-2026-0004',  54.25, 'refunded', now() - interval '33 days'),
('22222222-2222-2222-2222-222222222205', '11111111-1111-1111-1111-111111111105', 'ORD-2026-0005', 310.75, 'shipped',  now() - interval '30 days'),
('22222222-2222-2222-2222-222222222206', '11111111-1111-1111-1111-111111111106', 'ORD-2026-0006',  18.99, 'paid',     now() - interval '27 days'),
('22222222-2222-2222-2222-222222222207', '11111111-1111-1111-1111-111111111107', 'ORD-2026-0007',  97.40, 'paid',     now() - interval '24 days'),
('22222222-2222-2222-2222-222222222208', '11111111-1111-1111-1111-111111111108', 'ORD-2026-0008', 145.00, 'shipped',  now() - interval '20 days'),
('22222222-2222-2222-2222-222222222209', '11111111-1111-1111-1111-111111111109', 'ORD-2026-0009', 220.15, 'paid',     now() - interval '17 days'),
('22222222-2222-2222-2222-222222222210', '11111111-1111-1111-1111-111111111110', 'ORD-2026-0010',  65.00, 'refunded', now() - interval '14 days'),
('22222222-2222-2222-2222-222222222211', '11111111-1111-1111-1111-111111111101', 'ORD-2026-0011',  33.49, 'paid',     now() - interval '11 days'),
('22222222-2222-2222-2222-222222222212', '11111111-1111-1111-1111-111111111105', 'ORD-2026-0012', 412.00, 'shipped',  now() - interval '7 days');

insert into support_tickets (id, customer_id, order_id, category, status, description, created_at) values
('33333333-3333-3333-3333-333333333301', '11111111-1111-1111-1111-111111111101', '22222222-2222-2222-2222-222222222201', 'billing', 'open',
 'Customer reports duplicate charge for order ORD-2026-0001.', now() - interval '10 days'),

('33333333-3333-3333-3333-333333333302', '11111111-1111-1111-1111-111111111102', '22222222-2222-2222-2222-222222222202', 'returns', 'in_progress',
 'Wrong size delivered; customer requested exchange and return label.', now() - interval '9 days'),

('33333333-3333-3333-3333-333333333303', '11111111-1111-1111-1111-111111111103', '22222222-2222-2222-2222-222222222203', 'general', 'resolved',
 'Asked for updated shipping ETA and tracking clarification.', now() - interval '8 days'),

('33333333-3333-3333-3333-333333333304', '11111111-1111-1111-1111-111111111104', '22222222-2222-2222-2222-222222222204', 'billing', 'resolved',
 'Refund completed but customer did not see bank settlement yet.', now() - interval '7 days'),

('33333333-3333-3333-3333-333333333305', '11111111-1111-1111-1111-111111111105', '22222222-2222-2222-2222-222222222205', 'returns', 'escalated',
 'Item arrived damaged; customer requested full refund with photo evidence.', now() - interval '6 days'),

('33333333-3333-3333-3333-333333333306', '11111111-1111-1111-1111-111111111106', '22222222-2222-2222-2222-222222222206', 'billing', 'in_progress',
 'Promo code was not applied at checkout; requesting partial refund.', now() - interval '5 days'),

('33333333-3333-3333-3333-333333333307', '11111111-1111-1111-1111-111111111107', '22222222-2222-2222-2222-222222222207', 'general', 'open',
 'Customer wants to update shipping address after placing the order.', now() - interval '4 days'),

('33333333-3333-3333-3333-333333333308', '11111111-1111-1111-1111-111111111108', '22222222-2222-2222-2222-222222222208', 'returns', 'open',
 'Return requested for unopened item within return window.', now() - interval '3 days'),

('33333333-3333-3333-3333-333333333309', '11111111-1111-1111-1111-111111111109', '22222222-2222-2222-2222-222222222209', 'billing', 'escalated',
 'Customer states tax amount appears incorrect for shipping destination.', now() - interval '2 days'),

('33333333-3333-3333-3333-333333333310', '11111111-1111-1111-1111-111111111110', '22222222-2222-2222-2222-222222222210', 'returns', 'resolved',
 'Refund was issued after returned item passed warehouse inspection.', now() - interval '36 hours'),

('33333333-3333-3333-3333-333333333311', '11111111-1111-1111-1111-111111111101', '22222222-2222-2222-2222-222222222211', 'general', 'open',
 'Asked whether order can be bundled with a recent purchase.', now() - interval '18 hours'),

('33333333-3333-3333-3333-333333333312', '11111111-1111-1111-1111-111111111105', '22222222-2222-2222-2222-222222222212', 'billing', 'open',
 'Invoice email missing line-item breakdown; customer requested corrected invoice.', now() - interval '6 hours');

-- =================
-- 3) RLS (dev)
-- =================
-- PostgREST uses the `anon` / `authenticated` roles. Without policies, SELECT/INSERT
-- from the Supabase client (anon key) will see 0 rows or get 42501 errors.
-- Replace these with tighter policies before production.

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

-- SQL Editor will show THIS result (otherwise "Success. No rows returned" is normal):
select
  (select count(*)::bigint from customers) as customers,
  (select count(*)::bigint from orders) as orders,
  (select count(*)::bigint from support_tickets) as support_tickets;
