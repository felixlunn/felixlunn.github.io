-- FOI research: database schema for the password-protected FOI section of the Data Dashboard.
--
-- Run this once in your Supabase project (SQL Editor > New query > paste > Run). It is safe to run again.
-- Then add your team in the foi_members table (see the README: "FOI research section").
--
-- Security model
--   * Only people with a Supabase login AND a row in foi_members can read or write anything.
--     (Turn off public sign-ups too, so nobody can create a login themselves.)
--   * Every member can see every dataset. Only the person who uploaded a dataset, or an admin, can change or delete it.
--   * Original uploaded files go in a private storage bucket readable only by members.
--   * Ready-made datasets (police.uk, ERIC) can be removed for the whole team by an admin, and restored.

create extension if not exists pgcrypto;

-- Team members. Add a row for each person you invite; delete it to remove their access at once.
create table if not exists public.foi_members (
  email text primary key check (email = lower(email)),
  name text,
  role text not null default 'member' check (role in ('member', 'admin')),
  added_at timestamptz not null default now()
);

create or replace function public.is_foi_member() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.foi_members where email = lower(coalesce(auth.jwt() ->> 'email', '')));
$$;

create or replace function public.is_foi_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.foi_members where email = lower(coalesce(auth.jwt() ->> 'email', '')) and role = 'admin');
$$;

-- One uploaded FOI response, already matched to areas or organisations.
create table if not exists public.foi_datasets (
  id uuid primary key default gen_random_uuid(),
  department text not null check (department in ('policing', 'justice', 'health')),
  geography text not null constraint foi_datasets_geography_check
    check (geography in ('police_force', 'court', 'nhs_trust', 'health_area', 'mh_trust', 'ambulance_trust')),
  title text not null check (length(title) between 1 and 200),
  foi_reference text check (length(foi_reference) <= 100),
  authority text check (length(authority) <= 200),
  period text check (length(period) <= 100),
  requested_on date,
  received_on date,
  notes text check (length(notes) <= 5000),
  -- [{"key": "c1", "label": "Officers", "unit": "count", "direction": "higher_better"}, ...]
  columns jsonb not null check (jsonb_typeof(columns) = 'array'),
  -- [{"code": "E23000036", "source_name": "Avon & Somerset Constabulary", "values": {"c1": 123}}, ...]
  rows jsonb not null check (jsonb_typeof(rows) = 'array'),
  -- Rows that could not be matched: [{"source_name": "...", "values": {...}}]
  unmatched jsonb not null default '[]'::jsonb,
  -- Saved by the site at upload, so the dataset list loads without the rows:
  -- {"rows": 45, "unmatched": 2, "headline": {"col": {...}, "median": 412, "n": 43}}
  summary jsonb,
  file_path text,
  created_by uuid default auth.uid() references auth.users (id) on delete set null,
  created_by_email text not null default lower(coalesce(auth.jwt() ->> 'email', '')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists foi_datasets_department on public.foi_datasets (department, created_at desc);

-- Upgrades for databases set up with an earlier version of this file.
-- Nov 2026: dataset summaries. Older datasets get their sizes; their headline figure shows once re-uploaded.
alter table public.foi_datasets add column if not exists summary jsonb;
update public.foi_datasets
  set summary = jsonb_build_object('rows', jsonb_array_length(rows), 'unmatched', jsonb_array_length(unmatched), 'headline', null)
  where summary is null;
-- Nov 2026: mental health and ambulance trusts as FOI Health geographies.
alter table public.foi_datasets drop constraint if exists foi_datasets_geography_check;
alter table public.foi_datasets add constraint foi_datasets_geography_check
  check (geography in ('police_force', 'court', 'nhs_trust', 'health_area', 'mh_trust', 'ambulance_trust'));

create or replace function public.foi_touch() returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  new.created_by := old.created_by;         -- authorship can't be changed
  new.created_by_email := old.created_by_email;
  new.created_at := old.created_at;
  return new;
end $$;
drop trigger if exists foi_datasets_touch on public.foi_datasets;
create trigger foi_datasets_touch before update on public.foi_datasets for each row execute function public.foi_touch();

-- Ready-made datasets (police.uk, ERIC: built with the site's data, not uploaded) that an admin has removed for the
-- team. Deleting a row restores that dataset.
create table if not exists public.foi_hidden_builtins (
  id text primary key,
  hidden_by uuid default auth.uid() references auth.users (id) on delete set null,
  hidden_at timestamptz not null default now()
);

alter table public.foi_members enable row level security;
alter table public.foi_hidden_builtins enable row level security;
alter table public.foi_datasets enable row level security;

drop policy if exists "members see the team" on public.foi_members;
create policy "members see the team" on public.foi_members for select to authenticated using (public.is_foi_member());
drop policy if exists "admins manage the team" on public.foi_members;
create policy "admins manage the team" on public.foi_members for all to authenticated
  using (public.is_foi_admin()) with check (public.is_foi_admin());

drop policy if exists "members read datasets" on public.foi_datasets;
create policy "members read datasets" on public.foi_datasets for select to authenticated using (public.is_foi_member());
drop policy if exists "members add datasets" on public.foi_datasets;
create policy "members add datasets" on public.foi_datasets for insert to authenticated
  with check (public.is_foi_member() and created_by = auth.uid());
drop policy if exists "owners and admins edit datasets" on public.foi_datasets;
create policy "owners and admins edit datasets" on public.foi_datasets for update to authenticated
  using (public.is_foi_member() and (created_by = auth.uid() or public.is_foi_admin()))
  with check (public.is_foi_member());
drop policy if exists "owners and admins delete datasets" on public.foi_datasets;
create policy "owners and admins delete datasets" on public.foi_datasets for delete to authenticated
  using (public.is_foi_member() and (created_by = auth.uid() or public.is_foi_admin()));

drop policy if exists "members see removed ready-made datasets" on public.foi_hidden_builtins;
create policy "members see removed ready-made datasets" on public.foi_hidden_builtins for select to authenticated using (public.is_foi_member());
drop policy if exists "admins remove and restore ready-made datasets" on public.foi_hidden_builtins;
create policy "admins remove and restore ready-made datasets" on public.foi_hidden_builtins for all to authenticated
  using (public.is_foi_admin()) with check (public.is_foi_admin());

-- Signed-in users can reach the tables (newer projects don't grant this automatically); the row-level
-- security policies above then decide what each person may see or change. Nobody signed out can touch anything.
grant usage on schema public to authenticated;
grant select, insert, update, delete on public.foi_members, public.foi_datasets, public.foi_hidden_builtins to authenticated;
grant execute on function public.is_foi_member(), public.is_foi_admin() to authenticated;
revoke all on public.foi_members, public.foi_datasets, public.foi_hidden_builtins from anon;

-- Private bucket for the original files (CSV / Excel) as received.
insert into storage.buckets (id, name, public, file_size_limit)
values ('foi-files', 'foi-files', false, 20971520)
on conflict (id) do update set public = false;

drop policy if exists "members read foi files" on storage.objects;
create policy "members read foi files" on storage.objects for select to authenticated
  using (bucket_id = 'foi-files' and public.is_foi_member());
drop policy if exists "members upload foi files" on storage.objects;
create policy "members upload foi files" on storage.objects for insert to authenticated
  with check (bucket_id = 'foi-files' and public.is_foi_member() and owner = auth.uid());
drop policy if exists "owners and admins delete foi files" on storage.objects;
create policy "owners and admins delete foi files" on storage.objects for delete to authenticated
  using (bucket_id = 'foi-files' and public.is_foi_member() and (owner = auth.uid() or public.is_foi_admin()));
