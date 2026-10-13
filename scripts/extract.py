"""Turn a crawl of the legacy newgloucester.com site into the JSON data the Astro site renders.

Usage (run from anywhere, after scripts/crawl.py):
    python3 -I scripts/extract.py <crawl_dir> <repo_dir>

Inputs:  <crawl_dir>/index.json and <crawl_dir>/pages/*.html
Outputs: <repo_dir>/src/data/{nav,pages,records,redirects,inventory}.json
         <repo_dir>/public/media/uploads/*  (content images, downloaded once)

Every legacy URL that returned 200 ends up in exactly one place: a page, a record, or a
redirect to a page/record/file. scripts/audit.py checks that claim against the build.
"""
import sys, os, re, json, hashlib, collections, urllib.parse as up
import requests
import html as htmllib
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

CRAWL, REPO = sys.argv[1], sys.argv[2]
HOST = 'https://www.newgloucester.com'
DATA = os.path.join(REPO, 'src', 'data')
MEDIA = os.path.join(REPO, 'public', 'media', 'uploads')
os.makedirs(DATA, exist_ok=True)
os.makedirs(MEDIA, exist_ok=True)

idx = json.load(open(os.path.join(CRAWL, 'index.json')))
P = idx['pages']
_soups = {}


def soup(u):
    if u not in _soups:
        _soups[u] = BeautifulSoup(open(os.path.join(CRAWL, 'pages', P[u]['file'] + '.html'), 'rb').read(), 'lxml')
    return _soups[u]


def qs(u):
    return dict(up.parse_qsl(up.urlparse(u).query))


def norm(u, base=HOST + '/'):
    """Same normalisation the crawler used, so lookups line up."""
    u = (u or '').strip()
    if not u or u.lower().startswith(('mailto:', 'tel:', 'javascript:', '#')):
        return None
    u = up.urljoin(base, u.replace('&amp;', '&'))
    p = up.urlparse(u)
    if p.netloc.lower() in ('newgloucester.com', 'www.newgloucester.com'):
        q = up.parse_qsl(p.query, keep_blank_values=True)
        q = [(k, v.strip('{}').upper() if k.upper() in ('SEC', 'DE') else v) for k, v in q]
        q.sort()
        path = re.sub(r'\s', '', p.path) or '/'
        return up.urlunparse(('https', 'www.newgloucester.com', path, '', up.urlencode(q), ''))
    return u


def slugify(s):
    s = s.lower().replace('&', ' and ').replace("'", '').replace('#', '')
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return re.sub(r'-{2,}', '-', s)[:80].strip('-') or 'page'


def clean_title(t):
    return re.sub(r'\s+', ' ', re.sub(r'\s*-\s*New Gloucester, Maine\s*$', '', t or '')).strip()


ok = {u: m for u, m in P.items() if m.get('status') == 200 and 'file' in m}

# ---------------------------------------------------------------- page groups (dedupe)
def main_hash(u):
    mc = soup(u).select_one('main.content')
    return hashlib.md5(mc.get_text(' ', strip=True).encode()).hexdigest() if mc else None


def pref(u):
    q = qs(u)
    # friendly path first, then bare SEC, then anything with Type/MODE
    return (0 if not q else 1 if set(q) == {'SEC'} else 2, len(u))


section_urls = [u for u in ok if 'DE' not in qs(u) and 'month' not in qs(u)]
groups = collections.defaultdict(list)
for u in section_urls:
    h = main_hash(u)
    if h:
        groups[h].append(u)
canon_of = {}
for us in groups.values():
    us.sort(key=pref)
    for u in us:
        canon_of[u] = us[0]
canon_pages = sorted(set(canon_of.values()))

# ---------------------------------------------------------------- nav tree from the homepage
home = soup(HOST + '/')
nav_root = home.select_one('nav.primary > ul')


def walk(ul):
    out = []
    for li in ul.find_all('li', recursive=False):
        a = li.find('a')
        if not a:
            continue
        n = norm(a.get('href'))
        if not a.get_text(strip=True):
            continue  # icon-only links (search button) in the legacy menu
        item = {'title': re.sub(r'\s+', ' ', a.get_text(strip=True)), 'legacy': canon_of.get(n, n), 'children': []}
        sub = li.find('ul')
        if sub:
            item['children'] = walk(sub)
        out.append(item)
    return out


nav_tree = walk(nav_root)

# ---------------------------------------------------------------- paths
path_of = {}      # canonical legacy url -> new path
parent_of = {}    # canonical legacy url -> canonical legacy parent
nav_title = {}

FRIENDLY_FIX = {'/Accessibility': '/accessibility'}


