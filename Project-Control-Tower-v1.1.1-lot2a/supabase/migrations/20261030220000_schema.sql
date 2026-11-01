-- =====================================================================
-- Project Control Tower : schéma Supabase
-- Reprend les listes de index.html (PEOPLE, CLIENTS, PROJECTS, ACTIONS…)
-- et déplace dans la base les règles d'accès de la page :
--   * rôle   (ROLES : money, margin, internal)
--   * périmètre (scopeOf : projets ou clients affectés)
--   * matrice des droits (MATRIX : module × verbe)
-- Les identifiants restent ceux de l'application (p1, A-1042, ndl…).
-- =====================================================================

create schema if not exists app;          -- fonctions internes, non exposées par l'API
revoke all on schema app from public;
grant usage on schema app to authenticated;

-- ---------------------------------------------------------------------
-- Référentiels
-- ---------------------------------------------------------------------
create table public.roles (
  id        text primary key,               -- admin, direction, manager, commercial, cdp, techlead, consultant, dev, testeur, client
  label     text not null,
  question  text,
  money     boolean not null default false, -- budget, coûts, forecast
  margin    boolean not null default false, -- marges et CA
  internal  boolean not null default true   -- false = portail client
);

create table public.clients (
  id        text primary key,
  name      text not null,
  sector    text,
  city      text,
  color     text,
  label     text,
  managers  text[] not null default '{}',   -- people.id des managers
  sales     text[] not null default '{}',   -- people.id des commerciaux
  contacts  jsonb  not null default '[]'    -- [{n,r,e}]
);

create table public.people (
  id           text primary key,
  auth_user_id uuid unique references auth.users(id) on delete set null,
  name         text not null,
  role         text not null references public.roles(id),
  title        text,
  team         text,
  email        text unique,
  client_id    text references public.clients(id),
  is_virtual   boolean not null default false
);

-- capacité et compétences : données internes Demo ESN
create table public.people_internal (
  person_id text primary key references public.people(id) on delete cascade,
  cap       numeric,                        -- heures contractuelles / semaine
  meet      numeric,                        -- heures de réunions récurrentes / semaine
  skills    text[] not null default '{}'
);

create table public.client_contracts (
  ref       text primary key,
  client_id text not null references public.clients(id) on delete cascade,
  label     text,
  amount    numeric,
  end_date  date,
  kind      text,
  renew     boolean not null default false
);

-- ---------------------------------------------------------------------
-- Projets
-- ---------------------------------------------------------------------
create table public.projects (
  id            text primary key,
  code          text not null unique,
  name          text not null,
  client_id     text not null references public.clients(id),
  method        text,                       -- V | Agile
  pm            text references public.people(id),
  tl            text references public.people(id),
  team          text[] not null default '{}',
  descr         text,
  start_date    date,
  end_date      date,
  forecast_end  date,
  progress      int  not null default 0,
  phases        jsonb not null default '[]',   -- macro planning
  milestones    jsonb not null default '[]',
  tests         jsonb not null default '{}',   -- synthèse recette
  key_dates     jsonb not null default '[]',
  hyper         jsonb,                          -- hypercare
  lifecycle     jsonb not null default '[]',   -- historique des états (p.lc)
  week_plans    jsonb not null default '{}',
  agile         jsonb                           -- sprints, sprint, scrum, sprintList (projets Agile)
);

-- heures et affectations : données internes
create table public.project_internal (
  project_id text primary key references public.projects(id) on delete cascade,
  days       numeric,                        -- jours vendus
  h_base     numeric, h_done numeric, h_raf numeric,
  team_load  numeric,
  staff      jsonb not null default '[]'      -- [{id,role,pct,from,to}]
);

-- budget, CA, coûts : profils financiers uniquement
create table public.project_finance (
  project_id text primary key references public.projects(id) on delete cascade,
  ca         numeric,
  baseline   numeric,
  approved   numeric,
  consumed   numeric,
  raf_cost   numeric,
  lines      jsonb not null default '[]',
  causes     jsonb not null default '[]',
  series     jsonb,
  months     jsonb
);

