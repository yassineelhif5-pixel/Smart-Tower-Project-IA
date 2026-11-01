"""Génère supabase/seed.sql à partir des données de démonstration de index.html.

Usage (depuis la racine du dépôt) :
    python3 supabase/generate_seed.py

La page est chargée dans Chromium (Playwright) avec un navigateur vierge ;
les listes PEOPLE, CLIENTS, PROJECTS, ACTIONS… sont lues telles que l'application
les construit, puis converties en INSERT. Le script s'arrête si un champ
n'est rattaché à aucune colonne, pour qu'aucune donnée ne soit perdue.
Variable d'environnement facultative : CHROMIUM_PATH.
"""
import json, os, pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / 'index.html').as_uri()
OUT = ROOT / 'supabase' / 'seed.sql'

DUMP = r"""()=>({
  roles:ROLES, verbs:VERBS.map(v=>v[0]), modules:MODULES.map(m=>m[0]), matrix:MATRIX,
  people:PEOPLE, clients:CLIENTS, projects:PROJECTS, actions:ACTIONS, us:USERSTORIES,
  objectives:OBJECTIVES, todos:TODOS, worklog:WORKLOG, risks:RISKS, issues:ISSUES, crs:CRS,
  campaigns:CAMPAIGNS, defects:DEFECTS, docs:DOCS, meetings:MEETINGS, audit:AUDIT,
  settings:{lifecycle:LC, thresholds:state.T, time:TIME},
  scope:Object.fromEntries(Object.keys(PEOPLE).map(id=>{const s=scopeOf(id);
    return [id, s==='*' ? '*' : PROJECTS.filter(p=>(s.clients&&s.clients.includes(p.client))||(s.projects&&s.projects.includes(p.id))).map(p=>p.id)]}))
})"""

DJANGO_FIXTURE = ROOT / 'backend' / 'projects' / 'fixtures' / 'demo.json'


def write_django_fixture(d):
    """Données lues par « python manage.py load_demo » (backend Django)."""
    people = []
    for code, u in d['people'].items():
        first, _, last = u['name'].partition(' ')
        email = None if u.get('email') in (None, '—') else u['email']
        people.append({'code': code, 'username': (email.split('@')[0] if email else code), 'first_name': first,
                       'last_name': last, 'email': email or '', 'title': u.get('title', ''), 'team': u.get('team', ''),
                       'role': u['role'], 'client': u.get('client'), 'virtual': bool(u.get('virtual'))})
    out = {
        'clients': [{'code': k, 'name': c['name'], 'sector': c.get('sector', ''), 'city': c.get('city', ''),
                     'color': c.get('color', '')} for k, c in d['clients'].items()],
        'people': people,
        'projects': [{'id': p['id'], 'code': p['code'], 'name': p['name'], 'client': p['client'], 'method': p.get('method', ''),
                      'pm': p.get('pm'), 'tl': p.get('tl'), 'start': p.get('start'), 'end': p.get('end'),
                      'progress': p.get('progress', 0)} for p in d['projects']],
        'actions': [{'id': a['id'], 'project': a['p'], 'title': a['title'], 'owner': a.get('owner'), 'status': a['status'],
                     'type': a.get('type', ''), 'due': a.get('due')} for a in d['actions']],
        'scope': d['scope'],
    }
    DJANGO_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    DJANGO_FIXTURE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{DJANGO_FIXTURE.relative_to(ROOT)} : {len(people)} personnes, {len(out["projects"])} projets')

def lit(v):
    """Littéral SQL."""
    if v is None or v == '':
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (dict, list)):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    return "'" + str(v).replace("'", "''") + "'"

def arr(v):
    """Tableau text[]."""
    return 'array[' + ','.join(lit(x) for x in v) + ']::text[]' if v else "'{}'::text[]"

def insert(table, rows):
    if not rows:
        return ''
    cols = list(rows[0].keys())
    vals = ',\n  '.join('(' + ','.join(r[c] for c in cols) + ')' for r in rows)
    return f'insert into public.{table} ({", ".join(cols)}) values\n  {vals};\n\n'

def take(obj, mapping, where):
    """Vérifie que chaque champ de obj est prévu dans mapping."""
    extra = set(obj) - set(mapping)
    if extra:
        sys.exit(f'Champ non rattaché dans {where} : {sorted(extra)}')