def own_path(u, parent_path, title):
    p = up.urlparse(u)
    if not p.query and p.path != '/':
        return FRIENDLY_FIX.get(p.path, p.path.lower())
    return (parent_path.rstrip('/') + '/' + slugify(title)) if parent_path else '/' + slugify(title)


def assign(items, parent_url, parent_path):
    for it in items:
        u = it['legacy']
        if u not in path_of:
            path_of[u] = '/' if u == HOST + '/' else own_path(u, parent_path, it['title'])
            parent_of[u] = parent_url
            nav_title[u] = it['title']
        assign(it['children'], u, path_of[u])


assign(nav_tree, None, '')

# non-nav pages: parent = first canonical page that links to them (BFS order of crawl)
links_from = collections.defaultdict(list)
for u in canon_pages:
    for a in soup(u).select('main.content a[href]'):
        n = norm(a['href'], u)
        if n in canon_of:
            links_from[canon_of[n]].append(u)

pending = [u for u in canon_pages if u not in path_of]
for _ in range(6):
    left = []
    for u in pending:
        refs = [r for r in links_from.get(u, []) if r in path_of and r != u]
        if not refs and up.urlparse(u).query:
            left.append(u)
            continue
        par = refs[0] if refs else None
        h1 = soup(u).select_one('main.content h1')
        title = clean_title(soup(u).title.get_text()) or (h1.get_text(strip=True) if h1 else 'page')
        path_of[u] = own_path(u, path_of.get(par, ''), title)
        parent_of[u] = par
    pending = left
for u in pending:  # orphans (nothing links to them): still keep them
    path_of[u] = '/archive/' + slugify(clean_title(soup(u).title.get_text()))
    parent_of[u] = None

# special replacements: pages the new site renders with purpose-built templates
SPECIAL = {
    HOST + '/': '/',
    HOST + '/site-map': '/site-map',
    HOST + '/news': '/news',
}
cal_list = [u for u in canon_pages if 'B_EV' in u or 'DD1AC7A3' in u]
for u in cal_list:
    SPECIAL[u] = '/municipal-calendar'
news_list = [u for u in canon_pages if 'B_PR' in u]
for u in news_list:
    SPECIAL[u] = '/news'
for u, p in SPECIAL.items():
    if u in path_of:
        path_of[u] = p

# de-duplicate any colliding paths
seen = collections.Counter()
for u in sorted(path_of, key=lambda x: (pref(x), x)):
    p = path_of[u]
    if u in SPECIAL:
        continue
    seen[p] += 1
    if seen[p] > 1:
        path_of[u] = f'{p}-{seen[p]}'

# ---------------------------------------------------------------- media download
img_map = {}


def shrink(path, max_w=1600):
    from PIL import Image
    try:
        im = Image.open(path)
        if im.format not in ('JPEG', 'PNG') or im.width <= max_w and os.path.getsize(path) < 400_000:
            return
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
        if im.format == 'JPEG' or path.lower().endswith(('.jpg', '.jpeg')):
            im.convert('RGB').save(path, 'JPEG', quality=80, optimize=True, progressive=True)
        else:
            im.save(path, 'PNG', optimize=True)
    except Exception as e:
        print('shrink failed', path, e)


def local_image(src_url):
    if src_url in img_map:
        return img_map[src_url]
    name = up.unquote(up.urlparse(src_url).path.rsplit('/', 1)[-1])
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', name)
    dest = os.path.join(MEDIA, name)
    if not os.path.exists(dest):
        try:
            r = requests.get(src_url, timeout=60, headers={'User-Agent': 'Mozilla/5.0 (ng-site-migration)'})
            if r.status_code != 200 or not r.headers.get('content-type', '').startswith('image'):
                img_map[src_url] = src_url
                return src_url
            open(dest, 'wb').write(r.content)
            shrink(dest)
        except Exception:
            img_map[src_url] = src_url
            return src_url
    img_map[src_url] = '/media/uploads/' + name
    return img_map[src_url]


# ---------------------------------------------------------------- records (DE pages)
records = {}
broken = {u for u, m in P.items() if m.get('status') and m.get('status') != 200}


def file_info(href):
    href = href.strip()
    url = norm(href)
    if url and url.startswith('https://www.newgloucester.com'):
        url = url.split('?')[0] if not up.urlparse(url).query else url
    name = up.unquote(up.urlparse(url).path.rsplit('/', 1)[-1])
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    return {'name': name, 'url': url, 'ext': ext}


MONTHS = 'january|february|march|april|may|june|july|august|september|october|november|december'
MON_ABBR = {m[:3]: i + 1 for i, m in enumerate(MONTHS.split('|'))}


TYPOS = {'novembr': 'november', 'februaty': 'february', 'janaury': 'january'}


