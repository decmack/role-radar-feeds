import json, os, sys, tempfile, shutil, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import radar

GH = {'jobs': [
    {'id': 1, 'title': 'Head of Corporate Development', 'location': {'name': 'Sydney, NSW'}, 'absolute_url': 'u1'},
    {'id': 2, 'title': 'Software Engineer', 'location': {'name': 'Sydney'}, 'absolute_url': 'u2'},
    {'id': 3, 'title': 'Strategy Lead', 'location': {'name': 'London, UK'}, 'absolute_url': 'u3'},
    {'id': 4, 'title': 'Manager, Commercial Finance', 'location': {'name': 'AU - HQ - NSW'}, 'absolute_url': 'u4'},
    {'id': 5, 'title': 'IR Manager', 'location': {'name': ''}, 'absolute_url': 'u5'}]}
ASHBY = {'jobs': [
    {'id': 'a1', 'title': 'Chief of Staff', 'location': 'Remote', 'secondaryLocations': [], 'address': {'postalAddress': {'addressCountry': 'Australia'}}, 'jobUrl': 'ua1', 'isListed': True},
    {'id': 'a2', 'title': 'Strategy Manager', 'location': 'New York', 'secondaryLocations': [{'location': 'Sydney'}], 'jobUrl': 'ua2', 'isListed': True},
    {'id': 'a3', 'title': 'Hidden role', 'location': 'Sydney', 'jobUrl': 'ua3', 'isListed': False}]}
LEVER = [{'id': 'l1', 'text': 'FP&A Business Partner', 'categories': {'location': 'Sydney', 'allLocations': ['Sydney', 'Melbourne']}, 'hostedUrl': 'ul1'},
         {'id': 'l2', 'text': 'Financial Planning & Analysis Lead', 'categories': {'location': 'Singapore'}, 'hostedUrl': 'ul2'}]
WORK = {'jobs': [{'shortcode': 'W1', 'title': 'Treasury Analyst', 'city': 'Sydney', 'state': 'NSW', 'country': 'Australia', 'url': 'uw1'},
                 {'shortcode': 'W2', 'title': 'Director, Investments', 'city': 'Austin', 'state': 'TX', 'country': 'United States', 'url': 'uw2'}]}

SR = {'content': [{'id': 's1', 'name': 'Head of Strategy', 'location': {'city': 'Sydney', 'region': 'NSW', 'country': 'au'}},
                   {'id': 's2', 'name': 'Analyst', 'location': {'city': 'Dallas', 'country': 'us'}}]}
TT = '''<?xml version="1.0"?><rss xmlns:tt="http://teamtailor.com/locations"><channel>
<item><title>Strategy &amp; Planning Lead</title><link>https://x.teamtailor.com/jobs/111-strategy</link><tt:locations><tt:location><tt:name>HQ</tt:name><tt:city>Sydney</tt:city><tt:country>Australia</tt:country></tt:location></tt:locations></item>
<item><title>Brisbane Role</title><link>https://x.teamtailor.com/jobs/222-bne</link><tt:locations><tt:location><tt:city>Brisbane</tt:city><tt:country>Australia</tt:country></tt:location></tt:locations></item>
</channel></rss>'''

IJ = '<a class="x" href="/companies/acme-ai/jobs/head-of-strategy-123"><div>Head of Strategy</div></a><a href="/companies/acme-ai/jobs/head-of-strategy-123">dup</a><a href="/jobs/locations/sydney">x</a>'

class Loc(unittest.TestCase):
    def test_ij(self):
        r = radar.norm('inferencejobs', IJ)
        self.assertEqual(len(r), 1); self.assertEqual(r[0][1], 'Acme Ai: Head of Strategy')

    def test_new_kinds(self):
        r = radar.norm('smartrecruiters', dict(SR, company='X'))
        self.assertEqual(r[0], ('s1', 'Head of Strategy', 'Sydney, NSW, au', 'https://jobs.smartrecruiters.com/X/s1'))
        t = radar.norm('teamtailor', TT)
        self.assertEqual([x[0] for x in t], ['111', '222'])
        self.assertTrue(radar.is_sydney_eligible(t[0][2])); self.assertFalse(radar.is_sydney_eligible(t[1][2]))

    def test_rules(self):
        ok = ['Sydney', 'Sydney or Melbourne', 'AU - HQ - NSW', 'Sydney (45 Clarence St) | Melbourne | Australia', 'Australia', 'ANZ', 'APAC', '', 'Remote', 'Remote | Hybrid', 'Remote, Australia', 'North Sydney, New South Wales']
        no = ['Melbourne, Victoria, Australia', 'US-Remote', 'Remote in the US', 'London, UK', 'Brisbane', 'Remote US', 'Singapore', 'Perth, Western Australia']
        for x in ok: self.assertTrue(radar.is_sydney_eligible(x), x)
        for x in no: self.assertFalse(radar.is_sydney_eligible(x), x)