-- ---------------------------------------------------------------------
-- Exécution
-- ---------------------------------------------------------------------
create table public.actions (
  id          text primary key,
  project_id  text not null references public.projects(id) on delete cascade,
  title       text not null,
  phase       text,
  owner       text references public.people(id),
  prio        text,
  status      text not null check (status in ('todo','planned','doing','review','blocked','done')),
  est0        numeric, est numeric, done numeric, raf numeric,
  start_date  date, due date, fdue date,
  type        text,                         -- Fonctionnelle, Technique, Client…
  block       text not null default '',
  stage       text,
  us          text,
  done_at     date,
  history     jsonb not null default '[]'
);

-- les commentaires internes ne doivent pas atteindre le portail client
create table public.action_comments (
  id        bigint generated always as identity primary key,
  action_id text not null references public.actions(id) on delete cascade,
  author    text references public.people(id),
  at        text,
  body      text not null,
  internal  boolean not null default false
);

create table public.user_stories (
  id         text primary key,
  project_id text not null references public.projects(id) on delete cascade,
  sprint     int,
  title      text not null,
  pts        numeric,
  prio       text,
  story      text,
  ac         text,
  closed     date
);

create table public.objectives (
  id         text primary key,
  scope      text,
  project_id text references public.projects(id) on delete cascade,
  owner      text references public.people(id),
  title      text not null,
  due        date,
  items      jsonb not null default '[]'
);

create table public.todos (
  id       bigint generated always as identity primary key,
  owner    text not null references public.people(id) on delete cascade,
  label    text not null,
  done     boolean not null default false,
  position int not null default 0
);

-- heures réalisées (WORKLOG)
create table public.time_entries (
  id         bigint generated always as identity primary key,
  person_id  text not null references public.people(id),
  action_id  text references public.actions(id) on delete set null,
  project_id text not null references public.projects(id) on delete cascade,
  work_date  date not null,
  hours      numeric not null check (hours > 0),
  is_meeting boolean not null default false
);
create index on public.time_entries (person_id, work_date);
create index on public.time_entries (project_id);

-- ---------------------------------------------------------------------
-- Contrôle
-- ---------------------------------------------------------------------
create table public.risks (
  id             text primary key,
  project_id     text not null references public.projects(id) on delete cascade,
  title          text not null,
  prob           int, imp int,
  owner          text references public.people(id),
  status         text,
  due            date,
  mitigation     text,
  client_visible boolean not null default false,
  actions        text[] not null default '{}'
);

create table public.issues (
  id         text primary key,
  project_id text not null references public.projects(id) on delete cascade,
  kind       text, title text not null, prio text,
  owner      text references public.people(id),
  due        date,
  impact     text
);

create table public.change_requests (
  id           text primary key,
  project_id   text not null references public.projects(id) on delete cascade,
  title        text not null,
  requested_by text references public.people(id),
  hours        numeric, days numeric,
  status       text,
  vdate        date,
  fn           text, tech text
);
-- le montant est vu par les profils financiers et par le client, pas par l'équipe technique
create table public.change_request_amounts (
  cr_id  text primary key references public.change_requests(id) on delete cascade,
  amount numeric
);

create table public.test_campaigns (
  id text primary key,
  project_id text not null references public.projects(id) on delete cascade,
  name text, env text, version text,
  total int, pass int, fail int, todo int, crit int,
  owner text references public.people(id)
);

create table public.defects (
  id text primary key,
  project_id text not null references public.projects(id) on delete cascade,
  title text not null, sev text, status text,
  owner text references public.people(id)
);

create table public.documents (
  id             text primary key,
  project_id     text not null references public.projects(id) on delete cascade,
  name           text not null,
  ext            text,
  size_mb        numeric,
  type           text,                       -- cdc, sfd, hld, dat… (DOC_TYPES)
  dstat          text,                       -- Manquant, Brouillon, En revue, Validé
  entity         text,
  uploaded_by    text references public.people(id),
  uploaded_at    date,
  version        int not null default 1,
  scan_status    text,
  client_visible boolean not null default false
);

