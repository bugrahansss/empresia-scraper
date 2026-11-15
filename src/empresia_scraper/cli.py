"""Command line entry point.

    empresia-scraper telefonica mercadona -f csv -o companies.csv
    empresia-scraper --search "construcciones" --pages 2 --companies --limit 20
    empresia-scraper --borme 2026-11-13 --province madrid --details -o new_companies.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, List, Optional

from . import __version__
from .client import TOKEN_ENV, EmpresiaScraper, ScrapeError
from .parser import CSV_FIELDS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="empresia-scraper",
                                description="Scrape Empresia.es company reports, search results and BORME announcements.")
    p.add_argument("companies", nargs="*", help="Company slugs (telefonica) or company page URLs")
    p.add_argument("-i", "--input", help="Text file with one company slug or URL per line")
    p.add_argument("-s", "--search", action="append", default=[], help="Search text (repeatable)")
    p.add_argument("--pages", type=int, default=1, help="Search result pages (max 4, default: 1)")
    p.add_argument("--companies", dest="open_companies", action="store_true",
                   help="Open every company found by --search (1 request each)")
    p.add_argument("--borme", metavar="YYYY-MM-DD", help="List companies from the BORME of this date")
    p.add_argument("--act", default="constitucion", help="BORME act slug (default: constitucion)")
    p.add_argument("--province", default="", help="BORME province slug, e.g. madrid (default: all)")
    p.add_argument("--details", action="store_true", help="Open every BORME announcement (1 request each)")
    p.add_argument("--limit", type=int, default=0, help="Stop after this many items (default: no limit)")
    p.add_argument("-t", "--token", help=f"Scrape.do API token (default: ${TOKEN_ENV})")
    p.add_argument("-f", "--format", choices=("json", "csv"), default="json", help="Output format (default: json)")
    p.add_argument("-o", "--output", help="Write to this file instead of stdout")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _rows(items: List[Any]) -> List[dict]:
    rows = []
    for item in items:
        if hasattr(item, "to_row"):
            rows.append(item.to_row())
        else:
            row = item.to_dict()
            row.pop("details", None)
            rows.append(row)
    return rows


def _write(items: List[Any], fmt: str, stream) -> None:
    if fmt == "csv":
        rows = _rows(items)
        fields = CSV_FIELDS if items and hasattr(items[0], "to_row") else (list(rows[0]) if rows else [])
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        json.dump([i.to_dict() for i in items], stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    targets = list(args.companies)
    if args.input:
        with open(args.input, encoding="utf-8") as handle:
            targets.extend(l.strip() for l in handle if l.strip() and not l.startswith("#"))
    if not targets and not args.search and not args.borme:
        print("Nothing to do. Pass company slugs/URLs, --input FILE, --search TEXT or --borme DATE.", file=sys.stderr)
        return 2
    try:
        em = EmpresiaScraper(token=args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    items: List[Any] = []
    failures = 0
    for query in args.search:
        try:
            found = em.search(query, args.pages)
        except ScrapeError as exc:
            failures += 1
            print(f"fail  search {query!r}: {exc}", file=sys.stderr)
            continue
        print(f"found {len(found)} results for {query!r}", file=sys.stderr)
        if args.open_companies:
            targets.extend(r.url for r in found if r.kind == "EMPRESA" and r.url not in targets)
        else:
            items.extend(found)

    if args.borme:
        try:
            entries = em.borme(args.borme, args.act, args.province)
        except (ScrapeError, ValueError) as exc:
            failures += 1
            print(f"fail  borme {args.borme}: {exc}", file=sys.stderr)
            entries = []
        print(f"found {len(entries)} {args.act} announcements on {args.borme}", file=sys.stderr)
        entries = entries[: args.limit or None]
        if args.details:
            for entry in entries:
                try:
                    items.append(em.get_event(entry.event_url))
                except (ScrapeError, ValueError) as exc:
                    failures += 1
                    print(f"fail  {entry.event_url}: {exc}", file=sys.stderr)
        else:
            items.extend(entries)

    if args.limit > 0:
        targets = targets[: max(0, args.limit - len(items))] if items else targets[: args.limit]
    for target in targets:
        try:
            items.append(em.get_company(target))
            print(f"ok    {target}", file=sys.stderr)
        except (ScrapeError, ValueError) as exc:
            failures += 1
            print(f"fail  {target}: {exc}", file=sys.stderr)
    if args.limit > 0:
        items = items[: args.limit]

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="" if args.format == "csv" else None) as handle:
            _write(items, args.format, handle)
        print(f"Saved {len(items)} items to {args.output} ({em.credits_used} credits)", file=sys.stderr)
    else:
        _write(items, args.format, sys.stdout)
    return 1 if failures and not items else 0


if __name__ == "__main__":
    raise SystemExit(main())
