import requests
import json
import re
import time
from urllib.parse import unquote
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

class WaybackAnalyzer:
    def __init__(self, archived_url):
        self.archived_url = archived_url
        self.base_url = self._extract_original_url(archived_url)
        self.timestamp = self._extract_timestamp(archived_url)
        self.archive_origin = "https://web.archive.org"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; WaybackAnalyzer/1.0)"
        })

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

    def fetch_archived_page(self):
        resp = self.session.get(self.archived_url, timeout=30)
        resp.raise_for_status()
        return resp.text

    def extract_rewritten_resources(self, html):
        soup = BeautifulSoup(html, "html.parser")
        resources = []

        for img in soup.find_all("img"):
            src = img.get("src")
            if src and src.startswith(("/web/", "https://web.archive.org/web/")):
                resources.append({"type": "images", "url": src})

        for script in soup.find_all("script"):
            src = script.get("src")
            if src and src.startswith(("/web/", "https://web.archive.org/web/")):
                resources.append({"type": "scripts", "url": src})

        for link in soup.find_all("link", rel="stylesheet"):
            href = link.get("href")
            if href and href.startswith(("/web/", "https://web.archive.org/web/")):
                resources.append({"type": "stylesheets", "url": href})

        for iframe in soup.find_all("iframe"):
            src = iframe.get("src")
            if src and src.startswith(("/web/", "https://web.archive.org/web/")):
                resources.append({"type": "iframes", "url": src})

        return resources

    def get_resource_metadata(self, rewritten_url):
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

            delta_text = None
            if memento:
                try:
                    resource_dt = parsedate_to_datetime(memento)
                    main_dt = datetime.strptime(self.timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                    delta = resource_dt - main_dt

                    total_seconds = delta.total_seconds()
                    sign = "+" if total_seconds >= 0 else "-"
                    total_seconds = abs(total_seconds)

                    # ---- Browser-style delta calculation (30-day months, 12-month years) ----
                    # Years
                    years = int(total_seconds // (86400 * 30 * 12))
                    total_seconds -= years * 86400 * 30 * 12

                    # Months
                    months = int(total_seconds // (86400 * 30))
                    total_seconds -= months * 86400 * 30

                    # Days
                    days = int(total_seconds // 86400)
                    total_seconds -= days * 86400

                    # Hours
                    hours = int(total_seconds // 3600)
                    total_seconds -= hours * 3600

                    # Minutes
                    minutes = int(total_seconds // 60)
                    seconds = int(total_seconds % 60)

                    # Build parts list, only include non-zero units
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
                    if seconds > 0 and not parts:  # only if no larger unit
                        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

                    # If no parts, it's exactly 0 seconds
                    if not parts:
                        parts.append("0 seconds")

                    # Take only the first two units (like browser)
                    if len(parts) > 2:
                        parts = parts[:2]

                    delta_text = f"{sign} {', '.join(parts)}"

                except Exception as e:
                    print(f"\n[ERROR] Failed to parse Memento-Datetime: '{memento}'")
                    print(f"  Exception: {e}")
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

    def analyze_page(self):
        print(f"Analyzing: {self.archived_url}")
        print("Fetching archived HTML...")
        html = self.fetch_archived_page()

        print("Extracting rewritten resources...")
        resources = self.extract_rewritten_resources(html)
        print(f"Found {len(resources)} resources")

        results = []
        total = len(resources)
        for idx, res in enumerate(resources, 1):
            res_type = res["type"]
            rewritten_url = res["url"]
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


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Replicate 'About this capture' metadata extraction using HEAD requests"
    )
    parser.add_argument("url", help="Archived page URL (e.g., https://web.archive.org/web/.../https://...")
    parser.add_argument("-o", "--output", help="Output JSON file name", default=None)
    args = parser.parse_args()

    analyzer = WaybackAnalyzer(args.url)
    results = analyzer.analyze_page()

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
    main()