def date_from_title(t):
    for k, v in TYPOS.items():
        t = re.sub(k, v, t, flags=re.I)
    m = re.search(r'\b(0[1-9]|1[0-2])([0-3]\d)(20\d\d)\b', t)
    if m:
        return f'{m.group(3)}-{m.group(1)}-{m.group(2)}'
    m = re.search(r'(' + MONTHS + r'|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})', t, re.I)
    if m:
        mo = MON_ABBR[m.group(1)[:3].lower()]
        y = int(m.group(3))
        if 1990 <= y <= 2035:
            return f'{y:04d}-{mo:02d}-{int(m.group(2)):02d}'
    m = re.search(r'\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b', t)
    if m:
        mo, dd, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        if 1 <= mo <= 12 and 1 <= dd <= 31 and 1990 <= y <= 2035:
            return f'{y:04d}-{mo:02d}-{dd:02d}'
    return None


# event dates from calendar month grids
event_dates = collections.defaultdict(set)
for u in ok:
    q = qs(u)
    if 'month' not in q:
        continue
    y, mo = int(q['year']), int(q['month'])
    s = soup(u)
    for td in s.select('table.calendarTable td.calDay'):
        num = td.select_one('.calDayNum')
        if not num:
            continue
        for a in td.select('a.eventLink'):
            n = norm(a['href'], u)
            de = qs(n).get('DE')
            if de:
                event_dates[de].add(f'{y:04d}-{mo:02d}-{int(num.get_text(strip=True)):02d}')
    # list mode: h2 "October 2026" then items
    for art in s.select('article.summaryDisplay'):
        for a in art.select('a.item'):
            pass  # list mode carries no day numbers; grid covers the same events

for u in ok:
    q = qs(u)
    if 'DE' not in q:
        continue
    s = soup(u)
    art = s.select_one('main.content article.fullDisplay')
    if not art:
        continue
    kind = {'B_EV': 'event', 'B_PR': 'news', 'B_JOB': 'job'}.get(art['class'][-1], 'item')
    h1 = art.find('h1')
    title = re.sub(r'\s+', ' ', h1.get_text(' ', strip=True)) if h1 else clean_title(P[u]['title'])
    atts = []
    for a in art.select('.attachments a.link'):
        fi = file_info(a['href'])
        fi['label'] = a.get_text(strip=True)
        atts.append(fi)
    contact = art.select_one('.property.contactInfo')
    side = s.select_one('main.content .rightContent')
    side = side if side and side.get_text(strip=True) else None
    if kind == 'event':
        body = art.select_one('.description')
        dt = art.select_one('.eventsdatetime')
        dt_text = dt.get_text(' ', strip=True) if dt else ''
    elif kind == 'job':
        body = BeautifulSoup(str(art), 'lxml').find('article')
        for x in body.select('h1, .attachments'):
            x.decompose()
        dt_text = ''
    else:
        body = art.select_one('div.body > div.body') or art.select_one('div.body')
        if body is not None and body.find('h1'):
            body = BeautifulSoup(str(body), 'lxml').find('div')
            body.find('h1').decompose()
            for x in body.select('.newsdatetime'):
                x.decompose()
        dt = art.select_one('.newsdatetime')
        dt_text = dt.get_text(' ', strip=True) if dt else ''
    records[q['DE']] = {
        'id': q['DE'], 'sec': q.get('SEC'), 'kind': kind, 'title': title,
        'legacy': u, '_body': body, '_contact': contact,
        'attachments': atts, 'dateText': dt_text, '_side': side,
        'dates': sorted(event_dates.get(q['DE'], [])),
        'date': None,
    }

# which canonical page lists each record (first one wins)
listed_on = {}
for u in canon_pages:
    for a in soup(u).select('main.content a[href]'):
        n = norm(a['href'], u)
        de = qs(n).get('DE') if n else None
        if de and de in records and de not in listed_on:
            listed_on[de] = u


# ---------------------------------------------------------------- tidy: give legacy markup real structure
BLOCK = {'p', 'div', 'ul', 'ol', 'table', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'blockquote', 'iframe',
         'section', 'article', 'aside', 'figure', 'dl', 'main', 'header', 'footer'}
CONTAINERS = ['div', 'section', 'article', 'aside', 'main', 'header', 'footer', 'figure']
BULLET = re.compile(r'^\s*[•➢❖·►▪■◦●○✓✔➤→\-–*]\s+')
SENTENCE_END = re.compile(r'[.!?:)]["”’]?$')


def _placeholder(t):
    return isinstance(t, Tag) and t.name == 'div' and 'record-list' in (t.get('class') or [])


def _meaningful(nodes):
    return [n for n in nodes if not (isinstance(n, NavigableString) and not n.strip())]


