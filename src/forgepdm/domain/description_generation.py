"""Optional deterministic description proposals; no external service or CAD import."""

import json
from pathlib import Path

from forgepdm.domain.standard_parts import specification

TERMS = {
    "SCREW": "PARAFUSO",
    "NUT": "PORCA",
    "WASHER": "ARRUELA",
    "STUD": "PRISIONEIRO",
    "THREADED ROD": "BARRA ROSCADA",
    "HEX HEAD": "CABEÇA SEXTAVADA",
    "SOCKET HEAD": "CABEÇA CILÍNDRICA SEXTAVADO INTERNO",
    "HEX": "SEXTAVADA",
    "FLAT": "LISA",
    "COUNTERSUNK HEAD": "CABEÇA ESCAREADA",
    "BUTTON HEAD": "CABEÇA ABAULADA",
    "STEEL": "AÇO",
    "STAINLESS STEEL": "AÇO INOXIDÁVEL",
    "ZINC PLATED": "ZINCADO",
    "PLAIN": "SEM REVESTIMENTO",
    "BLACK OXIDE": "OXIDADO PRETO",
}


def generate(value, locale):
    if locale not in ("en", "pt-BR"):
        raise ValueError("unsupported proposal language")
    spec = specification(value)
    dictionary = json.loads(Path(__file__).with_name("fastener_terms.json").read_text())
    geometry = spec["geometry"]
    norm = geometry["Type"].upper()
    pair = dictionary["norms"].get(norm)
    if pair is None:
        raise ValueError("unknown standard; enter a manual translation")
    kind, family = pair
    missing = []

    def term(value):
        if value is None:
            missing.append("unspecified property")
            return "UNKNOWN" if locale == "en" else "NÃO ESPECIFICADO"
        value = value.upper()
        if locale == "en":
            return value
        if value in TERMS:
            return TERMS[value]
        # Grades and identifiers remain canonical; unknown vocabulary is explicit.
        missing.append(value)
        return value

    diameter = (
        geometry.get("DiameterCustom")
        if geometry.get("Diameter") == "custom"
        else geometry.get("Diameter", "DIMENSION UNKNOWN")
    )
    diameter = str(diameter).upper()
    if diameter.replace(".", "", 1).isdigit() and kind in ("SCREW", "NUT", "STUD", "THREADED ROD"):
        diameter = "M" + diameter
    dimensions = [diameter]
    if geometry.get("PitchCustom") not in (None, "0"):
        dimensions.append(geometry["PitchCustom"])
    length = (
        geometry.get("LengthCustom")
        if geometry.get("Length") == "custom"
        else geometry.get("Length")
    )
    if length:
        dimensions.append(length)
    dimensions = "X".join(dimensions)
    for key, label in [
        ("Width", "W"),
        ("ScrewLength", "SL"),
        ("SlotWidth", "SW"),
        ("ExternalDiam", "OD"),
        ("KeySize", "K"),
        ("Tcode", "T"),
    ]:
        if key in geometry:
            dimensions += " " + label + geometry[key]
    if geometry.get("LeftHanded") == "true":
        dimensions += " LH"
    if geometry.get("Blind") == "true":
        dimensions += " BLIND"
    text = " ".join(
        (
            term(kind),
            term(spec["material"])
            if spec["material"]
            else ("MATERIAL UNKNOWN" if locale == "en" else term(None)),
            term(family),
            norm,
            dimensions,
            spec["grade"].upper()
            if spec["grade"]
            else ("GRADE UNKNOWN" if locale == "en" else term(None)),
            term(spec["finish"])
            if spec["finish"]
            else ("FINISH UNKNOWN" if locale == "en" else term(None)),
        )
    )
    return {
        "text": text,
        "language": locale,
        "state": "draft",
        "warnings": missing,
        "provenance": {
            "origin": "rules",
            "provider": "fastener-terms",
            "version": dictionary["version"],
            "warnings": missing,
        },
    }
