import pagesJson from '../data/pages.json';
import recordsJson from '../data/records.json';
import navJson from '../data/nav.json';

export type Attachment = { name: string; url: string; ext: string; label: string };
export type RecordItem = {
  id: string;
  sec: string;
  kind: 'item' | 'event' | 'news' | 'job';
  title: string;
  legacy: string;
  attachments: Attachment[];
  dateText: string;
  dates: string[];
  date: string | null;
  listedOn: string | null;
  fallback: string;
  path: string | null;
  html: string;
  contactHtml: string;
  sidebarHtml: string;
  summary?: string;
  board: string | null;
  docType: string;
  meeting: boolean;
};
export type Page = {
  path: string;
  title: string;
  heading: string;
  legacy: string[];
  parent: string | null;
  html: string;
  sidebarHtml: string;
  records: string[];
  special: boolean;
};
export type NavItem = { title: string; href: string; children: NavItem[] };

export const pages = pagesJson as Page[];
export const records = recordsJson as RecordItem[];
export const nav = navJson as NavItem[];

export const pageByPath = new Map(pages.map((p) => [p.path, p]));
export const recordById = new Map(records.map((r) => [r.id, r]));

/** Where a record link should go: its own page, else straight to its single file. */
export function recordHref(r: RecordItem): string {
  if (r.path) return r.path;
  if (r.attachments.length) return r.attachments[0].url;
  return r.fallback;
}

/** Friendlier board names for the meetings hub. */
const BOARD_ALIASES: Record<string, string> = {
  'Select Board Meetings': 'Select Board',
  LMPC: 'Land Management Planning Committee',
  'Parks & Rec': 'Parks & Recreation Committee',
  'Adhoc Semiquincentennial Committee': 'Ad Hoc Semiquincentennial Committee',
  'Adhoc Municipal Complex Advisory Committee': 'Ad Hoc Municipal Complex Advisory Committee',
};
export const boardName = (b: string | null) => (b ? BOARD_ALIASES[b] ?? b : 'Other');

export function breadcrumbs(path: string): { title: string; href: string }[] {
  const out: { title: string; href: string }[] = [];
  let p = pageByPath.get(path);
  const guard = new Set<string>();
  while (p && p.parent && !guard.has(p.parent)) {
    guard.add(p.parent);
    const parent = pageByPath.get(p.parent);
    if (!parent) break;
    out.unshift({ title: parent.title, href: parent.path });
    p = parent;
  }
  return [{ title: 'Home', href: '/' }, ...out];
}

export const childrenOf = (path: string) =>
  pages.filter((p) => p.parent === path && p.path !== path).sort((a, b) => a.title.localeCompare(b.title, 'en', { numeric: true }));

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
export function formatDate(iso: string | null, style: 'long' | 'short' = 'long'): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  const month = MONTHS[m - 1];
  return style === 'long' ? `${month} ${d}, ${y}` : `${month.slice(0, 3)} ${d}, ${y}`;
}
export function weekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

/** Split migrated HTML around record-list placeholders. */
export function splitHtml(html: string): ({ html: string } | { ids: string[] })[] {
  const parts: ({ html: string } | { ids: string[] })[] = [];
  const re = /<div class="record-list" data-ids="([^"]*)"><\/div>/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html))) {
    if (m.index > last) parts.push({ html: html.slice(last, m.index) });
    parts.push({ ids: m[1].split(',').filter(Boolean) });
    last = m.index + m[0].length;
  }
  if (last < html.length) parts.push({ html: html.slice(last) });
  return parts;
}
