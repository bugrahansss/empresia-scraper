"""Fetch Empresia.es pages through the Scrape.do API.

Empresia sits behind Cloudflare. A handful of requests from one IP go through,
but a crawl of thousands of company pages from a single address is what gets
rate limited. Sending every request through Scrape.do rotates the IP for each
page, retries failures and keeps the crawl going. A plain Scrape.do request
(no extra parameters) is enough: 1 credit per page.
"""

from __future__ import annotations

import os
import re
import time
from typing import Iterator, List, Optional

import requests

from .parser import (
    BormeEntry,
    Company,
    Event,
    SearchResult,
    borme_url,
    company_url,
    is_event_url,
    parse_borme_links,
    parse_borme_listing,
    parse_company,
    parse_event,
    parse_search,
    search_page_range,
    search_url,
)

API_URL = "https://api.scrape.do/"
TOKEN_ENV = "SCRAPEDO_TOKEN"
BLOCK_RE = re.compile(r"just a moment\.\.\.|cf-chl-|attention required|cf-turnstile", re.I)
MAX_SEARCH_PAGES = 4  # Empresia stops at 100 results


class ScrapeError(RuntimeError):
    """Raised when a page cannot be fetched."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class EmpresiaScraper:
    """Search Empresia, read company reports and the daily BORME announcements.

    >>> em = EmpresiaScraper(token="YOUR_SCRAPEDO_TOKEN")
    >>> results = em.search("mercadona")
    >>> company = em.get_company("mercadona")
    >>> company.cif, company.cnae_code, company.share_capital_eur, company.employees
    >>> new = em.borme("2026-11-13", act="constitucion", province="madrid")
    """

    def __init__(self, token: Optional[str] = None, timeout: float = 60.0, retries: int = 2,
                 session: Optional[requests.Session] = None):
        self.token = token or os.environ.get(TOKEN_ENV, "")
        if not self.token:
            raise ValueError(f"A Scrape.do API token is required. Pass token=... or set {TOKEN_ENV}.")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session()
        self.requests_made = 0

    def fetch(self, url: str) -> str:
        """Raw HTML of ``url``. Failures and Cloudflare pages are retried."""
        params = {"token": self.token, "url": url}
        last_error: Optional[ScrapeError] = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = ScrapeError(f"Request failed: {exc}")
            else:
                if response.status_code == 200:
                    self.requests_made += 1
                    if not BLOCK_RE.search(response.text[:5000]):
                        return response.text
                    last_error = ScrapeError(f"Cloudflare challenge page for {url}", 200)
                else:
                    last_error = ScrapeError(f"Request for {url} failed with status {response.status_code}",
                                             status_code=response.status_code)
                    if 400 <= response.status_code < 500 and response.status_code != 429:
                        break
            if attempt < self.retries:
                time.sleep(2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    # Search -----------------------------------------------------------------

    def search(self, query: str, pages: int = 1, kind: str = "") -> List[SearchResult]:
        """Companies, officers and trademarks matching ``query``.

        ``kind`` keeps one type: ``EMPRESA`` (company), ``DIRECTIVO`` (officer) or
        ``DISTINTIVO`` (trademark). Empresia shows at most 100 results (4 pages).
        """
        results: List[SearchResult] = []
        seen = set()
        for page in range(1, min(max(1, pages), MAX_SEARCH_PAGES) + 1):
            html = self.fetch(search_url(query, page))
            first, _ = search_page_range(html)
            if page > 1 and first <= 1:
                break  # past the last page Empresia sends page 1 again
            found, total = parse_search(html)
            fresh = [r for r in found if r.url not in seen]
            if not fresh:
                break
            for item in fresh:
                seen.add(item.url)
                results.append(item)
            if total and first + 29 >= total:
                break
        if kind:
            results = [r for r in results if r.kind == kind.upper()]
        return results

    def search_companies(self, query: str, pages: int = 1, limit: int = 0) -> Iterator[Company]:
        """Search, then open each company found (one more request per company)."""
        companies = [r for r in self.search(query, pages, kind="EMPRESA")]
        for result in companies[: limit or None]:
            yield self.get_company(result.url)

    # Company pages ----------------------------------------------------------

    def get_company(self, slug_or_url: str) -> Company:
        """A company report, by slug (``telefonica``) or URL."""
        url = company_url(slug_or_url)
        return parse_company(self.fetch(url), url=url)

    # BORME ------------------------------------------------------------------

    def borme_acts(self, date: str) -> List[str]:
        """Act slugs published on ``date`` (``constitucion``, ``disolucion``, ``ampliacion-de-capital`` ...)."""
        return parse_borme_links(self.fetch(borme_url(date)), date)["acts"]

    def borme_provinces(self, date: str, act: str = "constitucion") -> List[str]:
        """Province slugs with at least one ``act`` announcement on ``date``."""
        return parse_borme_links(self.fetch(borme_url(date, act)), date)["provinces"]

    def borme(self, date: str, act: str = "constitucion", province: str = "") -> List[BormeEntry]:
        """Companies with ``act`` in the BORME of ``date``, for one province or all of them."""
        provinces = [province] if province else self.borme_provinces(date, act)
        entries: List[BormeEntry] = []
        for prov in provinces:
            for entry in parse_borme_listing(self.fetch(borme_url(date, act, prov))):
                entry.act, entry.province, entry.date = act, prov, date
                entries.append(entry)
        return entries

    def get_event(self, url: str) -> Event:
        """One announcement page (``/empresa/<slug>/evento/<id>/``)."""
        if not is_event_url(url):
            raise ValueError(f"Not an Empresia announcement page: {url}")
        if url.startswith("/"):
            url = "https://www.empresia.es" + url
        return parse_event(self.fetch(url), url=url)

    def new_companies(self, date: str, province: str = "", limit: int = 0) -> Iterator[Event]:
        """Incorporations published on ``date`` with capital, purpose, address and start date."""
        for entry in self.borme(date, "constitucion", province)[: limit or None]:
            if entry.event_url:
                yield self.get_event(entry.event_url)

    @property
    def credits_used(self) -> int:
        return self.requests_made
