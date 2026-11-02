"""Create synthetic sample documents for demos and manual testing.

All content is invented. Never add client or personal documents here.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import RGBColor

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def make_docx() -> Path:
    document = Document()

    header = document.sections[0].header.paragraphs[0]
    header.text = "Atlas Exports (Demo) - Export Documentation"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    document.add_heading("Commercial Invoice", level=1)

    intro = document.add_paragraph()
    intro.add_run("Seller: ").bold = True
    intro.add_run("Atlas Exports (Demo), 14 Harbour Road, Rotterdam")

    reference = document.add_paragraph()
    reference.add_run("Invoice number: ").bold = True
    reference.add_run("DEMO-2026-0042")
    reference.add_run("   |   Date: ").bold = True
    reference.add_run("31 October 2026")

    document.add_heading("Shipment summary", level=2)
    document.add_paragraph(
        "The goods are packed in export cartons and shipped on pallets. "
        "All items are of European origin and comply with the agreed quality standard."
    )

    note = document.add_paragraph()
    note.add_run("Important: ").bold = True
    note.add_run("the customer must arrange insurance before dispatch.")

    table = document.add_table(rows=4, cols=4)
    table.style = "Table Grid"
    values = [
        ["Description", "Quantity", "Unit price (EUR)", "Total (EUR)"],
        ["Organic cotton towels", "120 cartons", "18.50", "2,220.00"],
        ["Ceramic serving bowls", "48 cartons", "32.00", "1,536.00"],
        ["Total", "", "", "3,756.00"],
    ]
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            cell = table.cell(row_index, column_index)
            cell.text = value
            if row_index == 0 or row_index == 3:
                for run in cell.paragraphs[0].runs:
                    run.bold = True

    document.add_heading("Terms", level=2)
    document.add_paragraph(
        "Payment is due within 30 days. Delivery term: FOB Rotterdam. "
        "Please quote the invoice number in all correspondence."
    )

    footer = document.sections[0].footer.paragraphs[0]
    footer.text = "Atlas Exports (Demo) - synthetic document for evaluation only"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER

    heading_run = document.paragraphs[0].runs[0]
    heading_run.font.color.rgb = RGBColor(0x0C, 0x7C, 0x86)

    path = SAMPLES / "sample_export_invoice.docx"
    document.save(path)
    return path


def make_pdf() -> Path:
    document = fitz.open()

    page = document.new_page(width=595, height=842)
    page.insert_text((56, 72), "ATLAS EXPORTS (DEMO)", fontsize=20, fontname="hebo")
    page.insert_text((56, 100), "Packing List - DEMO-2026-0042", fontsize=13, fontname="helv")
    page.insert_text((56, 140), "Seller: Atlas Exports (Demo), 14 Harbour Road, Rotterdam", fontsize=10)
    page.insert_text((56, 160), "Buyer: Meridian Trading (Demo), 8 Market Street, Leeds", fontsize=10)
    page.insert_text((56, 180), "Ship date: 2 November 2026", fontsize=10)

    lines = [
        "Description                       Quantity        Net weight",
        "Organic cotton towels             120 cartons     480 kg",
        "Ceramic serving bowls             48 cartons      312 kg",
        "Recycled glass tumblers           60 cartons      270 kg",
    ]
    y = 230
    for line in lines:
        page.insert_text((56, y), line, fontsize=10, fontname="cour")
        y += 22

    page.insert_text(
        (56, 360),
        "The shipment is packed on 12 pallets. Cartons are labelled with the buyer reference.",
        fontsize=10,
    )
    page.insert_text(
        (56, 382),
        "Please inspect the goods on arrival and report any damage within five working days.",
        fontsize=10,
    )

    page2 = document.new_page(width=595, height=842)
    page2.insert_text((56, 72), "Terms and Conditions", fontsize=16, fontname="hebo")
    page2.insert_text(
        (56, 110),
        "1. Payment is due within 30 days of the invoice date.",
        fontsize=10,
    )
    page2.insert_text(
        (56, 132),
        "2. Delivery term is FOB Rotterdam unless agreed otherwise in writing.",
        fontsize=10,
    )
    page2.insert_text(
        (56, 154),
        "3. The seller is not responsible for delays caused by customs inspections.",
        fontsize=10,
    )
    page2.insert_text(
        (56, 176),
        "4. Insurance is arranged by the buyer before dispatch.",
        fontsize=10,
    )

    path = SAMPLES / "sample_packing_list.pdf"
    document.save(path, garbage=3, deflate=True)
    document.close()
    return path


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    print(make_docx())
    print(make_pdf())


if __name__ == "__main__":
    main()
