// A website's icon for the sources tags, fetched from DuckDuckGo's icon service by our server (visitors' browsers
// never contact it). A site with no icon answers an empty 404, so the page shows the site's first letter instead of
// DuckDuckGo's placeholder.
const SITE = /^(?=.{1,253}$)[a-z0-9-]+(\.[a-z0-9-]+)+$/;
const WEEK = 7 * 24 * 3600;

export async function GET(_req: Request, { params }: { params: Promise<{ site: string }> }) {
  const site = (await params).site.toLowerCase();
  if (!SITE.test(site)) return new Response(null, { status: 404 });
  const r = await fetch(`https://icons.duckduckgo.com/ip3/${site}.ico`, { next: { revalidate: WEEK } }).catch(() => null);
  const body = r?.ok ? await r.arrayBuffer() : null;
  // Tiny files are empty or 1-pixel icons: treat them as missing too.
  if (!body || body.byteLength < 100) return new Response(null, { status: 404, headers: { "Cache-Control": `public, max-age=${24 * 3600}` } });
  return new Response(body, {
    headers: { "Content-Type": r!.headers.get("content-type") ?? "image/x-icon", "Cache-Control": `public, max-age=${WEEK}` },
  });
}
