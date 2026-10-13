"""Download the legacy homepage photos (slider, tiles, Explore cards) into public/media/home."""
import os, sys, requests
from PIL import Image

REPO = sys.argv[1]
OUT = os.path.join(REPO, 'public', 'media', 'home')
os.makedirs(OUT, exist_ok=True)
BASE = 'https://www.newgloucester.com/vertical/Sites/%7BE9FFB5A1-D5A9-41DE-A9D8-FCFBE460957E%7D/uploads/'
NAMES = ['hiker-boys_Web.jpg', 'dairy-cows_Web.jpg', 'lakeview_Web.jpg', 'library-slider_Web.jpg', 'sunset-winter_Web.jpg',
         'calendar_Web.jpg', 'news-events_Web.jpg', 'agenda-minutes_Web.jpg', 'employment_Web.jpg',
         'library_Web.jpg', 'pinelandfarms_Web.jpg', 'shaker-house_Web.jpg', 'orchard_Web.jpg']
for n in NAMES:
    dest = os.path.join(OUT, n)
    if os.path.exists(dest):
        continue
    r = requests.get(BASE + n, timeout=60, headers={'User-Agent': 'Mozilla/5.0 (ng-site-migration)'})
    r.raise_for_status()
    open(dest, 'wb').write(r.content)
    im = Image.open(dest)
    w = 2000 if 'slider' in n or n.split('_')[0] in ('hiker-boys', 'dairy-cows', 'lakeview', 'sunset-winter') else 900
    if im.width > w:
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    im.convert('RGB').save(dest, 'JPEG', quality=78, optimize=True, progressive=True)
    print(n, im.size, os.path.getsize(dest) // 1024, 'KB')
