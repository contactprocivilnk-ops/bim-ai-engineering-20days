# -*- coding: utf-8 -*-
"""Audit Empty Drafting Views
Identifies empty drafting views, flags views placed on sheets, notes view template
associations, categorizes annotation/cloud-only views, and safely handles workshared models.
"""

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ViewDrafting,
    ViewType,
    Viewport,
    ElementCategoryFilter,
    ElementId,
    BuiltInCategory,
    CheckoutStatus,
    WorksharingUtils
)

doc = revit.doc
output = script.get_output()

# System and internal categories to ignore during geometry analysis
SYSTEM_CATEGORY_IDS = {
    int(BuiltInCategory.OST_Views),
    int(BuiltInCategory.OST_Viewers),
    int(BuiltInCategory.OST_Cameras),
    int(BuiltInCategory.OST_WeakDims),
}

# Categories considered non-geometry markup / pure annotations
ANNOTATION_CATEGORY_IDS = {
    int(BuiltInCategory.OST_TextNotes),
    int(BuiltInCategory.OST_Dimensions),
    int(BuiltInCategory.OST_RevisionClouds),
    int(BuiltInCategory.OST_RevisionCloudTags),
    int(BuiltInCategory.OST_GuideGrid),
    int(BuiltInCategory.OST_GenericAnnotation),
}


def get_placed_viewport_map(document):
    """Maps view ElementId to its host ViewSheet display string."""
    vp_map = {}
    if not document:
        return vp_map

    vp_collector = (
        FilteredElementCollector(document)
        .OfClass(Viewport)
        .WhereElementIsNotElementType()
    )

    for vp in vp_collector:
        v_id = vp.ViewId
        sheet_id = vp.SheetId
        sheet = document.GetElement(sheet_id) if sheet_id != ElementId.InvalidElementId else None
        if sheet and hasattr(sheet, "SheetNumber") and hasattr(sheet, "Name"):
            sheet_info = "{0} - {1}".format(sheet.SheetNumber, sheet.Name)
        else:
            sheet_info = "Sheet Id {0}".format(sheet_id.IntegerValue if hasattr(sheet_id, "IntegerValue") else sheet_id)
        vp_map[v_id] = sheet_info
    return vp_map


def is_checked_out_by_other(document, element_id):
    """Checks if the element is locked by another user in a workshared model."""
    if not document or not document.IsWorkshared:
        return False
    try:
        status = WorksharingUtils.GetCheckoutStatus(document, element_id)
        return status == CheckoutStatus.OwnedByOtherUser
    except Exception:
        return False


def analyze_view_contents(document, view):
    """Examines elements within a drafting view.

    Returns:
        vacant (bool): View contains no drafting or user elements.
        annotation_only (bool): View contains only annotations/clouds/grids.
        element_count (int): Count of valid user elements found.
    """
    # Verify using ElementCategoryFilter for system views exclusion
    view_collector = (
        FilteredElementCollector(document, view.Id)
        .WhereElementIsNotElementType()
    )

    elements = view_collector.ToElements()
    user_elements = []
    has_geometry = False
    has_annotations = False

    for elem in elements:
        if not elem or not elem.IsValidObject:
            continue

        cat = elem.Category
        if not cat:
            # Ignore non-categorized system elements (e.g. crop boxes, internal planes)
            continue

        cat_id = cat.Id.IntegerValue if hasattr(cat.Id, "IntegerValue") else int(cat.Id.Value)
        if cat_id in SYSTEM_CATEGORY_IDS:
            continue

        if cat_id in ANNOTATION_CATEGORY_IDS:
            has_annotations = True
        else:
            has_geometry = True

        user_elements.append(elem)

    element_count = len(user_elements)
    vacant = (element_count == 0)
    annotation_only = (element_count > 0 and has_annotations and not has_geometry)

    return vacant, annotation_only, element_count


