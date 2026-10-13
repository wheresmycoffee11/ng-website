"""Supplemental crawl: calendar months before the main crawl's window, plus their event pages.

Usage: python3 -I scripts/crawl_calendar.py <crawl_dir> <first_year> <last_year>
Merges into <crawl_dir>/index.json so scripts/extract.py picks the events up.
"""
import sys, os, json, time, hashlib, urllib.parse as up
import requests
from bs4 import BeautifulSoup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT, Y0, Y1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
CAL = 'DD1AC7A3-C794-4D25-9BF4-FDDB3FB73CBE'
S = requests.Session()
S.headers['User-Agent'] = 'Mozilla/5.0 (compatible; ng-site-inventory/1.0)'
idx = json.load(open(os.path.join(OUT, 'index.json')))


def norm(href):
    p = up.urlparse(up.urljoin('https://www.newgloucester.com/', href.replace('&amp;', '&')))
    q = sorted((k, v.strip('{}').upper() if k in ('SEC', 'DE') else v) for k, v in up.parse_qsl(p.query))
    return 'https://www.newgloucester.com' + p.path + '?' + up.urlencode(q)


def get(u):
    h = hashlib.md5(u.encode()).hexdigest()[:12]
    r = S.get(u, timeout=40)
    open(os.path.join(OUT, 'pages', h + '.html'), 'wb').write(r.content)
    s = BeautifulSoup(r.content, 'lxml')
    idx['pages'][u] = {'file': h, 'status': r.status_code, 'final': r.url, 'title': s.title.get_text(strip=True) if s.title else ''}
    return s


found = 0
for y in range(Y0, Y1 + 1):
    for m in range(1, 13):
        u = norm(f'/index.asp?Type=B_EV&SEC={CAL}&month={m}&year={y}')
        s = get(u)
        links = {norm(a['href']) for a in s.select('a.eventLink[href]')}
        for e in links:
            if e not in idx['pages']:
                get(e)
                found += 1
                time.sleep(0.2)
        print(y, m, len(links), flush=True)
        time.sleep(0.3)
json.dump(idx, open(os.path.join(OUT, 'index.json'), 'w'), indent=1)
print('new event pages', found)