create table public.meetings (
  id             text primary key,
  project_id     text not null references public.projects(id) on delete cascade,
  type           text, title text not null,
  date           date, time text, dur int,
  organizer      text references public.people(id),
  attendees      text[] not null default '{}',
  external       text[] not null default '{}',
  agenda         text[] not null default '{}',
  notes          text,
  decisions      text[] not null default '{}',
  actions        text[] not null default '{}',
  doc            text,
  client_visible boolean not null default false,
  status         text
);

create table public.audit_log (
  id         bigint generated always as identity primary key,
  at         text not null,
  actor      text,
  entity     text,
  event      text,
  old_value  text,
  new_value  text,
  trace      text
);

-- ---------------------------------------------------------------------
-- Paramétrage
-- ---------------------------------------------------------------------
-- matrice des droits : un booléen par verbe, dans l'ordre de VERBS
create table public.role_permissions (
  role    text not null references public.roles(id) on delete cascade,
  module  text not null,                   -- project, client, planning, action, budget, resource, document, test, risk, report, user, settings
  can_read boolean not null default false, can_create boolean not null default false,
  can_update boolean not null default false, can_delete boolean not null default false,
  can_approve boolean not null default false,
  primary key (role, module)
);

-- réglages partagés : lifecycle, thresholds, time
create table public.app_settings (
  key   text primary key,
  value jsonb not null
);

-- =====================================================================
-- Fonctions de droits (miroir de me(), role(), can(), scopeOf())
-- security definer : elles lisent les tables sans repasser par la RLS.
-- =====================================================================
create or replace function app.me() returns text
language sql stable security definer set search_path = public as $$
  select id from public.people where auth_user_id = auth.uid()
$$;

create or replace function app.my_role() returns text
language sql stable security definer set search_path = public as $$
  select role from public.people where auth_user_id = auth.uid()
$$;

create or replace function app.can(p_module text, p_verb text) returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((
    select case p_verb when 'read' then can_read when 'create' then can_create
                       when 'update' then can_update when 'delete' then can_delete
                       when 'approve' then can_approve end
    from public.role_permissions where role = app.my_role() and module = p_module), false)
$$;

create or replace function app.is_internal() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select internal from public.roles where id = app.my_role()), false)
$$;

-- ROLES.money && can('budget.read')
create or replace function app.has_money() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select money from public.roles where id = app.my_role()), false) and app.can('budget','read')
$$;

create or replace function app.has_margin() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select margin from public.roles where id = app.my_role()), false)
$$;

-- scopeOf() : admin et direction voient tout ; manager et commercial leurs clients ;
-- client son entreprise ; chef de projet ses projets ; les autres les projets où ils sont TL ou équipe
create or replace function app.in_scope(p_project text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.projects p
    join public.people u on u.auth_user_id = auth.uid()
    left join public.clients c on c.id = p.client_id
    where p.id = p_project and case u.role
      when 'admin'      then true
      when 'direction'  then true
      when 'manager'    then u.id = any(c.managers)
      when 'commercial' then u.id = any(c.sales)
      when 'client'     then p.client_id = u.client_id
      when 'cdp'        then p.pm = u.id
      else p.tl = u.id or u.id = any(p.team)
    end)
$$;

-- visibleClientIds() : clients du périmètre + clients des projets visibles
create or replace function app.client_visible(p_client text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.people u, public.clients c
    where u.auth_user_id = auth.uid() and c.id = p_client and (
      u.role in ('admin','direction')
      or (u.role = 'manager'    and u.id = any(c.managers))
      or (u.role = 'commercial' and u.id = any(c.sales))
      or (u.role = 'client'     and u.client_id = c.id)))
  or exists (select 1 from public.projects p where p.client_id = p_client and app.in_scope(p.id))
$$;

-- ACT_ALL : rôles qui voient les réalisations des autres
create or replace function app.sees_all_activity() returns boolean
language sql stable security definer set search_path = public as $$
  select app.my_role() in ('techlead','cdp','client','admin','manager','direction')
