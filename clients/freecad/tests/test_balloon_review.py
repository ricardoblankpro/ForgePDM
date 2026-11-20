"""Page-space marker placement has no document or UI side effects."""

from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import balloon_review as review


@pytest.mark.parametrize("projected", [False, True])
def test_bubble_position_uses_scaled_offset_and_owning_projection_group(projected):
    group = NS(TypeId="TechDraw::DrawProjGroup", X=100, Y=50, Views=[])
    unrelated = NS(TypeId="App::DocumentObjectGroup")
    source = NS(
        TypeId="TechDraw::DrawProjGroupItem" if projected else "TechDraw::DrawViewPart",
        X=10,
        Y=20,
        Rotation=37,
        getScale=lambda: 0.75,
        InList=[unrelated, group],
    )
    group.Views = [source]
    balloon = NS(SourceView=source, X=8, Y=-12)
    assert review.page_position(balloon) == ((116, 61) if projected else (16, 11))
    assert balloon.X == 8 and balloon.Y == -12


@pytest.mark.parametrize("fault", ["missing", "group", "scale", "infinite"])
def test_unlocatable_balloon_does_not_get_a_guessed_marker(fault):
    source = NS(TypeId="TechDraw::DrawViewPart", X=10, Y=20, getScale=lambda: 1)
    balloon = NS(SourceView=source, X=8, Y=12)
    if fault == "missing":
        balloon.SourceView = None
    elif fault == "group":
        source.TypeId, source.InList = "TechDraw::DrawProjGroupItem", []
    elif fault == "scale":
        source.getScale = lambda: 0
    else:
        balloon.X = float("inf")
    with pytest.raises(ValueError):
        review.page_position(balloon)


def test_caption_distinguishes_object_label_and_frozen_position():
    balloon = NS(Label="Balloon008", PDMBOMPosition="4", Text="4")
    assert review.caption(balloon) == "Balloon008 · BOM 4"
