"""Engineering quantity policy, explicit selection and historical revision pins."""

from copy import deepcopy
from uuid import uuid4

import pytest

from freecad.forgepdm.bom import propose_lines
from freecad.forgepdm.bom import quantity_changes


def manifest(*revisions):
    return {
        "profile": "freecad-app-link-v1",
        "references": [
            {
                "object_name": "Link{}".format(index),
                "property_name": "LinkedObject",
                "target_revision_id": revision,
            }
            for index, revision in enumerate(revisions)
        ],
    }


def select(*indices):
    return [("Link{}".format(index), "LinkedObject") for index in indices]


def test_repeated_occurrences_count_once_each_with_provenance_and_no_mutation():
    revision = str(uuid4())
    source = manifest(revision, revision, str(uuid4()))
    original = deepcopy(source)
    lines = propose_lines(source, select(1, 0))
    assert len(lines) == 1
    assert lines[0].as_payload() == {
        "component_revision_id": revision,
        "quantity": 2,
        "position": 1,
    }
    assert lines[0].occurrences == tuple(select(0, 1))
    assert source == original


def test_exact_revisions_are_separate_and_order_is_independent_of_input_order():
    first, second = str(uuid4()), str(uuid4())
    source = manifest(first, second, first)
    lines = propose_lines(source, select(2, 1, 0))
    source["references"].reverse()
    assert lines == propose_lines(source, select(0, 2, 1))
    assert [(line.component_revision_id, line.quantity, line.position) for line in lines] == [
        (first, 2, 1),
        (second, 1, 2),
    ]


def test_empty_selection_does_not_infer_components_from_dependencies():
    assert propose_lines(manifest(str(uuid4())), []) == ()


def test_quantity_diff_includes_manual_removal_and_split_line_totals():
    from decimal import Decimal

    revision, removed = str(uuid4()), str(uuid4())
    current = [
        {"component_revision_id": revision, "quantity": "1.25", "position": 1},
        {"component_revision_id": revision, "quantity": "0.25", "position": 2},
        {"component_revision_id": removed, "quantity": "3", "position": 3},
    ]
    proposed = propose_lines(manifest(revision, revision), select(0, 1))
    assert set(quantity_changes(current, proposed)) == {
        (revision, Decimal("1.5"), Decimal(2)),
        (removed, Decimal(3), Decimal(0)),
    }


@pytest.mark.parametrize("selection", [select(0, 0), select(9), [("Link0",)]])
def test_invalid_selection_is_rejected(selection):
    with pytest.raises(ValueError):
        propose_lines(manifest(str(uuid4())), selection)


@pytest.mark.parametrize("fault", ["profile", "duplicate", "revision", "property"])
def test_invalid_manifest_is_rejected(fault):
    source = manifest(str(uuid4()))
    if fault == "profile":
        source["profile"] = "unknown"
    elif fault == "duplicate":
        source["references"] *= 2
    elif fault == "revision":
        source["references"][0]["target_revision_id"] = "latest"
    else:
        source["references"][0]["property_name"] = "Unsupported"
    with pytest.raises(ValueError):
        propose_lines(source, select(0))
