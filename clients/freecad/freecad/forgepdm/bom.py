"""Read-only BOM proposals from explicitly selected pinned CAD occurrences."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class ProposedLine:
    component_revision_id: str
    position: int
    occurrences: tuple[tuple[str, str], ...]
    component_label: str = ""

    @property
    def quantity(self):
        return len(self.occurrences)

    def as_payload(self):
        return {
            "component_revision_id": self.component_revision_id,
            "quantity": self.quantity,
            "position": self.position,
        }


def quantity_changes(current, proposed):
    """Compare total quantities per exact revision, including manual split lines."""

    def totals(lines):
        result = {}
        for line in lines:
            key = line["component_revision_id"]
            result[key] = result.get(key, Decimal(0)) + Decimal(str(line["quantity"]))
        return result

    before = totals(current)
    after = totals([line.as_payload() for line in proposed])
    return tuple(
        (key, before.get(key, Decimal(0)), after.get(key, Decimal(0)))
        for key in sorted(before.keys() | after.keys())
        if before.get(key, Decimal(0)) != after.get(key, Decimal(0))
    )


def propose_lines(manifest, selected_occurrences):
    """Count selected direct links, retaining occurrence provenance for review.

    Selection is explicit: a CAD dependency is not automatically an engineering
    component. Nested manifests are not traversed. No server writes occur here.
    """
    if manifest.get("profile") != "freecad-app-link-v1":
        raise ValueError("Unsupported CAD reference profile")
    references, labels = {}, {}
    for reference in manifest["references"]:
        key = (reference["object_name"], reference["property_name"])
        if (
            any(not isinstance(value, str) or not value for value in key)
            or reference["property_name"] not in ("LinkedObject", "PDMStandardAssociation")
        ):
            raise ValueError("Unsupported CAD occurrence")
        if key in references:
            raise ValueError("Duplicate CAD occurrence")
        references[key] = str(UUID(reference["target_revision_id"]))
        labels.setdefault(references[key], reference.get("component_label", references[key]))

    selected = [tuple(key) for key in selected_occurrences]
    if any(len(key) != 2 for key in selected):
        raise ValueError("Invalid occurrence selection")
    if len(selected) != len(set(selected)):
        raise ValueError("Duplicate occurrence selection")
    if any(key not in references for key in selected):
        raise ValueError("Selected occurrence is absent from the pinned manifest")

    grouped = {}
    for key in sorted(selected):
        grouped.setdefault(references[key], []).append(key)
    return tuple(
        ProposedLine(revision_id, position, tuple(keys), labels[revision_id])
        for position, (revision_id, keys) in enumerate(grouped.items(), 1)
    )
