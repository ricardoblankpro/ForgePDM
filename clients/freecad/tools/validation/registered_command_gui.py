"""Read-only probe of retained native callbacks; close workflows before execution."""


def run(App, Gui, directory):
    import json
    from pathlib import Path

    import freecad.forgepdm as package
    from freecad.forgepdm import cad, commands, tasks, workspace
    from freecad.forgepdm.session import Session

    if Session.busy:
        raise RuntimeError("Wait for the current operation before probing command callbacks")
    previous_client, previous_user = Session.client, Session.user

    def state():
        return (
            App.ActiveDocument.Name if App.ActiveDocument else None,
            {
                doc.Name: (
                    doc.FileName,
                    workspace.digest(doc.FileName) if doc.FileName else None,
                    bool(cad.document_modified(doc)),
                )
                for doc in App.listDocuments().values()
            },
            [
                (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
                for s in Gui.Selection.getSelectionEx()
            ],
        )

    before, report = state(), {"addon": package.__version__, "mode": "read_only", "checks": []}
    original_run = tasks.run
    try:
        for identifier, class_name in (
            ("ForgePDM_Upload", "UploadCommand"),
            ("ForgePDM_CheckIn", "CheckInCommand"),
        ):
            received = []

            def inspect_only(workflow):
                try:
                    received.append(
                        workflow.gi_code is getattr(commands, class_name).action.__code__
                    )
                finally:
                    workflow.close()

            tasks.run = inspect_only
            Gui.runCommand(identifier)
            assert received == [True], "retained callback did not resolve current implementation"
            report["checks"].append(identifier + " resolves current action before execution")
    finally:
        tasks.run = original_run
    assert state() == before
    assert Session.client is previous_client and Session.user is previous_user and not Session.busy
    report["checks"].extend(
        [
            "no workflow body executed",
            "documents/files/dirty state/selection preserved",
            "session identity preserved",
        ]
    )
    report["documents_preserved"] = len(before[1])
    report["status"] = "passed"
    Path(directory).mkdir(parents=True, exist_ok=True)
    (Path(directory) / "registered-command-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report
