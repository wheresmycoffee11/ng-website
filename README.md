# New Gloucester, Maine: website rebuild

A rebuild of [newgloucester.com](https://www.newgloucester.com/) in [Astro](https://astro.build). Iteration 1 carries over everything on the current site and improves how it looks and works. Nothing new was added to the town's content.

## Run it

```bash
npm install
npm run dev        # http://localhost:4321
npm run build      # static site in dist/, plus the Pagefind search index
npm run preview
```

## What changed for residents

- **Meetings & Documents** (`/meetings`): all 1,431 agendas, agenda packets and minutes from every board in one list, filterable by board, type, year and keyword. Each row opens the file directly. On the old site that took two clicks per document, one board at a time.
- **Live hours**: Town Hall, Library and Transfer Station show "Open until 5pm" / "Closed now" in Maine time, in the header, homepage and footer.
- **Calendar** (`/municipal-calendar`): upcoming events as a readable list with the Meeting Places legend (LB, MH, RC, TH) beside it, and a toggle for past events back to January 2023.
- **Full-text search** across every page (Pagefind, runs in the browser, no server).
- **Long document lists** on board pages get an inline filter and year picker.
- **Mobile**: real mobile menu, no sideways scrolling, tap-friendly targets.
- **Accessibility**: skip link, visible focus, pausable slideshow that respects reduced-motion, readable contrast, semantic headings.
- **Neater pages**: the old site's content is restructured on import. Centered walls of text are left-aligned, run-on text is split into paragraphs, bold lead-ins become headings, typed bullets ("•", "➢") become real lists, filename link labels ("Title_Page.pdf") read as "Title Page", photo runs become a gallery, and section overview pages show their sub-pages as cards. The words themselves are unchanged (the audit checks this).
- **Town seal** from the current site as the logo and favicon, and the old homepage's "Home of the Shaker Community" tagline (it was baked into an image, so the crawl couldn't see it).
- **Old links keep working**: every old `index.asp?SEC=…&DE=…` address redirects to its new page (see below).

## How the content got here

The content is not hand-copied. It is extracted from a full crawl of the live site so coverage can be checked by machine.

| Step | Script | Output |
| --- | --- | --- |
| Crawl the site | `scripts/crawl.py <dir> 12000` | raw HTML for every page |
| Crawl older calendar months | `scripts/crawl_calendar.py <dir> 2019 2024` | events back to Jan 2023 (earliest posted) |
| Extract | `scripts/extract.py <dir> .` | `src/data/*.json`, images in `public/media/uploads` |
| Homepage photos | `scripts/home_media.py .` | `public/media/home` |
| Audit | `scripts/audit.py . <dir>` | `docs/coverage-report.md` |

Run Python with `-I` from outside the crawl directory, for example `python3 -I scripts/extract.py /path/to/crawl .`

`src/data/`:

- `pages.json`: 110 pages (every distinct page on the old site; duplicates reachable at several URLs were merged)
- `records.json`: 2,574 records: agendas, minutes, packets, news, calendar events, job postings
- `nav.json`: the old site's menu, unchanged in structure, pointing at new URLs
- `redirects.json`: old URL to new URL, for all 2,851 live legacy URLs
- `site.json`: address, phone, fax, hours (hand-maintained; hours also drive the open/closed badges)
- `inventory.json`: every document and external link the old site referenced

## Coverage audit

`docs/coverage-report.md` is the proof that nothing was left out. Current result: **0 problems**.

- 2,851 of 2,851 working legacy URLs map to a new page or file
- 1,987 of 1,987 linked documents are still linked
- All 183 external links are present (minus the CMS vendor's own links)
- Text of 266 old pages checked word by word against the new pages: median 100%, none under 98%
- All 2,574 record titles appear on the new site
- Zero broken internal links

The audit also caught real problems during the build, which were fixed: content that lived only in an old sidebar, invisible links whose text was a blank space, and email addresses missing `mailto:`.

## Known items before this could go live

1. **Documents are still served by the old host.** The ~2,000 PDFs and Word files are linked at their existing `www.newgloucester.com/vertical/...` addresses (a few at `newgloucester.govoffice.com`). They work today, but they must be copied over before the domain moves.
2. **Content is a snapshot from 2026-10-13.** There's no editing interface for town staff yet. That is the next iteration (a git-based CMS or an import from the current system).
3. **Legacy redirects run in the 404 page** so they work on any static host. A host with query-string redirect rules (Netlify, Cloudflare) could do them server-side from `redirects.json`.
4. **Deliberately not carried over:** the "Government Websites by Catalis" credit and Catalis's privacy-policy link (they belong to the current vendor, not the town).
5. **Already broken on the old site:** 2 links that went nowhere (a `file:///U:/...` path to a staff drive and a deleted page). The link text is kept, and the dead link is removed. They're listed at the bottom of the coverage report.
