import sys, os, re, json, time, hashlib, urllib.parse as up
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

OUT = sys.argv[1]
MAX = int(sys.argv[2])
HOST = 'www.newgloucester.com'
S = requests.Session()
S.headers['User-Agent'] = 'Mozilla/5.0 (compatible; ng-site-inventory/1.0)'
S.mount('https://', requests.adapters.HTTPAdapter(pool_maxsize=8))


def norm(u, base):
    u = u.strip()
    if not u or u.lower().startswith(('mailto:', 'tel:', 'javascript:', '#')):
        return None
    u = up.urljoin(base, u.replace('&amp;', '&'))
    p = up.urlparse(u)
    if p.netloc.lower() in ('newgloucester.com', 'www.newgloucester.com'):
        q = up.parse_qsl(p.query, keep_blank_values=True)
        q = [(k, v.strip('{}').upper() if k.upper() in ('SEC', 'DE') else v) for k, v in q]
        q.sort()
        path = re.sub(r'\s', '', p.path) or '/'
        return up.urlunparse(('https', HOST, path, '', up.urlencode(q), ''))
    return u


SKIP = re.compile(r'(\.(css|js|ico|svg|woff2?|ttf|mp4|mp3)$)|/repository/designs/', re.I)
DOC = re.compile(r'\.(pdf|docx?|xlsx?|pptx?|zip|txt|rtf|csv|jpe?g|png|gif)$|/vertical/Sites/|/uploads/', re.I)


def allowed(u):
    q = dict(up.parse_qsl(up.urlparse(u).query))
    if 'month' in q or 'year' in q:
        try:
            ym = int(q.get('year', 0)) * 12 + int(q.get('month', 1))
        except Exception:
            return False
        if not (2025 * 12 + 1 <= ym <= 2027 * 12 + 12):
            return False
    if any(k.lower() in ('searchtext', 'search', 'print', 'printer') for k in q):
        return False
    if q.get('Type') in ('B_SEARCH', 'B_PRINT'):
        return False
    return True


def fetch(u):
    h = hashlib.md5(u.encode()).hexdigest()[:12]
    err = None
    for i in range(3):
        try:
            return h, S.get(u, timeout=40)
        except Exception as e:
            err = e
            time.sleep(2 * (i + 1))
    return h, err


meta, docs, external, imgs = {}, {}, {}, {}
start = 'https://%s/' % HOST
seen = {start}
frontier = [start]


def dump():
    json.dump({'pages': meta, 'docs': docs, 'external': external, 'images': imgs},
              open(f'{OUT}/index.json', 'w'), indent=1)


with ThreadPoolExecutor(4) as ex:
    while frontier and len(meta) < MAX:
        batch, frontier = frontier[:40], frontier[40:]
        for u, (h, r) in zip(batch, ex.map(fetch, batch)):
            if isinstance(r, Exception) or r is None:
                meta[u] = {'error': str(r)}
                continue
            ct = r.headers.get('content-type', '')
            if 'html' not in ct:
                docs.setdefault(u, {'from': []})['ct'] = ct
                continue
            open(f'{OUT}/pages/{h}.html', 'wb').write(r.content)
            soup = BeautifulSoup(r.content, 'lxml')
            t = soup.title.get_text(strip=True) if soup.title else ''
            meta[u] = {'file': h, 'status': r.status_code, 'final': r.url, 'title': t}
            for im in soup.find_all('img', src=True):
                n = norm(im['src'], r.url)
                if n and '/repository/designs/' not in n:
                    imgs.setdefault(n, []).append(u)
            for tag in soup.find_all(['a', 'iframe', 'area']):
                raw = tag.get('href') or tag.get('src')
                if not raw:
                    continue
                n = norm(raw, r.url)
                if not n:
                    continue
                pp = up.urlparse(n)
                if pp.netloc == HOST:
                    if SKIP.search(pp.path):
                        continue
                    if DOC.search(pp.path):
                        docs.setdefault(n, {'from': []})['from'].append(u)
                        continue
                    if n not in seen and allowed(n):
                        seen.add(n)
                        frontier.append(n)
                else:
                    external.setdefault(n, []).append(u)
        print(len(meta), len(frontier), flush=True)
        dump()
        time.sleep(0.5)
dump()
print('DONE', len(meta), 'pages', len(docs), 'docs', len(external), 'external; frontier left', len(frontier))
