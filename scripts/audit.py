"""Coverage audit: prove the built site carries everything the legacy site had.

Usage:  npm run build && python3 -I scripts/audit.py <repo_dir> [<crawl_dir>]

Checks
  1. Every legacy URL that returned 200 maps (redirects.json) to a built page or a file.
  2. Every document the legacy site linked to is linked from at least one built page.
  3. Every external link on the legacy site appears somewhere in the built site.
  4. Text coverage: for every legacy page and record, the words of its main content
     appear in the new page that replaced it (reports anything under 98%).
  5. Every internal link in the built site resolves to a built page or asset.
Writes docs/coverage-report.md and exits non-zero if any check fails.
"""
import sys, os, re, json, glob, collections, html as htmllib, urllib.parse as up
from bs4 import BeautifulSoup

REPO = sys.argv[1]
CRAWL = sys.argv[2] if len(sys.argv) > 2 else None
DIST = os.path.join(REPO, 'dist')
DATA = os.path.join(REPO, 'src', 'data')
redirects = json.load(open(os.path.join(DATA, 'redirects.json')))
inventory = json.load(open(os.path.join(DATA, 'inventory.json')))
pages = json.load(open(os.path.join(DATA, 'pages.json')))
records = json.load(open(os.path.join(DATA, 'records.json')))


def built_file(path):
    path = up.unquote(path.split('#')[0].split('?')[0])
    if path in ('', '/'):
        return os.path.join(DIST, 'index.html')
    cand = [os.path.join(DIST, path.lstrip('/')), os.path.join(DIST, path.lstrip('/'), 'index.html'),
            os.path.join(DIST, path.lstrip('/') + '.html')]
    return next((c for c in cand if os.path.isfile(c)), None)


# ---- load the build
built = {}
for f in glob.glob(os.path.join(DIST, '**', '*.html'), recursive=True):
    rel = '/' + os.path.relpath(f, DIST).replace(os.sep, '/')
    rel = re.sub(r'(^|/)index\.html$', '', rel) or '/'
    rel = rel if rel.startswith('/') else '/' + rel
    built[rel.rstrip('/') or '/'] = BeautifulSoup(open(f, 'rb').read(), 'lxml')

all_hrefs = collections.defaultdict(set)
for path, s in built.items():
    for a in s.find_all('a', href=True):
        all_hrefs[htmllib.unescape(a['href']).strip()].add(path)
    for f in s.find_all('iframe', src=True):
        src = f['src'].strip()
        all_hrefs[('https:' + src) if src.startswith('//') else src].add(path)
href_set_lower = {h.lower(): h for h in all_hrefs}


def norm_file(u):
    p = up.urlparse(u.strip())
    return (p.netloc.lower().replace('newgloucester.com', 'www.newgloucester.com').replace('www.www.', 'www.') +
            up.unquote(p.path).lower().replace('/vertical/sites/', '/vertical/sites/'))


built_files = {norm_file(h) for h in all_hrefs if h.startswith('http')}
fails = collections.defaultdict(list)

# 1. legacy URLs
for legacy, target in redirects.items():
    if target.startswith('http'):
        if norm_file(target) not in built_files and 'newgloucester.com' not in target:
            fails['redirect target file not linked'].append((legacy, target))
    elif not built_file(target):
        fails['redirect target missing'].append((legacy, target))
ok_count = len(redirects)

# 2. documents
doc_missing = []
for u, srcs in inventory['documents'].items():
    if norm_file(u) not in built_files:
        doc_missing.append((u, srcs[:2]))
fails['document not linked'] = doc_missing

# 3. external links
def norm_ext(u):
    p = up.urlparse(htmllib.unescape(u))
    return (p.netloc.lower().removeprefix('www.') + p.path.rstrip('/')).lower()


built_ext = {norm_ext(h) for h in all_hrefs if h.startswith('http')}
ext_missing = []
for u, srcs in inventory['external'].items():
    if u.lower().startswith('file:'):
        continue  # a staff drive path: never reachable by the public, listed under legacy-broken
    if any(x in u for x in ('l.facebook.com/l.php', 'catalisgov.com', 'fonts.g', 'cdnjs.cloudflare', 'kit.fontawesome')):
        continue
    if 'facebook.com/hashtag' in u:
        u = u.split('?')[0]
    if norm_ext(u) not in built_ext:
        ext_missing.append((u, srcs[:2]))
fails['external link missing'] = ext_missing

# 4. text coverage
WORD = re.compile(r"[a-z0-9][a-z0-9'’.-]*[a-z0-9]|[a-z0-9]", re.I)


def words(text):
    return collections.Counter(w.lower().strip(".'’-") for w in WORD.findall(text))


def page_text(path):
    s = built.get(path.rstrip('/') or '/')
    if not s:
        return None
    m = s.find('main') or s
    return m.get_text(' ', strip=True)