$$;

grant execute on all functions in schema app to authenticated;

-- Relie un compte Supabase Auth à sa fiche people, par e-mail, à la création du compte
create or replace function app.link_auth_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  update public.people set auth_user_id = new.id
   where lower(email) = lower(new.email) and auth_user_id is null;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function app.link_auth_user();

-- =====================================================================
-- Row Level Security
-- Lecture : périmètre + rôle + matrice. Écriture : périmètre + matrice.
-- Aucune politique pour le rôle anon : sans connexion, la base ne renvoie rien.
-- =====================================================================
do $$ declare t text; begin
  foreach t in array array['roles','clients','people','people_internal','client_contracts','projects','project_internal',
    'project_finance','actions','action_comments','user_stories','objectives','todos','time_entries','risks','issues',
    'change_requests','change_request_amounts','test_campaigns','defects','documents','meetings','audit_log',
    'role_permissions','app_settings'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
  end loop;
end $$;
grant usage on all sequences in schema public to authenticated;

-- référentiels lisibles par tout utilisateur connecté
create policy roles_read    on public.roles            for select to authenticated using (true);
create policy perms_read    on public.role_permissions for select to authenticated using (true);
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy perms_write_ins on public.role_permissions for insert to authenticated with check (app.my_role() = 'admin');
create policy perms_write_upd on public.role_permissions for update to authenticated using (app.my_role() = 'admin') with check (app.my_role() = 'admin');
create policy perms_write_del on public.role_permissions for delete to authenticated using (app.my_role() = 'admin');
create policy settings_read  on public.app_settings for select to authenticated using (true);
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy settings_write_ins on public.app_settings for insert to authenticated with check (app.can('settings','update'));
create policy settings_write_upd on public.app_settings for update to authenticated using (app.can('settings','update')) with check (app.can('settings','update'));
create policy settings_write_del on public.app_settings for delete to authenticated using (app.can('settings','update'));

-- personnes : noms et fonctions visibles de tous (équipes, propriétaires d'actions) ; capacité réservée à l'interne
create policy people_read   on public.people for select to authenticated using (true);
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy people_write_ins on public.people for insert to authenticated with check (app.can('user','update'));
create policy people_write_upd on public.people for update to authenticated using (app.can('user','update')) with check (app.can('user','update'));
create policy people_write_del on public.people for delete to authenticated using (app.can('user','update'));
create policy people_int_read  on public.people_internal for select to authenticated using (app.is_internal());
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy people_int_write_ins on public.people_internal for insert to authenticated with check (app.can('resource','update') or app.can('settings','update'));
create policy people_int_write_upd on public.people_internal for update to authenticated using (app.can('resource','update') or app.can('settings','update')) with check (app.can('resource','update') or app.can('settings','update'));
create policy people_int_write_del on public.people_internal for delete to authenticated using (app.can('resource','update') or app.can('settings','update'));

create policy clients_read  on public.clients for select to authenticated using (app.client_visible(id));
create policy clients_write on public.clients for update to authenticated
  using (app.client_visible(id) and app.can('client','update'));
create policy contracts_read on public.client_contracts for select to authenticated
  using (app.client_visible(client_id) and app.has_money());

create policy projects_read  on public.projects for select to authenticated using (app.in_scope(id));
create policy projects_write on public.projects for update to authenticated
  using (app.in_scope(id) and app.can('project','update') and app.is_internal());
create policy proj_int_read  on public.project_internal for select to authenticated
  using (app.in_scope(project_id) and app.is_internal());
create policy proj_int_write on public.project_internal for update to authenticated
  using (app.in_scope(project_id) and app.can('resource','update'));
create policy proj_fin_read  on public.project_finance for select to authenticated
  using (app.in_scope(project_id) and app.has_money());
create policy proj_fin_write on public.project_finance for update to authenticated
  using (app.in_scope(project_id) and app.can('budget','update'));

-- actions : le client ne voit que ses actions et les actions de type Client ;
-- sans action.read, on ne voit que ses propres actions (comme l'assistant)
create policy actions_read on public.actions for select to authenticated using (
  app.in_scope(project_id)
  and (app.is_internal() or owner = app.me() or type = 'Client')
  and (app.can('action','read') or owner = app.me()));
create policy actions_insert on public.actions for insert to authenticated
  with check (app.in_scope(project_id) and app.can('action','create'));
create policy actions_update on public.actions for update to authenticated
  using (app.in_scope(project_id) and (app.can('action','update') or (owner = app.me() and not app.is_internal())));
create policy actions_delete on public.actions for delete to authenticated
  using (app.in_scope(project_id) and app.can('action','delete'));

create policy comments_read on public.action_comments for select to authenticated using (
  exists (select 1 from public.actions a where a.id = action_id)          -- hérite de la RLS des actions
  and (app.is_internal() or not internal));
create policy comments_insert on public.action_comments for insert to authenticated
  with check (author = app.me() and exists (select 1 from public.actions a where a.id = action_id)
              and (app.is_internal() or not internal));

create policy us_read  on public.user_stories for select to authenticated using (app.in_scope(project_id));
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy us_write_ins on public.user_stories for insert to authenticated with check (app.in_scope(project_id) and app.can('planning','update'));
create policy us_write_upd on public.user_stories for update to authenticated using (app.in_scope(project_id) and app.can('planning','update')) with check (app.in_scope(project_id) and app.can('planning','update'));
create policy us_write_del on public.user_stories for delete to authenticated using (app.in_scope(project_id) and app.can('planning','update'));

create policy obj_read  on public.objectives for select to authenticated
  using (app.is_internal() and (project_id is null or app.in_scope(project_id)) and app.can('action','read'));
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy obj_write_ins on public.objectives for insert to authenticated with check ((project_id is null or app.in_scope(project_id)) and (owner = app.me() or app.can('action','update')));
create policy obj_write_upd on public.objectives for update to authenticated using ((project_id is null or app.in_scope(project_id)) and (owner = app.me() or app.can('action','update'))) with check ((project_id is null or app.in_scope(project_id)) and (owner = app.me() or app.can('action','update')));
create policy obj_write_del on public.objectives for delete to authenticated using ((project_id is null or app.in_scope(project_id)) and (owner = app.me() or app.can('action','update')));

create policy todos_own on public.todos for all to authenticated
  using (owner = app.me()) with check (owner = app.me());

-- réalisations : les siennes ; celles des autres pour les rôles ACT_ALL, dans le périmètre
create policy time_read on public.time_entries for select to authenticated using (
  person_id = app.me() or (app.sees_all_activity() and app.in_scope(project_id)));
create policy time_insert on public.time_entries for insert to authenticated
  with check (app.in_scope(project_id) and (person_id = app.me() or app.can('resource','update')));
create policy time_update on public.time_entries for update to authenticated
  using (person_id = app.me() or app.can('resource','update'));
create policy time_delete on public.time_entries for delete to authenticated
  using (person_id = app.me() or app.can('resource','update'));

create policy risks_read on public.risks for select to authenticated using (
  app.in_scope(project_id) and app.can('risk','read') and (app.is_internal() or client_visible));
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy risks_write_ins on public.risks for insert to authenticated with check (app.in_scope(project_id) and (app.can('risk','create') or app.can('risk','update')));
create policy risks_write_upd on public.risks for update to authenticated using (app.in_scope(project_id) and app.can('risk','update')) with check (app.in_scope(project_id) and (app.can('risk','create') or app.can('risk','update')));
create policy risks_write_del on public.risks for delete to authenticated using (app.in_scope(project_id) and app.can('risk','update'));

create policy issues_read  on public.issues for select to authenticated using (app.in_scope(project_id));
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy issues_write_ins on public.issues for insert to authenticated with check (app.in_scope(project_id) and app.can('project','update'));
create policy issues_write_upd on public.issues for update to authenticated using (app.in_scope(project_id) and app.can('project','update')) with check (app.in_scope(project_id) and app.can('project','update'));
create policy issues_write_del on public.issues for delete to authenticated using (app.in_scope(project_id) and app.can('project','update'));

create policy cr_read   on public.change_requests for select to authenticated using (app.in_scope(project_id));
create policy cr_insert on public.change_requests for insert to authenticated
  with check (app.in_scope(project_id) and (app.my_role() = 'commercial' or app.can('project','create') or not app.is_internal()));
create policy cr_update on public.change_requests for update to authenticated
  using (app.in_scope(project_id) and (app.can('project','approve') or not app.is_internal()));
create policy cr_amt_read on public.change_request_amounts for select to authenticated using (
  exists (select 1 from public.change_requests c where c.id = cr_id) and (app.has_money() or not app.is_internal()));
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy cr_amt_write_ins on public.change_request_amounts for insert to authenticated with check (exists (select 1 from public.change_requests c where c.id = cr_id) and app.can('budget','update'));
create policy cr_amt_write_upd on public.change_request_amounts for update to authenticated using (exists (select 1 from public.change_requests c where c.id = cr_id) and app.can('budget','update')) with check (exists (select 1 from public.change_requests c where c.id = cr_id) and app.can('budget','update'));
create policy cr_amt_write_del on public.change_request_amounts for delete to authenticated using (exists (select 1 from public.change_requests c where c.id = cr_id) and app.can('budget','update'));

create policy camp_read on public.test_campaigns for select to authenticated
  using (app.in_scope(project_id) and app.can('test','read'));
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy camp_write_ins on public.test_campaigns for insert to authenticated with check (app.in_scope(project_id) and app.can('test','update'));
create policy camp_write_upd on public.test_campaigns for update to authenticated using (app.in_scope(project_id) and app.can('test','update')) with check (app.in_scope(project_id) and app.can('test','update'));
create policy camp_write_del on public.test_campaigns for delete to authenticated using (app.in_scope(project_id) and app.can('test','update'));
create policy defects_read on public.defects for select to authenticated
  using (app.in_scope(project_id) and app.can('test','read') and app.is_internal());
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy defects_write_ins on public.defects for insert to authenticated with check (app.in_scope(project_id) and (app.can('test','create') or app.can('test','update')));
create policy defects_write_upd on public.defects for update to authenticated using (app.in_scope(project_id) and app.can('test','update')) with check (app.in_scope(project_id) and (app.can('test','create') or app.can('test','update')));
create policy defects_write_del on public.defects for delete to authenticated using (app.in_scope(project_id) and app.can('test','update'));

create policy docs_read on public.documents for select to authenticated using (
  app.in_scope(project_id) and app.can('document','read') and (app.is_internal() or client_visible));
create policy docs_insert on public.documents for insert to authenticated
  with check (app.in_scope(project_id) and app.can('document','create'));
create policy docs_update on public.documents for update to authenticated
  using (app.in_scope(project_id) and (app.can('document','update') or app.can('document','approve')
         or (not app.is_internal() and client_visible)));

create policy mtg_read on public.meetings for select to authenticated using (
  app.in_scope(project_id) and (app.is_internal() or client_visible));
-- écriture uniquement : une règle « for all » s'appliquerait aussi à la lecture
create policy mtg_write_ins on public.meetings for insert to authenticated with check (app.in_scope(project_id) and app.is_internal() and app.can('action','create'));
create policy mtg_write_upd on public.meetings for update to authenticated using (app.in_scope(project_id) and app.is_internal() and app.can('action','create')) with check (app.in_scope(project_id) and app.is_internal() and app.can('action','create'));
create policy mtg_write_del on public.meetings for delete to authenticated using (app.in_scope(project_id) and app.is_internal() and app.can('action','create'));

-- journal d'audit : lecture administrateur ; chacun n'écrit qu'en son nom ; jamais modifié
create policy audit_read   on public.audit_log for select to authenticated using (app.my_role() = 'admin');
create policy audit_insert on public.audit_log for insert to authenticated with check (actor = app.me());