def main():
    exe = os.environ.get('CHROMIUM_PATH')
    with sync_playwright() as pw:
        b = pw.chromium.launch(**({'executable_path': exe} if exe else {}))
        pg = b.new_page()
        pg.route('**/*', lambda r: r.abort() if not r.request.url.startswith('file:') else r.continue_())
        pg.goto(PAGE); pg.wait_for_timeout(400)
        d = pg.evaluate(DUMP); b.close()

    sql = ['-- Données de démonstration générées par supabase/generate_seed.py — ne pas modifier à la main.\n',
           'begin;\n\n']

    sql.append(insert('roles', [dict(id=lit(k), label=lit(r['label']), question=lit(r.get('q')), money=lit(r['money']),
                                     margin=lit(r['margin']), internal=lit(r['internal'])) for k, r in d['roles'].items()]))

    perms = []
    for role, mods in d['matrix'].items():
        for m in d['modules']:
            flags = mods.get(m, [False] * 5)
            perms.append(dict(role=lit(role), module=lit(m), **{f'can_{v}': lit(bool(flags[i])) for i, v in enumerate(d['verbs'])}))
    sql.append(insert('role_permissions', perms))

    sql.append(insert('app_settings', [dict(key=lit(k), value=lit(v)) for k, v in d['settings'].items()]))

    clients, contracts = [], []
    for cid, c in d['clients'].items():
        take(c, {'managers', 'sales', 'name', 'sector', 'city', 'color', 'label', 'contacts', 'contracts'}, 'CLIENTS')
        clients.append(dict(id=lit(cid), name=lit(c['name']), sector=lit(c.get('sector')), city=lit(c.get('city')),
                            color=lit(c.get('color')), label=lit(c.get('label')), managers=arr(c.get('managers', [])),
                            sales=arr(c.get('sales', [])), contacts=lit(c.get('contacts', []))))
        for k in c.get('contracts', []):
            take(k, {'ref', 'label', 'amount', 'end', 'kind', 'renew'}, 'CLIENTS.contracts')
            contracts.append(dict(ref=lit(k['ref']), client_id=lit(cid), label=lit(k.get('label')), amount=lit(k.get('amount')),
                                  end_date=lit(k.get('end')), kind=lit(k.get('kind')), renew=lit(bool(k.get('renew')))))
    sql.append(insert('clients', clients))

    people, internal = [], []
    for pid, u in d['people'].items():
        # load est recalculé par la page (refreshLoads) : non stocké
        take(u, {'name', 'role', 'title', 'team', 'email', 'cap', 'load', 'meet', 'skills', 'virtual', 'client'}, 'PEOPLE')
        people.append(dict(id=lit(pid), name=lit(u['name']), role=lit(u['role']), title=lit(u.get('title')), team=lit(u.get('team')),
                           email=lit(None if u.get('email') in (None, '—') else u['email']), client_id=lit(u.get('client')),
                           is_virtual=lit(bool(u.get('virtual')))))
        if u.get('cap') is not None or u.get('skills') or u.get('meet') is not None:
            internal.append(dict(person_id=lit(pid), cap=lit(u.get('cap')), meet=lit(u.get('meet')), skills=arr(u.get('skills', []))))
    sql.append(insert('people', people))
    sql.append(insert('people_internal', internal))
    sql.append(insert('client_contracts', contracts))

    P_PUBLIC = {'id', 'code', 'name', 'client', 'method', 'pm', 'tl', 'team', 'desc', 'start', 'end', 'fend', 'progress', 'phases',
                'milestones', 'tests', 'keyDates', 'hyper', 'lc', 'weekPlans', 'sprints', 'sprint', 'scrum', 'sprintList'}
    P_INTERNAL = {'days', 'hBase', 'hDone', 'hRaf', 'teamLoad', 'staff'}
    P_FINANCE = {'ca', 'baseline', 'approved', 'consumed', 'rafCost', 'lines', 'causes', 'series', 'months'}
    projects, pint, pfin = [], [], []
    for p in d['projects']:
        take(p, P_PUBLIC | P_INTERNAL | P_FINANCE, 'PROJECTS')
        agile = {k: p[k] for k in ('sprints', 'sprint', 'scrum', 'sprintList') if k in p}
        projects.append(dict(id=lit(p['id']), code=lit(p['code']), name=lit(p['name']), client_id=lit(p['client']), method=lit(p.get('method')),
                             pm=lit(p.get('pm')), tl=lit(p.get('tl')), team=arr(p.get('team', [])), descr=lit(p.get('desc')),
                             start_date=lit(p.get('start')), end_date=lit(p.get('end')), forecast_end=lit(p.get('fend')),
                             progress=lit(p.get('progress', 0)), phases=lit(p.get('phases', [])), milestones=lit(p.get('milestones', [])),
                             tests=lit(p.get('tests', {})), key_dates=lit(p.get('keyDates', [])), hyper=lit(p.get('hyper')),
                             lifecycle=lit(p.get('lc', [])), week_plans=lit(p.get('weekPlans', {})), agile=lit(agile or None)))
        pint.append(dict(project_id=lit(p['id']), days=lit(p.get('days')), h_base=lit(p.get('hBase')), h_done=lit(p.get('hDone')),
                         h_raf=lit(p.get('hRaf')), team_load=lit(p.get('teamLoad')), staff=lit(p.get('staff', []))))
        pfin.append(dict(project_id=lit(p['id']), ca=lit(p.get('ca')), baseline=lit(p.get('baseline')), approved=lit(p.get('approved')),
                         consumed=lit(p.get('consumed')), raf_cost=lit(p.get('rafCost')), lines=lit(p.get('lines', [])),
                         causes=lit(p.get('causes', [])), series=lit(p.get('series')), months=lit(p.get('months'))))
    sql.append(insert('projects', projects))
    sql.append(insert('project_internal', pint))
    sql.append(insert('project_finance', pfin))

    actions, comments = [], []
    for a in d['actions']:
        take(a, {'id', 'p', 'title', 'phase', 'owner', 'prio', 'status', 'est0', 'est', 'done', 'raf', 'start', 'due', 'fdue', 'type',
                 'block', 'comments', 'history', 'stage', 'doneAt', 'us'}, 'ACTIONS')
        actions.append(dict(id=lit(a['id']), project_id=lit(a['p']), title=lit(a['title']), phase=lit(a.get('phase')), owner=lit(a.get('owner')),
                            prio=lit(a.get('prio')), status=lit(a['status']), est0=lit(a.get('est0')), est=lit(a.get('est')),
                            done=lit(a.get('done')), raf=lit(a.get('raf')), start_date=lit(a.get('start')), due=lit(a.get('due')),
                            fdue=lit(a.get('fdue')), type=lit(a.get('type')), block="''" if not a.get('block') else lit(a['block']),
                            stage=lit(a.get('stage')), us=lit(a.get('us')), done_at=lit(a.get('doneAt')), history=lit(a.get('history', []))))
        for c in a.get('comments', []):
            take(c, {'w', 'at', 't', 'internal'}, 'ACTIONS.comments')
            comments.append(dict(action_id=lit(a['id']), author=lit(c.get('w')), at=lit(c.get('at')), body=lit(c['t']),
                                 internal=lit(bool(c.get('internal')))))
    sql.append(insert('actions', actions))
    sql.append(insert('action_comments', comments))

    rows = []
    for u in d['us']:
        take(u, {'id', 'p', 'sprint', 'title', 'pts', 'prio', 'story', 'ac', 'closed'}, 'USERSTORIES')
        rows.append(dict(id=lit(u['id']), project_id=lit(u['p']), sprint=lit(u.get('sprint')), title=lit(u['title']), pts=lit(u.get('pts')),
                         prio=lit(u.get('prio')), story=lit(u.get('story')), ac=lit(u.get('ac')), closed=lit(u.get('closed'))))
    sql.append(insert('user_stories', rows))

    rows = []
    for o in d['objectives']:
        take(o, {'id', 'scope', 'p', 'owner', 'title', 'due', 'items'}, 'OBJECTIVES')
        rows.append(dict(id=lit(o['id']), scope=lit(o.get('scope')), project_id=lit(o.get('p')), owner=lit(o.get('owner')),
                         title=lit(o['title']), due=lit(o.get('due')), items=lit(o.get('items', []))))
    sql.append(insert('objectives', rows))

    rows = [dict(owner=lit(who), label=lit(t[0]), done=lit(bool(t[1])), position=lit(i))
            for who, lst in d['todos'].items() for i, t in enumerate(lst)]
    sql.append(insert('todos', rows))

    rows = []
    for w in d['worklog']:
        take(w, {'who', 'a', 'p', 'date', 'h', 'meet'}, 'WORKLOG')
        rows.append(dict(person_id=lit(w['who']), action_id=lit(w.get('a')), project_id=lit(w['p']), work_date=lit(w['date']),
                         hours=lit(w['h']), is_meeting=lit(bool(w.get('meet')))))
    sql.append(insert('time_entries', rows))

    rows = []
    for r in d['risks']:
        take(r, {'id', 'p', 'title', 'prob', 'imp', 'owner', 'status', 'due', 'mit', 'client', 'acts'}, 'RISKS')
        rows.append(dict(id=lit(r['id']), project_id=lit(r['p']), title=lit(r['title']), prob=lit(r.get('prob')), imp=lit(r.get('imp')),
                         owner=lit(r.get('owner')), status=lit(r.get('status')), due=lit(r.get('due')), mitigation=lit(r.get('mit')),
                         client_visible=lit(bool(r.get('client'))), actions=arr(r.get('acts', []))))
    sql.append(insert('risks', rows))

    rows = []
    for i in d['issues']:
        take(i, {'id', 'p', 'kind', 'title', 'prio', 'owner', 'due', 'impact'}, 'ISSUES')
        rows.append(dict(id=lit(i['id']), project_id=lit(i['p']), kind=lit(i.get('kind')), title=lit(i['title']), prio=lit(i.get('prio')),
                         owner=lit(i.get('owner')), due=lit(i.get('due')), impact=lit(i.get('impact'))))
    sql.append(insert('issues', rows))

    rows, amts = [], []
    for c in d['crs']:
        take(c, {'id', 'p', 'title', 'by', 'h', 'days', 'amt', 'status', 'vdate', 'fn', 'tech'}, 'CRS')
        rows.append(dict(id=lit(c['id']), project_id=lit(c['p']), title=lit(c['title']), requested_by=lit(c.get('by')), hours=lit(c.get('h')),
                         days=lit(c.get('days')), status=lit(c.get('status')), vdate=lit(c.get('vdate')), fn=lit(c.get('fn')), tech=lit(c.get('tech'))))
        amts.append(dict(cr_id=lit(c['id']), amount=lit(c.get('amt'))))
    sql.append(insert('change_requests', rows))
    sql.append(insert('change_request_amounts', amts))

    rows = []
    for c in d['campaigns']:
        take(c, {'id', 'p', 'name', 'env', 'version', 'total', 'pass', 'fail', 'todo', 'crit', 'owner'}, 'CAMPAIGNS')
        rows.append(dict(id=lit(c['id']), project_id=lit(c['p']), name=lit(c.get('name')), env=lit(c.get('env')), version=lit(c.get('version')),
                         total=lit(c.get('total')), **{'pass': lit(c.get('pass'))}, fail=lit(c.get('fail')), todo=lit(c.get('todo')),
                         crit=lit(c.get('crit')), owner=lit(c.get('owner'))))
    sql.append(insert('test_campaigns', rows))

    rows = []
    for b in d['defects']:
        take(b, {'id', 'p', 'title', 'sev', 'status', 'owner'}, 'DEFECTS')
        rows.append(dict(id=lit(b['id']), project_id=lit(b['p']), title=lit(b['title']), sev=lit(b.get('sev')), status=lit(b.get('status')),
                         owner=lit(b.get('owner'))))
    sql.append(insert('defects', rows))

    rows = []
    for x in d['docs']:
        take(x, {'id', 'name', 'ext', 'size', 'p', 'type', 'dstat', 'entity', 'by', 'at', 'v', 'status', 'client'}, 'DOCS')
        rows.append(dict(id=lit(x['id']), project_id=lit(x['p']), name=lit(x['name']), ext=lit(x.get('ext')), size_mb=lit(x.get('size')),
                         type=lit(x.get('type')), dstat=lit(x.get('dstat')), entity=lit(x.get('entity')), uploaded_by=lit(x.get('by')),
                         uploaded_at=lit(x.get('at')), version=lit(x.get('v', 1)), scan_status=lit(x.get('status')),
                         client_visible=lit(bool(x.get('client')))))
    sql.append(insert('documents', rows))

    rows = []
    for m in d['meetings']:
        take(m, {'id', 'p', 'type', 'title', 'date', 'time', 'dur', 'org', 'att', 'ext', 'agenda', 'notes', 'decisions', 'acts', 'doc',
                 'client', 'status'}, 'MEETINGS')
        rows.append(dict(id=lit(m['id']), project_id=lit(m['p']), type=lit(m.get('type')), title=lit(m['title']), date=lit(m.get('date')),
                         time=lit(m.get('time')), dur=lit(m.get('dur')), organizer=lit(m.get('org')), attendees=arr(m.get('att', [])),
                         external=arr(m.get('ext', [])), agenda=arr(m.get('agenda', [])), notes=lit(m.get('notes')),
                         decisions=arr(m.get('decisions', [])), actions=arr(m.get('acts', [])), doc=lit(m.get('doc')),
                         client_visible=lit(bool(m.get('client'))), status=lit(m.get('status'))))
    sql.append(insert('meetings', rows))

    rows = [dict(at=lit(a[0]), actor=lit(a[1]), entity=lit(a[2]), event=lit(a[3]), old_value=lit(a[4]), new_value=lit(a[5]),
                 trace=lit(a[6])) for a in d['audit']]
    sql.append(insert('audit_log', rows))

    write_django_fixture(d)
    sql.append('commit;\n')
    OUT.write_text(''.join(sql), encoding='utf-8')
    print(f'{OUT.relative_to(ROOT)} : {sum(s.count(chr(10) + "  (") for s in sql)} lignes de données')

if __name__ == '__main__':
    main()