def _is_block(n):
    return isinstance(n, Tag) and (n.name in BLOCK or _placeholder(n))


def _split_on_br(p, frag, min_run):
    """Split a <p> into several wherever `min_run` or more <br> sit in a row."""
    segs, cur, run = [], [], []
    for c in list(p.children):
        if isinstance(c, Tag) and c.name == 'br':
            run.append(c)
            continue
        if isinstance(c, NavigableString) and not c.strip() and run:
            continue
        if run:
            if len(run) >= min_run:
                segs.append(cur)
                cur = []
            else:
                cur.extend(run)
            run = []
        cur.append(c)
    segs.append(cur)
    segs = [sg for sg in segs if _meaningful(sg)]
    if len(segs) <= 1:
        for b in run:
            b.extract()
        return [p]
    out = []
    for sg in segs:
        np_ = frag.new_tag('p')
        for c in sg:
            np_.append(c.extract())
        p.insert_before(np_)
        out.append(np_)
    p.decompose()
    return out


def _lines(p):
    """Text of each <br>-separated line in a <p>."""
    lines, cur = [], ''
    for c in p.children:
        if isinstance(c, Tag) and c.name == 'br':
            lines.append(cur.strip())
            cur = ''
        else:
            cur += c.get_text() if isinstance(c, Tag) else str(c)
    lines.append(cur.strip())
    return [l for l in lines if l]


def tidy(root, frag):
    # 1. flatten wrapper containers; a container holding only inline content becomes a paragraph
    for t in root.find_all(CONTAINERS):
        if t.parent is None or _placeholder(t):
            continue
        if t.find_parent(['table', 'li', 'blockquote']):
            t.unwrap()
        elif any(_is_block(c) for c in t.children):
            t.unwrap()
        else:
            t.name = 'p'
    # 2. wrap loose inline runs at the top level in paragraphs
    run = []

    def flush():
        if _meaningful(run):
            np_ = frag.new_tag('p')
            run[0].insert_before(np_)
            for c in run:
                np_.append(c.extract())
        run.clear()
    for c in list(root.children):
        if _is_block(c):
            flush()
        else:
            run.append(c)
    flush()
    # 3. paragraphs: split on blank lines; split sentence-length lines and bullet lines
    for p in list(root.find_all('p')):
        if p.parent is None or p.find_parent(['table']):
            continue
        for q in _split_on_br(p, frag, 2):
            lines = _lines(q)
            bullets = sum(1 for l in lines if BULLET.match(l))
            long_lines = sum(1 for l in lines if len(l) > 70 and SENTENCE_END.search(l))
            if len(lines) > 1 and (bullets >= 2 or long_lines >= 2 or (long_lines and long_lines == len(lines) - 1 and len(lines) <= 3)):
                _split_on_br(q, frag, 1)
    # 4. a bold lead-in on its own line becomes a heading ("Charge:<br>Implement...")
    def all_bold(el):
        k = _meaningful(el.contents) if isinstance(el, Tag) and el.name == 'p' else []
        return bool(k) and all(isinstance(c, Tag) and (c.name in ('strong', 'b') or c.name == 'br') for c in k)
    bold_block = set()
    run = []
    for c in [c for c in root.children if isinstance(c, Tag)] + [None]:
        if c is not None and all_bold(c):
            run.append(c)
            continue
        if len(run) >= 3 or any(len(r.find_all(['strong', 'b'])) >= 3 for r in run):
            bold_block.update(id(r) for r in run)
        run = []
    for p in list(root.find_all('p')):
        if id(p) in bold_block or len(p.find_all(['strong', 'b'], recursive=False)) >= 3:
            continue
        if p.parent is None or p.find_parent(['table', 'li']):
            continue
        kids = _meaningful(p.contents)
        if not kids or not isinstance(kids[0], Tag) or kids[0].name not in ('strong', 'b'):
            continue
        lead = kids[0]
        text = lead.get_text(' ', strip=True)
        if not text or len(text) > 80 or re.search(r'[.!?]$', text) or lead.find('a') or re.fullmatch(r'[\d\s()#+.-]+', text):
            continue
        rest = kids[1:]
        if rest and not (isinstance(rest[0], Tag) and rest[0].name == 'br'):
            continue
        h = frag.new_tag('h3')
        h.string = re.sub(r'\s+', ' ', text)
        p.insert_before(h)
        lead.decompose()
        if rest:
            rest[0].extract()
        if not p.get_text(strip=True) and not p.find(['img', 'iframe']):
            p.decompose()
    # 4b. runs of short one-line paragraphs (hours, addresses, names) read as one block
    def short_line(el):
        if not (isinstance(el, Tag) and el.name == 'p') or el.find(['img', 'iframe', 'br']):
            return False
        t = el.get_text(' ', strip=True)
        return 0 < len(t) <= 60 and not re.search(r'[.!?]$', t) and not BULLET.match(t)
    run = []
    for c in [c for c in root.children if isinstance(c, Tag)] + [None]:
        if c is not None and short_line(c):
            run.append(c)
            continue
        if len(run) >= 2:
            first = run[0]
            for r in run[1:]:
                first.append(frag.new_tag('br'))
                for k in list(r.contents):
                    first.append(k.extract())
                r.decompose()
        run = []
    # 5. typed bullets become real lists
    for p in list(root.find_all('p')):
        if p.parent is None or not BULLET.match(p.get_text()):
            continue
        prev = p.find_previous_sibling()
        if prev is not None and prev.name == 'ul' and prev.get('data-typed') == '1' and prev.next_sibling is not None:
            ul = prev
        else:
            ul = frag.new_tag('ul', attrs={'data-typed': '1'})
            p.insert_before(ul)
        first = next((d for d in p.descendants if isinstance(d, NavigableString) and d.strip()), None)
        if first is not None:
            first.replace_with(BULLET.sub('', str(first), count=1))
        p.name = 'li'
        ul.append(p.extract())
    for ul in root.find_all('ul', attrs={'data-typed': '1'}):
        del ul['data-typed']
    # 6. stray breaks and rules
    for p in root.find_all(['p', 'li', 'h2', 'h3', 'h4']):
        kids = _meaningful(p.contents)
        while kids and isinstance(kids[0], Tag) and kids[0].name == 'br':
            kids.pop(0).extract()
        while kids and isinstance(kids[-1], Tag) and kids[-1].name == 'br':
            kids.pop().extract()
    for c in list(root.children):
        if isinstance(c, Tag) and c.name == 'br':
            c.extract()
    tops = [c for c in root.children if isinstance(c, Tag)]
    prev = None
    for c in tops:
        if c.name == 'hr' and (prev is None or prev.name == 'hr'):
            c.decompose()
            continue
        prev = c
    tops = [c for c in root.children if isinstance(c, Tag)]
    while tops and tops[-1].name == 'hr':
        tops.pop().decompose()
    for p in root.find_all('p'):
        if not p.get_text(strip=True) and not p.find(['img', 'iframe', 'table']):
            p.decompose()