class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        cfg = json.load(open(os.path.join(radar.HERE, 'feeds.json')))
        pick = {'greenhouse': GH, 'ashby': ASHBY, 'lever': LEVER, 'workable': WORK}
        pick['smartrecruiters'] = SR; pick['teamtailor'] = TT; pick['inferencejobs'] = IJ
        self.written = set()
        for f in cfg['feeds']:
            if f['kind'] in pick and f['kind'] not in self.written:
                if f['kind'] == 'teamtailor': open(os.path.join(self.d, f"{f['kind']}-{f['slug']}.xml"), 'w').write(TT)
                elif f['kind'] == 'inferencejobs': open(os.path.join(self.d, f"{f['kind']}-{f['slug']}.xml"), 'w').write(IJ)
                else: json.dump(pick[f['kind']], open(os.path.join(self.d, f"{f['kind']}-{f['slug']}.json"), 'w'))
                self.written.add(f['kind'])
        self.seen = os.path.join(radar.HERE, 'state', 'seen.json')
        self.had = os.path.exists(self.seen)
        if self.had: shutil.copy(self.seen, self.seen + '.bak'); os.remove(self.seen)
    def tearDown(self):
        shutil.rmtree(self.d)
        if os.path.exists(self.seen): os.remove(self.seen)
        if self.had: shutil.move(self.seen + '.bak', self.seen)
    def test_norm_and_filter(self):
        out, seen = radar.run(offline=self.d)
        self.assertTrue(out['baseline'])
        gh = [n for n, v in out['feeds'].items() if v['status'] == 'ok' and 'australia' in v]
        self.assertEqual(out['feedsOk'], len(self.written))     # exactly the feed kinds this test wrote a fixture for -- never hardcode this count, it drifts whenever feeds.json's kind set changes
        first = {k: v for k, v in out['feeds'].items() if v['status'] == 'ok'}
        titles = {(r['company'], r['title']) for r in out['newRoles']}
        # greenhouse: London excluded, blank-location + AU - HQ - NSW kept, 
        ghname = next(f['name'] for f in json.load(open(os.path.join(radar.HERE, 'feeds.json')))['feeds'] if f['kind'] == 'greenhouse')
        self.assertIn((ghname, 'Head of Corporate Development'), titles)
        self.assertIn((ghname, 'Manager, Commercial Finance'), titles)
        self.assertIn((ghname, 'IR Manager'), titles)
        self.assertNotIn((ghname, 'Strategy Lead'), titles)
        self.assertIn((ghname, 'Software Engineer'), titles)
        alltitles = [r['title'] for r in out['newRoles']]
        self.assertIn('Chief of Staff', alltitles); self.assertIn('Strategy Manager', alltitles)      # ashby remote / secondary Sydney
        self.assertNotIn('Hidden role', alltitles)
        self.assertIn('FP&A Business Partner', alltitles); self.assertNotIn('Financial Planning & Analysis Lead', alltitles)
        self.assertIn('Treasury Analyst', alltitles); self.assertNotIn('Director, Investments', alltitles)
    def test_diff_and_error_keeps_snapshot(self):
        out, seen = radar.run(offline=self.d)
        os.makedirs(os.path.dirname(self.seen), exist_ok=True); json.dump(seen, open(self.seen, 'w'))
        out2, seen2 = radar.run(offline=self.d)
        self.assertFalse(out2['baseline']); self.assertEqual(out2['newCount'], 0)
        # add a role + break one feed
        g = [f for f in json.load(open(os.path.join(radar.HERE, 'feeds.json')))['feeds'] if f['kind'] == 'greenhouse'][0]
        p = os.path.join(self.d, f"greenhouse-{g['slug']}.json")
        data = json.load(open(p)); data['jobs'].append({'id': 99, 'title': 'VP Strategy', 'location': {'name': 'Sydney'}, 'absolute_url': 'u99'})
        json.dump(data, open(p, 'w'))
        out3, seen3 = radar.run(offline=self.d)
        self.assertEqual([r['id'] for r in out3['newRoles']], ['99'])
        os.remove(p)                                           # feed now errors
        out4, seen4 = radar.run(offline=self.d)
        self.assertEqual(out4['feeds'][g['name']]['status'], 'error')
        self.assertEqual(seen4[g['name']], seen[g['name']])   # last good snapshot preserved
        self.assertEqual(out4['newCount'], 0)
if __name__ == '__main__': unittest.main()
