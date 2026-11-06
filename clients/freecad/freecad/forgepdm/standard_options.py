"""Controlled registration vocabulary and deterministic purchasing labels.

Sources and applicability limits: docs/fastener-selection-options-research.md.
Stored values retain the version-1 specification contract; labels are presentation.
"""

import re

from .standard_contract import specification

VERSION = 1
TYPES = {
    "SCREW": (
        "HEX HEAD",
        "HEX FLANGE HEAD",
        "SOCKET HEAD",
        "BUTTON HEAD",
        "COUNTERSUNK HEAD",
        "PAN HEAD",
        "CHEESE HEAD",
        "RAISED COUNTERSUNK HEAD",
        "SET",
        "SHOULDER",
        "OTHER",
    ),
    "NUT": (
        "HEX",
        "HEX HIGH",
        "HEX THIN",
        "HEX FLANGE",
        "HEX LOCK",
        "CAP",
        "SQUARE",
        "WING",
        "T-SLOT",
        "INSERT",
        "OTHER",
    ),
    "WASHER": ("FLAT", "SPRING", "TOOTHED", "CONTACT", "BELLEVILLE", "OTHER"),
    "STUD": ("DOUBLE END", "FULL THREAD", "OTHER"),
    "THREADED ROD": ("FULL THREAD", "OTHER"),
    "PIN": ("DOWEL", "TAPER", "SPRING", "SPLIT", "OTHER"),
    "RIVET": ("SOLID", "BLIND", "TUBULAR", "OTHER"),
    "INSERT": ("THREADED", "PRESS FIT", "OTHER"),
    "OTHER FASTENER": ("OTHER",),
}
NORMS = {}
for codes, kind, family in [
    (
        "ISO4014 ISO4015 ISO4016 ISO4017 ISO4018 ISO8676 ISO8765 DIN931 DIN933 DIN961 DIN571 ASMEB18.2.1.6",
        "SCREW",
        "HEX HEAD",
    ),
    ("ISO4162 ISO15071 ISO15072 EN1662 EN1665 ASMEB18.2.1.8", "SCREW", "HEX FLANGE HEAD"),
    ("ISO4762 ISO14579 DIN6912 DIN7984 ASMEB18.3.1A ASMEB18.3.1G", "SCREW", "SOCKET HEAD"),
    ("ISO7380-1 ISO7380-2 ISO7380 ASMEB18.3.3A ASMEB18.3.3B", "SCREW", "BUTTON HEAD"),
    ("ISO10642 ISO14581 ISO14582 ISO2009 ISO7046 DIN7991 ASMEB18.3.2", "SCREW", "COUNTERSUNK HEAD"),
    ("ISO1580 ISO7045 ISO14583 DIN7985", "SCREW", "PAN HEAD"),
    ("ISO1207 ISO14580 DIN84", "SCREW", "CHEESE HEAD"),
    ("ISO2010 ISO7047 ISO14584", "SCREW", "RAISED COUNTERSUNK HEAD"),
    ("ISO4026 ISO4027 ISO4028 ISO4029 ISO4766 DIN913 DIN914 DIN915 DIN916", "SCREW", "SET"),
    ("ISO7379 ASMEB18.3.4", "SCREW", "SHOULDER"),
    ("ISO4032 ISO8673 DIN934", "NUT", "HEX"),
    ("ISO4033 ISO8674", "NUT", "HEX HIGH"),
    ("ISO4035 ISO4036 ISO8675 DIN439", "NUT", "HEX THIN"),
    ("ISO4161 DIN6923", "NUT", "HEX FLANGE"),
    ("ISO7040 ISO7042 ISO10511 DIN985 DIN982 DIN980", "NUT", "HEX LOCK"),
    ("DIN1587", "NUT", "CAP"),
    ("DIN557 DIN562", "NUT", "SQUARE"),
    ("DIN315", "NUT", "WING"),
    (
        "ISO7089 ISO7090 ISO7091 ISO7092 ISO7093-1 ISO7093-2 ISO7094 DIN125 DIN126 DIN433 DIN9021 DIN7349",
        "WASHER",
        "FLAT",
    ),
    ("DIN127 DIN128 DIN137", "WASHER", "SPRING"),
    ("DIN6797 DIN6798", "WASHER", "TOOTHED"),
    ("DIN6796", "WASHER", "BELLEVILLE"),
    ("DIN975 DIN976 DIN976-1", "THREADED ROD", "FULL THREAD"),
]:
    for code in codes.split():
        NORMS[code] = (kind, family)


def option(identifier, label, value, group, extended=False):
    return dict(id=identifier, label=label, value=value, group=group, extended=extended)