# ---------------------------------------------------------------- HTML cleaning
KEEP_ATTR = {'a': {'href', 'title', 'target'}, 'img': {'src', 'alt', 'width', 'height'},
             'iframe': {'src', 'title', 'width', 'height', 'allow', 'allowfullscreen'},
             'td': {'colspan', 'rowspan'}, 'th': {'colspan', 'rowspan'}, 'ol': {'start', 'type'}}
DROP_TAGS = {'script', 'style', 'noscript', 'meta', 'link', 'form', 'input', 'button', 'select', 'textarea', 'o:p'}
UNWRAP = {'font', 'span', 'center', 'o:p', 'u1:p', 'st1:place', 'st1:city', 'st1:state', 'small', 'big'}


def unfacebook(href):
    p = up.urlparse(href)
    if p.netloc in ('l.facebook.com', 'lm.facebook.com') and p.path == '/l.php':
        tgt = dict(up.parse_qsl(p.query)).get('u')
        if tgt:
            t = up.urlparse(tgt)
            q = [(k, v) for k, v in up.parse_qsl(t.query) if k != 'fbclid']
            return up.urlunparse(t._replace(query=up.urlencode(q)))
    if 'facebook.com/hashtag/' in href:
        return href.split('?')[0]
    return href


unresolved_links = collections.Counter()


def rewrite_href(href, base):
    raw = (href or '').strip()
    if raw.lower().startswith(('mailto:', 'tel:')):
        return re.sub(r'\s', '', raw)
    if raw.startswith('#'):
        return raw
    if raw.lower().startswith('file:'):
        unresolved_links[raw] += 1
        return None
    n = norm(raw, base)
    if not n:
        return raw
    if not n.startswith('https://www.newgloucester.com'):
        return unfacebook(n)
    path = up.urlparse(n).path
    if re.fullmatch(r'/[^/\s]+@[^/\s]+\.[a-z]+', path, re.I):
        return 'mailto:' + path.lstrip('/')
    q = qs(n)
    if q.get('Design') == 'PrintView':
        q.pop('Design')
        n = norm('/index.asp?' + up.urlencode(q))
    if n in broken:
        unresolved_links[n] += 1
        return None
    if 'DE' in q and q['DE'] in records:
        return record_href(records[q['DE']])
    if n in canon_of:
        return path_of[canon_of[n]]
    if re.search(r'/vertical/|/uploads/|\.(pdf|docx?|xlsx?|pptx?|zip|kmz|jpe?g|png|gif)$', up.urlparse(n).path, re.I):
        return n  # documents stay on the town's existing file host for now
    if 'month' in q or q.get('Type') == 'B_EV':
        return '/municipal-calendar'
    unresolved_links[n] += 1
    return n


