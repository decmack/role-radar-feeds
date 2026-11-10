#!/usr/bin/env python3
"""Feed puller: fetches public ATS JSON job APIs, keeps Sydney-eligible roles,
diffs against the previous snapshot and writes latest.json.
Stdlib only. Usage: radar.py [--offline-dir DIR]  (offline dir = fixtures named <kind>-<slug>.json, for tests)"""
import json, os, re, sys, time, datetime as dt, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'feed-cache/1.0', 'Accept': 'application/json'}
SYD = re.compile(r'sydney|\bnsw\b|new south wales', re.I)
OTHER_AU = re.compile(r'melbourne|brisbane|perth|adelaide|canberra|hobart|darwin|victoria|queensland|\bvic\b|\bqld\b|western australia', re.I)
AU_GENERIC = re.compile(r'australia|\banz\b|apac|\bau\b', re.I)
PURE_REMOTE = re.compile(r'(remote|anywhere|hybrid|flexible|[\s,;|/()\-])*', re.I)

def is_sydney_eligible(loc):
    """Sydney or multi-location incl. Sydney: keep. Other-AU-city-only: drop. Generic AU/ANZ/APAC: keep (ambiguous).
    Bare 'Remote' keep; 'US-Remote' etc. drop. Blank location: keep."""
    loc = (loc or '').strip()
    if not loc or SYD.search(loc): return True
    if OTHER_AU.search(loc): return False
    if AU_GENERIC.search(loc): return True
    return bool(PURE_REMOTE.fullmatch(loc))

def urls(f):
    s = f['slug']
    return {'greenhouse': f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs',
            'ashby': f'https://api.ashbyhq.com/posting-api/job-board/{s}',
            'lever': f'https://api.lever.co/v0/postings/{s}?mode=json',
            'workable': f'https://apply.workable.com/api/v1/widget/accounts/{s}',
            'smartrecruiters': f'https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100',
            'teamtailor': f'https://{s}/jobs.rss'}[f['kind']]

def get(url, tries=3):
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(2 * (i + 1))
    raise err

def get_text(url, tries=3):
    err = None
    for i in range(tries):
        try:
            h = dict(UA); h['Accept'] = 'application/rss+xml, application/xml, text/xml'
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            err = e
            time.sleep(2 * (i + 1))
    raise err

def fetch(f):
    k = f['kind']
    if k == 'teamtailor': return get_text(urls(f))
    if k == 'smartrecruiters':
        base, content, off = urls(f), [], 0
        while True:
            d = get(f'{base}&offset={off}')
            page = d.get('content', [])
            content += page
            off += len(page)
            if not page or off >= int(d.get('totalFound', 0)) or off > 2000: break
        return {'content': content, 'company': f['slug']}
    return get(urls(f))

def _local(t): return t.rsplit('}', 1)[-1]

def norm_teamtailor(xml):
    out = []
    root = ET.fromstring(xml)
    for it in root.iter('item'):
        title = link = ''
        locs = []
        for el in it.iter():
            t = _local(el.tag)
            if el is it: continue
            if t == 'title' and not title: title = (el.text or '').strip()
            elif t == 'link' and not link: link = (el.text or '').strip()
            elif t == 'locations' or t == 'location':
                locs += [(x.text or '').strip() for x in el.iter() if x is not el and _local(x.tag) in ('city', 'state', 'region', 'country', 'name') and (x.text or '').strip()]
        m = re.search(r'/jobs/(\d+)', link)
        rid = m.group(1) if m else (link or title)
        out.append((rid, title, ', '.join(dict.fromkeys(locs)), link))
    return out

