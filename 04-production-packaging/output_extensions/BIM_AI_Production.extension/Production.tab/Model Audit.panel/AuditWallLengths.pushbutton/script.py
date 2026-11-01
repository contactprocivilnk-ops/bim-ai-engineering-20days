import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    Wall,
    BuiltInParameter,
    UnitUtils,
    LabelUtils
)
from pyrevit import revit, script, HOST_APP

def get_length_display_unit(doc):
    revit_ver = int(HOST_APP.version)
    doc_units = doc.GetUnits()
    if revit_ver >= 2022:
        from Autodesk.Revit.DB import SpecTypeId
        length_fo = doc_units.GetFormatOptions(SpecTypeId.Length)
        display_unit = length_fo.GetUnitTypeId()
        unit_label = LabelUtils.GetLabelForUnit(display_unit)
    else:
        from Autodesk.Revit.DB import UnitType
        length_fo = doc_units.GetFormatOptions(UnitType.UT_Length)
        display_unit = length_fo.GetDisplayUnits()
        unit_label = LabelUtils.GetLabelFor(display_unit)
    return display_unit, unit_label

def audit_wall_lengths():
    doc = revit.doc
    if not doc:
        return

    output = script.get_output()
    output.set_title("Audit Wall Lengths")

    display_unit, unit_label = get_length_display_unit(doc)

    walls = (
        FilteredElementCollector(doc)
        .OfClass(Wall)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    if not walls:
        output.print_md("### No walls found in the current project.")
        return

    # Thresholds in internal units (feet)
    # Micro-wall threshold: ~1/8" (0.0104 ft) or short wall threshold: 1.0 ft (~304.8 mm)
    sliver_threshold_feet = 0.1
    short_threshold_feet = 1.0

    sliver_threshold_display = UnitUtils.ConvertFromInternalUnits(sliver_threshold_feet, display_unit)
    short_threshold_display = UnitUtils.ConvertFromInternalUnits(short_threshold_feet, display_unit)

    table_data = []
    sliver_count = 0
    short_count = 0
    total_length_internal = 0.0

    for wall in walls:
        if not wall or not wall.IsValidObject:
            continue

        param = wall.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
        if not param or not param.HasValue:
            continue

        raw_length = param.AsDouble()
        total_length_internal += raw_length
        display_length = UnitUtils.ConvertFromInternalUnits(raw_length, display_unit)

        wall_type = doc.GetElement(wall.GetTypeId())
        type_name = wall_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() if wall_type else "Unknown"

        status = "Normal"
        if raw_length <= sliver_threshold_feet:
            status = "CRITICAL: Sliver Wall"
            sliver_count += 1
        elif raw_length <= short_threshold_feet:
            status = "WARNING: Short Wall"
            short_count += 1

        workset_name = "-"
        if doc.IsWorkshared:
            workset_param = wall.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM)
            if workset_param:
                workset_name = workset_param.AsValueString()

        # Only list walls that meet the warning/sliver criteria or have anomalously small lengths
        if raw_length <= short_threshold_feet:
            table_data.append([
                output.linkify(wall.Id),
                wall.Name,
                type_name,
                "{:.3f} {}".format(display_length, unit_label),
                status,
                workset_name
            ])

    total_display_length = UnitUtils.ConvertFromInternalUnits(total_length_internal, display_unit)

    output.print_md("# Model Audit: Wall Lengths")
    output.print_md(
        "**Total Walls Evaluated:** {} | "
        "**Cumulative Length:** {:.2f} {}".format(len(walls), total_display_length, unit_label)
    )
    output.print_md(
        "**Sliver Threshold:** < {:.3f} {} | "
        "**Short Threshold:** < {:.3f} {}".format(
            sliver_threshold_display, unit_label, short_threshold_display, unit_label
        )
    )

    if table_data:
        output.print_md("### Flagged Walls ({} Found)".format(len(table_data)))
        output.print_table(
            table_data=table_data,
            title="Short & Sliver Walls",
            columns=["Element ID", "Wall Name", "Type", "Length", "Severity", "Workset"]
        )
    else:
        output.print_md("### No sliver or abnormally short walls detected.")

if __name__ == "__main__":
    audit_wall_lengths()