def clean(node, base, demote=True):
    if node is None:
        return ''
    frag = BeautifulSoup(str(node), 'lxml')
    root = frag.body or frag
    for c in root.find_all(string=lambda x: isinstance(x, Comment)):
        c.extract()
    for t in root.find_all(list(DROP_TAGS)):
        t.decompose()
    for t in root.find_all(True):
        if ':' in t.name:
            t.unwrap()
    for t in root.find_all(list(UNWRAP)):
        t.unwrap()
    for t in root.find_all(True):
        center = 'center' in (t.get('style', '') + str(t.get('align', ''))).lower()
        if 'record-list' in (t.get('class') or []):
            continue
        keep = KEEP_ATTR.get(t.name, set())
        t.attrs = {k: v for k, v in t.attrs.items() if k in keep}
    if demote:
        for h in root.find_all('h1'):
            h.name = 'h2'
    for a in root.find_all('a'):
        if a.get('href'):
            new = rewrite_href(a['href'], base)
            if new is None:  # link was already broken on the legacy site: keep the text
                a.unwrap()
                continue
            a['href'] = new
            if a['href'].startswith('http') and 'newgloucester.com' not in a['href']:
                a['rel'] = 'noopener'
            m = re.search(r'\.(pdf|docx?|xlsx?|pptx?|kmz|zip)$', a['href'], re.I)
            if m and not a.get_text(strip=True) and not a.find('img'):
                # invisible on the legacy site (link text was a space): show the file name
                a.clear()
                a.append(up.unquote(a['href'].rsplit('/', 1)[-1]))
            label = a.get_text(' ', strip=True)
            if m and re.fullmatch(r'[\w().,&-]+\.(pdf|docx?|xlsx?|pptx?)', label, re.I) and '_' in label:
                # a raw file name used as link text: "Title_Page.pdf" -> "Title Page"
                a.clear()
                a.append(re.sub(r'\s+', ' ', re.sub(r'[_]+', ' ', label.rsplit('.', 1)[0])).strip())
            if m and not re.search(r'\((pdf|word|doc|docx|excel|xlsx?)\)\s*$', a.get_text(' ', strip=True), re.I):
                a['class'] = 'doc'
                a['data-ext'] = m.group(1).upper()
        a.attrs.pop('target', None)
        if not a.get('href') and not a.get_text(strip=True):
            a.decompose()
    for img in root.find_all('img'):
        n = norm(img.get('src', ''), base)
        if n and n.startswith('https://www.newgloucester.com'):
            img['src'] = local_image(n)
        img['loading'] = 'lazy'
        img['alt'] = img.get('alt', '')
    for f in root.find_all('iframe'):
        f['loading'] = 'lazy'
        f['title'] = f.get('title') or 'Embedded content'
    # drop empty blocks repeatedly
    for _ in range(3):
        for t in root.find_all(['p', 'div', 'strong', 'b', 'em', 'i', 'li', 'h2', 'h3', 'h4']):
            if t.attrs is None or 'record-list' in (t.get('class') or []):
                continue
            keepers = ['img', 'iframe', 'hr', 'table'] + ([] if t.name == 'p' else ['br', 'div'])
            if not t.get_text(strip=True) and not t.find(keepers):
                t.decompose()
    tidy(root, frag)
    # collapse runs of <br>
    html = ''.join(str(x) for x in root.contents)
    html = re.sub(r'(<br/>\s*){3,}', '<br/><br/>', html)
    html = re.sub(r'&nbsp;|\xa0', ' ', html)
    html = re.sub(r'[ \t]{2,}', ' ', html)
    return html.strip()


# ---------------------------------------------------------------- record pages / links
def has_body(r):
    b = r['_body']
    return bool((b and (b.get_text(strip=True) or b.find(['img', 'iframe']))) or r.get('_side'))


def record_href(r):
    return r['path'] if r.get('path') else (r['attachments'][0]['url'] if r['attachments'] else r.get('fallback', '/'))


