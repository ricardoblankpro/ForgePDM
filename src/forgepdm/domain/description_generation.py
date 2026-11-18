"""Optional deterministic description proposals; no external service or CAD import."""

import json
from pathlib import Path

from forgepdm.domain.standard_parts import specification

# Adding a resource does not enable a language in the review service/UI.
VOCABULARIES = {"pt-BR": "fastener_locales/pt-BR.json"}


def generate(value, locale):
    if locale not in ("en", "pt-BR"):
        raise ValueError("unsupported proposal language")
    spec = specification(value)
    root = Path(__file__).parent
    dictionary = json.loads((root / "fastener_terms.json").read_text(encoding="utf-8"))
    vocabulary = (
        json.loads((root / VOCABULARIES[locale]).read_text(encoding="utf-8"))
        if locale != "en"
        else None
    )
    geometry = spec["geometry"]
    norm = geometry["Type"].upper()
    pair = dictionary["norms"].get(norm)
    if pair is None:
        raise ValueError("unknown standard; enter a manual translation")
    kind, family = pair
    missing = []

    def term(value, section):
        if value is None:
            missing.append(f"{section}: unspecified property")
            return vocabulary["messages"]["UNSPECIFIED"]
        if locale == "en":
            return value.upper()
        translated = vocabulary[section].get(value.upper())
        if translated is not None:
            return translated
        missing.append(f"{section}: {value}")
        return value

    def property_term(key, section):
        # Use the original spelling for an unknown free-text purchasing term.
        if locale == "en":
            return term(spec[key], section)
        return term(None if spec[key] is None else str(value[key]).strip(), section)

    diameter = (
        geometry.get("DiameterCustom")
        if geometry.get("Diameter") == "custom"
        else geometry.get("Diameter", "DIMENSION UNKNOWN")
    )
    diameter = str(diameter).upper()
    if locale != "en" and (diameter == "DIMENSION UNKNOWN" or diameter == "NONE"):
        missing.append("Diameter: unspecified property")
        diameter = vocabulary["messages"]["DIMENSION UNKNOWN"]
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
    elif locale != "en" and geometry.get("Length") == "custom":
        missing.append("LengthCustom: unspecified property")
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
    for key, label in [("LeftHanded", "LH"), ("Blind", "BLIND")]:
        if geometry.get(key) == "true":
            dimensions += " " + term(label, "descriptors")
        elif locale != "en" and geometry.get(key) not in (None, "false"):
            missing.append(f"{key}: {value['geometry'][key]}")
            dimensions += f" {key}={value['geometry'][key]}"
    grade = spec["grade"]
    if grade:
        grade = grade.upper()
        if vocabulary:
            # Mechanical identifiers are never translated or treated as vocabulary gaps.
            grade = vocabulary["grades"].get(grade, grade)
    else:
        grade = "GRADE UNKNOWN" if locale == "en" else term(None, "grade")
    text = " ".join(
        (
            term(kind, "types"),
            property_term("material", "materials")
            if spec["material"]
            else ("MATERIAL UNKNOWN" if locale == "en" else term(None, "material")),
            term(family, "families"),
            norm,
            dimensions,
            grade,
            property_term("finish", "finishes")
            if spec["finish"]
            else ("FINISH UNKNOWN" if locale == "en" else term(None, "finish")),
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
            **(
                {"vocabulary_language": locale, "vocabulary_version": vocabulary["version"]}
                if vocabulary
                else {}
            ),
            "warnings": missing,
        },
    }
