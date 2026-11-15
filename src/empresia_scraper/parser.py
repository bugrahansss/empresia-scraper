"""Parse Empresia.es pages: company reports, search results and BORME announcements.

Empresia renders everything on the server, so each page already holds its data
in the HTML:

* A **company page** (``/empresa/<slug>/``) has the identity box (name, phones,
  fax, address, websites, an e-mail hidden by Cloudflare's e-mail obfuscation),
  the corporate purpose with its CNAE code, CIF, incorporation date, share
  capital, sales band, registry, last filed accounts, employees, governing
  body and auditor. Below that come the yearly sales series (inside a Google
  Charts call), the board, every officer with the dates of appointment and
  removal, the BORME announcement timeline and the trademarks.
* A **search page** (``/busqueda/?q=<text>&pagina=<n>``) lists 30 results per
  page (companies, officers and trademarks), at most 100 in total.
* A **BORME day** (``/borme/fecha/<date>/acto/<act>/provincia/<province>/``)
  lists every company with that act (incorporations, dissolutions, capital
  changes...) published in the Official Gazette of the Commercial Registry
  that day, each with a link to the announcement page.
* An **announcement page** (``/empresa/<slug>/evento/<id>/``) has the text of the
  announcement and, for incorporations, a table with registry, start date,
  corporate purpose, registered address and share capital.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.empresia.es"
COMPANY_RE = re.compile(r"^(?:https?://(?:www\.)?empresia\.es)?/empresa/([a-z0-9][a-z0-9-]*)/?(?:[?#].*)?$")
EVENT_RE = re.compile(r"^(?:https?://(?:www\.)?empresia\.es)?/empresa/([a-z0-9][a-z0-9-]*)/evento/(\d+)/?(?:[?#].*)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SALES_RE = re.compile(r"arrayToDataTable\(\s*\[\s*\[\s*'A[^']*'\s*,\s*'Ventas'\s*\]\s*((?:,\s*\[[^\]]*\]\s*)*)\]")
COUNT_RE = re.compile(r"([\d.]+)\s+resultados?\.\s+Mostrando del\s+(\d+)\s+al\s+(\d+)")


def _text(node: Optional[Tag]) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()
    return "" if value in {"-", "--"} else value


def _abs(href: str) -> str:
    if not href:
        return ""
    return href if href.startswith("http") else BASE_URL + href


def company_url(slug_or_url: str) -> str:
    """``telefonica`` or ``/empresa/telefonica/`` or a full URL -> the company page URL."""
    value = slug_or_url.strip()
    match = COMPANY_RE.match(value)
    if match:
        return f"{BASE_URL}/empresa/{match.group(1)}/"
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
        return f"{BASE_URL}/empresa/{value}/"
    raise ValueError(f"Not an Empresia company page or slug: {slug_or_url}")


def is_company_url(url: str) -> bool:
    return bool(COMPANY_RE.match(url.strip()))


def is_event_url(url: str) -> bool:
    return bool(EVENT_RE.match(url.strip()))


def search_url(query: str, page: int = 1) -> str:
    url = f"{BASE_URL}/busqueda/?q={quote_plus(query.strip())}"
    return url + (f"&pagina={page}" if page > 1 else "")


def borme_url(date: str, act: str = "", province: str = "") -> str:
    """BORME day page, optionally for one act (``constitucion``) and one province (``madrid``)."""
    if not DATE_RE.match(date):
        raise ValueError(f"Date must be YYYY-MM-DD: {date}")
    url = f"{BASE_URL}/borme/fecha/{date}/"
    if act:
        url += f"acto/{act.strip('/')}/"
        if province:
            url += f"provincia/{province.strip('/')}/"
    return url


def decode_cfemail(encoded: str) -> str:
    """Cloudflare e-mail obfuscation: first byte is the XOR key for the rest."""
    try:
        data = bytes.fromhex(encoded)
    except ValueError:
        return ""
    if not data:
        return ""
    key = data[0]
    return bytes(b ^ key for b in data[1:]).decode("utf-8", "ignore")


def parse_amount(value: str) -> Optional[float]:
    """``5.670.161.554,00 €`` -> 5670161554.0 (Spanish number format)."""
    match = re.search(r"-?[\d.]+(?:,\d+)?", value or "")
    if not match:
        return None
    try:
        return float(match.group(0).replace(".", "").replace(",", "."))
    except ValueError:
        return None


@dataclass
class Officer:
    name: str = ""
    role: str = ""
    since: str = ""
    until: str = ""
    url: str = ""
    is_company: bool = False


@dataclass
class Announcement:
    date: str = ""
    title: str = ""
    text: str = ""
    registration: str = ""
    pdf_url: str = ""


@dataclass
class Trademark:
    name: str = ""
    status: str = ""
    url: str = ""


@dataclass
class Company:
    """One company report from Empresia."""

    name: str = ""
    cif: str = ""
    phones: List[str] = field(default_factory=list)
    fax: str = ""
    address: str = ""
    websites: List[str] = field(default_factory=list)
    email: str = ""
    corporate_purpose: str = ""
    cnae_code: str = ""
    cnae_description: str = ""
    incorporation_date: str = ""
    age: str = ""
    share_capital: str = ""
    share_capital_eur: Optional[float] = None
    sales_band: str = ""
    registry: str = ""
    last_accounts_year: str = ""
    employees: Optional[int] = None
    governing_body: str = ""
    auditor: str = ""
    sales_history: Dict[str, float] = field(default_factory=dict)
    board: List[Officer] = field(default_factory=list)
    officers: List[Officer] = field(default_factory=list)
    announcements: List[Announcement] = field(default_factory=list)
    trademarks: List[Trademark] = field(default_factory=list)
    url: str = ""

    @property
    def slug(self) -> str:
        match = COMPANY_RE.match(self.url)
        return match.group(1) if match else ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_row(self, separator: str = " | ") -> Dict[str, Any]:
        """Flat dict for CSV: lists joined, nested lists summarised."""
        row = {k: v for k, v in self.to_dict().items() if k in CSV_FIELDS}
        row["phones"] = separator.join(self.phones)
        row["websites"] = separator.join(self.websites)
        row["sales_history"] = separator.join(f"{y}: {v}" for y, v in self.sales_history.items())
        row["board"] = separator.join(f"{o.name} ({o.role})" for o in self.board)
        row["officers_count"] = len(self.officers)
        row["announcements_count"] = len(self.announcements)
        row["trademarks_count"] = len(self.trademarks)
        return row


CSV_FIELDS = [
    "name", "cif", "phones", "fax", "address", "websites", "email", "corporate_purpose", "cnae_code",
    "cnae_description", "incorporation_date", "age", "share_capital", "share_capital_eur", "sales_band", "registry",
    "last_accounts_year", "employees", "governing_body", "auditor", "sales_history", "board", "officers_count",
    "announcements_count", "trademarks_count", "url",
]


def _field_map(container: Tag) -> Dict[str, Tag]:
    """Label -> value node for the ``list-group-item-heading`` / ``list-group-item-text`` pairs."""
    fields: Dict[str, Tag] = {}
    for heading in container.select("span.list-group-item-heading"):
        value = heading.find_next_sibling("p", class_="list-group-item-text")
        if value is not None:
            fields[_text(heading).rstrip(":")] = value
    return fields


def _split_websites(text: str) -> List[str]:
    parts = re.split(r"(?=(?:https?://|www\.))", text.replace(" ", ""))
    sites = []
    for part in parts:
        part = part.strip().rstrip("/")
        if part and "." in part and part not in sites:
            sites.append(part)
    return sites


def _numbers(text: str) -> List[str]:
    """Phone numbers in a text: tokens of 9+ digits (Spanish numbers are 9 digits)."""
    found = []
    for token in text.replace("\xa0", " ").split():
        token = token.strip(".,;")
        if re.fullmatch(r"\+?\d{9,13}", token) and token not in found:
            found.append(token)
    return found


def _identity(box: Tag, company: Company) -> None:
    name = box.select_one("span.bolder")
    company.name = _text(name)
    for p in box.find_all("p"):
        phone_icon = p.find("i", class_="fa-phone")
        if phone_icon is None:
            continue
        raw = p.decode_contents()
        main, _, fax = raw.partition('class="fa fa-fax"')
        company.phones = _numbers(BeautifulSoup(main, "html.parser").get_text(" "))
        fax_numbers = _numbers(BeautifulSoup("<i " + fax, "html.parser").get_text(" ")) if fax else []
        company.fax = fax_numbers[0] if fax_numbers else ""
        break
    address_icon = box.find("i", class_="fa-address-book")
    if address_icon is not None and address_icon.parent is not None:
        para = address_icon.parent
        parts = []
        for node in para.children:
            if isinstance(node, Tag) and node.name == "a":
                break
            parts.append(node.get_text(" ") if isinstance(node, Tag) else str(node))
        company.address = _clean(" ".join(parts)).rstrip(". ").strip()
        if company.address and not company.address.endswith(")"):
            company.address = company.address.rstrip(".")
    globe = box.find("i", class_="fa-globe")
    if globe is not None:
        texts = []
        for node in globe.next_siblings:
            if isinstance(node, Tag) and node.name in ("br", "i"):
                break
            texts.append(node.get_text("") if isinstance(node, Tag) else str(node))
        company.websites = _split_websites("".join(texts))
    cf = box.select_one("[data-cfemail]")
    if cf is not None:
        company.email = decode_cfemail(cf.get("data-cfemail", ""))
    else:
        mail = box.select_one('a[href^="mailto:"]')
        if mail is not None:
            company.email = mail["href"][7:]


def _officers(soup: BeautifulSoup) -> List[Officer]:
    officers = []
    for row in soup.select("#ListaRelaciones tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        link = cells[0].find("a")
        icon = cells[0].find("i")
        officers.append(Officer(
            name=_text(link) or _text(cells[0]),
            role=_text(cells[1]),
            since=_clean(_text(row.select_one("td.td-relent-desde"))),
            until=_clean(_text(row.select_one("td.td-relent-hasta"))),
            url=_abs(link.get("href", "")) if link else "",
            is_company=bool(icon and "fa-building" in icon.get("class", [])),
        ))
    return officers


def _board(soup: BeautifulSoup) -> List[Officer]:
    board = []
    for li in soup.select("#organigrama li"):
        link = li.find("a")
        if link is None:
            continue
        role = _clean("".join(str(s) for s in li.find_all(string=True, recursive=False)))
        board.append(Officer(name=_text(link), role=role, url=_abs(link.get("href", "")),
                             is_company=link.get("href", "").startswith("/empresa/")))
    return board


def _announcements(soup: BeautifulSoup) -> List[Announcement]:
    items = []
    for li in soup.select("#ListaEventos > li"):
        time_tag = li.find("time")
        date = time_tag.get("datetime", "") if time_tag else ""
        for content in li.select("div.event-content"):
            title = _text(content.find("h3")).rstrip(".")
            date_box = content.select_one("div.event-date")
            registration = ""
            pdf = ""
            if date_box is not None:
                match = re.search(r"Fecha inscripci[oó]n:\s*(.+)", _text(date_box))
                registration = _clean(match.group(1)) if match else ""
                pdf_match = re.search(r"https://www\.boe\.es/[^'\"]+\.pdf", str(date_box))
                pdf = pdf_match.group(0) if pdf_match else ""
                date_box.extract()
            heading = content.find("h3")
            if heading is not None:
                heading.extract()
            items.append(Announcement(date=date, title=title, text=_text(content), registration=registration, pdf_url=pdf))
    return items


def _trademarks(soup: BeautifulSoup) -> List[Trademark]:
    marks = []
    for mark in soup.select("#MarcasEmpresa div.marca"):
        link = mark.select_one("dd a")
        status = mark.select_one("dd span")
        marks.append(Trademark(name=_text(mark.select_one("dt")), status=_text(status), url=_abs(link.get("href", "")) if link else ""))
    return marks


def parse_company(html: str, url: str = "") -> Company:
    """Parse a company page (``/empresa/<slug>/``)."""
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one("div.datos-ident")
    if box is None:
        raise ValueError("No company data on this page (not an Empresia company report?)")
    company = Company(url=url)
    _identity(box, company)
    if not company.name:
        title = _text(soup.find("title"))
        company.name = re.sub(r"\s*\(CIF.*$|\s*-\s*Informe.*$", "", title)

    fields = _field_map(box)
    purpose = fields.get("Objeto social")
    if purpose is not None:
        lines = [l.strip() for l in purpose.get_text("\n").split("\n") if l.strip()]
        cnae_lines = [l for l in lines if l.startswith("CNAE")]
        company.corporate_purpose = _clean(" ".join(l for l in lines if not l.startswith("CNAE")))
        if cnae_lines:
            match = re.match(r"CNAE\s+(\d+)\s*-\s*(.*)", cnae_lines[0])
            if match:
                company.cnae_code, company.cnae_description = match.group(1), _clean(match.group(2))
    get = lambda label: _clean(_text(fields.get(label)))  # noqa: E731
    company.cif = get("CIF")
    company.incorporation_date = get("Fecha constitución")
    company.age = get("Antigüedad")
    company.share_capital = get("Capital social").replace("€", "EUR").strip()
    company.share_capital_eur = parse_amount(company.share_capital) if company.share_capital else None
    sales = fields.get("Ventas")
    if sales is not None:
        tip = sales.select_one("[title]")
        company.sales_band = _clean(tip["title"]) if tip is not None else get("Ventas")
    company.registry = get("Registro")
    company.last_accounts_year = get("Últimas cuentas depositadas")
    employees = get("Número empleados")
    company.employees = int(employees.replace(".", "")) if employees.replace(".", "").isdigit() else None
    company.governing_body = get("Órgano administración")
    company.auditor = get("Auditor")

    match = SALES_RE.search(html)
    if match:
        for year, value in re.findall(r"\[\s*(\d{4})\s*,\s*([-\d.]+)\s*\]", match.group(1)):
            try:
                company.sales_history[year] = float(value)
            except ValueError:
                pass
    company.board = _board(soup)
    company.officers = _officers(soup)
    company.announcements = _announcements(soup)
    company.trademarks = _trademarks(soup)
    return company


@dataclass
class SearchResult:
    name: str = ""
    kind: str = ""  # EMPRESA, DIRECTIVO or DISTINTIVO
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_search(html: str) -> Tuple[List[SearchResult], int]:
    """Results of a search page and the total the site reports."""
    soup = BeautifulSoup(html, "html.parser")
    total = 0
    counter = soup.select_one("div.ralign")
    match = COUNT_RE.search(_text(counter)) if counter else None
    if match:
        total = int(match.group(1).replace(".", ""))
    results = []
    table = soup.select_one("#contenido table")
    for row in table.select("tbody tr") if table else []:
        cell = row.find("td")
        link = cell.find("a") if cell else None
        if link is None:
            continue
        kind = _clean(cell.get_text(" ").replace(link.get_text(" "), "", 1)).upper()
        results.append(SearchResult(name=_text(link), kind=kind, url=_abs(link.get("href", ""))))
    return results, total


def search_page_range(html: str) -> Tuple[int, int]:
    """``(first, last)`` result numbers shown on a search page, ``(0, 0)`` if unknown."""
    soup = BeautifulSoup(html, "html.parser")
    match = COUNT_RE.search(_text(soup.select_one("div.ralign")))
    return (int(match.group(2)), int(match.group(3))) if match else (0, 0)


@dataclass
class BormeEntry:
    company: str = ""
    company_url: str = ""
    event_url: str = ""
    act: str = ""
    province: str = ""
    date: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_borme_listing(html: str) -> List[BormeEntry]:
    """Companies on a BORME act page for one province."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for row in soup.select("#contenido table tbody tr"):
        link = row.select_one("a.lk") or row.find("a")
        if link is None or not link.get("href", "").startswith("/empresa/"):
            continue
        event = row.select_one('a[href*="/evento/"]')
        entries.append(BormeEntry(company=_text(link), company_url=_abs(link["href"]),
                                  event_url=_abs(event["href"]) if event else ""))
    return entries


