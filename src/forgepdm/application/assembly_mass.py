"""Read-only mass projection of the shared exact engineering BOM traversal."""

from forgepdm.application.bom_reports import bom_report


class AssemblyMassService:
    def __init__(self, database, authorization):
        self.database = database
        self.authorization = authorization

    def read(self, user, revision_id):
        return bom_report(self.database, self.authorization, user, revision_id)["mass"]
