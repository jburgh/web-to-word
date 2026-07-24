"""Generate a Pandoc reference.docx styled to resemble the Just the Docs site.

Starts from Pandoc's built-in reference document and patches:
  - the theme fonts (major/minor) to a system sans-serif (Segoe UI), matching
    the site's `system-ui` stack;
  - heading color to near-black (#1A1A1A), matching the site headings;
  - the Hyperlink character style to CDC blue (#005DAA) with an underline,
    matching `.main-content a` on the site.

Code stays Consolas (Pandoc's default VerbatimChar), which matches the site's
`SFMono-Regular, Menlo, Consolas` monospace stack closely enough.

Usage:  python scripts/make_reference.py styles.docx

"Similar, not exact" is the goal — these are print-friendly approximations, not
a pixel match. Content is never touched; this only defines styles.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import zipfile

BODY_FONT = "Segoe UI"          # Word's closest ubiquitous match for system-ui
HEADING_COLOR = "1A1A1A"        # site h1 color
LINK_COLOR = "005DAA"           # site .main-content a color (CDC blue)
# Pandoc's default accent colors, matched with \s+ so embedded newlines/indent
# in the source XML don't defeat the replacement.
HEADING_ACCENT_RE = re.compile(r'<w:color\s+w:val="0F4761"\s+w:themeColor="accent1"\s+w:themeShade="BF"\s*/>')
LINK_ACCENT_RE = re.compile(r'<w:color\s+w:val="4F81BD"\s+w:themeColor="accent1"\s*/>')

# Heading 2/3 share this spacing; widen the space above (before) for breathing room.
HEADING_SPACING_OLD = '<w:spacing w:before="160" w:after="80" />'
HEADING_SPACING_NEW = '<w:spacing w:before="340" w:after="100" />'

TABLE_BORDER_COLOR = "B3B3B3"   # mid-gray cell borders
TABLE_HEADER_FILL = "F0F0F0"    # light gray header row shading

# Callout palette: (background tint, left-bar accent), taken from the site's own
# callout colors (see contributing/styles.md). Boxes get a thin gray border on
# three sides and a thick colored accent bar on the left, plus the tint fill.
CALLOUTS = {
    "Note":      ("E6EFF7", "2474B6"),  # blue
    "Important": ("FBEDD6", "ECB046"),  # yellow
    "Warning":   ("F8E4EB", "CB3E6E"),  # red
    "New":       ("EAF5DC", "9ACC54"),  # green
    "Highlight": ("F1E9EE", "A1518B"),  # purple (no label)
}


def _default_reference() -> bytes:
    return subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        check=True, capture_output=True,
    ).stdout


def _patch_theme(xml: str) -> str:
    # Replace the major (heading) and minor (body) latin typefaces.
    xml = xml.replace('typeface="Aptos Display"', f'typeface="{BODY_FONT}"')
    xml = xml.replace('typeface="Aptos"', f'typeface="{BODY_FONT}"')
    return xml


def _callout_style(style_id: str, fill: str, bar: str) -> str:
    gray = "D6DEE6"
    return (
        f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{style_id}">'
        f'<w:name w:val="{style_id}" /><w:basedOn w:val="BodyText" /><w:qFormat />'
        f'<w:pPr>'
        f'<w:pBdr>'
        f'<w:top w:val="single" w:sz="4" w:space="6" w:color="{gray}" />'
        f'<w:left w:val="single" w:sz="24" w:space="8" w:color="{bar}" />'
        f'<w:bottom w:val="single" w:sz="4" w:space="6" w:color="{gray}" />'
        f'<w:right w:val="single" w:sz="4" w:space="6" w:color="{gray}" />'
        f'</w:pBdr>'
        f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}" />'
        f'<w:spacing w:before="120" w:after="120" />'
        f'<w:ind w:left="187" w:right="120" />'
        f'</w:pPr>'
        f'</w:style>'
    )


def _sourcecode_style() -> str:
    """Paragraph style for fenced code blocks: light gray box + Consolas.

    Pandoc emits one SourceCode-styled paragraph per code line; identical borders
    on adjacent paragraphs merge into a single box in Word.
    """
    gray = "D0D7DE"
    return (
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="SourceCode">'
        '<w:name w:val="Source Code" /><w:basedOn w:val="Normal" /><w:qFormat />'
        '<w:pPr>'
        '<w:pBdr>'
        f'<w:top w:val="single" w:sz="4" w:space="4" w:color="{gray}" />'
        f'<w:left w:val="single" w:sz="4" w:space="8" w:color="{gray}" />'
        f'<w:bottom w:val="single" w:sz="4" w:space="4" w:color="{gray}" />'
        f'<w:right w:val="single" w:sz="4" w:space="8" w:color="{gray}" />'
        '</w:pBdr>'
        '<w:shd w:val="clear" w:color="auto" w:fill="F6F8FA" />'
        '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto" />'
        '<w:ind w:left="120" w:right="120" />'
        '</w:pPr>'
        '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" /><w:sz w:val="18" /></w:rPr>'
        '</w:style>'
    )


def _patch_styles(xml: str) -> str:
    # Heading color: only headings carry the 0F4761 accent, so this is precise.
    xml = HEADING_ACCENT_RE.sub(f'<w:color w:val="{HEADING_COLOR}" />', xml)
    # Hyperlink style: recolor and add an underline so links read as links.
    xml = LINK_ACCENT_RE.sub(
        f'<w:color w:val="{LINK_COLOR}" /><w:u w:val="single" />', xml
    )
    # More space above H2/H3 (this spacing string is unique to those two styles).
    xml = xml.replace(HEADING_SPACING_OLD, HEADING_SPACING_NEW)

    # Code font size. Pandoc styles code runs (both inline and block) with the
    # VerbatimChar character style, whose run props OVERRIDE the SourceCode
    # paragraph style. So the size must be set HERE to take effect. 18 = 9pt.
    def _patch_verbatim(m: re.Match) -> str:
        return m.group(0).replace('<w:sz w:val="22" />', '<w:sz w:val="18" />')

    xml = re.sub(
        r'<w:style [^>]*w:styleId="VerbatimChar".*?</w:style>',
        _patch_verbatim, xml, flags=re.S,
    )

    # Table: borders on every cell + a shaded header row.
    borders = (
        '<w:tblBorders>'
        f'<w:top w:val="single" w:sz="4" w:color="{TABLE_BORDER_COLOR}" />'
        f'<w:left w:val="single" w:sz="4" w:color="{TABLE_BORDER_COLOR}" />'
        f'<w:bottom w:val="single" w:sz="4" w:color="{TABLE_BORDER_COLOR}" />'
        f'<w:right w:val="single" w:sz="4" w:color="{TABLE_BORDER_COLOR}" />'
        f'<w:insideH w:val="single" w:sz="4" w:color="{TABLE_BORDER_COLOR}" />'
        f'<w:insideV w:val="single" w:sz="4" w:color="{TABLE_BORDER_COLOR}" />'
        '</w:tblBorders>'
    )

    def _patch_table(m: re.Match) -> str:
        block = m.group(0)
        if "<w:tblBorders>" not in block:
            block = block.replace("<w:tblPr>", "<w:tblPr>" + borders, 1)
        # Shade + embolden the header row.
        header_props = (
            f'<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="{TABLE_HEADER_FILL}" />'
            '<w:tcBorders><w:bottom w:val="single" w:sz="8" '
            f'w:color="{TABLE_BORDER_COLOR}" /></w:tcBorders>'
            '<w:vAlign w:val="bottom" /></w:tcPr>'
        )
        block = re.sub(r'<w:tcPr>.*?</w:tcPr>', header_props, block, count=1, flags=re.S)
        # Add bold run props to the first-row style def if not present.
        block = block.replace(
            '<w:tblStylePr w:type="firstRow">',
            '<w:tblStylePr w:type="firstRow"><w:rPr><w:b /></w:rPr>',
        )
        return block

    xml = re.sub(
        r'<w:style w:type="table"[^>]*w:styleId="Table".*?</w:style>',
        _patch_table, xml, flags=re.S,
    )

    # Inject callout + code-block paragraph styles before the closing tag.
    extra_xml = "".join(
        _callout_style(sid, fill, bar) for sid, (fill, bar) in CALLOUTS.items()
    ) + _sourcecode_style()
    xml = xml.replace("</w:styles>", extra_xml + "</w:styles>")
    return xml


def build_reference(out_path: str) -> str:
    src = _default_reference()
    zin = zipfile.ZipFile(io.BytesIO(src))

    patched: dict[str, bytes] = {}
    for name in zin.namelist():
        data = zin.read(name)
        if name == "word/theme/theme1.xml":
            data = _patch_theme(data.decode("utf-8")).encode("utf-8")
        elif name == "word/styles.xml":
            data = _patch_styles(data.decode("utf-8")).encode("utf-8")
        patched[name] = data

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in patched.items():
            zout.writestr(name, data)
    return out_path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "styles.docx"
    path = build_reference(out)
    print(f"wrote {path}")
