"""Generation simple du rapport PDF a partir du Markdown."""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def md_to_pdf(md_path: Path, pdf_path: Path) -> None:
    styles = getSampleStyleSheet()
    story = []
    in_code = False
    code_lines: list[str] = []

    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                story.append(Paragraph("<br/>".join(code_lines), styles["Code"]))
                story.append(Spacer(1, 6))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue
        if not line:
            story.append(Spacer(1, 6))
            continue
        if line.startswith("# "):
            story.append(Paragraph(line[2:], styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(line[3:], styles["Heading1"]))
        elif line.startswith("### "):
            story.append(Paragraph(line[4:], styles["Heading2"]))
        elif line.startswith("- "):
            story.append(Paragraph("• " + line[2:], styles["BodyText"]))
        else:
            story.append(Paragraph(line, styles["BodyText"]))

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    doc.build(story)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", default="rapport_technique.md")
    parser.add_argument("--pdf", default="rapport_technique.pdf")
    args = parser.parse_args()
    md_to_pdf(Path(args.md), Path(args.pdf))


if __name__ == "__main__":
    main()