MATERIALS = [option("unknown", "UNKNOWN", None, "unknown")]
for identifier, label, value, group, extended in [
    ("steel", "STEEL (ALLOY UNSPECIFIED)", "steel", "steel", False),
    ("carbon", "CARBON STEEL", "carbon steel", "steel", False),
    ("alloy", "ALLOY STEEL", "alloy steel", "steel", False),
    ("spring", "SPRING STEEL", "spring steel", "steel", True),
    ("ss", "STAINLESS STEEL (GROUP UNSPECIFIED)", "stainless steel", "stainless", False),
    ("a2", "STAINLESS STEEL A2", "stainless steel a2", "a2", False),
    ("a4", "STAINLESS STEEL A4", "stainless steel a4", "a4", False),
]:
    MATERIALS.append(option(identifier, label, value, group, extended))
for code in ("A1", "A3", "A5", "A8", "F1", "C1", "C3", "C4", "D2", "D4", "D6", "D8"):
    MATERIALS.append(
        option(
            "ss-" + code.lower(),
            "STAINLESS STEEL " + code,
            "stainless steel " + code.lower(),
            "stainless-extended",
            True,
        )
    )
for code in ("18-8", "304", "305", "316", "316L", "410"):
    MATERIALS.append(
        option(
            "aisi-" + code.lower(),
            "STAINLESS STEEL " + code,
            "stainless steel " + code.lower(),
            "stainless-extended",
            True,
        )
    )
for identifier, label, group in [
    ("copper", "COPPER", "nonferrous"),
    ("brass", "BRASS", "nonferrous"),
    ("phosphor-bronze", "PHOSPHOR BRONZE", "nonferrous"),
    ("silicon-bronze", "SILICON BRONZE", "nonferrous"),
    ("aluminium-bronze", "ALUMINIUM BRONZE", "nonferrous"),
    ("nickel-silver", "NICKEL SILVER", "nonferrous"),
    ("copper-nickel-silicon", "COPPER NICKEL SILICON", "nonferrous"),
    ("aluminium", "ALUMINIUM (ALLOY UNSPECIFIED)", "nonferrous"),
    ("ti2", "TITANIUM GRADE 2", "nonferrous"),
    ("ti5", "TITANIUM GRADE 5 TI-6AL-4V", "nonferrous"),
    ("monel400", "MONEL 400", "special"),
    ("monelk500", "MONEL K500", "special"),
    ("inconel600", "INCONEL 600", "special"),
    ("inconel625", "INCONEL 625", "special"),
    ("inconel718", "INCONEL 718", "special"),
    ("hastelloyc276", "HASTELLOY C-276", "special"),
    ("hastelloyc22", "HASTELLOY C-22", "special"),
    ("nimonic80a", "NIMONIC 80A", "special"),
]:
    MATERIALS.append(
        option(
            identifier,
            label,
            label.lower(),
            group,
            group == "special" or identifier not in ("copper", "brass", "aluminium", "ti2", "ti5"),
        )
    )
for alloy, temper in [
    ("5019", None),
    ("6082", "T6"),
    ("6056", "T6"),
    ("6060", "T8"),
    ("6013", "T8"),
    ("2017", "T6"),
    ("7050", "T73"),
    ("7075", "T6"),
    ("7075", "T73"),
]:
    label = "ALUMINIUM " + alloy + ("-" + temper if temper else "")
    MATERIALS.append(
        option(
            "al-" + alloy + ("-" + temper.lower() if temper else ""),
            label,
            label.lower(),
            "nonferrous",
            True,
        )
    )
for code in ("PA6", "PA66", "POM", "PP", "PE-HD", "PE-LD", "PEEK", "PTFE", "PFA", "PVDF"):
    MATERIALS.append(
        option(
            "polymer-" + code.lower(),
            code,
            code.lower(),
            "polymer",
            code not in ("PA6", "PA66", "PEEK"),
        )
    )

