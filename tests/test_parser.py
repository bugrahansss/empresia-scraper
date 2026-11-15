import csv
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from empresia_scraper import (  # noqa: E402
    EmpresiaScraper,
    ScrapeError,
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
from empresia_scraper import cli  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
COMPANY = (FIX / "company_ejemplo.html").read_text(encoding="utf-8")
SEARCH = (FIX / "search_ejemplo.html").read_text(encoding="utf-8")
LISTING = (FIX / "borme_madrid.html").read_text(encoding="utf-8")
EVENT = (FIX / "event_ejemplo.html").read_text(encoding="utf-8")
CHALLENGE = (FIX / "challenge.html").read_text(encoding="utf-8")
CURL = "https://www.empresia.es/empresa/ejemplo-soluciones/"


class R:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        return self.responses.pop(0)


class UrlTests(unittest.TestCase):
    def test_company_url(self):
        self.assertEqual(company_url("telefonica"), "https://www.empresia.es/empresa/telefonica/")
        self.assertEqual(company_url("/empresa/telefonica/"), "https://www.empresia.es/empresa/telefonica/")
        self.assertEqual(company_url("https://www.empresia.es/empresa/telefonica"), "https://www.empresia.es/empresa/telefonica/")
        with self.assertRaises(ValueError):
            company_url("https://example.com/x")

    def test_search_url(self):
        self.assertEqual(search_url("hola mundo"), "https://www.empresia.es/busqueda/?q=hola+mundo")
        self.assertTrue(search_url("x", 3).endswith("&pagina=3"))

    def test_borme_url(self):
        self.assertEqual(borme_url("2026-11-13", "constitucion", "madrid"),
                         "https://www.empresia.es/borme/fecha/2026-11-13/acto/constitucion/provincia/madrid/")
        with self.assertRaises(ValueError):
            borme_url("13/11/2026")

    def test_helpers(self):
        self.assertEqual(decode_cfemail("2a" + "".join(format(ord(c) ^ 0x2A, "02x") for c in "a@b.es")), "a@b.es")
        self.assertEqual(decode_cfemail("zz"), "")
        self.assertEqual(parse_amount("5.670.161.554,00 EUR"), 5670161554.0)
        self.assertEqual(parse_amount("3.000,00 Euros"), 3000.0)
        self.assertIsNone(parse_amount("-"))


class CompanyTests(unittest.TestCase):
    def setUp(self):
        self.c = parse_company(COMPANY, url=CURL)

    def test_identity(self):
        c = self.c
        self.assertEqual(c.name, "EJEMPLO SOLUCIONES SL")
        self.assertEqual(c.phones, ["910000001", "910000002"])
        self.assertEqual(c.fax, "910000009")
        self.assertEqual(c.address, "CALLE EJEMPLO, 1 - PLANTA 2 (MADRID)")
        self.assertEqual(c.websites, ["www.example.com", "www.example.org"])
        self.assertEqual(c.email, "info@example.com")
        self.assertEqual(c.slug, "ejemplo-soluciones")

    def test_registry_fields(self):
        c = self.c
        self.assertEqual(c.cif, "B00000000")
        self.assertEqual(c.corporate_purpose, "Desarrollo de software y consultoria informatica.")
        self.assertEqual((c.cnae_code, c.cnae_description), ("6201", "Actividades de programación informática"))
        self.assertEqual(c.incorporation_date, "15/03/2015")
        self.assertEqual(c.share_capital_eur, 60000.0)
        self.assertEqual(c.sales_band, "Entre 500.000 y 1.000.000 euros")
        self.assertEqual(c.registry, "Madrid")
        self.assertEqual(c.last_accounts_year, "2025")
        self.assertEqual(c.employees, 12)
        self.assertEqual(c.governing_body, "Administrador único")
        self.assertEqual(c.auditor, "")
        self.assertEqual(c.sales_history, {"2023": 0.61, "2024": 0.74, "2025": 0.92})

    def test_people_and_events(self):
        c = self.c
        self.assertEqual([(o.name, o.role) for o in c.board], [("Doe Jane", "Adm. Unico")])
        self.assertEqual(len(c.officers), 2)
        self.assertEqual(c.officers[0].since, "15/03/2015")
        self.assertEqual(c.officers[0].until, "")
        self.assertTrue(c.officers[1].is_company)
        self.assertEqual(c.officers[1].until, "01/06/2022")
        self.assertEqual(len(c.announcements), 2)
        first = c.announcements[0]
        self.assertEqual((first.date, first.title), ("2026-10-29", "Cambio de domicilio social"))
        self.assertTrue(first.pdf_url.endswith("BORME-A-2026-209-28.pdf"))
        self.assertTrue(first.registration.startswith("22/10/2026"))
        self.assertNotIn("Fecha inscripción", first.text)
        self.assertEqual(c.announcements[1].date, "2026-10-29")
        self.assertEqual([(t.name, t.status) for t in c.trademarks], [("EJEMPLO APP", "Marca caducada")])

    def test_row_and_errors(self):
        row = self.c.to_row()
        self.assertEqual(row["phones"], "910000001 | 910000002")
        self.assertEqual(row["officers_count"], 2)
        with self.assertRaises(ValueError):
            parse_company("<html><body>nothing</body></html>")


class ListingTests(unittest.TestCase):
    def test_search(self):
        results, total = parse_search(SEARCH)
        self.assertEqual(total, 3)
        self.assertEqual([r.kind for r in results], ["EMPRESA", "DIRECTIVO", "DISTINTIVO"])
        self.assertEqual(results[0].url, CURL)

    def test_borme(self):
        entries = parse_borme_listing(LISTING)
        self.assertEqual([e.company for e in entries], ["EJEMPLO SOLUCIONES SL", "DEMO LOGISTICA SL"])
        self.assertTrue(entries[1].event_url.endswith("/empresa/demo-logistica/evento/1000011/"))
        links = parse_borme_links(LISTING, "2026-11-13")
        self.assertEqual(links["provinces"], ["madrid", "barcelona"])
        self.assertEqual(links["acts"], ["constitucion", "disolucion"])

    def test_event(self):
        e = parse_event(EVENT, url="u")
        self.assertEqual(e.company, "EJEMPLO SOLUCIONES SL")
        self.assertEqual(e.published, "2026-11-13")
        self.assertEqual((e.registry, e.start_date, e.share_capital_eur), ("Madrid", "16.10.26", 3000.0))
        self.assertEqual(e.address, "CALLE EJEMPLO, 1 (MADRID)")
        self.assertTrue(e.pdf_url.endswith(".pdf"))
        self.assertTrue(e.registration.startswith("05/11/2026"))


class ClientTests(unittest.TestCase):
    def test_requires_token(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                EmpresiaScraper()

    def test_get_company_plain_request(self):
        s = Session([R(200, COMPANY)])
        em = EmpresiaScraper(token="t", session=s)
        c = em.get_company("ejemplo-soluciones")
        self.assertEqual(c.cif, "B00000000")
        self.assertEqual(s.calls[0], {"token": "t", "url": CURL})
        self.assertEqual(em.credits_used, 1)

    @mock.patch("empresia_scraper.client.time.sleep")
    def test_retry_challenge_then_ok(self, _):
        s = Session([R(200, CHALLENGE), R(502), R(200, COMPANY)])
        c = EmpresiaScraper(token="t", session=s).get_company(CURL)
        self.assertEqual(c.name, "EJEMPLO SOLUCIONES SL")
        self.assertEqual(len(s.calls), 3)

    def test_404_not_retried(self):
        s = Session([R(404)])
        with self.assertRaises(ScrapeError) as ctx:
            EmpresiaScraper(token="t", session=s, retries=3).get_company("nope")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(len(s.calls), 1)

    def test_search_stops_on_last_page(self):
        s = Session([R(200, SEARCH)])
        results = EmpresiaScraper(token="t", session=s).search("ejemplo", pages=4, kind="empresa")
        self.assertEqual([r.name for r in results], ["EJEMPLO SOLUCIONES SL"])
        self.assertEqual(len(s.calls), 1)

    def test_borme_all_provinces(self):
        s = Session([R(200, LISTING), R(200, LISTING), R(200, LISTING)])
        entries = EmpresiaScraper(token="t", session=s).borme("2026-11-13")
        self.assertEqual(len(entries), 4)
        self.assertEqual({e.province for e in entries}, {"madrid", "barcelona"})
        self.assertTrue(s.calls[2]["url"].endswith("/provincia/barcelona/"))

    def test_new_companies(self):
        s = Session([R(200, LISTING), R(200, EVENT), R(200, EVENT)])
        events = list(EmpresiaScraper(token="t", session=s).new_companies("2026-11-13", province="madrid"))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].share_capital_eur, 3000.0)
        with self.assertRaises(ValueError):
            EmpresiaScraper(token="t", session=Session([])).get_event(CURL)


class CliTests(unittest.TestCase):
    def run_cli(self, argv, responses):
        s = Session(responses)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("empresia_scraper.client.requests.Session", return_value=s), \
                mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            code = cli.main(argv + ["-t", "t"])
        return code, out.getvalue(), err.getvalue()

    def test_company_json(self):
        code, out, _ = self.run_cli(["ejemplo-soluciones"], [R(200, COMPANY)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["cif"], "B00000000")

    def test_company_csv(self):
        code, out, _ = self.run_cli(["ejemplo-soluciones", "-f", "csv"], [R(200, COMPANY)])
        row = next(csv.DictReader(io.StringIO(out)))
        self.assertEqual(row["cnae_code"], "6201")

    def test_borme_details(self):
        code, out, _ = self.run_cli(["--borme", "2026-11-13", "--province", "madrid", "--details", "--limit", "1"],
                                    [R(200, LISTING), R(200, EVENT)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["registry"], "Madrid")

    def test_search_csv(self):
        code, out, _ = self.run_cli(["--search", "ejemplo", "-f", "csv"], [R(200, SEARCH)])
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual(len(rows), 3)

    def test_nothing_to_do(self):
        code, _, err = self.run_cli([], [])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
