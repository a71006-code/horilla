
import fitz
import os

def inspect_pdf(filename):
    path = os.path.join("report/static/report/forms", filename)
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    print(f"--- Inspecting {filename} ---")
    doc = fitz.open(path)
    for page_num, page in enumerate(doc):
        widgets = page.widgets()
        if widgets:
            print(f"Page {page_num + 1} Widgets:")
            for w in widgets:
                print(f"  Field Name: '{w.field_name}' | Current Value: '{w.field_value}'")
        else:
            print(f"Page {page_num + 1}: No widgets found.")

inspect_pdf("f941.pdf")
inspect_pdf("fde9.pdf")
inspect_pdf("fde9c.pdf")
