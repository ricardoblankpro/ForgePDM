"""Exercise exact configuration/PDF loaders on owned copies, never original documents."""


def run(App, Gui, configuration, directory):
    import hashlib
    import json
    from pathlib import Path

    import Part
    from freecad.forgepdm import (
        balloon_auto,
        balloon_geometry as geometry,
        cad,
        commands,
        drawing_balloons as balloons,
        drawing_export,
    )
    from freecad.forgepdm.geometry_fingerprint import fingerprint
    from freecad.forgepdm.session import Session

    assert not Session.busy
    assert not App.listDocuments(), "Run this harness in a separate FreeCAD process"
    assert Path(App.getUserAppDataDir()).resolve().is_relative_to(Path("/tmp")), (
        "Use an isolated temporary FreeCAD profile"
    )
    assert Path(configuration["directory"]).resolve().is_relative_to(Path("/tmp")), (
        "Use a copied temporary configuration"
    )
    assert Session.client is None, "The isolated native process must not have a production login"
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    prior = set(App.listDocuments())
    active = App.ActiveDocument
    view = Gui.activeDocument().activeView() if active else None
    active_page = view.getPage().Name if hasattr(view, "getPage") else None
    client, user = Session.client, Session.user
    observer = balloon_auto._observer
    suspended = observer.suspended if observer else None
    if observer:
        observer.suspended = True
    original_bytes = {
        d.Name: hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest()
        for d in App.listDocuments().values()
    }
    checks, opened = [], None

    def check(label, condition):
        (destination / "progress.json").write_text(
            json.dumps({"checks": checks, "current": label, "passed": bool(condition)}, indent=2)
        )
        assert condition, label
        checks.append(label)

    def rejected(balloon, binding):
        try:
            balloons.validate_attachment(balloon, binding)
        except ValueError:
            return True
        return False

    def close_fixture():
        nonlocal opened
        if opened is not None:
            for doc in reversed(opened["owned"]):
                App.closeDocument(doc.Name)
            opened = None

    try:
        opened = cad.open_configuration(configuration, commands._set_metadata)
        root = opened["root"]
        plans, physical, manual = [], {}, {}
        for page in root.Objects:
            if page.TypeId != "TechDraw::DrawPage":
                continue
            for balloon in page.Views:
                if not getattr(balloon, "PDMBOMBinding", ""):
                    continue
                binding = json.loads(balloon.PDMBOMBinding)
                if binding["format"] == 1:
                    manual[balloon.Name] = balloon.PDMBOMBinding
                    continue
                plans.append((balloon, balloons.plan_legacy_upgrade(page, balloon)))
                for obj, _rid, shape in geometry.components(balloon.SourceView):
                    if obj.Name in physical:
                        continue
                    text = shape.exportBrepToString()
                    restored = Part.Shape()
                    restored.importBrepFromString(text)
                    check(
                        obj.Name + " geometric fingerprint survives native BREP roundtrip",
                        fingerprint(text) == fingerprint(restored.exportBrepToString()),
                    )
                    physical[obj.Name] = fingerprint(text)
        check("Legacy targets are verified without guessing different components", bool(plans))
        expected = {
            b.Name: (p["position"], p["attachment"]["component"], b.PDMBOMTable.Name)
            for b, p in plans
        }
        root.openTransaction("Fixture stable balloon evidence")
        for balloon, plan in plans:
            balloon.PDMBOMBinding = json.dumps(plan, sort_keys=True)
            table = balloon.PDMBOMTable
            data = json.loads(table.PDMTableData)
            data["format"] = 7
            table.PDMTableData = json.dumps(data, sort_keys=True)
        root.recompute()
        root.commitTransaction()
        cad.settle_techdraw(root)
        pages = [
            dict(page_name=p.Name, page_label=p.Label, filename=p.Name + ".pdf")
            for p in root.Objects
            if p.TypeId == "TechDraw::DrawPage"
        ]
        check(
            "Stable bindings pass native PDF preflight after recompute",
            not any(balloons.issues(root.getObject(p["page_name"])) for p in pages),
        )
        candidate, binding = plans[0]
        x = candidate.OriginX
        candidate.OriginX = float(x) + 1
        check("A real arrow movement still fails validation", rejected(candidate, binding))
        candidate.OriginX = x
        wrong = dict(binding, attachment=dict(binding["attachment"], component="MissingOccurrence"))
        check(
            "An unchanged fingerprint cannot bypass exact arrow-target validation",
            rejected(candidate, wrong),
        )
        component = root.getObject(binding["attachment"]["component"])
        placement = component.Placement
        moved = App.Placement(placement)
        moved.Base.x += 0.1
        component.Placement = moved
        check(
            "A real component placement change still fails validation", rejected(candidate, binding)
        )
        component.Placement = placement
        root.recompute()
        cad.settle_techdraw(root)
        root.save()
        Gui.getDocument(root.Name).Modified = False
        check(
            "Manual bindings, automatic targets and BOM Positions are preserved",
            all(root.getObject(n).PDMBOMBinding == text for n, text in manual.items())
            and all(
                (b.PDMBOMPosition, p["attachment"]["component"])
                == (str(p["position"]), expected[b.Name][1])
                for b, p in plans
            ),
        )
        close_fixture()
        opened = cad.open_configuration(configuration, commands._set_metadata)
        root = opened["root"]
        check(
            "Stable links survive exact reconstruction/relink/recompute/save loader",
            not any(balloons.issues(root.getObject(p["page_name"])) for p in pages),
        )
        check(
            "Every reopened binding keeps its component, position and table",
            all(
                (
                    json.loads(root.getObject(n).PDMBOMBinding)["position"],
                    json.loads(root.getObject(n).PDMBOMBinding)["attachment"]["component"],
                    root.getObject(n).PDMBOMTable.Name,
                )
                == target
                for n, target in expected.items()
            ),
        )
        close_fixture()
        drawing_export.export(configuration, pages, destination, commands._set_metadata)
        check(
            "The actual PDF export pipeline accepts the reconstructed stable links",
            all(
                (destination / f"page_{i:04d}.pdf").read_bytes().startswith(b"%PDF-")
                for i in range(1, len(pages) + 1)
            ),
        )
        result = {
            "checks": checks,
            "stable_bindings": len(plans),
            "manual_bindings": len(manual),
            "freecad": App.Version(),
            "occt": Part.OCC_VERSION,
            "server_mutations": False,
            "original_document_writes": False,
        }
        (destination / "report.json").write_text(json.dumps(result, indent=2))
        return result
    finally:
        close_fixture()
        for name in set(App.listDocuments()) - prior:
            doc = App.getDocument(name)
            if Path(doc.FileName).is_relative_to(Path(configuration["directory"])):
                App.closeDocument(name)
        if observer:
            observer.suspended = suspended
        if active is not None:
            App.setActiveDocument(active.Name)
            if active_page:
                active.getObject(active_page).ViewObject.show()
        assert set(App.listDocuments()) == prior
        assert Session.client is client and Session.user is user and not Session.busy
        assert all(
            hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() == original_bytes[d.Name]
            for d in App.listDocuments().values()
        )
