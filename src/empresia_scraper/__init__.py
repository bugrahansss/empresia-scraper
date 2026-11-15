"""Scrape Empresia.es company reports, search results and BORME announcements with Python."""

from .client import EmpresiaScraper, ScrapeError
from .parser import (
    CSV_FIELDS,
    Announcement,
    BormeEntry,
    Company,
    Event,
    Officer,
    SearchResult,
    Trademark,
    borme_url,
    company_url,
    decode_cfemail,
    parse_amount,
    parse_borme_links,
    parse_borme_listing,
    parse_company,
    parse_event,
    parse_search,
    search_url,
)

__all__ = [
    "CSV_FIELDS",
    "Announcement",
    "BormeEntry",
    "Company",
    "EmpresiaScraper",
    "Event",
    "Officer",
    "ScrapeError",
    "SearchResult",
    "Trademark",
    "borme_url",
    "company_url",
    "decode_cfemail",
    "parse_amount",
    "parse_borme_links",
    "parse_borme_listing",
    "parse_company",
    "parse_event",
    "parse_search",
    "search_url",
]

__version__ = "0.1.0"
