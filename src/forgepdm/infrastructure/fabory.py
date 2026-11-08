"""Bounded public product-page reads; no search crawling or speculative mass."""

import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from forgepdm.domain.reference_mass import mass_kg

AGENT = "ForgePDM-reference-mass/1.0"
ROOT = "https://www.fabory.com"
# Verified supplier families. A generated article is only a candidate: every
# specification, article identity and mass is checked against the returned page.
FAMILIES = (
    (
        {"iso4017", "din933"},
        "steel",
        "8.8",
        "zinc plated",
        "01210",
        "hexagon-head-screw-iso-4017-steel-zinc-plated-8-8",
    ),
    (
        {"iso4017", "din933"},
        "steel",
        "8.8",
        "zinc plated yellow passivated",
        "01230",
        "hexagon-head-screw-iso-4017-steel-zinc-plated-yellow-passivated-8-8",
    ),
    ({"iso4032"}, "steel", "8", "zinc plated", "01301", "hexagon-nut-iso-4032-steel-zinc-plated-8"),
    ({"iso4032"}, "steel", "8", "plain", "01104", "hexagon-nut-iso-4032-steel-plain-8"),
    (
        {"iso4762", "din912"},
        "steel",
        "10.9",
        "plain",
        "07015",
        "hexagon-socket-head-cap-screw-din-912-steel-plain-10-9",
    ),
    (
        {"iso4762", "din912"},
        "stainless steel a2",
        "a2-70",
        "plain",
        "51050",
        "hexagon-socket-head-cap-screw-din-912-stainless-steel-a2",
    ),
    (
        {"iso7089", "din125-1a", "din125a"},
        "steel",
        "200 hv",
        "zinc plated",
        "38093",
        "plain-washer-din-125-1a-steel-zinc-plated-200-hv",
    ),
)


class Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = {}, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            if len(self.row) == 2 and all(self.row):
                self.rows.setdefault(self.row[0].casefold(), set()).add(self.row[1].casefold())
            self.row = None


def dimensions(spec):
    geom = spec["geometry"]
    if set(geom) - {"Type", "Diameter", "Length", "LengthCustom", "LeftHanded"}:
        return None
    if geom.get("LeftHanded", "false") != "false":
        return None
    diameter = re.fullmatch(r"m([1-9]\d?)", geom.get("Diameter", ""))
    if not diameter:
        return None
    length = geom.get("Length")
    if length == "custom":
        return None
    if length is not None and not re.fullmatch(r"[1-9]\d{0,2}", length):
        return None
    return diameter[1], length


def candidate_url(spec):
    dims = dimensions(spec)
    if not dims:
        return None
    diameter, length = dims
    for types, material, grade, finish, prefix, slug in FAMILIES:
        if (
            spec["geometry"]["Type"] in types
            and spec["material"] == material
            and (spec["grade"] or "").replace(" ", "") == grade.replace(" ", "")
            and spec["finish"] == finish
        ):
            washer = prefix in ("38093", "01301", "01104")
            if washer == (length is not None):
                return None
            code = (
                prefix + f"{int(diameter) * 10:03d}" + ("001" if washer else f"{int(length):03d}")
            )
            return (
                ROOT
                + "/en_NL/"
                + slug
                + "-m"
                + diameter
                + ("x" + length if length else "")
                + "/p/"
                + code
            )
    return None


def allowed_url(url):
    p = urlsplit(url)
    return bool(
        p.scheme == "https"
        and p.netloc == "www.fabory.com"
        and not p.query
        and not p.fragment
        and "-sku/" not in p.path
        and re.fullmatch(r"/(en|en_NL)/[a-z0-9%()+.,_-]+/p/\d{11}", p.path)
    )


def parse_product(body, url, spec):
    """Fail closed for incomplete, conflicting, kit or nonmatching specifications."""
    if not allowed_url(url) or not dimensions(spec):
        return None
    parser = Rows()
    parser.feed(body.decode("utf-8"))
    rows = parser.rows

    def only(key):
        values = rows.get(key, set())
        return next(iter(values)) if len(values) == 1 else None

    diameter, length = dimensions(spec)
    requested = re.fullmatch(r"(iso|din)(.+)", spec["geometry"]["Type"])
    if not requested or only(requested[1]) != {"125a": "125-1a"}.get(requested[2], requested[2]):
        return None
    if only("diameter") != "m" + diameter:
        return None
    if length and (only("length") != length + " mm" or only("thread direction") != "right"):
        return None
    if length and only("thread") != "metric thread":
        return None
    material = only("material")
    grade = only("class")
    technical = only("material technical")
    if technical:
        material = (material or "") + " " + technical
        if grade and technical in ("a2", "a4"):
            grade = technical + "-" + grade
    # Missing finish is not proof of plain finish. Only the verified uncoated
    # A2 family is explicitly allowed to omit this attribute.
    finish = only("surface treatment")
    if finish is None and url.split("/p/")[-1].startswith("51050"):
        finish = "plain"
    if (material, (grade or "").replace(" ", ""), finish) != (
        spec["material"],
        (spec["grade"] or "").replace(" ", ""),
        spec["finish"],
    ):
        return None
    if (
        requested[1] == "iso"
        and requested[2] == "4032"
        and (only("thread direction") != "right" or only("thread") != "metric thread")
    ):
        return None
    article = only("article number")
    if not article or article.replace(".", "") != url.split("/p/")[-1]:
        return None
    grams = only("weight per piece (g)")
    if not grams or not re.fullmatch(r"\d+(?:\.\d+)?", grams):
        return None
    return {
        "supplier": "Fabory",
        "source_url": url,
        "source_article": article,
        "source_mass": grams,
        "source_unit": "g",
        "source_quantity": "1",
        "mass_kg": mass_kg(grams, "g", 1),
        "source_sha256": hashlib.sha256(body).hexdigest(),
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A changed canonical URL is a missing result, never an unrestricted fetch.
        return None


class FaboryProvider:
    def __init__(self, fetch=None):
        self.fetch = fetch or self._fetch

    @staticmethod
    def _fetch(url):
        with build_opener(NoRedirect()).open(
            Request(url, headers={"User-Agent": AGENT}), timeout=4
        ) as response:
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("Supplier response too large")
            return body

    def lookup(self, spec):
        url = candidate_url(spec)
        if url is None:
            return None
        policy = RobotFileParser()
        policy.parse(self.fetch(ROOT + "/robots.txt").decode("utf-8").splitlines())
        if not policy.can_fetch(AGENT, url):
            return None
        return parse_product(self.fetch(url), url, spec)
