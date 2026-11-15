# Empresia Scraper

[![PyPI](https://img.shields.io/pypi/v/empresia-scraper)](https://pypi.org/project/empresia-scraper/)
[![Python](https://img.shields.io/pypi/pyversions/empresia-scraper)](https://pypi.org/project/empresia-scraper/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Scrape [Empresia.es](https://www.empresia.es), the free Spanish company directory built on the Commercial Registry (BORME), into structured data. Open a company report and get its **CIF, CNAE code, corporate purpose, share capital, sales band, sales history, employees, registry, address, phones, websites, e-mail, board, officers with appointment dates, BORME announcements and trademarks**. Search by name, or pull **every company incorporated on a given day**, province by province. JSON or CSV.

```bash
pip install empresia-scraper
export SCRAPEDO_TOKEN=your_token
empresia-scraper telefonica mercadona -f csv -o companies.csv
empresia-scraper --borme 2026-11-13 --province madrid --details -o new_companies.json
```

## Why go through an API

```python
import requests

requests.get("https://www.empresia.es/empresa/telefonica/")
# fine for a few pages; a crawl of thousands of companies from one IP is what gets throttled
```

Empresia sits behind Cloudflare. A few requests from your laptop go through, but bulk crawls (all incorporations of a month, thousands of company reports) from a single IP are what get rate limited. This package sends each page through [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=readme&utm_campaign=empresia-scraper), which rotates the IP for every request and retries failures. A plain Scrape.do request is enough: **1 credit per page**, about 2 seconds.

## Where the data is

Empresia renders on the server, so every field is in the HTML:

* **Company page** (`/empresa/<slug>/`): the identity box (`.datos-ident`) holds name, phones, fax, address and websites; the e-mail is hidden with Cloudflare's e-mail obfuscation (`data-cfemail`, a one-byte XOR key) and decoded here. Label/value pairs give CIF, incorporation date, share capital, sales band, registry, last filed accounts, employees, governing body and auditor. The yearly sales series sits in a Google Charts `arrayToDataTable(...)` call. Below: the board (`#organigrama`), officers with appointment and removal dates (`#ListaRelaciones`), the BORME timeline (`#ListaEventos`) and trademarks (`#MarcasEmpresa`).
* **Search** (`/busqueda/?q=<text>&pagina=<n>`): companies, officers and trademarks. Empresia stops at 100 results.
* **BORME day** (`/borme/fecha/<date>/acto/<act>/provincia/<province>/`): every company with that act (incorporation, dissolution, capital increase, change of address, appointments...) published that day, with a link to each announcement.
* **Announcement** (`/empresa/<slug>/evento/<id>/`): for incorporations, a table with registry, start date, corporate purpose, registered address and share capital, plus the link to the official BORME PDF.

In a live test: a company page returned 13 board members, 30 officers, 31 announcements and 9 trademarks in one request; the BORME of 13 November 2026 had 41 act types across 34 provinces, and Barcelona alone had 71 incorporations.

The company page shows the 30 most recent officers and announcements; the rest load on demand and are not collected.

## Python

```python
from empresia_scraper import EmpresiaScraper

em = EmpresiaScraper(token="YOUR_SCRAPEDO_TOKEN")  # or set SCRAPEDO_TOKEN

company = em.get_company("telefonica")             # slug or URL
print(company.cif, company.cnae_code, company.share_capital_eur, company.employees)
print(company.sales_band, company.sales_history)
print([(o.name, o.role) for o in company.board][:3])

results = em.search("construcciones", pages=2, kind="EMPRESA")

for event in em.new_companies("2026-11-13", province="madrid", limit=10):
    print(event.company, event.share_capital_eur, event.corporate_purpose)

print(em.borme_acts("2026-11-13"))                 # constitucion, disolucion, ...
print(em.credits_used)
```

## Command line

```bash
# Company reports by slug or URL
empresia-scraper telefonica https://www.empresia.es/empresa/mercadona/ -f csv -o companies.csv

# Search, then open every company found (one request each)
empresia-scraper --search "construcciones" --pages 2 --companies --limit 20

# New incorporations of one day (all provinces if --province is left out)
empresia-scraper --borme 2026-11-13 --province barcelona --details -f csv -o new_bcn.csv

# Any other act: dissolutions in Valencia
empresia-scraper --borme 2026-11-13 --act disolucion --province valencia
```

## Fields

**Company:** `name`, `cif`, `phones`, `fax`, `address`, `websites`, `email`, `corporate_purpose`, `cnae_code`, `cnae_description`, `incorporation_date`, `age`, `share_capital`, `share_capital_eur`, `sales_band`, `registry`, `last_accounts_year`, `employees`, `governing_body`, `auditor`, `sales_history`, `board`, `officers`, `announcements`, `trademarks`, `url`.

**Announcement:** `title`, `company`, `company_url`, `published`, `pdf_url`, `text`, `registration`, `registry`, `start_date`, `corporate_purpose`, `address`, `share_capital`, `share_capital_eur`, `details`, `url`.

Values Empresia shows as `-` come back empty. The sales band is a range ("Superior a 2.500.000 euros"), not an exact figure.

## Use it responsibly

The data comes from public registers (BORME, BOE, OEPM), but officers are real people, so their names are personal data under the GDPR. Use it for legitimate purposes such as B2B research, KYC or market analysis, keep only what you need, honour objection requests and respect Empresia's terms. This is not legal advice.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

The fixtures are fictional ("EJEMPLO SOLUCIONES SL", example.com).

## License

MIT
