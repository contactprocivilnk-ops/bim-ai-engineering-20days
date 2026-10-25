from Autodesk.Revit.DB import FilteredElementCollector, ViewDrafting, ElementId
from pyrevit import revit, forms

doc = revit.doc
active_view_id = doc.ActiveView.Id

# Query all drafting views in the document
drafting_views = FilteredElementCollector(doc).OfClass(ViewDrafting).ToElements()

views_to_delete = []

for view in drafting_views:
    # Exclude view templates
    if view.IsTemplate:
        continue

    # Never delete the currently active view to prevent UI crashes
    if view.Id == active_view_id:
        continue

    # Fast zero-element check in the view context
    if FilteredElementCollector(doc, view.Id).GetElementCount() == 0:
        views_to_delete.append(view)

if not views_to_delete:
    forms.alert("No empty drafting views found.", title="Purge Empty Drafting Views", exitscript=True)

deleted_count = 0

with revit.Transaction("Purge Empty Drafting Views"):
    for view in views_to_delete:
        try:
            doc.Delete(view.Id)
            deleted_count += 1
        except Exception:
            # Skip views that cannot be deleted due to dependencies
            continue

forms.alert(
    "Successfully purged {} empty drafting view(s).".format(deleted_count),
    title="Purge Empty Drafting Views"
)