import asyncio
import json
import re
from datetime import datetime, timezone
from playwright.async_api import async_playwright
import requests
from email.utils import parsedate_to_datetime

class WaybackDomExtractor:
    def __init__(self, archived_url):
        self.archived_url = archived_url
        self.base_url = self._extract_original_url(archived_url)
        self.timestamp = self._extract_timestamp(archived_url)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def _extract_timestamp(self, url):
        match = re.search(r"/web/(\d{14})/", url)
        if not match:
            raise ValueError(f"Could not extract timestamp from {url}")
        return match.group(1)

    def _extract_original_url(self, url):
        match = re.search(r"/web/\d{14}/(.+)", url)
        if not match:
            raise ValueError(f"Could not extract original URL from {url}")
        return match.group(1)

    async def extract_rewritten_resources(self, page):
        """Recursively collect all rewritten URLs from the DOM."""
        resources = await page.evaluate("""
            () => {
                const results = [];
                const seen = new Set();

                function addUrl(url, tagName, attr, rel) {
                    if (!url) return;
                    // Only keep rewritten URLs
                    if (!(url.startsWith('/web/') || url.startsWith('https://web.archive.org/web/'))) return;
                    // Skip Wayback's own toolbar assets
                    if (url.includes('web-static.archive.org') || url.includes('/_static/')) return;
                    if (seen.has(url)) return;
                    seen.add(url);
                    // Determine type from prefix
                    let type = 'other';
                    if (url.includes('/im_/')) type = 'images';
                    else if (url.includes('/js_/')) type = 'scripts';
                    else if (url.includes('/cs_/')) type = 'stylesheets';
                    else if (url.includes('/if_/')) type = 'iframes';
                    else if (url.includes('/fr_/')) type = 'frames';
                    else if (url.includes('/mp_/')) type = 'other';
                    // Also check tag name for better guessing
                    const tag = (tagName || '').toLowerCase();
                    if (tag === 'img') type = 'images';
                    else if (tag === 'script') type = 'scripts';
                    else if (tag === 'link' && rel === 'stylesheet') type = 'stylesheets';
                    else if (tag === 'iframe') type = 'iframes';
                    else if (tag === 'video' || tag === 'audio') type = 'media';
                    else if (tag === 'source') type = 'source';
                    else if (tag === 'object' || tag === 'embed') type = 'object';
                    results.push({ url, type });
                }

                function parseSrcset(srcset) {
                    if (!srcset) return [];
                    return srcset.split(',').map(s => s.trim().split(' ')[0]).filter(u => u);
                }

                function extractStyleUrls(style) {
                    if (!style) return [];
                    const matches = style.match(/url\\(['"]?([^'"()]+)['"]?\\)/g);
                    if (!matches) return [];
                    return matches.map(m => m.replace(/url\\(['"]?/, '').replace(/['"]?\\)/, ''));
                }

                function traverse(node) {
                    // Walk child nodes
                    if (node.childNodes) {
                        for (let child of node.childNodes) {
                            traverse(child);
                        }
                    }
                    // If it's an element, check attributes
                    if (node.nodeType === 1) {
                        const tag = node.tagName.toLowerCase();
                        const rel = node.rel || '';
                        // Check src, href, data-src, data-original, etc.
                        const attrs = ['src', 'href', 'data-src', 'data-original', 'data-srcset'];
                        for (let attr of attrs) {
                            let val = node.getAttribute(attr);
                            if (val) {
                                if (attr === 'data-srcset' || attr === 'srcset') {
                                    for (let u of parseSrcset(val)) {
                                        addUrl(u, tag, attr, rel);
                                    }
                                } else {
                                    addUrl(val, tag, attr, rel);
                                }
                            }
                        }
                        // srcset attribute (if not covered)
                        let srcset = node.getAttribute('srcset');
                        if (srcset) {
                            for (let u of parseSrcset(srcset)) {
                                addUrl(u, tag, 'srcset', rel);
                            }
                        }
                        // style attribute for background images
                        const style = node.getAttribute('style');
                        if (style) {
                            const styleUrls = extractStyleUrls(style);
                            for (let u of styleUrls) {
                                addUrl(u, tag, 'style', rel);
                            }
                        }
                        // Shadow DOM
                        if (node.shadowRoot) {
                            traverse(node.shadowRoot);
                        }
                        // Iframe content (same-origin only)
                        if (tag === 'iframe' && node.contentDocument) {
                            try {
                                traverse(node.contentDocument);
                            } catch (e) { /* cross-origin */ }
                        }
                    }
                }

                traverse(document);
                return results;
            }
        """)
        return resources

    def get_resource_metadata(self, rewritten_url):
        if rewritten_url.startswith("/web/"):
            full_url = "https://web.archive.org" + rewritten_url
        else:
            full_url = rewritten_url

        try:
            resp = self.session.head(full_url, timeout=20, allow_redirects=True)
            status = resp.status_code
            memento = resp.headers.get("Memento-Datetime")
            content_type = resp.headers.get("Content-Type")
            final_url = resp.url

            # Compute delta
            delta_text = None
            if memento:
                try:
                    resource_dt = parsedate_to_datetime(memento)
                    main_dt = datetime.strptime(self.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                    delta = resource_dt - main_dt
                    total_seconds = delta.total_seconds()
                    sign = "+" if total_seconds >= 0 else "-"
                    total_seconds = abs(total_seconds)

                    years = int(total_seconds // (86400 * 30 * 12))
                    total_seconds -= years * 86400 * 30 * 12
                    months = int(total_seconds // (86400 * 30))
                    total_seconds -= months * 86400 * 30
                    days = int(total_seconds // 86400)
                    total_seconds -= days * 86400
                    hours = int(total_seconds // 3600)
                    total_seconds -= hours * 3600
                    minutes = int(total_seconds // 60)
                    seconds = int(total_seconds % 60)

                    parts = []
                    if years > 0:
                        parts.append(f"{years} year{'s' if years != 1 else ''}")
                    if months > 0:
                        parts.append(f"{months} month{'s' if months != 1 else ''}")
                    if days > 0:
                        parts.append(f"{days} day{'s' if days != 1 else ''}")
                    if hours > 0:
                        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
                    if minutes > 0:
                        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
                    if seconds > 0 and not parts:
                        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
                    if not parts:
                        parts.append("0 seconds")
                    if len(parts) > 2:
                        parts = parts[:2]
                    delta_text = f"{sign} {', '.join(parts)}"
                except Exception:
                    delta_text = "unknown"

            return {
                "rewritten_url": rewritten_url,
                "full_url": full_url,
                "status_code": status,
                "memento_datetime": memento,
                "content_type": content_type,
                "final_url": final_url,
                "delta_text": delta_text,
                "available": status == 200,
            }
        except Exception as e:
            return {
                "rewritten_url": rewritten_url,
                "full_url": full_url,
                "status_code": "error",
                "error": str(e),
                "delta_text": None,
                "available": False,
            }

    async def analyze_page(self):
        print(f"Analyzing: {self.archived_url}")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # Block analytics to speed up
            await page.route("**/*", lambda route: route.abort() if any(
                domain in route.request.url for domain in [
                    "google-analytics.com", "googletagmanager.com", "analytics",
                    "chartbeat.com", "amplitude.com", "cookielaw.org",
                    "doubleclick.net", "pub.network", "onesignal.com"
                ]
            ) else route.continue_())

            print("Loading page...")
            await page.goto(self.archived_url, wait_until="load", timeout=60000)
            await page.wait_for_timeout(2000)

            # Scroll to bottom to trigger lazy loading
            print("Scrolling to load lazy content...")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(1000)

            print("Extracting rewritten resources from DOM...")
            resources = await self.extract_rewritten_resources(page)
            print(f"Found {len(resources)} rewritten resources")

            # Deduplicate (should already be deduped but let's be safe)
            seen = set()
            unique = []
            for r in resources:
                if r["url"] not in seen:
                    seen.add(r["url"])
                    unique.append(r)
            resources = unique

            await browser.close()

        results = []
        total = len(resources)
        for idx, res in enumerate(resources, 1):
            rewritten_url = res["url"]
            res_type = res["type"]
            print(f"  [{idx}/{total}] Checking {res_type}: {rewritten_url[:80]}...")
            metadata = self.get_resource_metadata(rewritten_url)
            metadata["type"] = res_type
            results.append(metadata)

        output = {
            "archived_page_url": self.archived_url,
            "original_url": self.base_url,
            "capture_timestamp": self.timestamp,
            "analysis_time": datetime.now().isoformat(),
            "total_resources": len(results),
            "resources": results,
            "summary": self._generate_summary(results),
        }
        return output

    def _generate_summary(self, resources):
        total = len(resources)
        available = sum(1 for r in resources if r.get("available", False))
        status_counts = {}
        for r in resources:
            status = r.get("status_code")
            if status is not None and status != "error":
                status_counts[str(status)] = status_counts.get(str(status), 0) + 1
            else:
                status_counts["error"] = status_counts.get("error", 0) + 1

        by_type = {}
        for r in resources:
            t = r["type"]
            if t not in by_type:
                by_type[t] = {"total": 0, "available": 0}
            by_type[t]["total"] += 1
            if r.get("available", False):
                by_type[t]["available"] += 1

        return {
            "total": total,
            "available": available,
            "status_counts": status_counts,
            "by_type": by_type,
        }

    def save_json(self, data, filename=None):
        if filename is None:
            filename = f"wayback_dom_analysis_{self.timestamp}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved results to {filename}")
        return filename

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract rewritten resources from DOM and get Memento-Datetime")
    parser.add_argument("url", help="Archived page URL")
    parser.add_argument("-o", "--output", help="Output JSON file name", default=None)
    args = parser.parse_args()

    extractor = WaybackDomExtractor(args.url)
    results = await extractor.analyze_page()

    summary = results["summary"]
    print("\n" + "="*60)
    print("ANALYSIS SUMMARY")
    print("="*60)
    print(f"Total resources: {summary['total']}")
    print(f"Available (HTTP 200): {summary['available']}")
    print("\nStatus code distribution:")
    for code, count in summary["status_counts"].items():
        print(f"  {code}: {count}")
    print("\nBy resource type:")
    for t, stats in summary["by_type"].items():
        print(f"  {t}: {stats['available']}/{stats['total']} available")

    extractor.save_json(results, args.output)

if __name__ == "__main__":
    asyncio.run(main())