for de, r in records.items():
    r['date'] = (r['dates'][0] if r['dates'] else None) or date_from_title(r['title'])
    lp = listed_on.get(de)
    r['listedOn'] = path_of[canon_of[lp]] if lp else None
    if r['kind'] == 'news':
        base = '/news'
    elif r['kind'] == 'event':
        base = '/municipal-calendar'
    elif r['kind'] == 'job':
        base = '/employment'
    else:
        base = r['listedOn'] or '/documents'
    needs_page = has_body(r) or len(r['attachments']) != 1 or r['kind'] in ('news', 'job') or bool(r['_contact'] and r['_contact'].get_text(strip=True))
    if r['kind'] == 'event' and not has_body(r) and not r['attachments']:
        needs_page = False
    r['fallback'] = base
    r['path'] = None
    if needs_page:
        suffix = '-' + r['date'] if r['kind'] == 'event' and r['date'] else ''
        r['path'] = base.rstrip('/') + '/' + slugify(r['title'])[:60] + suffix

# unique record paths, and never collide with a page path
taken = set(path_of.values())
for r in sorted(records.values(), key=lambda r: r['legacy']):
    if r['path']:
        p, i = r['path'], 2
        while p in taken:
            p = f"{r['path']}-{i}"
            i += 1
        r['path'] = p
        taken.add(p)

for de, r in records.items():
    hb = has_body(r)
    b = r.pop('_body')
    r['html'] = clean(b, r['legacy']) if hb else ''
    sd = r.pop('_side')
    r['sidebarHtml'] = clean(sd, r['legacy']) if sd else ''
    if hb and not (b and (b.get_text(strip=True) or b.find(['img', 'iframe']))):
        r['html'] = ''
    c = r.pop('_contact')
    r['contactHtml'] = clean(c, r['legacy']) if c and c.get_text(strip=True) else ''

# ---------------------------------------------------------------- page content
GENERIC = re.compile(r'^(agendas?|minutes|pb ?min.*|pb agendas.*)$', re.I)


def drop_repeat_heading(html, *titles):
    m = re.match(r'\s*<h[23][^>]*>(.*?)</h[23]>', html, re.S)
    if m and re.sub(r'<[^>]+>|\s+', '', htmllib.unescape(m.group(1))).lower() in {re.sub(r'\s+', '', t or '').lower() for t in titles}:
        return html[m.end():]
    return html


def page_record(u):
    s = soup(u)
    inner = s.select_one('main.content .insideMainContent') or s.select_one('main.content')
    inner = BeautifulSoup(str(inner), 'lxml').find(True)
    h1 = inner.find('h1')
    heading = re.sub(r'\s+', ' ', h1.get_text(' ', strip=True)) if h1 else clean_title(P[u]['title'])
    if h1:
        h1.decompose()
    # list items that point at records: remember them so templates can render rich lists
    listed = []
    for a in inner.select('a[href]'):
        n = norm(a['href'], u)
        de = qs(n).get('DE') if n else None
        if de and de in records and de not in listed:
            listed.append(de)
    # boxes that are nothing but record links become placeholders for <RecordList>
    for box in inner.select('.box'):
        if 'sectionIntro' in (box.get('class') or []):
            continue
        body = box.select_one('.body') or box
        kids = [k for k in body.find_all(recursive=False)]
        arts = [k for k in kids if k.name == 'article' and 'summaryDisplay' in (k.get('class') or [])]
        if not arts or len(arts) != len(kids):
            continue
        ids = []
        for art in arts:
            a = art.select_one('a.item[href]') or art.select_one('a[href]')
            de = qs(norm(a['href'], u)).get('DE') if a else None
            if not de or de not in records:
                ids = None
                break
            ids.append(de)
            extra = BeautifulSoup(str(art), 'lxml').find('article')
            for h in extra.find_all(['h2', 'h3']):
                h.decompose()
            for x in extra.select('.newsdatetime, .eventsdatetime'):
                x.decompose()
            if extra.get_text(strip=True) and not records[de].get('summary'):
                records[de]['summary'] = clean(extra, u)
        if ids:
            ph = soup(u).new_tag('div', attrs={'class': 'record-list', 'data-ids': ','.join(ids)})
            box.replace_with(ph)
    # calendar navigation chrome is replaced by our own calendar
    for x in inner.select('.calMonth, ._calendarbox, .listlinks'):
        x.decompose()
    side = s.select_one('main.content .rightContent')
    title = nav_title.get(u) or clean_title(P[u]['title']) or heading
    return {
        'path': path_of[u],
        'title': title,
        'heading': heading,
        'legacy': sorted([x for x in canon_of if canon_of[x] == u], key=pref),
        'parent': (path_of.get(parent_of.get(u)) if parent_of.get(u) else None) if path_of.get(parent_of.get(u)) != path_of[u] else None,
        'html': drop_repeat_heading(clean(inner, u), heading, title),
        'sidebarHtml': clean(side, u) if side and side.get_text(strip=True) else '',
        'records': listed,
        'special': u in SPECIAL,
    }