FINISHES = [option("unknown", "UNKNOWN", None, "all")]
for identifier, label, value, group, extended in [
    ("plain", "PLAIN", "plain", "all", False),
    ("plain-oil", "PLAIN OILED", "plain oiled", "metal", False),
    ("black-oxide", "BLACK OXIDE", "black oxide", "steel", False),
    ("black-oxide-oil", "BLACK OXIDE OILED", "black oxide oiled", "steel", False),
    ("zinc-phosphate", "ZINC PHOSPHATE", "zinc phosphate", "steel", True),
    ("manganese-phosphate", "MANGANESE PHOSPHATE", "manganese phosphate", "steel", True),
    ("phosphate-oil", "PHOSPHATE OILED", "phosphate oiled", "steel", True),
    ("zinc", "ZINC PLATED", "zinc plated", "steel", False),
    ("zinc-clear", "ZINC PLATED CLEAR PASSIVATED", "zinc plated clear passivated", "steel", False),
    (
        "zinc-yellow",
        "ZINC PLATED YELLOW PASSIVATED",
        "zinc plated yellow passivated",
        "steel",
        False,
    ),
    ("zinc-black", "ZINC PLATED BLACK PASSIVATED", "zinc plated black passivated", "steel", False),
    ("zinc-nickel", "ZINC NICKEL PLATED", "zinc nickel plated", "steel", False),
    ("zinc-iron", "ZINC IRON PLATED", "zinc iron plated", "steel", True),
    ("hot-dip", "HOT DIP GALVANIZED", "hot dip galvanized", "steel", False),
    ("mechanical-zinc", "MECHANICALLY ZINC PLATED", "mechanically zinc plated", "steel", True),
    ("zinc-flake", "ZINC FLAKE COATED", "zinc flake coated", "steel", False),
    ("passivated", "PASSIVATED", "passivated", "stainless", False),
    ("electropolished", "ELECTROPOLISHED", "electropolished", "stainless", True),
    ("black-stainless", "BLACKENED STAINLESS", "blackened stainless", "stainless", True),
    ("anodized", "ANODIZED", "anodized", "anodizable", False),
    ("nickel", "NICKEL PLATED", "nickel plated", "metal", True),
    ("chrome", "NICKEL CHROMIUM PLATED", "nickel chromium plated", "metal", True),
    ("copper", "COPPER PLATED", "copper plated", "metal", True),
    ("brass", "BRASS PLATED", "brass plated", "metal", True),
    ("bronze", "COPPER TIN PLATED", "copper tin plated", "metal", True),
    ("silver", "SILVER PLATED", "silver plated", "metal", True),
    ("gold", "GOLD PLATED", "gold plated", "metal", True),
    ("tin", "TIN PLATED", "tin plated", "metal", True),
    ("tin-zinc", "TIN ZINC PLATED", "tin zinc plated", "metal", True),
    ("copper-nickel", "COPPER NICKEL PLATED", "copper nickel plated", "metal", True),
    (
        "copper-nickel-chrome",
        "COPPER NICKEL CHROMIUM PLATED",
        "copper nickel chromium plated",
        "metal",
        True,
    ),
    ("copper-silver", "COPPER SILVER PLATED", "copper silver plated", "metal", True),
    ("ptfe", "PTFE COATED", "ptfe coated", "metal", True),
    ("organic", "ORGANIC TOPCOAT", "organic topcoat", "metal", True),
    ("dry-film", "DRY FILM LUBRICATED", "dry film lubricated", "metal", True),
    ("wax", "WAXED", "waxed", "metal", True),
    ("cadmium", "CADMIUM PLATED (SPECIALIST / LEGACY)", "cadmium plated", "steel", True),
]:
    FINISHES.append(option(identifier, label, value, group, extended))


def find(options, identifier):
    entry = next((o for o in options if o["id"] == identifier), None)
    if entry is None:
        raise ValueError("Choose an available specification option")
    return entry


def classification(geometry):
    norm = str(geometry.get("Type", "")).upper().replace(" ", "")
    return NORMS.get(norm)


def grades(material_id, kind, family, geometry, extended=False):
    material = find(MATERIALS, material_id)
    result = [option("unknown", "UNKNOWN", None, "unknown")]

    def add(system, codes, extra=False):
        if extra and not extended:
            return
        for code in codes:
            value = code.lower() if system.startswith("ISO") else (system + " " + code).lower()
            result.append(option(system + ":" + code, system + " — " + code, value, system, extra))

    metric = not str(geometry.get("Type", "")).upper().startswith(("ASME", "ANSI"))
    group = material["group"]
    if group == "steel":
        if kind in ("SCREW", "STUD", "THREADED ROD") and family != "SET":
            if metric:
                codes = ["4.6", "4.8", "5.6", "5.8", "6.8", "8.8", "9.8", "10.9", "12.9"]
                match = re.match(
                    r"m([0-9]+(?:\.[0-9]+)?)", str(geometry.get("Diameter", "")).lower()
                )
                if match and float(match[1]) > 16:
                    codes.remove("9.8")
                add("ISO 898-1", codes)
                add("ISO 898-1", ["0" + c for c in codes], True)
            add("SAE J429", ["GRADE 1", "GRADE 2", "GRADE 5", "GRADE 8"], metric)
            add(
                "ASTM",
                [
                    "A307 A",
                    "A307 B",
                    "A193 B7",
                    "A320 L7",
                    "A320 L43",
                    "A354 BC",
                    "A354 BD",
                    "A449",
                    "F1554 36",
                    "F1554 55",
                    "F1554 105",
                    "F3125 A325 TYPE 1",
                    "F3125 A325 TYPE 3",
                    "F3125 A490 TYPE 1",
                    "F3125 A490 TYPE 3",
                ],
                True,
            )
        elif kind == "NUT":
            if metric:
                if str(geometry.get("Type", "")).upper() == "ISO4036":
                    add("DIN 267-24", ["14H"])
                else:
                    add(
                        "ISO 898-2",
                        ["04", "05"] if family == "HEX THIN" else ["5", "6", "8", "10", "12"],
                    )
                add("LEGACY NUT CLASS", ["4", "9"], True)
            add("ASTM", ["A194 2H", "A194 7", "A563 A", "A563 DH"], True)
        elif kind == "WASHER" and family == "FLAT":
            add("ISO 898-3", ["100HV", "200HV", "300HV"])
            add("ISO 898-3", ["380HV"], True)
            add("OTHER HARDNESS", ["140HV"], True)
            add("ASTM", ["F436", "F844"], True)
        elif family == "SET":
            add("ISO 898-5", ["14H", "22H", "33H", "45H"])
    elif group in ("a2", "a4"):
        code = material["id"].upper()
        if kind in ("SCREW", "NUT", "STUD", "THREADED ROD") and family not in ("SET", "HEX THIN"):
            add("ISO 3506", [code + "-" + c for c in ("50", "70", "80")])
        elif kind == "WASHER" and family == "FLAT":
            add("OTHER HARDNESS", ["140HV", "200HV"], True)
    if (
        group in ("stainless", "stainless-extended")
        and extended
        and kind in ("SCREW", "STUD", "THREADED ROD")
        and family != "SET"
    ):
        add(
            "ASTM",
            ["A193 B8 CLASS 1", "A193 B8 CLASS 2", "A193 B8M CLASS 1", "A193 B8M CLASS 2"],
            True,
        )
    # Unverified extended stainless pairs are deliberately not cross-joined.
    if group in ("nonferrous", "polymer", "special"):
        result.append(option("not-applicable", "NOT APPLICABLE", "not applicable", "none"))
    return result


