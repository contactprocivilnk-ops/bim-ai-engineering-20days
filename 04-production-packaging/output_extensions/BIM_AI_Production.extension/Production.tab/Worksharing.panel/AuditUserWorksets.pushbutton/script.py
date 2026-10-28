# -*- coding: utf-8 -*-
"""Audit User Worksets in the active workshared Revit model.

Inspects all user-created worksets, reports element counts, visibility,
open status, and highlights potential model health warnings.
"""

from pyrevit import revit, DB, script, forms
from Autodesk.Revit.DB import (
    FilteredWorksetCollector,
    WorksetKind,
    Workset,
    FilteredElementCollector,
    ElementWorksetFilter
)

def audit_user_worksets():
    doc = revit.doc
    if not doc:
        forms.alert("No active document detected.", exitscript=True)
        return

    if not doc.IsWorkshared:
        forms.alert(
            "The active document is not workshared.\n"
            "Workset auditing requires a workshared project.",
            title="Workset Audit",
            exitscript=True
        )
        return

    output = script.get_output()
    output.set_title("Audit User Worksets")

    collector = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
    user_worksets = collector.ToWorksets()

    if not user_worksets:
        output.print_md("### No user worksets found in this project.")
        return

    table_data = []
    empty_worksets = []
    default_named_worksets = []

    for ws in sorted(user_worksets, key=lambda w: w.Name.lower()):
        ws_id = ws.Id
        ws_name = ws.Name
        is_open = ws.IsOpen
        is_visible = ws.IsVisibleByDefault
        owner = ws.Owner if ws.Owner else "None"

        try:
            ws_filter = ElementWorksetFilter(ws_id, False)
            element_count = FilteredElementCollector(doc).WherePasses(ws_filter).GetElementCount()
        except Exception:
            element_count = 0

        flags = []
        if element_count == 0:
            flags.append("Empty")
            empty_worksets.append(ws_name)
        if ws_name.strip().lower() in ["workset1", "workset 1"]:
            flags.append("Default Name")
            default_named_worksets.append(ws_name)
        if not is_visible:
            flags.append("Hidden By Default")

        status_str = ", ".join(flags) if flags else "OK"

        table_data.append([
            ws_name,
            str(ws_id.IntegerValue),
            str(element_count),
            "Yes" if is_open else "No",
            "Yes" if is_visible else "No",
            owner,
            status_str
        ])

    output.print_md("# Workset Audit Summary")
    output.print_md(
        "**Total User Worksets:** {0} | **Empty Worksets:** {1}".format(
            len(user_worksets), len(empty_worksets)
        )
    )

    if empty_worksets:
        output.print_md(
            "**Warning:** The following worksets contain 0 elements: "
            + ", ".join("`{}`".format(name) for name in empty_worksets)
        )

    if default_named_worksets:
        output.print_md(
            "**Notice:** Default naming detected: "
            + ", ".join("`{}`".format(name) for name in default_named_worksets)
        )

    output.print_table(
        table_data=table_data,
        title="User Worksets Overview",
        columns=[
            "Workset Name",
            "Workset ID",
            "Element Count",
            "Is Open",
            "Visible By Default",
            "Current Owner",
            "Audit Notes"
        ]
    )

if __name__ == "__main__":
    audit_user_worksets()