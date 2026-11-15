"""Every company incorporated in one province on one BORME day, with capital and purpose, to CSV.

    export SCRAPEDO_TOKEN=your_token
    python examples/new_companies_to_csv.py 2026-11-13 madrid
"""

import csv
import sys

from empresia_scraper import EmpresiaScraper

date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-13"
province = sys.argv[2] if len(sys.argv) > 2 else "madrid"

em = EmpresiaScraper()
fields = ["company", "registry", "start_date", "share_capital_eur", "corporate_purpose", "address", "published", "url"]
with open(f"new_companies_{province}_{date}.csv", "w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    count = 0
    for event in em.new_companies(date, province=province):
        writer.writerow(event.to_dict())
        count += 1
print(f"{count} new companies, {em.credits_used} credits")
