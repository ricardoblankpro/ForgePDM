"""Versioned OCCT text fingerprint, independent of FreeCAD and native shape mutation."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import hashlib
import re


PROFILE = "occt-brep-q12-v1"
_REAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_HEADERS = {
    "CASCADE Topology V1, (c) Matra-Datavision",
    "CASCADE Topology V2, (c) Matra-Datavision",
    "CASCADE Topology V3, (c) Open Cascade",
}
_QUANTUM = Decimal("1e-12")


def canonical_brep(text):
    """Retain topology, geometry and placements; omit only transient flags/roundoff.

    The real-number grid is 1e-12 in OCCT's serialized units. This is a
    conservative serialization fingerprint, not a general shape-equivalence test.
    Unknown formats and malformed shape/flag sections fail closed.
    """
    if not isinstance(text, str) or len(text) > 64 * 1024**2:
        raise ValueError("Unsupported geometry fingerprint size")
    text = text.strip()
    if not text or text.splitlines()[0] not in _HEADERS:
        raise ValueError("Unsupported OCCT geometry fingerprint format")
    headers = list(re.finditer(r"(?m)^TShapes\s+(\d+)\s*$", text))
    if len(headers) != 1:
        raise ValueError("Invalid OCCT shape section")
    header = headers[0]
    shapes = text[header.end() :]
    flags = list(re.finditer(r"(?m)^[01]{7}[ \t]*$", shapes))
    types = re.findall(r"(?m)^(?:Ve|Ed|Wi|Fa|Sh|So|CS|Co)[ \t]*$", shapes)
    count = int(header[1])
    if not count or len(flags) != count or len(types) != count:
        raise ValueError("Unsupported OCCT topology or shape flags")
    # Free, Modified and Checked describe kernel processing state. The remaining
    # four flags, shape orientations and every topology reference are retained.
    shapes = re.sub(r"(?m)^([01]{3})([01]{4})[ \t]*$", r"000\2", shapes)
    tokens = []
    with localcontext() as context:
        context.prec = 100
        for token in (text[: header.end()] + shapes).split():
            if token.lower() in ("nan", "inf", "+inf", "-inf"):
                raise ValueError("Non-finite geometry cannot be fingerprinted")
            if _REAL.fullmatch(token) and ("." in token or "e" in token.lower() or token == "-0"):
                try:
                    value = Decimal(token).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
                except InvalidOperation as error:
                    raise ValueError("Unsupported geometry numeric range") from error
                token = "0" if not value else format(value, "f").rstrip("0").rstrip(".")
            tokens.append(token)
    return " ".join(tokens)


def fingerprint(text):
    normalized = canonical_brep(text)
    return hashlib.sha256((PROFILE + "\n" + normalized).encode("utf-8")).hexdigest()
