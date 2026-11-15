"""Compatibility projection of the shared engineering BOM report for drawings."""

from forgepdm.application.bom_reports import bom_report, project_report
from forgepdm.domain.entities import Conflict


def drawing_bom(database, authorization, user, revision_id):
    value = project_report(bom_report(database, authorization, user, revision_id), "direct")
    if len(value["lines"]) > 500:
        raise Conflict("Drawing BOM exceeds the 500 direct-line limit")
    return value