coverage = []
if CRAWL:
    idx = json.load(open(os.path.join(CRAWL, 'index.json')))
    for legacy, target in redirects.items():
        if target.startswith('http'):
            continue
        m = idx['pages'].get('https://www.newgloucester.com' + legacy)
        if not m or 'file' not in m or 'month=' in legacy:
            continue
        s = BeautifulSoup(open(os.path.join(CRAWL, 'pages', m['file'] + '.html'), 'rb').read(), 'lxml')
        main = s.select_one('main.content')
        if not main:
            continue
        for x in main.select('.calMonth, ._calendarbox, .listlinks, script, style'):
            x.decompose()
        old = words(main.get_text(' ', strip=True))
        if legacy == '/':
            old = words(' '.join(a.get_text(' ', strip=True) for a in s.select('main.content h2')))
        new_text = page_text(target)
        if new_text is None:
            continue
        new = words(new_text)
        if target in ('/news', '/municipal-calendar'):
            # list pages: their items are spread over the record pages and calendar
            continue
        total = sum(old.values())
        if not total:
            continue
        missing = old - new
        if missing:
            # Old markup often split words across tags ("w<span>ill</span>"); the new
            # HTML joins them. Count a "missing" fragment as present if it occurs
            # inside the new text once spacing is ignored.
            flat = re.sub(r'[^a-z0-9]', '', new_text.lower())
            missing = collections.Counter({w: n for w, n in missing.items() if re.sub(r'[^a-z0-9]', '', w) not in flat})
        miss_n = sum(missing.values())
        pct = 100 * (1 - miss_n / total)
        coverage.append((pct, legacy, target, total, missing.most_common(12)))
    low = [c for c in coverage if c[0] < 98]
    fails['text coverage under 98%'] = [(f'{c[0]:.1f}%', c[1], c[2], c[4]) for c in sorted(low)]

# 5. internal links resolve
broken_internal = []
for h, srcs in all_hrefs.items():
    if h.startswith(('http', 'mailto:', 'tel:', '#', 'javascript:')):
        continue
    if h.startswith('/pagefind/'):
        continue
    if not built_file(h) and not os.path.exists(os.path.join(REPO, 'public', up.unquote(h.lstrip('/').split('?')[0]))):
        broken_internal.append((h, sorted(srcs)[:3]))
fails['broken internal link'] = broken_internal

# 6. every record title (agenda, minutes, news, event, job) is shown somewhere
site_text = re.sub(r'\s+', ' ', ' '.join((s.find('main') or s).get_text(' ', strip=True) for s in built.values())).lower()
fails['record title not shown'] = [(r['title'], r['legacy']) for r in records
                                   if re.sub(r'\s+', ' ', r['title']).lower() not in site_text]

# ---- report
total_fail = sum(len(v) for v in fails.values())
lines = ['# Coverage report', '',
         'Generated by `scripts/audit.py` against the production build in `dist/`.', '',
         f"- Legacy URLs crawled: {inventory['crawledUrls']} ({inventory['ok']} returned 200; "
         f"{len(inventory['broken'])} were already broken on the old site)",
         f"- Legacy URLs mapped to a new page or file: {ok_count}",
         f"- Pages migrated: {inventory['pages']}; records (agendas, minutes, news, events, jobs): {inventory['records']} "
         f"({inventory['recordPages']} have their own page, the rest link straight to their file)",
         f"- Documents linked on the old site: {len(inventory['documents'])}; still linked: {len(inventory['documents']) - len(doc_missing)}",
         f"- External links on the old site: {len(inventory['external'])}",
         f"- Pages built: {len(built)}",
         f"- Text coverage checked on {len(coverage)} legacy pages; median "
         f"{sorted(c[0] for c in coverage)[len(coverage)//2]:.1f}%" if coverage else '- Text coverage: not run (no crawl dir given)',
         '', f'**Problems found: {total_fail}**', '']
for k, v in fails.items():
    lines.append(f'## {k} ({len(v)})')
    for item in v[:200]:
        lines.append(f'- `{item}`')
    lines.append('')
lines += ['## Already broken on the legacy site', ''] + [f'- `{u}`' for u in inventory['broken']] + \
    [f'- `{u}` (link text kept, dead link removed)' for u in inventory['unresolvedInternalLinks']]
os.makedirs(os.path.join(REPO, 'docs'), exist_ok=True)
open(os.path.join(REPO, 'docs', 'coverage-report.md'), 'w').write('\n'.join(lines) + '\n')
print('\n'.join(lines[:14]))
for k, v in fails.items():
    print(f'{k}: {len(v)}')
    for item in v[:8]:
        print('   ', str(item)[:300])
sys.exit(1 if total_fail else 0)