def get_view_template_name(document, view):
    """Returns the assigned view template name, or 'None'."""
    tpl_id = view.ViewTemplateId
    if tpl_id and tpl_id != ElementId.InvalidElementId:
        template = document.GetElement(tpl_id)
        if template and hasattr(template, "Name"):
            return template.Name
    return "None"


def main():
    if not doc:
        forms.alert("No active document found.", title="Audit Empty Drafting Views", exitscript=True)
        return

    # 1. Collect all drafting views, strictly excluding templates
    collector = (
        FilteredElementCollector(doc)
        .OfClass(ViewDrafting)
        .WhereElementIsNotElementType()
    )

    drafting_views = [
        v for v in collector
        if not v.IsTemplate and v.ViewType == ViewType.DraftingView
    ]

    if not drafting_views:
        forms.alert("No drafting views found in the model.", title="Audit Empty Drafting Views", exitscript=True)
        return

    # 2. Map viewports to host sheets
    viewport_map = get_placed_viewport_map(doc)

    # 3. Analyze each view
    audit_data = []
    deletable_views = []

    for view in drafting_views:
        v_id = view.Id
        view_name = view.Name or "<Unnamed View>"
        placed_sheet = viewport_map.get(v_id, None)
        is_locked = is_checked_out_by_other(doc, v_id)
        template_name = get_view_template_name(doc, view)

        vacant, annotation_only, count = analyze_view_contents(doc, view)

        if vacant:
            if placed_sheet:
                status = "EMPTY (Placed on Sheet)"
                action = "DO NOT DELETE (Breakage Risk)"
            elif is_locked:
                status = "EMPTY (Locked/Checked Out)"
                action = "SKIPPED (Workshared)"
            else:
                status = "TRULY VACANT"
                action = "Eligible for Deletion"
                deletable_views.append(view)
        elif annotation_only:
            status = "ANNOTATION / CLOUD ONLY"
            action = "Review (Placed on: {0})".format(placed_sheet) if placed_sheet else "Review (Unplaced)"
        else:
            status = "POPULATED"
            action = "Keep"

        if status != "POPULATED":
            id_val = v_id.IntegerValue if hasattr(v_id, "IntegerValue") else v_id.Value
            audit_data.append([
                view_name,
                str(id_val),
                status,
                str(count),
                placed_sheet if placed_sheet else "None",
                template_name,
                "Yes" if is_locked else "No",
                action
            ])

    # 4. Display report
    output.print_md("# Audit Empty Drafting Views Report")
    output.print_md("**Total Drafting Views Scanned:** {0}".format(len(drafting_views)))

    if not audit_data:
        output.print_md("### All drafting views contain valid drafting geometry. No empty views found.")
        return

    output.print_table(
        table_data=audit_data,
        columns=["View Name", "View ID", "Status", "Elements", "Placed On Sheet", "Template", "Owned by Other", "Action"],
        formats=["{}", "{}", "{}", "{}", "{}", "{}", "{}", "{}"]
    )

    # 5. Clean up truly vacant, unplaced, unlocked views
    if deletable_views:
        delete_prompt = forms.alert(
            "Found {0} truly vacant and unplaced drafting view(s).\n\n"
            "Views on sheets and locked views are protected and excluded.\n"
            "Would you like to delete these vacant views?".format(len(deletable_views)),
            title="Clean Up Vacant Views",
            yes=True,
            no=True
        )

        if delete_prompt:
            deleted_count = 0
            with revit.Transaction("Purge Vacant Drafting Views"):
                for v in deletable_views:
                    v_name = v.Name
                    try:
                        doc.Delete(v.Id)
                        deleted_count += 1
                    except Exception as ex:
                        print("Failed to delete view '{0}': {1}".format(v_name, str(ex)))

            forms.alert(
                "Successfully deleted {0} vacant drafting view(s).".format(deleted_count),
                title="Cleanup Complete"
            )


if __name__ == "__main__":
    main()
