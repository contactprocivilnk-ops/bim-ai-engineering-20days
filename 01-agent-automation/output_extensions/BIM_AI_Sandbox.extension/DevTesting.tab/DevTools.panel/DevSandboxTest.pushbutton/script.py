# -*- coding: utf-8 -*-
"""Dev Sandbox Test Tool."""

from pyrevit import revit, forms

doc = revit.doc

def run_sandbox_test():
    if not doc:
        forms.alert('No active document found!', title='Sandbox Warning')
        return
    
    doc_title = doc.Title
    is_family = doc.IsFamilyDocument
    
    msg = "--- Automation Pipeline Test Successful! ---\n\n"
    msg += "Active Document: {}\n".format(doc_title)
    msg += "Document Type: {}\n".format('Family Document' if is_family else 'Project Model')
    msg += "Status: pyRevit folder scaffold generated automatically by AI pipeline."
    
    forms.alert(msg, title='BIM AI Engineering Test')

if __name__ == '__main__':
    run_sandbox_test()
