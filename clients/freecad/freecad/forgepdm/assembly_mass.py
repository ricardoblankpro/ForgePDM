"""Presentation of backend assembly mass without accessing local geometry."""


def summary(mass):
    if mass["mass_kg"] is None:
        title = "Total unavailable. Known subtotal: {} kg".format(mass["known_mass_kg"])
    else:
        title = "Assembly mass: {} kg".format(mass["mass_kg"])
    lines = [title, "Stored engineering BOM and published masses; local CAD edits excluded."]
    if mass.get("contains_cad_estimates"):
        lines.append("Includes estimated fastener mass from CAD.")
    for issue in mass["issues"]:
        lines.append(
            "{}-{} × {}: {}".format(
                issue["item_number"], issue["revision_label"], issue["quantity"], issue["reason"]
            )
        )
    return "\n".join(lines)
