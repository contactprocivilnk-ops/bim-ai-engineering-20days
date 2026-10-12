# -*- coding: utf-8 -*- 
"""Audit 3D Views Without Worksets.

Identifies and reports all 3D views that do not have a valid or user-defined
workset assigned in a workshared project.
"""

import sys
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    View3D,
    BuiltInParameter,
    WorksetTable,
    WorksetId
)
from pyrevit import revit, forms, script

doc = revit.doc
output = script.get_output()

if not doc:
    forms.alert("No active document found.", title="Audit 3D Views", exit=True)

# Edge Case: Document is not workshared
if not doc.IsWorkshared:
    forms.alert(
        "The active document is not workshared.\n"
        "Workset auditing cannot be performed on non-workshared projects.",
        title="Audit 3D Views",
        exit=True
    )

views_collector = (
    FilteredElementCollector(doc)
    .OfClass(View3D)
    .WhereElementIsNotElementType()
)

views_without_workset = []
audited_views = []
skipped_templates = 0
skipped_transient = 0

workset_table = doc.GetWorksetTable()

for view in views_collector:
    try:
        # Edge Case: View is invalid or deleted
        if not view.IsValidObject:
            skipped_transient += 1
            continue

        # Edge Case: View is a view template
        if view.IsTemplate:
            skipped_templates += 1
            continue

        # Edge Case: Internal system view, transient view, or assembly view
        view_name = getattr(view, "Name", "")
        if not view_name or view.IsAssemblyView:
            skipped_transient += 1
            continue

        view_id_str = str(getattr(view.Id, "Value", getattr(view.Id, "IntegerValue", view.Id)))

        # Edge Case: ELEM_PARTITION_PARAM is null, uninitialized, or invalid
        ws_param = view.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
        if ws_param is None:
            views_without_workset.append({
                "view_id": view.Id,
                "name": view_name,
                "id_str": view_id_str,
                "reason": "ELEM_PARTITION_PARAM parameter is null"
            })
            continue

        if not ws_param.HasValue:
            views_without_workset.append({
                "view_id": view.Id,
                "name": view_name,
                "id_str": view_id_str,
                "reason": "Workset parameter is uninitialized (no value)"
            })
            continue

        ws_id_int = ws_param.AsInteger()
        if ws_id_int is None or ws_id_int < 0:
            views_without_workset.append({
                "view_id": view.Id,
                "name": view_name,
                "id_str": view_id_str,
                "reason": "Invalid workset integer ID ({})".format(ws_id_int)
            })
            continue

        workset_id = WorksetId(ws_id_int)
        if workset_id == WorksetId.InvalidWorksetId:
            views_without_workset.append({
                "view_id": view.Id,
                "name": view_name,
                "id_str": view_id_str,
                "reason": "Assigned to WorksetId.InvalidWorksetId"
            })
            continue

        # Validate workset presence in WorksetTable
        if not WorksetTable.IsValidWorksetId(doc, workset_id):
            views_without_workset.append({
                "view_id": view.Id,
                "name": view_name,
                "id_str": view_id_str,
                "reason": "WorksetId {} is not valid in current WorksetTable".format(ws_id_int)
            })
            continue

        workset = workset_table.GetWorkset(workset_id)
        if workset is None:
            views_without_workset.append({
                "view_id": view.Id,
                "name": view_name,
                "id_str": view_id_str,
                "reason": "Workset {} not found in document".format(ws_id_int)
            })
            continue

        audited_views.append({
            "view_id": view.Id,
            "name": view_name,
            "id_str": view_id_str,
            "workset_name": workset.Name,
            "workset_id": str(ws_id_int)
        })

    except Exception as ex:
        v_name = getattr(view, "Name", "Unknown View")
        v_id_val = getattr(getattr(view, "Id", None), "Value", getattr(getattr(view, "Id", None), "IntegerValue", "N/A"))
        views_without_workset.append({
            "view_id": getattr(view, "Id", None),
            "name": v_name,
            "id_str": str(v_id_val),
            "reason": "Exception during audit: {}".format(str(ex))
        })

output.print_md("# 3D View Workset Audit Report")
output.print_md("**Total Active 3D Views Evaluated:** {}".format(len(audited_views) + len(views_without_workset)))
output.print_md("**Templates Skipped:** {}".format(skipped_templates))
output.print_md("**Internal / Transient Views Skipped:** {}".format(skipped_transient))
output.insert_divider()

if views_without_workset:
    output.print_md("### :warning: 3D Views Missing Valid Worksets ({})".format(len(views_without_workset)))
    table_data = [
        [
            item["name"],
            output.linkify(item["view_id"]) if item.get("view_id") else item["id_str"],
            item["reason"]
        ]
        for item in views_without_workset
    ]
    output.print_table(
        table_data=table_data,
        columns=["View Name", "Element ID", "Audit Issue"]
    )

    forms.alert(
        "Audit completed with issues.\n\n"
        "Found {} 3D view(s) without a valid workset assigned.\n"
        "Review the report window for details.".format(len(views_without_workset)),
        title="Audit Results",
        warn_icon=True
    )
else:
    output.print_md("### :white_check_mark: All Active 3D Views Have Valid Worksets Assigned")
    if audited_views:
        table_data = [
            [
                item["name"],
                output.linkify(item["view_id"]),
                item["workset_name"],
                item["workset_id"]
            ]
            for item in audited_views
        ]
        output.print_table(
            table_data=table_data,
            columns=["View Name", "Element ID", "Workset Name", "Workset ID"]
        )

    forms.alert(
        "All {} audited 3D views are properly associated with valid worksets.".format(len(audited_views)),
        title="Audit Complete",
        warn_icon=False
    )