def parse_borme_links(html: str, date: str) -> Dict[str, List[str]]:
    """Acts and provinces linked from a BORME day or act page."""
    acts, provinces = [], []
    for href in re.findall(r'href="(?:https://www\.empresia\.es)?(/borme/fecha/' + re.escape(date) + r'/acto/[^"#]+)"', html):
        match = re.match(r"/borme/fecha/[^/]+/acto/([^/]+)/(?:provincia/([^/]+)/)?$", href)
        if not match:
            continue
        if match.group(2):
            if match.group(2) not in provinces:
                provinces.append(match.group(2))
        elif match.group(1) not in acts:
            acts.append(match.group(1))
    return {"acts": acts, "provinces": provinces}


@dataclass
class Event:
    """One BORME announcement page."""

    title: str = ""
    company: str = ""
    company_url: str = ""
    published: str = ""
    pdf_url: str = ""
    text: str = ""
    registration: str = ""
    registry: str = ""
    start_date: str = ""
    corporate_purpose: str = ""
    address: str = ""
    share_capital: str = ""
    share_capital_eur: Optional[float] = None
    details: Dict[str, str] = field(default_factory=dict)
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_event(html: str, url: str = "") -> Event:
    """Parse an announcement page (``/empresa/<slug>/evento/<id>/``)."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#contenido")
    if content is None:
        raise ValueError("No announcement on this page")
    event = Event(url=url)
    event.title = _text(soup.select_one("h1"))
    published = soup.select_one("#spanFechaPublicacion time")
    event.published = published.get("datetime", "") if published else ""
    source = soup.select_one("#spanFuente a")
    event.pdf_url = source.get("href", "") if source else ""
    intro = content.find("p")
    company_link = intro.find("a", href=COMPANY_RE) if intro else None
    if company_link is None:
        company_link = content.find("a", href=re.compile(r"^/empresa/[^/]+/$"))
    if company_link is not None:
        event.company = _text(company_link)
        event.company_url = _abs(company_link["href"])
    body = content.select_one("div.eventonly")
    if body is not None:
        paragraph = body.find("p")
        event.text = _text(paragraph)
        for row in body.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                event.details[_text(cells[0]).rstrip(":")] = _text(cells[1])
        date_box = body.select_one("div.event-date")
        match = re.search(r"Fecha inscripci[oó]n:\s*(.+)", _text(date_box)) if date_box else None
        event.registration = _clean(match.group(1)) if match else ""
    if not event.company:
        event.company = event.details.get("Sociedad", "")
    event.registry = event.details.get("Registro", "")
    event.start_date = event.details.get("Fecha inicio", "")
    event.corporate_purpose = event.details.get("Objeto social", "")
    event.address = event.details.get("Domicilio", "")
    event.share_capital = event.details.get("Capital", "")
    event.share_capital_eur = parse_amount(event.share_capital) if event.share_capital else None
    return event


def to_json(items: List[Any]) -> str:
    return json.dumps([i.to_dict() for i in items], indent=2, ensure_ascii=False)
