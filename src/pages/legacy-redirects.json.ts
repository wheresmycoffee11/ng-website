import redirects from '../data/redirects.json';

/** Old index.asp?SEC=…&DE=… URLs can't be redirected by a static host, so 404.astro looks them up here. */
export function GET() {
  return new Response(JSON.stringify(redirects), { headers: { 'Content-Type': 'application/json' } });
}
