#!/usr/bin/env python3
"""Helper for the daily scan task. Usage: rr.py W load [REPO] | rules | mark "<failed feeds ;-separated>" [REPO]
W = working dir holding the ArtifactData dumps (W/meta/config.json, W/meta/feedState.json, W/jobs/*.json)
REPO = clone of the feed repo (latest.json from the nightly Actions pull); optional."""
import json, glob, os, sys, re, datetime as dt
from zoneinfo import ZoneInfo
W, cmd = sys.argv[1], sys.argv[2]
REPO = sys.argv[3] if len(sys.argv) > 3 and cmd == 'load' else (sys.argv[4] if len(sys.argv) > 4 else None)
def L(p):
    with open(os.path.join(W, p)) as fh: return json.load(fh)
norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())
cfg = L('meta/config.json')
now = dt.datetime.now(ZoneInfo('Australia/Sydney')); today = now.date()
try: seen = L('meta/feedState.json').get('lastChecked', {})
except Exception: seen = {}
weekly = today.strftime('%A').lower() in str(cfg.get('weeklyCheckDay', 'Monday')).lower()
slow = int(cfg.get('slowCadenceDays', 3))
KW = [k.lower() for k in (cfg.get('keywords') or []) + (cfg.get('titleKeywordsExtra') or [])]
WB = [k.lower() for k in (cfg.get('titleKeywordsWordBoundary') or [])]
def kw_match(title):
    t = title.lower()
    return any(k in t for k in KW) or any(re.search(r'\b%s\b' % re.escape(k), t) for k in WB)
latest, covered, repo_note = None, set(), 'no repo supplied'
if REPO and os.path.exists(os.path.join(REPO, 'latest.json')):
    with open(os.path.join(REPO, 'latest.json')) as fh: latest = json.load(fh)
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(latest['generatedAt'])).total_seconds() / 3600
    if age <= 30:
        covered = {n for n, v in latest['feeds'].items() if v.get('status') == 'ok'}
        repo_note = 'repo pull %.0fh old: %d feeds covered, %d errored' % (age, len(covered), len(latest['feeds']) - len(covered))
    else:
        repo_note = 'repo pull is %.0fh old -- STALE, ignored; fetch all due feeds yourself' % age; latest = None
elif REPO: repo_note = 'latest.json missing in repo'
def due(c):
    if c['name'] in covered: return False
    cad = c.get('cadence')
    if cad == 'weekly': return weekly
    if cad == 'every-3-days':
        d = seen.get(c['name'])
        return not d or (today - dt.date.fromisoformat(d)).days >= slow
    return True
feeds = [c for c in cfg['companies'] if c.get('mode') == 'feed']
D = [c for c in feeds if due(c)]
if cmd == 'load':
    jobs = []
    for p in sorted(glob.glob(os.path.join(W, 'jobs', '*.json'))):
        with open(p) as fh: j = json.load(fh)
        j['_id'] = os.path.basename(p)[:-5]; j['_live'] = (j.get('status') or 'new') not in ('passed', 'rejected'); jobs.append(j)
    print('TODAY', today, today.strftime('%A'), '| weeklyCheckDay today:', weekly, '|', repo_note)
    for k in ('keywords', 'emailThreshold', 'fetchGuidance', 'writeGuidance'): print(k.upper() + ':', json.dumps(cfg.get(k), ensure_ascii=False))
    fn = cfg.get('feedNotes', {})
    for k in ['indeed', 'inferencejobs'] + (['seek'] if weekly else []): print('FEEDNOTE ' + k + ':', fn.get(k, ''))
    print('\nDUE FEEDS TO FETCH YOURSELF (%d of %d feeds; %d covered by the repo pull) -- name | url | scope | note' % (len(D), len(feeds), len(covered)))
    for c in D: print(' | '.join([c['name'], c.get('url') or '', c.get('fetchScope') or 'all', c.get('note') or '']))
    print('\nNOT DUE TODAY (skip; do not record):', ', '.join(c['name'] for c in feeds if c not in D and c['name'] not in covered))
    for m in ('browser', 'external'): print('MODE ' + m + ' (record status only):', ', '.join(c['name'] for c in cfg['companies'] if c.get('mode') == m))
    print('\nOUTSIDE FEEDS:'); [print(u) for u in cfg.get('outsideFeeds', []) + (cfg.get('outsideFeedsSeekWeekly', []) if weekly else [])]
    def cov_for(company):
        k = norm(company)
        return next((n for n in covered if norm(n) and (norm(n) in k or k in norm(n))), None)
    def is_known(company, rid, title):
        k = norm(company)
        for j in jobs:
            jk = norm(j.get('company'))
            if not (jk == k or (k and jk and (k in jk or jk in k))): continue
            tail = j['_id'].rsplit('-', 1)[-1].lower()
            if tail and len(tail) >= 4 and rid.lower().startswith(tail): return True
            if norm(j.get('title')) == norm(title): return True
        return False
    print('\nKNOWN ROLES -- id | company | title | LIVE:<status> when the user has not passed on / rejected it | repo check')
    for j in jobs:
        tag = ''
        if j['_live'] and not re.match(r'(seek|indeed|linkedin)-', j['_id']):
            f = cov_for(j.get('company', ''))
            if f:
                tail = j['_id'].rsplit('-', 1)[-1].lower()
                opened = any(o.lower().startswith(tail) for o in latest['openIds'].get(f, [])) if tail else False
                tag = 'OPEN-IN-REPO' if opened else 'NOT-OPEN-IN-REPO'
        print(' | '.join([j['_id'], str(j.get('company')), str(j.get('title'))[:60], ('LIVE:' + (j.get('status') or 'new')) if j['_live'] else '', tag]))
    if latest and covered:
        kwr = [r for r in latest['newRoles'] if r['company'] in covered and kw_match(r['title'])]
        unk = [r for r in kwr if not is_known(r['company'], r['id'], r['title'])]
        print('\nREPO FEEDS: baseline=%s; %d new roles since the previous pull, %d title-keyword matches, %d of those not yet in the tracker' % (latest['baseline'], latest['newCount'], len(kwr), len(unk)))
        print('REPO FEED ERRORS (fetch these yourself if they are in the DUE list above):', {n: v.get('error') for n, v in latest['feeds'].items() if v.get('status') != 'ok'})
        print('UNKNOWN KEYWORD ROLES FROM REPO (company | ats id | title | location | url) -- apply Step 4, read and score:')
        for r in unk: print(' | '.join([r['company'], r['id'], r['title'], r['location'], r['url']]))
        print('RUN RECORD ENTRIES FOR REPO FEEDS (merge into runs/<today>.companies):')
        print(json.dumps({n: {'status': 'ok', 'total': v['total'], 'sydney': v['australia'], 'note': 'repo pull'} for n, v in latest['feeds'].items() if v.get('status') == 'ok'}))
elif cmd == 'rules':
    for k in ('positioningStrategy', 'employerTrajectory'): print(k.upper() + ':', json.dumps(cfg.get(k), ensure_ascii=False))
elif cmd == 'mark':
    failed = {x.strip() for x in (sys.argv[3] if len(sys.argv) > 3 else '').split(';') if x.strip()}
    for c in D:
        if c['name'] not in failed: seen[c['name']] = str(today)
    with open(os.path.join(W, 'feedState_out.json'), 'w') as fh: json.dump({'lastChecked': seen, 'updated': str(today)}, fh)
    print('wrote feedState_out.json;', len([c for c in D if c['name'] not in failed]), 'feeds marked checked', today)