def norm(kind, data):
    out = []
    if kind == 'greenhouse':
        for j in data.get('jobs', []):
            out.append((str(j['id']), j.get('title', ''), (j.get('location') or {}).get('name', ''), j.get('absolute_url', '')))
    elif kind == 'ashby':
        for j in data.get('jobs', []):
            if j.get('isListed') is False: continue
            locs = [j.get('location') or ''] + [(s.get('location') if isinstance(s, dict) else str(s)) or '' for s in j.get('secondaryLocations') or []]
            pa = ((j.get('address') or {}).get('postalAddress') or {})
            locs += [pa.get('addressLocality', ''), pa.get('addressRegion', ''), pa.get('addressCountry', '')]
            out.append((str(j['id']), j.get('title', ''), ' | '.join(x for x in locs if x), j.get('jobUrl', '')))
    elif kind == 'lever':
        for j in data if isinstance(data, list) else []:
            c = j.get('categories') or {}
            locs = [c.get('location') or ''] + list(c.get('allLocations') or [])
            out.append((str(j['id']), j.get('text', ''), ' | '.join(dict.fromkeys(x for x in locs if x)), j.get('hostedUrl', '')))
    elif kind == 'teamtailor':
        return norm_teamtailor(data)
    elif kind == 'smartrecruiters':
        for j in data.get('content', []):
            l = j.get('location') or {}
            loc = ', '.join(x for x in [l.get('city', ''), l.get('region', ''), l.get('country', '')] if x)
            if l.get('remote'): loc = (loc + ', Remote').strip(', ')
            out.append((str(j['id']), j.get('name', ''), loc, f"https://jobs.smartrecruiters.com/{data.get('company', '')}/{j['id']}"))
    elif kind == 'workable':
        for j in data.get('jobs', []):
            locs = [j.get('city', ''), j.get('state', ''), j.get('country', '')]
            if j.get('telecommuting'): locs.append('Remote')
            out.append((str(j.get('shortcode') or j.get('id')), j.get('title', ''), ', '.join(x for x in locs if x), j.get('url', '')))
    return out

def run(offline=None, now=None):
    with open(os.path.join(HERE, 'feeds.json')) as fh: cfg = json.load(fh)
    seen_path = os.path.join(HERE, 'state', 'seen.json')
    prev = None
    if os.path.exists(seen_path):
        with open(seen_path) as fh: prev = json.load(fh)
    baseline = prev is None
    prev = prev or {}
    def one(f):
        try:
            if offline:
                ext = 'xml' if f['kind'] == 'teamtailor' else 'json'
                with open(os.path.join(offline, f"{f['kind']}-{f['slug']}.{ext}")) as fh: data = fh.read() if ext == 'xml' else json.load(fh)
                if f['kind'] == 'smartrecruiters': data['company'] = f['slug']
            else:
                data = fetch(f)
            return f, norm(f['kind'], data), None
        except Exception as e:
            return f, None, f'{type(e).__name__}: {e}'[:200]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(one, cfg['feeds']))
    today = (now or dt.datetime.now(ZoneInfo('Australia/Sydney'))).date().isoformat()
    feeds, new, openids, seen = {}, [], {}, {}
    for f, rows, err in results:
        n = f['name']
        if err:
            feeds[n] = {'status': 'error', 'error': err}
            if n in prev: seen[n] = prev[n]          # keep last good snapshot for this feed
            continue
        au = [r for r in rows if is_sydney_eligible(r[2])]
        ids = {r[0] for r in au}
        feeds[n] = {'status': 'ok', 'total': len(rows), 'australia': len(au)}
        openids[n] = sorted(ids)
        seen[n] = sorted(ids)
        old = set(prev.get(n, []))
        for rid, title, loc, url in au:
            if baseline or n not in prev or rid not in old:
                new.append({'company': n, 'id': rid, 'title': title, 'location': loc, 'url': url})
    out = {'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'sydneyDate': today,
           'baseline': baseline, 'feedsOk': sum(1 for v in feeds.values() if v['status'] == 'ok'), 'feedsTotal': len(feeds),
           'newCount': len(new), 'feeds': feeds, 'newRoles': new, 'openIds': openids}
    return out, seen

if __name__ == '__main__':
    offline = sys.argv[sys.argv.index('--offline-dir') + 1] if '--offline-dir' in sys.argv else None
    out, seen = run(offline)
    os.makedirs(os.path.join(HERE, 'state'), exist_ok=True)
    with open(os.path.join(HERE, 'latest.json'), 'w') as fh: json.dump(out, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(HERE, 'state', 'seen.json'), 'w') as fh: json.dump(seen, fh, indent=0, sort_keys=True)
    print(f"feeds ok {out['feedsOk']}/{out['feedsTotal']}; new {out['newCount']}; baseline={out['baseline']}")
    for n, v in out['feeds'].items():
        if v['status'] != 'ok': print('ERROR', n, v['error'])
    if out['feedsOk'] == 0: sys.exit(1)
