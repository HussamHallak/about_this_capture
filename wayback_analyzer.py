import asyncio
import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse
from playwright.async_api import async_playwright
import requests

class WaybackBrowserAnalyzer:
    def __init__(self, archived_url):
        self.archived_url = archived_url
        self.base_url = self._extract_original_url(archived_url)
        self.timestamp = self._extract_timestamp(archived_url)
        self.archive_origin = "https://web.archive.org"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; WaybackAnalyzer/1.0)"
        })
        self.resources = []

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

    async def extract_resources_from_page(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # Navigate to the archived page
            print(f"Loading {self.archived_url}...")
            await page.goto(self.archived_url, wait_until="networkidle", timeout=60000)
            
            # Wait a bit more for any lazy content
            await page.wait_for_timeout(2000)
            
            # Extract all elements with src or href starting with /web/ or https://web.archive.org/web/
            resources = await page.evaluate("""
                () => {
                    const results = [];
                    const elements = document.querySelectorAll('[src], [href]');
                    const seen = new Set();
                    for (const el of elements) {
                        let url = el.getAttribute('src') || el.getAttribute('href');
                        if (!url) continue;
                        // Only keep rewritten URLs (relative or absolute)
                        if (url.startsWith('/web/') || url.startsWith('https://web.archive.org/web/')) {
                            // Determine type
                            let type = 'other';
                            const tag = el.tagName.toLowerCase();
                            if (tag === 'img') type = 'images';
                            else if (tag === 'script') type = 'scripts';
                            else if (tag === 'link' && el.rel === 'stylesheet') type = 'stylesheets';
                            else if (tag === 'iframe') type = 'iframes';
                            else if (tag === 'video' || tag === 'audio') type = 'media';
                            else if (tag === 'source') type = 'source';
                            else if (tag === 'object' || tag === 'embed') type = 'object';
                            else if (tag === 'link' && el.rel === 'preload') type = 'preload';
                            
                            // Also check srcset, data-src, etc.
                            const srcset = el.getAttribute('srcset');
                            if (srcset) {
                                // Parse srcset, but we'll just add the main src for now
                            }
                            const key = url;
                            if (!seen.has(key)) {
                                seen.add(key);
                                results.push({ url, type });
                            }
                        }
                    }
                    // Also look for elements with data-src, data-original, etc. that might not have src/href
                    const dataElements = document.querySelectorAll('[data-src], [data-original], [data-srcset]');
                    for (const el of dataElements) {
                        let url = el.getAttribute('data-src') || el.getAttribute('data-original') || el.getAttribute('data-srcset');
                        if (!url) continue;
                        if (url.startsWith('/web/') || url.startsWith('https://web.archive.org/web/')) {
                            // Parse srcset? For simplicity, treat as image
                            const tag = el.tagName.toLowerCase();
                            const type = (tag === 'img' || tag === 'source') ? 'images' : 'other';
                            const key = url;
                            if (!seen.has(key)) {
                                seen.add(key);
                                results.push({ url, type });
                            }
                        }
                    }
                    return results;
                }
            """)
            
            await browser.close()
            return resources

    def get_resource_metadata(self, rewritten_url):
        # Same as before: HEAD request, read headers
        if rewritten_url.startswith("/web/"):
            full_url = self.archive_origin + rewritten_url
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
                    from email.utils import parsedate_to_datetime
                    from datetime import timezone
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

                except Exception as e:
                    delta_text = "unknown"

            return {
                "rewritten_url": rewritten_url,
                "full_url": full_url,
                "status_code": status,
                "memento_datetime": memento,
                "content_type": content_type,
                "final_url": final_url,
                "available": status == 200,
                "delta_text": delta_text,
            }

        except requests.exceptions.RequestException as e:
            return {
                "rewritten_url": rewritten_url,
                "full_url": full_url,
                "status_code": "error",
                "error": str(e),
                "available": False,
            }

    async def analyze_page(self):
        print(f"Analyzing: {self.archived_url}")
        print("Extracting resources via headless browser...")
        resources = await self.extract_resources_from_page()
        print(f"Found {len(resources)} rewritten resources in the DOM")

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
            filename = f"wayback_analysis_{self.timestamp}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Saved results to {filename}")
        return filename

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Headless browser extraction of 'About this capture' resources")
    parser.add_argument("url", help="Archived page URL")
    parser.add_argument("-o", "--output", help="Output JSON file name", default=None)
    args = parser.parse_args()

    analyzer = WaybackBrowserAnalyzer(args.url)
    results = await analyzer.analyze_page()

    summary = results["summary"]
    print("\n" + "="*60)
    print("ANALYSIS SUMMARY")
    print("="*60)
    print(f"Total resources: {summary['total']}")
    print(f"Available (HTTP 200 with Memento-Datetime): {summary['available']}")
    print("\nStatus code distribution:")
    for code, count in summary["status_counts"].items():
        print(f"  {code}: {count}")
    print("\nBy resource type:")
    for t, stats in summary["by_type"].items():
        print(f"  {t}: {stats['available']}/{stats['total']} available")

    analyzer.save_json(results, args.output)

if __name__ == "__main__":
    asyncio.run(main())