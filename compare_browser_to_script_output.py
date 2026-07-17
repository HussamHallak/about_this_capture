#!/usr/bin/env python3
"""
compare_urls.py

Extracts URLs from a plain-text "timestamps" file and a Wayback-Machine style
JSON resource file, then reports:
  - URLs unique to the text file
  - URLs unique to the JSON file
  - URLs common to both files

Usage:
    python compare_urls.py <txt_file> <json_file> [-o output_prefix]

The script writes three files:
    <output_prefix>_unique_txt.txt
    <output_prefix>_unique_json.txt
    <output_prefix>_common.txt
and also prints a summary to stdout.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit, parse_qsl, urlencode

# Matches the wayback-machine wrapper prefix, e.g.:
#   /web/20260207013744im_/https://example.com/...
#   https://web.archive.org/web/20260207013744cs_/https://example.com/...
WAYBACK_PREFIX_RE = re.compile(r'/web/\d+[a-zA-Z]*_/(https?://.+)$')

# Matches a bare URL at the start of a line in the text file (before any
# trailing "  -2 days 10 hours" / "  +55 seconds" style timestamp delta).
TXT_LINE_URL_RE = re.compile(r'^\s*(https?://\S+?)(?:\s+[-+].*)?\s*$')


def normalize(url: str) -> str:
    """Normalize a URL so equivalent URLs compare equal.

    - Strips any Wayback Machine wrapper prefix to get the original URL.
    - Percent-decodes the URL so differently-encoded (but equivalent)
      URLs match (e.g. Arabic filenames encoded vs. the same bytes
      literally, or %2C vs. a literal comma).
    """
    url = url.strip()

    # Unwrap Wayback Machine style prefixes, possibly nested.
    while True:
        m = WAYBACK_PREFIX_RE.search(url)
        if not m:
            break
        url = m.group(1)

    # Percent-decode for consistent comparison.
    try:
        url = unquote(url)
    except Exception:
        pass

    # Sort query-string parameters so that URLs which only differ in
    # parameter order (e.g. '?resize=X&quality=Y' vs '?quality=Y&resize=X')
    # are treated as identical.
    try:
        parts = urlsplit(url)
        if parts.query:
            params = sorted(parse_qsl(parts.query, keep_blank_values=True))
            new_query = urlencode(params)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except Exception:
        pass

    return url


def extract_urls_from_txt(path: Path):
    """Extract URLs from the plain text timestamps file.

    Each non-empty line is expected to start with a URL, optionally followed
    by whitespace and a +/- time delta (e.g. '-2 days 10 hours').
    """
    urls = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = TXT_LINE_URL_RE.match(line)
            if m:
                urls.append(m.group(1))
            elif line.startswith('http'):
                # Fallback: just take the first whitespace-separated token.
                urls.append(line.split()[0])
    return urls


def extract_urls_from_json(path: Path):
    """Extract URLs from the Wayback-style JSON file.

    Looks at every resource entry's 'full_url' (falling back to
    'rewritten_url' or 'final_url' if needed) so we get one original URL
    per resource.
    """
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)

    urls = []
    resources = data.get('resources', [])
    for res in resources:
        raw = res.get('full_url') or res.get('rewritten_url') or res.get('final_url')
        if raw:
            urls.append(raw)
    return urls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('txt_file', type=Path, help='Path to the .txt timestamps file')
    parser.add_argument('json_file', type=Path, help='Path to the .json resources file')
    parser.add_argument(
        '-o', '--output-prefix', default='url_comparison',
        help='Prefix for the output files (default: url_comparison)'
    )
    parser.add_argument(
        '--outdir', type=Path, default=Path('.'),
        help='Directory to write output files to (default: current directory)'
    )
    args = parser.parse_args()

    raw_txt_urls = extract_urls_from_txt(args.txt_file)
    raw_json_urls = extract_urls_from_json(args.json_file)

    # Map normalized URL -> one example original form (for nicer reporting)
    txt_map = {}
    for u in raw_txt_urls:
        txt_map.setdefault(normalize(u), u)

    json_map = {}
    for u in raw_json_urls:
        json_map.setdefault(normalize(u), u)

    txt_set = set(txt_map.keys())
    json_set = set(json_map.keys())

    unique_txt = sorted(txt_set - json_set)
    unique_json = sorted(json_set - txt_set)
    common = sorted(txt_set & json_set)

    args.outdir.mkdir(parents=True, exist_ok=True)

    def write_list(filename, normalized_urls, source_map):
        out_path = args.outdir / filename
        with out_path.open('w', encoding='utf-8') as f:
            for nu in normalized_urls:
                f.write(source_map[nu] + '\n')
        return out_path

    txt_out = write_list(f'{args.output_prefix}_unique_txt.txt', unique_txt, txt_map)
    json_out = write_list(f'{args.output_prefix}_unique_json.txt', unique_json, json_map)
    # For common URLs, show the normalized (original, unwrapped) form.
    common_out = args.outdir / f'{args.output_prefix}_common.txt'
    with common_out.open('w', encoding='utf-8') as f:
        for nu in common:
            f.write(nu + '\n')

    print(f'Text file:  {args.txt_file}  -> {len(raw_txt_urls)} URLs found, {len(txt_set)} unique')
    print(f'JSON file:  {args.json_file} -> {len(raw_json_urls)} URLs found, {len(json_set)} unique')
    print()
    print(f'Unique to text file:  {len(unique_txt)}  -> {txt_out}')
    print(f'Unique to JSON file:  {len(unique_json)} -> {json_out}')
    print(f'Common to both:       {len(common)}  -> {common_out}')


if __name__ == '__main__':
    main()