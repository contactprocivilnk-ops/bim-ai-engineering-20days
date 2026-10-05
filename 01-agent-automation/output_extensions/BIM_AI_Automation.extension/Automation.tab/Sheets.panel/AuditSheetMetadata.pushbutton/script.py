س# -*- coding: utf-8 -*-
"""AuditSheetMetadata

Audits all sheets in the project and alerts the user if any sheet lacks a valid
sheet number or sheet name, accounting for placeholder sheets, templates, and null values.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ViewSheet,
    BuiltInParameter,
    Parameter
)
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons
from pyrevit import revit, forms, script

output = script.get_output()
doc = revit.doc


def get_clean_param_string(element, bip):
    """Safely retrieves and cleans string values from a BuiltInParameter."""
    try:
        param = element.get_Parameter(bip)
        if not isinstance(param, Parameter) or not param.HasValue:
            return ""
        val = param.AsString()
        if val is None:
            return ""
        return val.strip()
    except Exception:
        return ""


def main():
    if not doc:
        forms.alert("No active document found.", title="Audit Sheet Metadata", exitscript=True)
        return

    # Collect all ViewSheet instances
    collector = FilteredElementCollector(doc).OfClass(ViewSheet).ToElements()
    if not collector:
        TaskDialog.Show("Audit Sheet Metadata", "No ViewSheet elements were found in the current project.")
        return

    # Filter out sheet view templates or invalid elements
    valid_sheets = []
    for s in collector:
        if not isinstance(s, ViewSheet):
            continue
        if hasattr(s, "IsTemplate") and s.IsTemplate:
            continue
        valid_sheets.append(s)

    if not valid_sheets:
        TaskDialog.Show("Audit Sheet Metadata", "No non-template ViewSheet elements found in the project.")
        return

    audit_findings = []
    flagged_sheet_count = 0

    for sheet in valid_sheets:
        issues = []
        is_placeholder = sheet.IsPlaceholder

        num_val = get_clean_param_string(sheet, BuiltInParameter.SHEET_NUMBER)
        if not num_val:
            issues.append("Missing or whitespace Sheet Number")

        name_val = get_clean_param_string(sheet, BuiltInParameter.SHEET_NAME)
        if not name_val:
            issues.append("Missing or whitespace Sheet Name")
        elif name_val.strip().upper() == "UNNAMED":
            issues.append("Sheet Name remains default 'Unnamed'")

        # Edge case: Placeholder sheets with partial/empty metadata
        if is_placeholder and (not num_val or not name_val):
            issues.append("Placeholder Sheet lacks required identity metadata")

        if issues:
            flagged_sheet_count += 1
            display_num = num_val if num_val else "[NO NUMBER]"
            display_name = name_val if name_val else "[NO NAME]"
            audit_findings.append({
                "element_id": sheet.Id,
                "number": display_num,
                "name": display_name,
                "placeholder": "Yes" if is_placeholder else "No",
                "issues": "; ".join(issues)
            })

    output.print_md("# Sheet Metadata Audit Report")
    output.print_md(
        "**Total Sheets Evaluated:** {} | **Sheets with Issues:** {}".format(
            len(valid_sheets),
            flagged_sheet_count
        )
    )
    output.print_md("---")

    if not audit_findings:
        output.print_md("### All sheets passed the metadata audit with valid numbers and names.")
        td = TaskDialog("Audit Sheet Metadata")
        td.MainInstruction = "Metadata Audit Passed"
        td.MainContent = "All {} sheets have valid sheet numbers and names.".format(len(valid_sheets))
        td.CommonButtons = TaskDialogCommonButtons.Ok
        td.Show()
        return

    table_data = []
    for item in sorted(audit_findings, key=lambda x: x["number"]):
        table_data.append([
            output.linkify(item["element_id"]),
            item["number"],
            item["name"],
            item["placeholder"],
            item["issues"]
        ])

    output.print_table(
        table_data=table_data,
        columns=["Element Id", "Sheet Number", "Sheet Name", "Is Placeholder", "Issues Detected"]
    )

    dialog = TaskDialog("Audit Sheet Metadata")
    dialog.MainInstruction = "Audit Completed: Issues Detected"
    dialog.MainContent = (
        "Evaluated {} sheets.\n"
        "Found {} sheet(s) lacking valid sheet numbers or names.\n"
        "Review the pyRevit output window for element links and details."
    ).format(len(valid_sheets), flagged_sheet_count)
    dialog.CommonButtons = TaskDialogCommonButtons.Ok
    dialog.Show()


if __name__ == "__main__":
    main()