def finishes(material_id, extended=False):
    material = find(MATERIALS, material_id)
    allowed = {"all"}
    group = material["group"]
    if group == "steel":
        allowed.update(("metal", "steel"))
    elif group in ("stainless", "a2", "a4", "stainless-extended"):
        allowed.update(("metal", "stainless"))
    elif group in ("nonferrous", "special"):
        allowed.add("metal")
        if material_id.startswith(("aluminium", "al-", "ti")):
            allowed.add("anodizable")
    return [o for o in FINISHES if o["group"] in allowed and (extended or not o["extended"])]


def dimension(geometry, kind):
    diameter = geometry.get("Diameter")
    if diameter == "custom":
        diameter = geometry.get("DiameterCustom")
    parts = []
    if diameter:
        diameter = str(diameter).upper().replace(" ", "")
        if re.fullmatch(r"[0-9.]+", diameter) and kind in ("SCREW", "NUT", "STUD", "THREADED ROD"):
            diameter = "M" + diameter
        parts.append(diameter)
    pitch = geometry.get("PitchCustom")
    if pitch and pitch != "0":
        parts.append(str(pitch))
    length = geometry.get("Length")
    if length == "custom":
        length = geometry.get("LengthCustom")
    if length:
        parts.append(str(length))
    text = "X".join(parts) if parts else "DIMENSION UNKNOWN"
    for key, label in [
        ("Width", "W"),
        ("ScrewLength", "SL"),
        ("SlotWidth", "SW"),
        ("ExternalDiam", "OD"),
        ("KeySize", "K"),
        ("Tcode", "T"),
    ]:
        if key in geometry:
            text += " " + label + str(geometry[key])
    if geometry.get("LeftHanded") == "true":
        text += " LH"
    if geometry.get("Blind") == "true":
        text += " BLIND"
    return text.upper()


def catalog_text(spec, kind, family):
    spec = specification(spec)
    if kind not in TYPES or family not in TYPES[kind]:
        raise ValueError("Choose a fastener type and family")
    g = spec["geometry"]
    name = " ".join(
        (
            kind,
            spec["material"] or "MATERIAL UNKNOWN",
            family,
            g["Type"],
            dimension(g, kind),
            spec["grade"] or "GRADE UNKNOWN",
            spec["finish"] or "FINISH UNKNOWN",
        )
    ).upper()
    name = " ".join(name.split())
    if len(name) > 200:
        raise ValueError("The generated name exceeds the 200-character catalog limit")
    description = name
    return name, description


def selected_spec(geometry, material_id, grade_id, finish_id, kind, family, extended=False):
    material = find(MATERIALS, material_id)
    if material["extended"] and not extended:
        raise ValueError("Enable extended materials before selecting this entry")
    grade = find(grades(material_id, kind, family, geometry, extended), grade_id)
    finish = find(finishes(material_id, extended), finish_id)
    return specification(
        dict(
            geometry=geometry,
            material=material["value"],
            grade=grade["value"],
            finish=finish["value"],
        )
    )