pages = [page_record(u) for u in canon_pages]
# merge duplicate special pages (calendar list/grid, news list) into one entry each
merged = {}
for p in pages:
    if p['path'] in merged:
        m = merged[p['path']]
        m['legacy'] = sorted(set(m['legacy'] + p['legacy']), key=pref)
        m['records'] += [r for r in p['records'] if r not in m['records']]
    else:
        merged[p['path']] = p
pages = list(merged.values())
page_by_path = {p['path']: p for p in pages}


def board_of(path):
    p = page_by_path.get(path)
    while p and GENERIC.match(p['title']):
        p = page_by_path.get(p['parent'])
    return p['title'] if p else None


MEETING_ROOTS = ('/agenda-minutes', '/select-board-meetings')
for r in records.values():
    lo = r['listedOn']
    r['board'] = board_of(lo) if lo else None
    t = r['title'].lower()
    r['docType'] = ('Agenda Packet' if 'packet' in t else 'Agenda' if 'agenda' in t else 'Minutes' if re.search(r'\bmin(utes)?\b|pbmin', t) else
                    'Notice' if re.search(r'notice|hearing', t) else 'Document')
    r['meeting'] = bool(lo and (lo.startswith(MEETING_ROOTS) or (page_by_path.get(lo) and re.match(r'pb ?min|pb agendas', page_by_path[lo]['title'], re.I))))
    if lo and '/agenda-minutes' not in lo and r['docType'] in ('Agenda', 'Minutes', 'Agenda Packet') and r['kind'] == 'item':
        r['meeting'] = True

# Titles that are only a date ("June 20, 2006") take their type from the page that lists them
for r in records.values():
    pg = page_by_path.get(r['listedOn'] or '')
    if r['docType'] == 'Document' and pg:
        if re.search(r'min', pg['title'], re.I):
            r['docType'] = 'Minutes'
        elif re.search(r'agenda', pg['title'], re.I):
            r['docType'] = 'Agenda'

# Planning Board archive pages live under /planning; label their board explicitly
for r in records.values():
    lo = r['listedOn'] or ''
    pg = page_by_path.get(lo)
    if pg and re.match(r'pb ?min|pb agendas', pg['title'], re.I):
        r['board'] = 'Planning Board'

# ---------------------------------------------------------------- nav.json (new paths)
def nav_out(items):
    return [{'title': i['title'], 'href': path_of.get(i['legacy'], i['legacy']), 'children': nav_out(i['children'])} for i in items]


nav = nav_out(nav_tree)

# ---------------------------------------------------------------- redirects
redirects = {}
for u, c in canon_of.items():
    redirects[u.replace('https://www.newgloucester.com', '')] = path_of[c]
for r in records.values():
    redirects[r['legacy'].replace('https://www.newgloucester.com', '')] = record_href(r)
for u in ok:
    if 'month' in qs(u):
        redirects[u.replace('https://www.newgloucester.com', '')] = '/municipal-calendar'

for u in ok:  # anything left (e.g. Design=PrintView copies) goes to the page it prints
    key = u.replace('https://www.newgloucester.com', '')
    if key not in redirects:
        q = qs(u)
        q.pop('Design', None)
        alt = norm('/index.asp?' + up.urlencode(q)) if q else None
        redirects[key] = path_of.get(canon_of.get(alt), '/')

# ---------------------------------------------------------------- write
json.dump(nav, open(os.path.join(DATA, 'nav.json'), 'w'), indent=1)
json.dump(pages, open(os.path.join(DATA, 'pages.json'), 'w'), indent=1)
json.dump(sorted(records.values(), key=lambda r: (r['date'] or '', r['title']), reverse=True),
          open(os.path.join(DATA, 'records.json'), 'w'), indent=1)
json.dump(dict(sorted(redirects.items())), open(os.path.join(DATA, 'redirects.json'), 'w'), indent=1)

docs = {}
for u, info in idx['docs'].items():
    docs[u] = sorted(set(info.get('from', [])))
inventory = {
    'crawledUrls': len(P), 'ok': len(ok), 'broken': sorted(broken),
    'pages': len(pages), 'records': len(records),
    'recordPages': sum(1 for r in records.values() if r['path']),
    'documents': docs, 'external': {k: sorted(set(v))[:3] for k, v in idx['external'].items()},
    'unresolvedInternalLinks': dict(unresolved_links),
}
json.dump(inventory, open(os.path.join(DATA, 'inventory.json'), 'w'), indent=1)
print('pages', len(pages), 'records', len(records), 'record pages', inventory['recordPages'],
      'images', len(img_map), 'unresolved', len(unresolved_links))
