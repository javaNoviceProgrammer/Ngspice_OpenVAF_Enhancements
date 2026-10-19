#!/usr/bin/env python3
r"""Build docs/Ngspice-OpenVAF-Features.pptx, the features deck of the enhanced
ngspice + openvaf-r.

    python3 docs/build_features_deck.py                  # writes docs/Ngspice-OpenVAF-Features.pptx
    python3 docs/build_features_deck.py -o /tmp/deck.pptx --month "November 2026"

Needs python-pptx (1.0 or later), Pillow and lxml; no network.

WHAT IS READ FROM THE REPO. Every count the deck quotes comes from the tree at
build time, so a rebuild after new enhancements stays true without edits:
- the latest enhancement number and the number of write-ups (enhancements_doc/);
- each feature area's enhancement count (the catalog's data in docs/index.html):
  the chart, the compiler and simulator totals, and each slide's kicker;
- the regression sweep, from the newest write-up that records "The full sweep:
  N of M";
- the VA_TEST corpus (VA_TEST/compile_report.md);
- the bug-hunt pages, proposals and example folders.
A catalog area that is renamed stops the build with the names it found.
Two builds of one tree give the same slide XML; only the chart's embedded
workbook (its creation time) and the zip entry times differ.

WHAT IS WRITTEN BY HAND. The feature cards, their E-number chips, the code
snippets, the timeline and the limits are curated in this file. A new feature
appears in the deck when a card here names it. The Verilog-A snippets were
compiled with the committed openvaf-r and the results they print come from real
ngspice runs; keep that true when changing them.

STRUCTURE. A theme (colours and the Cambria/Calibri fonts), three layouts
(Title, Section, Content) whose title placeholders carry the styling, one
PowerPoint section per part, speaker notes on every slide. Teal marks the
compiler, orange the simulator, green verification. Each E-number chip links to
its write-up on GitHub. The pictures are the example suites' committed result
plots.

CHECKING A BUILD. The script prints "FIT?" for any text box whose estimated
text height exceeds the box; it is an estimate, so look at the slides too.
PowerPoint on macOS is sandboxed and asks for file access when it opens a repo
path; copying the deck into its container avoids the prompt. From the repo root:

    C=~/Library/Containers/com.microsoft.Powerpoint/Data/tmp/deckcheck
    mkdir -p $C && cp docs/Ngspice-OpenVAF-Features.pptx $C/deck.pptx
    osascript -e "tell application \"Microsoft PowerPoint\"" \
              -e "open (POSIX file \"$C/deck.pptx\")" \
              -e "save active presentation in (POSIX file \"$C/deck.pdf\") as save as PDF" \
              -e "close active presentation saving no" -e "end tell"
    pdftoppm -jpeg -r 96 $C/deck.pdf $C/slide     # $C/slide-01.jpg ... ; rm -r $C when done
"""
import argparse
import copy
import datetime
import glob
import math
import os
import re
import uuid

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.dml import MSO_THEME_COLOR as TC
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

NB = "\u00a0"                # keeps a number on the line of its unit
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "docs", "Ngspice-OpenVAF-Features.pptx")
GH = "https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements"
WRITEUP = GH + "/blob/main/enhancements_doc/Enhancement-%d.md"

THEME = {
    "name": "Ngspice OpenVAF",
    "head": "Cambria", "body": "Calibri",
    "colors": {
        "dk1": "1B2533", "lt1": "FFFFFF", "dk2": "0E1A2B", "lt2": "EEF2F6",
        "accent1": "00A39A",   # compiler: teal
        "accent2": "F28C28",   # simulator: orange
        "accent3": "5B6B7F",   # slate, muted
        "accent4": "2E9E5B",   # verification: green
        "accent5": "D64545",   # limits: red
        "accent6": "FFC857",   # highlight on dark
        "hlink": "007F78", "folHlink": "5B6B7F",
    },
}
HEX = THEME["colors"]

W, H = 13.333, 7.5
MX = 0.6                     # side margin
TOP = 1.55                   # content top
BOT = 6.85                   # content bottom
CW = W - 2 * MX              # content width

warnings = []
F = {}                       # the facts read from the repo, filled by facts()
AREA = {}                    # catalog area name -> enhancement count

WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen", "twenty"]


def word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def stable_id(key):
    """A GUID that is the same on every build, so rebuilds do not churn the XML."""
    return "{%s}" % str(uuid.uuid5(uuid.NAMESPACE_URL, "ngspice-openvaf-features/" + key)).upper()


def facts(repo, month):
    nums = []
    for f in os.listdir(os.path.join(repo, "enhancements_doc")):
        m = re.match(r"Enhancement-(\d+)\.md$", f)
        if m:
            nums.append(int(m.group(1)))
    F["latest"], F["writeups"] = max(nums), len(nums)

    html = open(os.path.join(repo, "docs", "index.html"), encoding="utf-8").read()
    areas = []
    for side, name, _x, chips_ in re.findall(
            r'\{d:"([^"]*)",n:"([^"]*)",x:"((?:[^"\\]|\\.)*)",c:\[(.*?)\]\]\}', html, re.S):
        n = len(re.findall(r'\[(\d+),"((?:[^"\\]|\\.)*)"\]', chips_ + "]"))
        areas.append((name, n, side))
        AREA[name] = n
    if not areas:
        raise SystemExit("docs/index.html: no feature areas found; has the catalog's data format changed?")
    F["areas"] = areas
    F["comp"] = sum(n for _, n, d in areas if d == "compiler")
    F["sim"] = sum(n for _, n, d in areas if d == "simulator")
    F["n_comp"] = sum(1 for *_, d in areas if d == "compiler")
    F["n_sim"] = sum(1 for *_, d in areas if d == "simulator")
    F["area_sum"] = sum(n for _, n, _ in areas)

    F["sweep_pass"] = F["sweep_total"] = F["sweep_at"] = None
    for n in sorted(nums, reverse=True):
        t = open(os.path.join(repo, "enhancements_doc", "Enhancement-%d.md" % n), encoding="utf-8").read()
        m = re.search(r"full sweep: (\d+) of (\d+)", t, re.I)
        if m:
            F["sweep_pass"], F["sweep_total"], F["sweep_at"] = int(m.group(1)), int(m.group(2)), n
            break
    if F["sweep_total"] is None:
        raise SystemExit("enhancements_doc: no write-up records \"The full sweep: N of M\"")

    rep_ = open(os.path.join(repo, "VA_TEST", "compile_report.md"), encoding="utf-8").read()
    m = re.search(r"Standalone models: (\d+)/(\d+) compile", rep_)
    F["va_ok"], F["va_standalone"] = int(m.group(1)), int(m.group(2))
    F["va_files"] = int(re.search(r"Files: (\d+)", rep_).group(1))

    F["hunts"] = len(glob.glob(os.path.join(repo, "docs", "bug_hunts", "*.md")))
    F["proposals"] = len(glob.glob(os.path.join(repo, "docs", "proposals", "*.md")))
    F["examples"] = len([d for d in glob.glob(os.path.join(repo, "examples", "*_examples")) if os.path.isdir(d)])
    F["month"] = month


def area(*names):
    for n in names:
        if n not in AREA:
            raise SystemExit("docs/index.html has no feature area %r; it has: %s" % (n, ", ".join(AREA)))
    return " + ".join(str(AREA[n]) for n in names)


def kc(side, *names):
    return "%s · %s enhancements" % (side, area(*names))


def sweep_all_pass():
    return F["sweep_pass"] == F["sweep_total"]


def sweep_text():
    return "all passing" if sweep_all_pass() else "%d of them passing" % F["sweep_pass"]


# --------------------------------------------------------------- theme
def apply_theme(prs):
    part = prs.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(part.blob)
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    root.set("name", THEME["name"])
    clr = root.find(".//{%s}clrScheme" % a)
    clr.set("name", THEME["name"])
    for el in list(clr):
        tag = etree.QName(el).localname
        for c in list(el):
            el.remove(c)
        etree.SubElement(el, "{%s}srgbClr" % a).set("val", HEX[tag])
    fs = root.find(".//{%s}fontScheme" % a)
    fs.set("name", THEME["name"])
    fs.find("{%s}majorFont/{%s}latin" % (a, a)).set("typeface", THEME["head"])
    fs.find("{%s}minorFont/{%s}latin" % (a, a)).set("typeface", THEME["body"])
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def E(tag, **attrs):
    ns, name = tag.split(":")
    el = etree.Element("{%s}%s" % (A_NS if ns == "a" else P_NS, name))
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def sub(parent, tag, **attrs):
    el = E(tag, **attrs)
    parent.append(el)
    return el


def scheme_fill(parent, val):
    sf = sub(parent, "a:solidFill")
    sub(sf, "a:schemeClr", val=val)
    return sf


def set_bg(layout_or_slide, val):
    cSld = layout_or_slide._element.find(qn("p:cSld"))
    old = cSld.find(qn("p:bg"))
    if old is not None:
        cSld.remove(old)
    bg = E("p:bg")
    bgPr = sub(bg, "p:bgPr")
    scheme_fill(bgPr, val)
    sub(bgPr, "a:effectLst")
    cSld.insert(0, bg)


def place(ph, x, y, w, h):
    ph.left, ph.top, ph.width, ph.height = Inches(x), Inches(y), Inches(w), Inches(h)


def ph_style(ph, size, color, bold=True, align="l", anchor="ctr", font="+mj-lt"):
    """Set a layout placeholder's own text defaults through its lstStyle."""
    txBody = ph._element.find(qn("p:txBody"))
    bodyPr = txBody.find(qn("a:bodyPr"))
    bodyPr.set("anchor", anchor)
    for k in ("lIns", "rIns", "tIns", "bIns"):
        bodyPr.set(k, "0")
    na = bodyPr.find(qn("a:normAutofit"))
    for c in list(bodyPr):
        bodyPr.remove(c)
    sub(bodyPr, "a:noAutofit")
    old = txBody.find(qn("a:lstStyle"))
    lst = E("a:lstStyle")
    lvl = sub(lst, "a:lvl1pPr", algn=align, marL="0", indent="0")
    sub(lvl, "a:buNone")
    d = sub(lvl, "a:defRPr", sz=str(int(size * 100)), b="1" if bold else "0")
    scheme_fill(d, color)
    sub(d, "a:latin", typeface=font)
    txBody.replace(old, lst) if old is not None else txBody.insert(1, lst)


def layout_textbox(prs, layout, x, y, w, h, text, size, color, align, field=None):
    """Put a fixed text box on a layout (the footer, the slide number)."""
    tmp = prs.slides.add_slide(layout)
    tb = tmp.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    if field:
        r = E("a:fld", id=stable_id("field/" + field), type=field)
        rPr = sub(r, "a:rPr", lang="en-US", sz=str(size * 100))
        scheme_fill(rPr, color)
        t = sub(r, "a:t")
        t.text = "‹#›"
        p._p.append(r)
    else:
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.color.theme_color = color
    el = copy.deepcopy(tb._element)
    ids = [int(x) for x in layout._element.xpath(".//p:cNvPr/@id")]
    el.find(".//" + qn("p:cNvPr")).set("id", str(max(ids + [1]) + 1))
    layout.shapes._spTree.append(el)
    # drop the scratch slide
    sldIdLst = prs.slides._sldIdLst
    sid = sldIdLst[-1]
    prs.part.drop_rel(sid.rId)
    sldIdLst.remove(sid)


def setup_layouts(prs):
    master = prs.slide_master
    # master title style
    titleStyle = master._element.find(qn("p:txStyles")).find(qn("p:titleStyle"))
    lvl = titleStyle.find(qn("a:lvl1pPr"))
    d = lvl.find(qn("a:defRPr"))
    d.set("sz", "3400")
    d.set("b", "1")
    for c in list(d):
        if etree.QName(c).localname == "solidFill":
            d.remove(c)
    sf = E("a:solidFill")
    sub(sf, "a:schemeClr", val="tx2")
    d.insert(0, sf)

    layouts = {l.name: l for l in prs.slide_layouts}
    keep = {"Title Slide": "Title", "Section Header": "Section", "Title Only": "Content"}
    for name, l in list(layouts.items()):
        if name not in keep:
            prs.slide_layouts.remove(l)
    out = {}
    for name, l in layouts.items():
        if name in keep:
            l._element.find(qn("p:cSld")).set("name", keep[name])
            out[keep[name]] = l
    # drop date/footer/slide-number placeholders from the kept layouts
    for l in out.values():
        for ph in list(l.placeholders):
            if ph.placeholder_format.type is not None and ph.placeholder_format.idx in (10, 11, 12):
                ph._element.getparent().remove(ph._element)

    # Title (dark)
    t = out["Title"]
    set_bg(t, "tx2")
    for ph in t.placeholders:
        if ph.placeholder_format.idx == 0:
            place(ph, MX + 0.2, 1.75, 6.6, 1.9)
            ph_style(ph, 46, "bg1", anchor="b")
        elif ph.placeholder_format.idx == 1:
            place(ph, MX + 0.2, 3.85, 6.4, 1.1)
            ph_style(ph, 22, "accent6", bold=False, anchor="t", font="+mn-lt")
    # Section (dark)
    s = out["Section"]
    set_bg(s, "tx2")
    for ph in s.placeholders:
        if ph.placeholder_format.idx == 0:
            place(ph, MX + 0.2, 2.35, 7.6, 1.5)
            ph_style(ph, 40, "bg1", anchor="b")
        elif ph.placeholder_format.idx == 1:
            place(ph, MX + 0.2, 4.05, 7.2, 1.6)
            ph_style(ph, 18, "bg2", bold=False, anchor="t", font="+mn-lt")
    # Content (light)
    c = out["Content"]
    set_bg(c, "bg1")
    for ph in c.placeholders:
        if ph.placeholder_format.idx == 0:
            place(ph, MX, 0.62, CW, 0.75)
            ph_style(ph, 34, "tx2", anchor="ctr")
    layout_textbox(prs, c, MX, 7.03, 6, 0.25, "Enhanced ngspice + openvaf-r", 10, TC.ACCENT_3, PP_ALIGN.LEFT)
    layout_textbox(prs, c, W - MX - 1.0, 7.03, 1.0, 0.25, None, 10, "accent3", PP_ALIGN.RIGHT, field="slidenum")
    return out


# ------------------------------------------------------------- helpers
def est_lines(text, w_in, size, bold=False, mono=False):
    cw = size * (0.0083 if mono else (0.0074 if bold else 0.0068))
    per = max(1, int(w_in / cw))
    n = 0
    for para in text.split("\n"):
        n += max(1, math.ceil(len(para) / per))
    return n


def check_fit(tag, text, w_in, h_in, size, bold=False, mono=False, spacing=1.2):
    need = est_lines(text, w_in, size, bold, mono) * size * spacing / 72
    if need > h_in + 0.02:
        warnings.append("%s: %.2f in needed, %.2f in given: %r" % (tag, need, h_in, text[:60]))


def color(font, tcol, bright=0.0):
    font.color.theme_color = tcol
    if bright:
        font.color.brightness = bright


def text(slide, x, y, w, h, paras, size=14, tcol=TC.TEXT_1, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, bright=0.0, italic=False, mono=False, bullets=False,
         space_after=0, name=None, check=True, line=None, head=False):
    """paras: a string (\\n separates paragraphs) or a list of paragraphs, each a
    string or a list of runs (text, dict(bold, color, bright, mono, size, italic, link))."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(paras, str):
        paras = paras.split("\n")
    flat = []
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if space_after:
            p.space_after = Pt(space_after)
        if line:
            p.line_spacing = line
        runs = [(para, {})] if isinstance(para, str) else para
        flat.append("".join(r[0] for r in runs))
        for t, o in runs:
            r = p.add_run()
            r.text = t
            f = r.font
            f.size = Pt(o.get("size", size))
            f.bold = o.get("bold", bold)
            f.italic = o.get("italic", italic)
            color(f, o.get("color", tcol), o.get("bright", bright))
            if o.get("mono", mono):
                f.name = "Courier New"
            elif head:
                f.name = "+mj-lt"
            if o.get("link"):
                r.hyperlink.address = o["link"]
        if bullets:
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(Inches(0.22)))
            pPr.set("indent", str(-Inches(0.22)))
            bc = sub(pPr, "a:buClr")
            sub(bc, "a:schemeClr", val="accent3")
            sub(pPr, "a:buFont", typeface="Arial")
            sub(pPr, "a:buChar", char="•")
    if check:
        extra = (space_after / 72.0) * (len(flat) - 1)
        check_fit(name or flat[0][:30], "\n".join(flat), w - (0.22 if bullets else 0),
                  h - extra, size, bold, mono, spacing=(line or 1.2) if line else 1.2)
    return tb


def rect(slide, x, y, w, h, tcol=TC.BACKGROUND_2, bright=0.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
         radius=0.06, line=None, name=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        s.name = name
    s.shadow.inherit = False
    if tcol is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.theme_color = tcol
        if bright:
            s.fill.fore_color.brightness = bright
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.theme_color = line[0]
        if len(line) > 2:
            s.line.color.brightness = line[2]
        s.line.width = Pt(line[1])
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.text_frame.text = ""
    return s


def shape_text(s, t, size=14, tcol=TC.BACKGROUND_1, bold=True, align=PP_ALIGN.CENTER, mono=False,
               bright=0.0, anchor=MSO_ANCHOR.MIDDLE, margin=0.05):
    tf = s.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = anchor
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        color(r.font, tcol, bright)
        if mono:
            r.font.name = "Courier New"


def chips(slide, x, y, nums, acc, h=0.26, gap=0.06, right=None):
    """E-number chips, each a link to its write-up. Returns the width used."""
    widths = [0.5 + 0.075 * len(str(n)) for n in nums]
    total = sum(widths) + gap * (len(nums) - 1) if nums else 0
    cx = (right - total) if right is not None else x
    for n, wd in zip(nums, widths):
        s = rect(slide, cx, y, wd, h, acc, 0.82, radius=0.5, name="Chip E-%d" % n)
        shape_text(s, "E-%d" % n, size=10, tcol=acc, bright=-0.35, margin=0.02)
        s.click_action.hyperlink.address = WRITEUP % n
        cx += wd + gap
    return total


def card(slide, x, y, w, h, title, body, nums=(), acc=TC.ACCENT_1, size=14, tsize=15, fill_bright=0.0):
    rect(slide, x, y, w, h, TC.BACKGROUND_2, fill_bright, name="Card " + title)
    check_fit("card title " + title, title, w - 0.36, 0.3, tsize, bold=True)
    text(slide, x + 0.18, y + 0.13, w - 0.36, 0.32, title, size=tsize, bold=True, tcol=TC.TEXT_2,
         anchor=MSO_ANCHOR.MIDDLE, name="Card title " + title, check=False)
    text(slide, x + 0.18, y + 0.5, w - 0.36, h - 0.5 - (0.42 if nums else 0.1), body, size=size,
         tcol=TC.TEXT_1, name="Card body " + title)
    if nums:
        chips(slide, x + 0.18, y + h - 0.36, list(nums), acc, h=0.24)


def grid(slide, x, y, w, h, cols, rows, items, acc, gap=0.2, size=14):
    cwid = (w - gap * (cols - 1)) / cols
    chgt = (h - gap * (rows - 1)) / rows
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        card(slide, x + c * (cwid + gap), y + r * (chgt + gap), cwid, chgt, it[0], it[1],
             it[2] if len(it) > 2 else (), acc, size=size)


def picture(slide, path, x, y, w=None, h=None, caption=None, cap_h=0.5, frame=True):
    full = os.path.join(REPO, path)
    iw, ih = Image.open(full).size
    cx, cw_ = x, w
    if w is not None and h is not None:
        s = min(w / iw, h / ih)
        pw, phh = iw * s, ih * s
        x += (w - pw) / 2
    elif w is not None:
        pw, phh = w, w * ih / iw
    else:
        pw, phh = h * iw / ih, h
    pic = slide.shapes.add_picture(full, Inches(x), Inches(y), Inches(pw), Inches(phh))
    pic.name = "Plot " + os.path.basename(path)
    if frame:
        pic.line.color.theme_color = TC.BACKGROUND_2
        pic.line.color.brightness = -0.1
        pic.line.width = Pt(0.75)
    if caption:
        text(slide, cx, y + phh + 0.1, cw_ if cw_ else pw, cap_h, caption, size=11, tcol=TC.ACCENT_3, italic=True,
             name="Caption " + os.path.basename(path))
    return pw, phh


def code(slide, x, y, w, h, src, size=12, title=None):
    rect(slide, x, y, w, h, TC.TEXT_2, radius=0.04, name="Code panel")
    yy = y + 0.18
    if title:
        text(slide, x + 0.25, yy, w - 0.5, 0.3, title, size=12, bold=True, tcol=TC.ACCENT_6,
             name="Code title", check=False)
        yy += 0.4
    text(slide, x + 0.25, yy, w - 0.5, h - (yy - y) - 0.15, src, size=size, tcol=TC.BACKGROUND_1,
         mono=True, name="Code", line=1.0)


def kicker(slide, t, acc):
    tb = text(slide, MX, 0.3, CW, 0.3, t.upper(), size=11, bold=True, tcol=acc, bright=-0.25,
              name="Kicker", check=False)
    for r in tb.text_frame.paragraphs[0].runs:
        r.font._rPr.set("spc", "120")


def new(prs, L, layout, title, section, notes, kick=None, acc=TC.ACCENT_1):
    s = prs.slides.add_slide(L[layout])
    s.shapes.title.text = title
    SECTIONS.setdefault(section, []).append(s)
    if kick:
        kicker(s, kick, acc)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


SECTIONS = {}
SECTION_ORDER = []


def section(name):
    SECTION_ORDER.append(name)
    return name


def write_sections(prs):
    p14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
    pres = prs.part._element
    extLst = pres.find(qn("p:extLst"))
    if extLst is None:
        extLst = sub(pres, "p:extLst")
    ext = sub(extLst, "p:ext", uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}")
    lst = etree.SubElement(ext, "{%s}sectionLst" % p14, nsmap={"p14": p14})
    for name in SECTION_ORDER:
        sec = etree.SubElement(lst, "{%s}section" % p14)
        sec.set("name", name)
        sec.set("id", stable_id("section/" + name))
        ids = etree.SubElement(sec, "{%s}sldIdLst" % p14)
        for s in SECTIONS.get(name, []):
            etree.SubElement(ids, "{%s}sldId" % p14).set("id", str(s.slide_id))


def arrow(slide, x, y, w=0.3, h=0.3, tcol=TC.ACCENT_3, bright=0.35):
    s = rect(slide, x, y, w, h, tcol, bright, shape=MSO_SHAPE.RIGHT_ARROW, name="Arrow")
    return s


def stat(slide, x, y, w, h, big, label, acc, big_size=48, dark=False, label_size=14):
    rect(slide, x, y, w, h, TC.TEXT_2 if dark else TC.BACKGROUND_2, 0.12 if dark else 0.0,
         name="Stat " + big)
    text(slide, x + 0.25, y + 0.2, w - 0.5, 0.95, big, size=big_size, bold=True, tcol=acc,
         bright=(0 if dark else -0.15), name="Stat number " + big, check=False, head=True)
    text(slide, x + 0.25, y + 0.2 + big_size / 72 * 1.25, w - 0.5, h - 0.4 - big_size / 72 * 1.25,
         label, size=label_size, tcol=TC.BACKGROUND_1 if dark else TC.TEXT_1, name="Stat label " + big)


def table(slide, x, y, w, colw, rows, header_fill=TC.TEXT_2, size=13, row_h=0.36, head_size=13,
          col_colors=None, name="Table"):
    nr, nc = len(rows), len(rows[0])
    gf = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(row_h * nr))
    gf.name = name
    tbl = gf.table
    tbl.first_row = True
    tbl.horz_banding = False
    for j, cw in enumerate(colw):
        tbl.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        tbl.rows[i].height = Inches(row_h)
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = Inches(0.1)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if i == 0:
                cell.fill.fore_color.theme_color = header_fill
            else:
                cell.fill.fore_color.theme_color = TC.BACKGROUND_2 if i % 2 == 0 else TC.BACKGROUND_1
            tf = cell.text_frame
            tf.word_wrap = True
            runs = val if isinstance(val, list) else [(val, {})]
            p = tf.paragraphs[0]
            for t, o in runs:
                r = p.add_run()
                r.text = t
                r.font.size = Pt(o.get("size", head_size if i == 0 else size))
                r.font.bold = o.get("bold", i == 0)
                if i == 0:
                    color(r.font, TC.BACKGROUND_1)
                else:
                    color(r.font, o.get("color", TC.TEXT_1), o.get("bright", 0))
                if o.get("mono"):
                    r.font.name = "Courier New"
            if i > 0:
                check_fit("%s r%d c%d" % (name, i, j), "".join(t for t, _ in runs), colw[j] - 0.2,
                          row_h - 0.06, size, any(o.get("bold") for _, o in runs))
    return tbl


# ---------------------------------------------------------------- deck
def build(out):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    apply_theme(prs)
    L = setup_layouts(prs)
    prs.core_properties.title = "Enhanced ngspice + openvaf-r: features"
    prs.core_properties.author = "Meisam Bahadori"
    prs.core_properties.subject = "Every feature of the enhanced ngspice-46 and openvaf-r toolchain"
    T1, T2, T4 = TC.ACCENT_1, TC.ACCENT_2, TC.ACCENT_4

    # ===================================================== Introduction
    sec = section("Introduction")
    s = new(prs, L, "Title", "Enhanced ngspice + openvaf-r", sec,
            "A tour of every feature of the toolchain: the openvaf-r Verilog-A compiler and the "
            "ngspice-46 simulator, as extended by %d enhancements. Each feature slide carries " % F["latest"] +
            "E-number chips; clicking a chip opens that enhancement's write-up on GitHub.")
    s.placeholders[1].text = "A Verilog-A compiler and a circuit simulator, extended as a pair"
    text(s, MX + 0.2, 5.35, 6.4, 0.8,
         [[("Every feature of %d enhancements · %s" % (F["latest"], F["month"]), {})],
          [("Dr. Meisam Bahadori", {"bold": True})]],
         size=16, tcol=TC.BACKGROUND_2, space_after=4, name="Byline")
    pw, ph = picture(s, "examples/eye_examples/eye_diagram.png", 7.55, 1.55, w=5.2, frame=False)
    text(s, 7.55, 1.55 + ph + 0.12, 5.2, 0.5,
         "A 2 Gb/s PRBS through an RC channel, drawn by ngspice's eye command (examples/eye_examples)",
         size=11, tcol=TC.BACKGROUND_2, italic=True, name="Title caption")

    # --- the toolchain
    s = new(prs, L, "Content", "Two tools that work as one", sec,
            "openvaf-r compiles a Verilog-A file into an OSDI shared object whose residuals and "
            "Jacobians come from automatic differentiation. ngspice loads the object at run time "
            "with pre_osdi and simulates its instances, N devices, beside its built-in devices in "
            "every analysis. The two are a pair: this ngspice reads only openvaf-r objects (OSDI 0.7), "
            "and stock ngspice rejects them.",
            kick="The toolchain", acc=TC.ACCENT_3)
    steps = [("model.va", "Verilog-A source: the analog subset of Verilog-AMS (LRM 2023, Annex C)", None),
             ("openvaf-r", "parse, HIR, MIR, automatic differentiation, LLVM", T1),
             ("model.osdi", "a shared object with analytic Jacobians, OSDI 0.7", None),
             ("ngspice-46", "pre_osdi loads it; N devices sit beside built-in ones", T2),
             ("results", "vectors, .meas, plots, Touchstone and raw files", None)]
    bw, gap = 2.1, (CW - 5 * 2.1) / 4
    for i, (t, d, acc) in enumerate(steps):
        x = MX + i * (bw + gap)
        rect(s, x, 1.75, bw, 2.3, acc if acc else TC.BACKGROUND_2, -0.25 if acc else 0.0, name="Step " + t)
        text(s, x + 0.18, 1.95, bw - 0.36, 0.45, t, size=20, bold=True,
             tcol=TC.BACKGROUND_1 if acc else TC.TEXT_2, mono=(i in (0, 2)), name="Step title " + t,
             check=False)
        text(s, x + 0.18, 2.5, bw - 0.36, 1.45, d, size=14,
             tcol=TC.BACKGROUND_1 if acc else TC.TEXT_1, name="Step text " + t)
        if i < 4:
            arrow(s, x + bw + (gap - 0.28) / 2, 2.76, 0.28, 0.28)
    cards = [("Use them as a pair",
              "A .osdi from this compiler needs this ngspice: stock ngspice rejects OSDI 0.7, and "
              "original OpenVAF 0.3 objects get a recompile message.", ()),
             ("Built on",
              "OpenVAF by Pascal Kuthe, OpenVAF-Reloaded by Árpád Bűrmen, and ngspice-46. "
              "The combined work is GPL-3.0.", ()),
             ("The goals",
              "Make ngspice the most capable open SPICE simulator, and openvaf-r the most complete "
              "Verilog-A compiler.", ())]
    grid(s, MX, 4.45, CW, 1.95, 3, 1, cards, TC.ACCENT_3, gap=0.3, size=16)

    # --- numbers
    s = new(prs, L, "Content", "The project by the numbers", sec,
            "%d is the latest enhancement number; %d write-ups exist because a few enhancements "
            "were written up together. The regression sweep has %d verify suites, %s at E-%d. "
            "VA_TEST holds %d .va files, of which %d are standalone models; %s."
            % (F["latest"], F["writeups"], F["sweep_total"], sweep_text(), F["sweep_at"], F["va_files"],
               F["va_standalone"], "all compile" if F["va_ok"] == F["va_standalone"]
               else "%d of them compile" % F["va_ok"]),
            kick="At a glance", acc=TC.ACCENT_3)
    stats = [(str(F["latest"]), "enhancements numbered, with %d detailed write-ups" % F["writeups"], T1),
             (str(len(F["areas"])), "feature areas in the live, searchable catalog", T2),
             (str(F["sweep_total"]), "verify suites in the regression sweep, " + sweep_text(), T4),
             (str(F["va_ok"]), "standalone industry compact models compile: BSIM, PSP, HiCUM, MEXTRAM, EKV…", T1),
             ("5", "platforms built by CI: Linux x86-64 and ARM64, macOS Apple Silicon and Intel, Windows", T2),
             (str(F["hunts"]), "bug-hunt and correctness-campaign pages: what was probed, found and fixed", T4)]
    sw, sh, g = (CW - 2 * 0.3) / 3, 2.4, 0.3
    for i, (b, l, acc) in enumerate(stats):
        r, c = divmod(i, 3)
        stat(s, MX + c * (sw + g), TOP + 0.1 + r * (sh + g), sw, sh, b, l, acc, big_size=54)

    # --- where the work went (chart)
    s = new(prs, L, "Content", "Where the work went", sec,
            "Enhancements per feature area, from the live catalog (docs/index.html). Teal bars are "
            "compiler areas, orange bars simulator areas. An enhancement can sit in two areas, so the "
            "bars sum to %d for %d write-ups. Compiler correctness and robustness is the largest " % (F["area_sum"], F["writeups"]) +
            "area by far: crash and hang fixes, wrong-answer fixes, corpus and LRM sweeps.",
            kick="Enhancements per feature area", acc=TC.ACCENT_3)
    short = {"RF / periodic steady-state suite": "RF / periodic steady state",
             "Optimization & parametric sweeps": "Optimization & sweeps"}
    areas = [(short.get(n, n), c, 1 if d == "compiler" else 2)
             for n, c, d in sorted(F["areas"], key=lambda a: -a[1])]
    cd = CategoryChartData()
    cd.categories = [a[0] for a in areas]
    cd.add_series("Enhancements", [a[1] for a in areas])
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(MX), Inches(TOP), Inches(8.6),
                            Inches(BOT - TOP), cd)
    gf.name = "Chart enhancements per area"
    ch = gf.chart
    ch.has_legend = False
    ch.has_title = False
    ch.font.size = Pt(11)
    ch.font.name = "+mn-lt"
    ch.font.color.theme_color = TC.TEXT_1
    plot = ch.plots[0]
    plot.gap_width = 45
    plot.vary_by_categories = False
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size = Pt(11)
    dl.font.bold = True
    dl.font.color.theme_color = TC.TEXT_1
    ser = plot.series[0]
    for i, a in enumerate(areas):
        pt = ser.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.theme_color = T1 if a[2] == 1 else T2
    ca = ch.category_axis
    ca.reverse_order = True
    ca.tick_labels.font.size = Pt(11)
    ca.format.line.color.theme_color = TC.BACKGROUND_2
    ca.has_major_gridlines = False
    va = ch.value_axis
    va.visible = False
    va.has_major_gridlines = False
    va.maximum_scale = math.ceil(max(a[1] for a in areas) * 1.13 / 10) * 10
    stat(s, 9.55, TOP, 3.18, 2.45, str(F["comp"]), "enhancements in the %s compiler areas" % word(F["n_comp"]),
         T1, big_size=48)
    stat(s, 9.55, TOP + 2.75, 3.18, 2.45, str(F["sim"]), "enhancements in the %s simulator areas" % word(F["n_sim"]),
         T2, big_size=48)

    # --- agenda
    s = new(prs, L, "Content", "Four parts", sec,
            "Part 1 covers the compiler area by area, Part 2 the simulator, Part 3 how every feature "
            "is verified, and Part 4 how to start, what is out of scope and where to read more.",
            kick="Agenda", acc=TC.ACCENT_3)
    parts = [("1", "openvaf-r, the compiler", "Language coverage, analog operators, hierarchy, buses and arrays, "
              "tables and noise, system tasks, robustness", T1),
             ("2", "ngspice-46, the simulator", "OSDI devices, analyses, the RF suite, S-parameters, signal integrity, "
              "convergence, KLU, statistics, optimization, reliability, workflow", T2),
             ("3", "Verification", "The verify-suite pipeline, physics validation, campaigns, the timeline, "
              "platforms", T4),
             ("4", "Using it", "Getting started in four steps, scope and known limits, the documentation map",
              TC.ACCENT_3)]
    for i, (n, t, d, acc) in enumerate(parts):
        y = TOP + 0.1 + i * 1.3
        c = rect(s, MX, y, 0.95, 0.95, acc, shape=MSO_SHAPE.OVAL, name="Part number " + n)
        shape_text(c, n, size=30, tcol=TC.BACKGROUND_1, bold=True)
        text(s, MX + 1.3, y + 0.02, 10.5, 0.42, t, size=22, bold=True, tcol=TC.TEXT_2, name="Part " + n,
             check=False)
        text(s, MX + 1.3, y + 0.5, 10.5, 0.5, d, size=15, tcol=TC.TEXT_1, name="Part text " + n)

    # ===================================================== Part 1
    sec = section("Part 1 · openvaf-r")
    s = new(prs, L, "Section", "openvaf-r: the Verilog-A compiler", sec,
            "The compiler targets Annex C of the Verilog-AMS LRM 2023, the analog-only subset. "
            "Because derivatives come from automatic differentiation, a construct only counts as "
            "supported when it produces correct derivatives as well as correct values.")
    s.placeholders[1].text = ("Part 1 · Annex C of the Verilog-AMS LRM 2023, clause by clause. A construct "
                              "counts as supported only when its values and its derivatives are right.")
    stat(s, 9.0, 2.6, 3.7, 2.3, str(F["comp"]), "enhancements across %s compiler feature areas" % word(F["n_comp"]),
         TC.ACCENT_1,
         big_size=60, dark=True, label_size=16)

    # --- language coverage table
    s = new(prs, L, "Content", "Language coverage at a glance", sec,
            "Summary of docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md. Every entry is backed by "
            "a committed verify suite. Extensions beyond Annex C are warned; SPICE primitives cannot be "
            "instantiated from Verilog-A source (instantiate them in the netlist); digital and "
            "mixed-signal constructs are outside Annex C and are rejected with located diagnostics.",
            kick="LRM 2023 compliance", acc=T1)
    G = {"color": TC.ACCENT_4, "bright": -0.25, "bold": True}
    Y = {"color": TC.ACCENT_2, "bright": -0.3, "bold": True}
    R = {"color": TC.ACCENT_5, "bold": True}
    M = {"color": TC.ACCENT_3, "bold": True}
    rows = [["LRM clause", "Status", "What it covers"],
            ["2 · Lexical conventions", [("Full", G)], "escaped identifiers, based literals, SI suffixes, attributes"],
            ["3 · Data types and parameters", [("Full", G)], "ranges, localparam, aliasparam, arrays, paramsets, block scope"],
            ["3.5–3.13 · Natures, disciplines, nets", [("Full", G)], "buses, implicit nets, nodesets, derived natures"],
            ["4.1–4.4 · Operators and functions", [("Full", G)], "Table 4-2 precedence, string relations, $clog2, ln1p, expm1"],
            ["4.5 · Analog operators", [("Full", G)], "every operator, audited clause by clause (E-514)"],
            ["4.6 · Noise", [("Full", G)], "white, flicker, noise_table(_log), correlation per call site"],
            ["5 · Analog behaviour", [("Full", G)], "analog blocks, contributions, events, loops, analog functions"],
            ["6 · Hierarchy", [("Full", G)], "instantiation, generate, defparam, paramsets, $mfactor"],
            ["9 · System tasks", [("Full", G)], "display, file and string I/O, random, simulation control"],
            ["10 · Compiler directives", [("Full", G)], "`include, `define, `__FILE__, `__LINE__, `begin_keywords"],
            ["casex, casez, <<<, >>>", [("Extension", Y)], "beyond Annex C, accepted and warned"],
            ["Annex E · SPICE primitives", [("Refused", M)], "a clean error: instantiate SPICE devices in the netlist"],
            ["Digital and mixed signal", [("Out of scope", R)], "outside Annex C; rejected with located diagnostics"]]
    table(s, MX, TOP, CW, [4.3, 1.6, 6.23], rows, size=13, row_h=0.37, name="Coverage table")

    # --- analog operators
    s = new(prs, L, "Content", "Analog operators and dynamics", sec,
            "The continuous-time operators of LRM 4.5 and the events of LRM 5.10. absdelay is solved "
            "as a synthetic-node DAE. transition and slew are the simulator's own ramps, scheduled from "
            "accepted changes of the input. A cross or above event now lands the time step on the "
            "interpolated crossing instead of the step grid (E-759).",
            kick=kc("Compiler", "Analog operators & dynamics"), acc=T1)
    items = [("Delays & filters", "absdelay as a synthetic-node DAE; laplace_* and zi_* in every form, "
              "complex poles and zeros", (1, 4, 31)),
             ("Integrators", "idt with initial conditions and assert/reset forms, idtmod, ddt, ddx; "
              "summed ddt terms all count", (28, 52)),
             ("Ramps & limiters", "transition and slew per LRM 4.5.8–4.5.9: rise time, breakpoints, "
              "the interruption rule; $limit", (698, 61)),
             ("Events", "cross, above, timer, last_crossing; the time step lands on the crossing, "
              "not the step grid", (8, 759)),
             ("Step events", "@(initial_step), @(final_step) with phase lists; once per sens run, "
              "state carried across .dc", (53, 789)),
             ("Step control", "$discontinuity restarts the integration or rejects the step; "
              "$bound_step, smallest wins", (24, 55))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T1)
    picture(s, "examples/bessel_filter_examples/ac_compare.png", 8.45, TOP, w=4.28, h=4.3,
            caption="A 5th-order Bessel low-pass built with laplace_* matches scipy over six decades "
                    "(examples/bessel_filter_examples)")

    # --- hierarchy
    s = new(prs, L, "Content", "Modules, parameters and hierarchy", sec,
            "Hierarchy is resolved by a compile-time elaboration pass, after which the pipeline sees "
            "one flat module. Structure binds at compile time (generate, genvars, defparam, paramsets, "
            "bus widths); behaviour binds at simulation time. A paramset's own parameters are instance "
            "parameters, and an overloaded family is selected per instance (E-644).",
            kick=kc("Compiler", "Modules, parameters & hierarchy"), acc=T1)
    items = [("Instantiation", "Hierarchy flattened at compile time; a child's unnamed branches stay "
              "the child's own", (5, 757)),
             ("generate", "for, if and case generate with genvars, legacy and bare blocks; genvar "
              "loops in analog blocks", (67, 407)),
             ("Parameters", "Ranges, localparam, aliasparam, defparam, block-scoped and array "
              "parameters, freeze", (58, 87)),
             ("paramset", "Overloaded families picked per instance from the card's and the "
              "instance's values", (21, 644)),
             ("Natures", "Derived natures, nature attributes, domain-binding checks per "
              "LRM 3.6.2.2", (39, 50)),
             ("Libraries & state", "Several modules in one .osdi; persistent variables; several "
              "analog blocks", (76, 60))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T1)
    picture(s, "examples/opamp741_examples/plots/opamp741.png", 8.45, TOP, w=4.28,
            caption="A transistor-level µA741 built from a Verilog-A BJT: follower, open-loop AC "
                    "and slew limiting (examples/opamp741_examples)", cap_h=0.7)
    rect(s, 8.45, TOP + 3.8, 4.28, BOT - TOP - 3.8, TC.TEXT_2, radius=0.06, name="Binding panel")
    text(s, 8.7, TOP + 3.93, 3.78, BOT - TOP - 4.03,
         [[("Structure binds at compile time: ", {"bold": True, "color": TC.ACCENT_6}),
           ("hierarchy, generate, defparam, paramsets, bus widths. ", {}),
           ("Behaviour binds at run time: ", {"bold": True, "color": TC.ACCENT_6}),
           ("loop counts and if arms may follow the parameters.", {})]],
         size=14, tcol=TC.BACKGROUND_1, name="Binding text")

    # --- nets & arrays
    s = new(prs, L, "Content", "Buses, branches, ports and arrays", sec,
            "Topology beyond scalar electrical nodes, and arrays everywhere a value can go. The code "
            "on the right is checked: compiled with the committed openvaf-r and run in ngspice, it "
            "draws 1, 2, 4 and 8 mA from four 1 V sources. A genvar loop inside an analog block is "
            "unrolled at elaboration (E-407), which is how the LRM writes 'contribute to every bit'.",
            kick=kc("Compiler", "Branches, nets & ports", "Arrays"), acc=T1)
    items = [("Buses", "Vectored nets and ports, bit-selects and ranges a[0:1]; v(a[0]) in "
              "print and plot", (3, 221)),
             ("Implicit nets", "An undeclared net takes the discipline of the port it "
              "connects", (41, 340)),
             ("Flow probes", "I(<port>), probe-only branches as ideal ammeters, hierarchical "
              "branch probes", (29, 36)),
             ("Indirect assignment", "V(out) : V(x) == 0 writes an ideal op-amp; placement rules "
              "enforced", (2,)),
             ("Array values", "Literals, aggregates and dynamic indexing; N-D arrays with "
              "per-element overrides", (14, 15)),
             ("Arrays in functions", "Array arguments in, out and inout; arrays returned from "
              "analog functions", (20, 23))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T1)
    code(s, 8.45, TOP, 4.28, BOT - TOP,
         "`include \"disciplines.vams\"\n"
         "module bank(a, b);\n"
         "  inout [0:3] a;\n"
         "  electrical [0:3] a;\n"
         "  inout b; electrical b;\n"
         "  parameter real g = 1m\n"
         "    from (0:inf);\n"
         "  genvar i;\n"
         "  analog begin\n"
         "    for (i = 0; i < 4; i = i + 1)\n"
         "      I(a[i], b) <+\n"
         "        g * (1 << i) * V(a[i], b);\n"
         "  end\n"
         "endmodule\n\n"
         "// ngspice op, 1 V on each bit:\n"
         "// 1, 2, 4, 8 mA",
         size=12, title="A 4-bit bus and one genvar loop")

    # --- tables & noise
    s = new(prs, L, "Content", "Lookup tables and noise models", sec,
            "$table_model is lowered to differentiable MIR, so its Jacobian is exact rather than "
            "finite-differenced; it works in any number of dimensions with linear or cubic-spline "
            "interpolation. On the noise side, same-named sources are correlated and sum coherently, "
            "and since E-364 a device's white and flicker noise also enters a transient.",
            kick=kc("Compiler", "Lookup tables", "Noise modeling (Verilog-A)"), acc=T1)
    colw = (CW - 0.4) / 2
    for i, (head, nums, bl, img, cap, py, phh) in enumerate([
            ("Lookup tables", (16, 17, 22, 40),
             ["$table_model in any number of dimensions: linear, cubic spline, isoline files",
              "Lowered to differentiable MIR: an exact Jacobian, no finite differences",
              "Data inline, from arrays or from files; extrapolation per dimension"],
             "examples/mdtable_examples/mdtable_iv.png",
             "A bilinear 2-D I(Vgs, Vds) table as a transistor (examples/mdtable_examples)", 2.3, 2.3),
            ("Noise models", (9, 42, 54, 364),
             ["white_noise, flicker_noise, noise_table and noise_table_log",
              "Same-named sources correlate and sum coherently; op-dependent factors",
              "Node-free noise factors (OSDI 0.7); device noise also in .tran"],
             "examples/noise_examples/noise_spectra.png",
             "Each noise source against its analytic spectrum (examples/noise_examples)", 2.0, 2.6)]):
        x = MX + i * (colw + 0.4)
        rect(s, x, TOP, colw, BOT - TOP, TC.BACKGROUND_2, name="Column " + head)
        text(s, x + 0.25, TOP + 0.18, 2.6, 0.35, head, size=18, bold=True, tcol=TC.TEXT_2,
             name="Column title " + head, check=False)
        chips(s, 0, TOP + 0.22, list(nums), T1, right=x + colw - 0.25)
        text(s, x + 0.25, TOP + 0.7, colw - 0.5, 1.6, bl, size=14, bullets=True, space_after=4,
             name="Column bullets " + head)
        picture(s, img, x + 0.25, TOP + py, w=colw - 0.5, h=phh, caption=cap, cap_h=0.45)

    # --- system tasks
    s = new(prs, L, "Content", "System tasks and functions", sec,
            "LRM chapter 9. Random draws are reproducible per instance and stable across Newton "
            "iterations. Display and severity tasks defer to the accepted iteration (LRM 9.4.6, "
            "9.7.3), so a message prints once per accepted point rather than once per Newton step. "
            "$dist_* returns integers and $rdist_* reals, as the LRM says (E-376).",
            kick=kc("Compiler", "System tasks & functions"), acc=T1)
    items = [("$random", "Random", "$random, every $dist_* and $rdist_*; reproducible per instance", (10, 376)),
             ("$fopen", "File I/O", "$fopen, $fwrite, $fscanf, $fgetc, $ungetc, append mode", (11, 107)),
             ("$sscanf", "Strings", "$sformat and $sscanf in every base; string compare and returns", (105, 106)),
             ("$display", "Display", "$display, $strobe, $monitor, $write: the full format surface", (71,)),
             ("$fatal", "Simulation control", "$finish, $stop, $fatal and $error at the accepted iteration", (55, 378)),
             ("$simparam", "Environment", "$simparam, $simparam$str, analysis(), $temperature, $vt", (25, 30)),
             ("$test$plusargs", "Plusargs", "$test$plusargs and $value$plusargs read the simulator's arguments", (215,)),
             ("$clog2", "Math", "$clog2, $rtoi, $itor, ln1p, expm1; hypot and atan2 derivatives fixed", (101, 185))]
    cwid, chgt, g = (CW - 3 * 0.25) / 4, (BOT - TOP - 0.25) / 2, 0.25
    for i, (tok, t, d, nums) in enumerate(items):
        r, c = divmod(i, 4)
        x, y = MX + c * (cwid + g), TOP + r * (chgt + g)
        rect(s, x, y, cwid, chgt, TC.BACKGROUND_2, name="Card " + t)
        tk = rect(s, x + 0.2, y + 0.2, 2.05, 0.42, TC.TEXT_2, radius=0.2, name="Token " + tok)
        shape_text(tk, tok, size=13, tcol=TC.ACCENT_1, bright=0.2, mono=True)
        text(s, x + 0.2, y + 0.8, cwid - 0.4, 0.35, t, size=16, bold=True, tcol=TC.TEXT_2,
             name="Card title " + t, check=False)
        text(s, x + 0.2, y + 1.2, cwid - 0.4, chgt - 1.65, d, size=14, name="Card body " + t)
        chips(s, x + 0.2, y + chgt - 0.42, list(nums), T1)

    # --- operators, control flow, compile time
    s = new(prs, L, "Content", "Operators, control flow and compile time", sec,
            "Operator semantics were audited against the LRM (E-37, E-38). About 70 % of compile "
            "time goes to LLVM optimizing one eval function (docs/internals/openvaf_internals/"
            "OpenVAF_compile_time_analysis.md). Elaboration and expression handling were made "
            "linear where they had been exponential or quadratic.",
            kick=kc("Compiler", "Operators, control flow & preprocessor"), acc=T1)
    items = [("Operators", "Table 4-2 precedence; {…} concatenation, {n{…}} replication; "
              "<<< and >>>", (37, 38, 34)),
             ("Control flow", "do…while, repeat, disable, break, continue, return; casex "
              "and casez", (19, 78)),
             ("Literals & directives", "Escaped identifiers, based integers; `__FILE__`, "
              "`__LINE__`; recursion guard", (46, 85)),
             ("Compile cost", "Nested ?: from O(2^N) to O(N); wide buses and instance arrays "
              "elaborate in linear time", (147, 404)),
             ("Strings", "Escape sequences read in one pass; string relational operators "
              "and string returns", (48, 106)),
             ("Domain errors", "A constant outside a builtin's domain is a compile error naming "
              "the value", (396, 509))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T1)
    picture(s, "examples/benchmark_examples/plots/compile_times.png", 8.45, TOP, w=4.28,
            caption="Flagship compile times, median of 3: BSIM-CMG 3.9 s, MEXTRAM 505 0.37 s. "
                    "About 70 % of the time is LLVM optimizing one eval function.", cap_h=0.9)

    # --- robustness
    s = new(prs, L, "Content", "Correctness and robustness", sec,
            "The largest single area. Evidence: the public VA-Models corpus (%d standalone models) " % F["va_standalone"] +
            "compiles; the 496-file corpus compiles with no assertion failure in an assertions-enabled "
            "build (E-347); the robustness campaign used the production corpus, about 50 adversarial "
            "inputs and 4,000 mutation-fuzzing iterations (E-147, E-148); 2,089 constant-folded "
            "expressions found ln1p and expm1 crashing for every non-literal argument (E-510); every "
            "code example in the LRM 2023 is a compliance case (E-84).",
            kick=kc("Compiler", "Compiler correctness & robustness"), acc=T1)
    rect(s, MX, TOP, 3.5, BOT - TOP, TC.TEXT_2, name="Big stat panel")
    text(s, MX + 0.3, TOP + 0.35, 2.9, 1.2, area("Compiler correctness & robustness"), size=72, bold=True, tcol=T1, name="Big stat",
         check=False, head=True)
    text(s, MX + 0.3, TOP + 1.65, 2.9, 3.4,
         "enhancements in the largest area: crash and hang fixes, wrong-answer fixes, corpus "
         "and LRM sweeps, physics checks, lints that name silent mistakes",
         size=16, tcol=TC.BACKGROUND_1, name="Big stat label")
    ev = [("%d / %d" % (F["va_ok"], F["va_standalone"]), "standalone VA-Models compile: BSIM4/6/CMG/SOI, PSP, HiCUM, MEXTRAM, EKV", (56, 159)),
          ("496", "corpus files compile with no assertion failure in an assertions build", (347,)),
          ("4,000", "mutation-fuzz iterations and ~50 adversarial inputs; crash paths fixed", (147, 148)),
          ("2,089", "constant-folded expressions fuzzed; two library calls fixed", (510,)),
          ("LRM 2023", "every code example in the standard extracted and compiled", (84,)),
          ("Lints", "silent mistakes named: L022 discarded contribution, L031 input-port write", (400, 639))]
    x0, cwid, chgt, g = MX + 3.8, (CW - 3.8 - 0.25 * 2) / 3, (BOT - TOP - 0.25) / 2, 0.25
    for i, (b, l, nums) in enumerate(ev):
        r, c = divmod(i, 3)
        x, y = x0 + c * (cwid + g), TOP + r * (chgt + g)
        rect(s, x, y, cwid, chgt, TC.BACKGROUND_2, name="Evidence " + b)
        text(s, x + 0.22, y + 0.2, cwid - 0.44, 0.65, b, size=30, bold=True, tcol=T1, bright=-0.15,
             name="Evidence number " + b, check=False, head=True)
        text(s, x + 0.22, y + 0.92, cwid - 0.44, chgt - 1.4, l, size=14, name="Evidence text " + b)
        chips(s, x + 0.22, y + chgt - 0.42, list(nums), T1)

    # ===================================================== Part 2
    sec = section("Part 2 · ngspice-46")
    s = new(prs, L, "Section", "ngspice-46: the simulator", sec,
            "The simulator side: compiled Verilog-A devices take part in every analysis, and the "
            "simulator gains a complete RF periodic suite, statistics, optimization, convergence aids, "
            "a KLU solver at parity, post-layout reduction, reliability and workflow tooling.")
    s.placeholders[1].text = ("Part 2 · Compiled Verilog-A devices as first-class citizens, a complete RF "
                              "periodic suite, statistics, optimization and convergence aids.")
    stat(s, 9.0, 2.6, 3.7, 2.3, str(F["sim"]), "enhancements across %s simulator feature areas" % word(F["n_sim"]),
         TC.ACCENT_2,
         big_size=60, dark=True, label_size=16)

    # --- OSDI devices
    s = new(prs, L, "Content", "Compiled devices in ngspice", sec,
            "The deck is the handbook's first example (docs/handbook/01-getting-started.md): "
            "pre_osdi loads the compiled model before the circuit is parsed, instances use the N "
            "letter, and the model card's type is the Verilog-A module name. Variables with a desc "
            "attribute are operating-point variables, readable as @n1[name] wherever ngspice vectors "
            "are.", kick="Simulator · the OSDI device path", acc=T2)
    code(s, MX, TOP, 4.75, BOT - TOP,
         "* divider from a Verilog-A resistor\n"
         "vin in 0 dc 2\n"
         "n1 in mid ra\n"
         "n2 mid 0 rb\n"
         ".model ra myres(r=1k)\n"
         ".model rb myres(r=1k)\n"
         ".control\n"
         "pre_osdi myres.osdi\n"
         "op\n"
         "print v(mid)\n"
         ".endc\n"
         ".end\n\n"
         "$ ngspice -b divider.cir\n"
         "v(mid) = 1.000000e+00",
         size=12, title="divider.cir")
    items = [("Instances & cards", "N devices; the card names the module; (* type=\"instance\" *) "
              "parameters on the line", (644,)),
             ("Multiplicity", "m and $mfactor scale currents, charges and noise; temp and dtemp "
              "reach the model", (336, 755)),
             ("Op-point variables", "print @n1[ids], .save, .meas and show n1 for every "
              "desc variable", (69,)),
             ("Change in session", "alter and altermod; pre_osdi -f reloads a recompiled .osdi "
              "without a restart", (229,)),
             ("Terminal currents", "@n1[i_p] is the device's total current, complex in ac "
              "and sp", (394, 835)),
             ("Exact numbers", "A netlist number is the double its text names, so 1.2 meets "
              "from [0:1.2]", (643,))]
    grid(s, MX + 5.05, TOP, CW - 5.05, BOT - TOP, 2, 3, items, T2)

    # --- analysis coverage table
    s = new(prs, L, "Content", "Every analysis takes compiled devices", sec,
            "The audited status of each analysis with OSDI devices (handbook section 3.4, updated "
            "for later enhancements). Jacobians come from automatic differentiation and are "
            "cross-checked against numeric derivatives on PSP103 in examples/physcheck_examples.",
            kick="Simulator · analysis coverage", acc=T2)
    rows = [["Analysis", "With compiled Verilog-A devices", "Enhancements"],
            ["op, .dc, .ac, .tran", "Full; autodiff Jacobians match numeric derivatives on PSP103 to ~1e-5", "E-57, E-62"],
            [".noise", "All source types, correlated sources, op-dependent and shaped factors", "E-42, E-54"],
            ["Transient noise", "A device's white and flicker noise enters .tran when the deck uses trnoise", "E-364"],
            [".tf, .sens", "Exact; .sens restores models and instances byte for byte", "E-179, E-440"],
            [".pz", "Exact for linear devices, bit-identical to built-in twins; pzeig mode", "E-171, E-173"],
            [".disto", "Taylor tensors from the analytic Jacobian, no variable-count limit", "E-352, E-359"],
            [".sp", "Any port count; noise figure and noise parameters for 2-ports", "E-63, E-202"],
            ["PSS, PAC, Pnoise, PXF, HB, QPSS", "The whole RF suite runs on OSDI devices", "E-117 to E-154"]]
    table(s, MX, TOP, CW, [3.3, 6.73, 2.1], rows, size=14, row_h=0.56, head_size=14, name="Analysis table")

    # --- standard analyses
    s = new(prs, L, "Content", "Standard analyses, extended", sec,
            "A .dc sweep over a device or model parameter refreshes the device per point as alter "
            "would and restores the value afterwards. Since E-534 every sweep knob kind takes "
            "lin, dec and oct scales. .sens leaves the circuit as it found it (E-440, E-685). "
            ".disto for Verilog-A devices differences Taylor tensors from the analytic Jacobian "
            "inside ngspice (E-359).", kick=kc("Simulator", "Standard analyses"), acc=T2)
    items = [("Device sweeps", ".dc over @n1[r], model parameters @mm[g] and wildcards @*[p]; "
              "lin, dec, oct", (62, 534)),
             (".tf and .sens", "Exact against analytic derivatives; the circuit is left as "
              "found", (179, 685)),
             (".pz", "Exact for linear devices; eigenvalue pole-zero pzeig; KLU complex "
              "determinant", (173, 171)),
             (".disto", "Verilog-A distortion via Taylor tensors; proven exact against harmonic "
              "balance", (352, 255)),
             ("stb", "Loop gain with phase and gain margins; .meas ac margins and "
              "batch vdb", (198, 203)),
             ("Measurements", ".meas param and expr in control blocks; avg, integ and rms "
              "windows clipped", (311, 302))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T2)
    picture(s, "examples/analyses_examples/plots/nested_sweep.png", 8.45, TOP, w=4.28,
            caption=".dc over an OSDI instance parameter inside a source sweep "
                    "(examples/analyses_examples)", cap_h=0.45)
    picture(s, "examples/pzeig_examples/pzeig.png", 8.45, TOP + 3.3, w=4.28, h=1.55,
            caption="pzeig: all poles of a 10-section RC ladder, exact (examples/pzeig_examples)", cap_h=0.4)

    # --- RF suite
    s = new(prs, L, "Content", "The RF periodic steady-state suite", sec,
            "PSS by shooting (driven mode avoids the frequency hunt and is about 1000x cheaper on a "
            "pumped varactor, E-176) feeds PAC, Pnoise with cyclostationary folding, PXF and PSP. "
            "Harmonic balance (exact row-form Jacobian since E-902) feeds the two-tone QP set. "
            "Oscillators have hbosc and phase noise; envelope following jumps whole periods with "
            "an implicit monodromy. Each has a dot card: .pss .pac .pnoise .pxf .psp .hb .qpss "
            ".hbosc .phasenoise.", kick=kc("Simulator", "RF / periodic steady-state suite"), acc=T2)
    lanes = [("PSS", "shooting, driven mode", ["PAC", "Pnoise", "PXF", "PSP"], (117, 176)),
             ("HB", "harmonic balance", ["QPSS", "QPAC", "QPnoise", "QPXF"], (134, 902)),
             ("Oscillators", "hbosc, phasenoise", ["Envelope following"], (140, 154))]
    lw = 7.55
    for i, (lead, sub_, outs, nums) in enumerate(lanes):
        y = TOP + i * 1.62
        b = rect(s, MX, y, 1.9, 1.3, T2, -0.25, name="Lane " + lead)
        text(s, MX + 0.15, y + 0.15, 1.6, 0.4, lead, size=18, bold=True, tcol=TC.BACKGROUND_1,
             name="Lane title " + lead, check=False)
        text(s, MX + 0.15, y + 0.58, 1.6, 0.65, sub_, size=13, tcol=TC.BACKGROUND_1,
             name="Lane text " + lead)
        arrow(s, MX + 2.0, y + 0.5, 0.3, 0.3)
        ox, ow = MX + 2.4, lw - 2.4
        bwid = (ow - 0.15 * (len(outs) - 1)) / len(outs)
        for j, o in enumerate(outs):
            ob = rect(s, ox + j * (bwid + 0.15), y, bwid, 0.82, T2, 0.8, name="Out " + o)
            shape_text(ob, o, size=15, tcol=T2, bright=-0.45, bold=True)
        chips(s, ox, y + 0.98, list(nums), T2)
    text(s, MX, TOP + 4.85, lw, 0.45, "Every analysis has a dot card and runs on built-in and OSDI devices.",
         size=14, italic=True, tcol=TC.ACCENT_3, name="RF note")
    picture(s, "examples/envelope_examples/envelope_ringup.png", 8.45, TOP, w=4.28,
            caption="Envelope following: 26 samples reproduce ~3000 carrier periods "
                    "(examples/envelope_examples)", cap_h=0.45)
    picture(s, "examples/pssdriven_examples/pssdriven.png", 8.45, TOP + 2.95, w=4.28,
            caption="Driven-mode PSS: geometric convergence (examples/pssdriven_examples)", cap_h=0.4)

    # --- S-parameters
    s = new(prs, L, "Content", "S-parameters, Touchstone and RF measures", sec,
            "Ports for .sp are voltage sources tagged with portnum and z0. wrsnp writes Touchstone "
            "v1 for any port count. pre_snp vector-fits a Touchstone file into a model, either "
            "compiled through openvaf-r or stamped directly by a native N-port device (E-242) that "
            "removes the compile step at high port counts.", kick="Simulator · RF", acc=T2)
    items = [(".sp", "Any port count; S, Y, Z vectors; NF and noise parameters; an O(N³) "
              "inverse", (63, 202)),
             ("Touchstone I/O", "wrsnp writes ri, ma or db as S, Y or Z; rdsnp reads, noise "
              "rows too", (72, 749)),
             ("pre_snp", "Touchstone to a vector-fitted model: an OSDI device or a native "
              "N-port", (200, 242)),
             ("Stability & load-pull", "rfstab: K, Δ, μ, MSG and MAG; loadpull contours on a "
              "Smith chart", (253, 234)),
             ("Large-signal RF", "P1dB and IP3; LNA noise figure with noise match and the "
              "Friis cascade", (164, 168)),
             ("Smith views", "pyplot -smith draws S-parameters on a Smith chart", (254,))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T2)
    picture(s, "examples/rfpa_examples/rfpa_ip3.png", 8.45, TOP, w=4.28,
            caption="AM-AM compression and two-tone IM3 of a SiGe HBT (examples/rfpa_examples)", cap_h=0.4)
    picture(s, "examples/noisefigure_examples/noisefigure.png", 8.45, TOP + 2.65, w=4.28,
            caption="LNA noise figure: noise match and Friis cascade (examples/noisefigure_examples)",
            cap_h=0.4)

    # --- signal integrity
    s = new(prs, L, "Content", "Signal integrity: PRBS, PAM4 and eyes", sec,
            "PRBS(v1 v2 tbit [td [tr [tf [order [seed]]]]]) on voltage and current sources is a "
            "Fibonacci shift register with the standard maximal-length taps; orders 7, 9, 11, 15, 23 "
            "and 31 are what pattern generators send. PAM4 reads two bits per symbol, Gray coded, "
            "which at orders 13 and 31 is IEEE 802.3's PRBS13Q and PRBS31Q (E-752). eye measures "
            "height, width and RMS jitter (E-207).", kick="Simulator · SerDes", acc=T2)
    code(s, MX, TOP, 6.0, 2.55,
         "Vtx tx 0 PRBS(0 1 1n 0 50p 50p 7)\n"
         "Vp4 tq 0 PAM4(-0.6 0.6 100p 0 10p 10p 13)\n"
         ".control\n"
         "tran 5p 2u\n"
         "eye v(rx) -ui 1n -tstart 3n\n"
         ".endc", size=12, title="A PRBS7, a PRBS13Q and an eye")
    items = [("PRBS and PAM4", "Orders 7, 9, 11, 15, 23 and 31 on V and I sources; PAM4 Gray "
              "coded, PRBS13Q and PRBS31Q; every transition a breakpoint; the stream a pure "
              "function of time", (752,)),
             ("eye and pyplot -eye", "eye measures eye height, eye width and RMS jitter of any "
              "waveform; pyplot -eye draws persistence-shaded eyes", (207, 208))]
    grid(s, MX, TOP + 2.85, 6.0, BOT - TOP - 2.85, 2, 1, items, T2)
    picture(s, "examples/eye_examples/eye_diagram.png", 6.95, TOP, w=5.78,
            caption="A 2 Gb/s PRBS through an RC channel: eye height 565%smV, eye width 461%sps, "
                    "RMS jitter 15.9%sps (examples/eye_examples)" % (NB, NB, NB), cap_h=0.5)

    # --- convergence
    s = new(prs, L, "Content", "Convergence and integration", sec,
            "ngspice's operating point already escalates through gmin and source stepping. "
            ".option convhelp adds the globalized Newton line search (E-111) and pseudo-transient "
            "continuation (E-127) to the ladder, reaches for them without being asked, and reports "
            "which aid produced the point (E-204). Five integration methods were measured against each "
            "other in E-419, and the results that overturned expectations are recorded there.",
            kick=kc("Simulator", "Convergence & integration"), acc=T2)
    ladder = ["Newton", "gmin stepping", "source stepping", "line search", "pseudo-transient"]
    bw, g = (CW - 4 * 0.45) / 5, 0.45
    for i, t in enumerate(ladder):
        x = MX + i * (bw + g)
        b = rect(s, x, TOP + 0.05, bw, 0.95, T2, -0.25 if i >= 3 else 0.6, name="Rung " + t)
        shape_text(b, t, size=16, tcol=TC.BACKGROUND_1 if i >= 3 else T2,
                   bright=0 if i >= 3 else -0.45, bold=True)
        if i < 4:
            arrow(s, x + bw + 0.08, TOP + 0.38, 0.29, 0.29)
    text(s, MX, TOP + 1.15, CW, 0.35,
         [[(".option convhelp", {"bold": True, "mono": True}),
           (" climbs the whole ladder itself and reports which aid found the operating point", {})]],
         size=14, tcol=TC.TEXT_1, name="Ladder note")
    items = [("Accuracy presets", ".option errpreset sets the tolerances together: "
              "conservative, moderate, liberal", (110,)),
             ("Five integrators", "trap and gear 1–6, plus trbdf2, sdirk and adams; "
              "ordfix pins the order", (419, 181)),
             ("Order control", ".option dynorder picks the Gear order from the local "
              "truncation error", (128,)),
             ("Guards", "False convergence on singular B-sources caught; device "
              "convergence tests honoured", (256, 889))]
    grid(s, MX, TOP + 1.75, 7.55, BOT - TOP - 1.75, 2, 2, items, T2)
    picture(s, "examples/corenum_examples/corenum.png", 8.45, TOP + 1.75, w=4.28,
            caption="The integrator certified: accepted points satisfy the exact BDF formula to "
                    "machine precision, and ordfix converges at h^k (examples/corenum_examples)", cap_h=0.9)

    # --- KLU
    s = new(prs, L, "Content", "KLU, at parity with Sparse", sec,
            "Sparse 1.3 stays the default; .option klu selects KLU, which now runs every analysis. "
            "The Sparse-versus-KLU differential campaign (examples/solverdiff_examples) uses numpy as "
            "a third opinion and asserts against eps times each deck's condition number: 37 of 37, "
            "no solver defect. KLU's advantage grows with circuit size.", kick=kc("Simulator", "KLU solver parity & tuning"),
            acc=T2)
    items = [("Every analysis", "KLU runs noise, pole-zero, sensitivity and distortion as "
              "Sparse does", (113, 114, 115)),
             ("Periodic & restart", "PSS under KLU; a checkpoint resumes under the other "
              "solver", (118, 180)),
             ("Tuning", "Ordering, scaling and BTF controls for KLU", (152,)),
             ("Accuracy", "Iterative refinement of real solves; the residual measured per "
              "row", (867, 868)),
             ("Hardening", "Solver glue: null checks, collapse maps and bounds fixed", (232, 233)),
             ("Differential campaign", "37 of 37 against a numpy third opinion and each deck's "
              "condition", ())]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T2)
    picture(s, "examples/solver_stress/plots/speedup.png", 8.45, TOP, w=4.28,
            caption="KLU speedup over Sparse 1.3 against circuit size "
                    "(examples/solver_stress)", cap_h=0.45)
    stat(s, 8.45, TOP + 3.45, 2.04, BOT - TOP - 3.45, "≈70x", "faster than Sparse on large meshes", T2,
         big_size=30)
    stat(s, 10.69, TOP + 3.45, 2.04, BOT - TOP - 3.45, "37/37", "differential checks, no solver defect",
         T2, big_size=30)

    # --- statistics
    s = new(prs, L, "Content", "Statistics, variability and yield", sec,
            "Monte Carlo reaches OSDI parameters through both ngspice idioms. Latin-hypercube "
            "sampling measured about 130x lower estimator variance at the same N (E-149). highsigma "
            "scales the sigmas for importance sampling, reaching 4 to 6 sigma from a few thousand "
            "runs (E-150); wcd finds the worst-case distance and most probable failure point (E-305). "
            "docs/internals/ngspice_internals/ngspice_statistics.md is the complete guide.",
            kick=kc("Simulator", "Statistical / variability / yield"), acc=T2)
    items = [("Monte Carlo on OSDI", "reset loops re-draw .param values into OSDI cards; "
              "warm-started trials", (66, 188)),
             ("Latin hypercube", "mcsample lhs: about 130x lower estimator variance at the "
              "same N", (149,)),
             ("High sigma", "highsigma reaches 4–6σ in a few thousand runs; wcd finds the "
              "worst case", (150, 305)),
             ("Correlations & yield", "mccorr and mvnorm correlations; montecarlo -expr -track "
              "packages yield", (151,)),
             ("Design centring", "optimize -center maximizes yield or Cpk against -spec "
              "limits", (206,)),
             ("Records", ".option savemc and writemc keep every draw and every result", (742,))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T2)
    picture(s, "examples/montecarlo_examples/plots/mc_distributions.png", 8.45, TOP, w=4.28,
            caption="Gaussian and uniform Monte Carlo on an OSDI parameter against the analytic "
                    "density, 500 runs each (examples/montecarlo_examples)", cap_h=0.7)
    picture(s, "examples/savemc_examples/mc_example5/draws_hist.png", 8.45, TOP + 2.75, w=4.28, h=2.0,
            caption="Draws recorded by .option savemc (examples/savemc_examples)", cap_h=0.4)

    # --- statistics in the model
    s = new(prs, L, "Content", "Statistics declared in the model", sec,
            "Attributes on Verilog-A parameters carry the statistics in an OSDI side table. With "
            ".option osdimc (alias automc) every run-class command is a fresh trial: no reset, no "
            "netlist re-expansion, no agauss in the deck; the first run after sourcing is the nominal "
            "baseline. The corner attribute gives each parameter's value per corner. Both decks were "
            "run with the committed binaries: 1.000 mA then 0.945 mA under osdimc, 0.909 mA at "
            "corner ss.", kick="Simulator · from Verilog-A attributes", acc=T2)
    code(s, MX, TOP, 7.1, 2.75,
         "`include \"disciplines.vams\"\n"
         "module rstat(p, n);\n"
         "  inout p, n; electrical p, n;\n"
         "  (* std_rel=0.05 *)             parameter real r  = 1k;\n"
         "  (* dist=\"uniform\", std=2e-4 *) parameter real tc = 1e-3;\n"
         "  (* corner=\"ss=+10%, ff=-10%\" *) parameter real k  = 1.0;\n"
         "  analog I(p, n) <+ V(p, n) /\n"
         "    (k * r * (1 + tc * ($temperature - 300.15)));\n"
         "endmodule", size=12, title="rstat.va")
    code(s, MX, TOP + 3.0, 7.1, BOT - TOP - 3.0,
         ".option osdimc mcseed=7   ; each run a fresh trial\n"
         "op  →  i = 1.000 mA      ; first run: nominal\n"
         "op  →  i = 0.945 mA      ; a trial\n\n"
         ".option corner=ss        ; k = 1.1\n"
         "op  →  i = 0.909 mA", size=12, title="The deck side")
    items = [("No reset loop", "std, std_rel and dist travel in an OSDI side table; "
              "osdimc makes each run a trial", (530,)),
             ("Corners in the source", "A value, a % of nominal or ±kσ per corner; "
              ".option corner selects one", (654,)),
             ("All corners at once", ".option autocorner runs nominal and every declared "
              "corner, side by side", (656,))]
    grid(s, MX + 7.4, TOP, CW - 7.4, BOT - TOP, 1, 3, items, T2)

    # --- optimization
    s = new(prs, L, "Content", "Optimization and sweeps", sec,
            "optimize varies knobs, re-runs analyses and drives an objective to a minimum. Knobs are "
            "-param (alter), -mparam (altermod) and -dparam (.param; the optimum is written into the "
            "deck, E-767). -constrain adds bounds held by an augmented Lagrangian (E-766); -polish "
            "finishes a global method locally and -starts adds Latin-hypercube restarts (E-764). The "
            "outcome is published as optimize_status, optimize_converged, optimize_cost and "
            "optimize_evals (E-762).", kick=kc("Simulator", "Optimization & parametric sweeps"), acc=T2)
    rows = [["-method", "Kind", "Reach for it when"],
            [[("nm", {"mono": True, "bold": True})], "simplex", "the default for a scalar -minimize"],
            [[("lm", {"mono": True, "bold": True})], "least squares", "the default for -target fits, up to 100 knobs"],
            [[("tr", {"mono": True, "bold": True})], "trust region", "smooth objectives: 2–7x fewer evaluations"],
            [[("pso de sa", {"mono": True, "bold": True})], "global", "the whole knob box has to be searched"],
            [[("cmaes", {"mono": True, "bold": True})], "adaptive global", "knobs over decades or correlated"],
            [[("bayes", {"mono": True, "bold": True})], "GP surrogate", "slow decks: the basin in 10–20 runs"],
            [[("nsga2", {"mono": True, "bold": True})], "multi-objective", "a Pareto front of several objectives"]]
    table(s, MX, TOP, 7.55, [1.55, 1.9, 4.1], rows, size=14, row_h=0.58, head_size=14, name="Methods table")
    text(s, MX, TOP + 4.85, 7.55, 0.45,
         [[("Scripts read the outcome: ", {"bold": True}),
           ("optimize_status, optimize_converged, optimize_cost, optimize_evals", {"mono": True, "size": 12})]],
         size=14, name="Outcome note")
    items = [("Knobs & constraints", "-param, -mparam, -dparam; -constrain; -polish and "
              "-starts", (766, 764)),
             ("sweep", "One sweep command and .sweep card for every knob kind; -overlay, "
              "-vs", (146, 190)),
             ("Fast paths", "Sweeps in linear time, 87x at 64k points; .param changed in "
              "place", (345, 320))]
    grid(s, MX + 7.85, TOP, CW - 7.85, BOT - TOP, 1, 3, items, T2)

    # --- post-layout & reliability
    s = new(prs, L, "Content", "Post-layout parasitics and reliability", sec,
            "reduce is TICER model-order reduction for extracted RC networks; its sparse version "
            "scales to millions of nodes (E-155, E-156). aging runs the industry flow stress, "
            "degrade, re-simulate for HCI, NBTI and TDDB (E-157). emir reports power-grid IR drop "
            "and electromigration risk (E-158).", kick="Simulator · %d enhancements" % (AREA["Post-layout parasitics"] + AREA["Reliability / aging"]), acc=T2)
    cols = [("reduce · TICER", (155, 156), "Extracted RC networks reduced to small equivalents; "
             "the sparse version scales to millions of nodes", "examples/reduce_examples/reduce_ac.png",
             "A 25-node network and its 3- and 6-node reductions agree in band",
             "reduce <fmax> [factor <f>]\n  [keep <node> ...]"),
            ("aging", (157,), "Stress, degrade, re-simulate: HCI, NBTI and TDDB aging to a target "
             "lifetime", "examples/aging_examples/aging_iv.png",
             "NBTI shifts the transfer curve over 40 years; ΔVth ∝ t^0.25",
             "aging <t_target> [rate <opvar>]\n  [dynamic <tstop>]"),
            ("emir", (158,), "Power-grid IR drop and electromigration sign-off on the "
             "rail's segments", "examples/emir_examples/emir_grid.png",
             "The rail sags to 0.780%sV at the far tap; current density sets EM risk" % NB,
             "emir [rail <V>] [jmax <A/m2>]\n  [top <k>]")]
    colw = (CW - 2 * 0.3) / 3
    for i, (t, nums, d, img, cap, cmd) in enumerate(cols):
        x = MX + i * (colw + 0.3)
        rect(s, x, TOP, colw, BOT - TOP, TC.BACKGROUND_2, name="Column " + t)
        text(s, x + 0.22, TOP + 0.18, 2.3, 0.35, t, size=18, bold=True, tcol=TC.TEXT_2,
             name="Column title " + t, check=False)
        chips(s, 0, TOP + 0.22, list(nums), T2, right=x + colw - 0.22)
        text(s, x + 0.22, TOP + 0.7, colw - 0.44, 1.0, d, size=14, name="Column text " + t)
        picture(s, img, x + 0.22, TOP + 1.7, w=colw - 0.44, h=2.0, caption=cap, cap_h=0.55)
        rect(s, x + 0.22, BOT - 0.95, colw - 0.44, 0.75, TC.TEXT_2, radius=0.08, name="Command " + t)
        text(s, x + 0.37, BOT - 0.86, colw - 0.74, 0.6, cmd, size=11, mono=True, tcol=TC.BACKGROUND_1,
             name="Command text " + t, line=1.0)

    # --- workflow
    s = new(prs, L, "Content", "Workflow and usability", sec,
            "savestate and loadstate serialize a transient's integration state and resume it in a "
            "fresh process (E-131); set autosave saves on Ctrl-C (E-192). pyplot sends any vector to "
            "matplotlib. Raw strings and f-strings work in control scripts (E-553). help all lists "
            "every command (E-753). .option saveused, autobus and autoadapt keep large decks small "
            "and wired. XSPICE code models are bundled with every prebuilt binary.",
            kick=kc("Simulator", "Workflow, docs & benchmarks"), acc=T2)
    items = [("Checkpoint & restart", "savestate and loadstate resume a transient in a new "
              "process; autosave on Ctrl-C", (131, 192)),
             ("pyplot", "matplotlib from the prompt: subplots, bode, smith, eye, hist, "
              "contour, fft", (94, 298)),
             ("Control language", "Raw strings, f-strings; help all and a full help "
              "optimize", (553, 753)),
             ("Large decks", ".option saveused keeps only what is read; autobus, "
              "autoadapt wire buses", (469, 444)),
             ("Output", "wrdata CSV, clean rawfile round trips, a sweep progress "
              "bar", (231, 129)),
             ("XSPICE", "Code models bundled per platform: gain, summer, oscillators, "
              "ADC/DAC bridges", (223,))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T2)
    picture(s, "examples/syntaxhl_examples/syntaxhl.png", 8.45, TOP, w=4.28,
            caption="Syntax highlighting at the ngspice prompt, re-colored on every keystroke "
                    "(E-169, E-170)", cap_h=0.5)
    code(s, 8.45, TOP + 3.3, 4.28, BOT - TOP - 3.3,
         "run\n"
         "savestate run.ckpt\n"
         "* later, in a fresh process:\n"
         "loadstate run.ckpt\n"
         "echo f\"fc {mean(fc):.4g} Hz\"",
         size=12, title="A checkpoint and an f-string")

    # ===================================================== Part 3
    sec = section("Part 3 · Verification")
    s = new(prs, L, "Section", "How it is verified", sec,
            "Every feature claimed in the handbook is guarded by a verify script that compiles the "
            "Verilog-A model with the committed compiler, runs it through the committed ngspice, and "
            "checks the numbers against closed-form or independent expectations.")
    s.placeholders[1].text = ("Part 3 · Every claim has a script that computes its own expected number, "
                              "on both linear solvers, on five platforms.")
    stat(s, 9.0, 2.6, 3.7, 2.3, "%d/%d" % (F["sweep_pass"], F["sweep_total"]),
         "verify suites passing in the regression sweep at E-%d" % F["sweep_at"],
         TC.ACCENT_4, big_size=50, dark=True, label_size=16)

    # --- pipeline
    s = new(prs, L, "Content", "From a change to a release", sec,
            "Each enhancement follows the same path. The suite answers 'did anything change?' on "
            "every fold; the campaigns on the following slides answer 'is it correct?'. A pass means "
            "the number is right, not that a run finished.", kick="The verification pipeline", acc=T4)
    steps = [("Fold", "the change, its write-up and the change logs, together"),
             ("Verify", "a verify_*.py checks closed-form or independent references"),
             ("Both solvers", "each suite runs under Sparse 1.3 and under KLU"),
             ("Full sweep", "%d suites, eight at a time, %s" % (F["sweep_total"], sweep_text())),
             ("CI", "five platforms build and test, and the binaries are committed"),
             ("Release", "a tagged GitHub release with the write-up as its notes")]
    bw, g = (CW - 5 * 0.2) / 6, 0.2
    for i, (t, d) in enumerate(steps):
        x = MX + i * (bw + g)
        rect(s, x, TOP + 0.45, bw, 3.3, TC.BACKGROUND_2, name="Pipeline " + t)
        c = rect(s, x + (bw - 0.8) / 2, TOP, 0.8, 0.8, T4, shape=MSO_SHAPE.OVAL, name="Pipeline number %d" % (i + 1))
        shape_text(c, str(i + 1), size=24, tcol=TC.BACKGROUND_1)
        text(s, x + 0.15, TOP + 1.0, bw - 0.3, 0.4, t, size=17, bold=True, tcol=TC.TEXT_2,
             align=PP_ALIGN.CENTER, name="Pipeline title " + t, check=False)
        text(s, x + 0.15, TOP + 1.5, bw - 0.3, 2.1, d, size=16, name="Pipeline text " + t)
    rect(s, MX, TOP + 4.15, CW, 1.15, TC.TEXT_2, name="Quote panel")
    text(s, MX + 0.4, TOP + 4.15, CW - 0.8, 1.15,
         [[("“A pass means the number is right, not that a run finished.”", {"italic": True})]],
         size=22, tcol=TC.BACKGROUND_1, anchor=MSO_ANCHOR.MIDDLE, name="Quote", align=PP_ALIGN.CENTER)

    # --- physics
    s = new(prs, L, "Content", "Physics validation", sec,
            "examples/physcheck_examples checks industry models against analytic device laws through "
            "the whole toolchain; dynphys and tempphys extend it to charge and temperature. The CMC "
            "sweep compiles and loads 19 of 19 compact models and compares C-V and fT against "
            "ngspice's built-in twins.", kick=kc("Simulator", "Physics validation"), acc=T4)
    items = [("Junction law", "60 mV/decade slopes recovered through the full "
              "pipeline", (57,)),
             ("Noise identity", "Thermal noise matches 4kT/R", (57,)),
             ("Jacobians", "AC against numeric derivatives on PSP103 to ~1e-5", (57,)),
             ("Dynamic charge", "Cgg from AC equals Cgg from the transient", (75,)),
             ("Temperature", "A band gap of ≈1.25%seV extracted from a compiled MEXTRAM" % NB, (80,)),
             ("CMC suite", "19 of 19 models compile and load; C-V and fT against built-in "
              "twins", (160, 161))]
    grid(s, MX, TOP, 7.55, BOT - TOP, 2, 3, items, T4)
    picture(s, "examples/physcheck_examples/plots/gummel.png", 8.45, TOP, w=4.28, h=2.3,
            caption="MEXTRAM 505 Gummel plot: the ideal 60%smV/decade slope "
                    "(examples/physcheck_examples)" % NB, cap_h=0.45)
    picture(s, "examples/cmcsweep_examples/cmcsweep_coverage.png", 8.45, TOP + 3.0, w=4.28, h=1.85,
            caption="CMC coverage: 19 of 19 compile and load (examples/cmcsweep_examples)", cap_h=0.4)

    # --- campaigns
    s = new(prs, L, "Content", "Campaigns beyond the suite", sec,
            "The OSDI and solver campaigns sit outside run_regression.py on purpose (run_campaign.py, "
            "run_solverdiff.py). The bug-hunt pages in docs/bug_hunts record each campaign's "
            "harnesses, findings and the enhancement that fixed each finding; the most recent, the "
            "analyses correctness campaign of October 2026, produced E-895 to E-908.",
            kick="Independent references", acc=T4)
    rows = [["Campaign", "Instrument", "Result"],
            ["OSDI correctness", "83 oracle checks: analyses, sweeps, optimizers, Monte Carlo, RF", "83 / 83"],
            ["Sparse vs KLU", "numpy as a third opinion; assert within eps · cond", "37 / 37"],
            ["Compiler robustness", "production corpus, ~50 adversarial inputs, 4,000 mutants", "4 crash paths fixed"],
            ["LRM 2023 examples", "every code example in the standard, compiled", "a compliance suite"],
            ["Correctness hunts", "%d pages: OSDI, solvers, transient, nonlinear, analyses" % F["hunts"],
             "each fix an enhancement"]]
    table(s, MX, TOP, CW, [2.9, 6.53, 2.7], rows, size=15, row_h=0.72, head_size=14, name="Campaign table")
    text(s, MX, TOP + 4.55, CW, 0.7,
         "OSDI devices come out bit-identical to ngspice's built-in R, C, L and G through op, ac, tran, "
         "tf, pz and sens.", size=15, italic=True, tcol=TC.ACCENT_3, name="Campaign note")

    # --- timeline
    s = new(prs, L, "Content", "Milestones by enhancement number", sec,
            "A selection of milestones in the order the work happened; the enhancement number is "
            "the axis. The full one-line index is docs/handbook/05-enhancement-index.md, and the "
            "catalog groups every enhancement by area.", kick="Timeline", acc=T4)
    ms = [(1, "absdelay, the first operator", T1), (62, ".dc @inst sweeps", T2),
          (110, "accuracy presets, line search", T2), (134, "harmonic balance", T2),
          (154, "envelope following completes the RF suite", T2), (200, "pre_snp: Touchstone to OSDI", T2),
          (364, "transient noise for OSDI devices", T2), (530, "statistics in Verilog-A", T1),
          (654, "corners in the source", T1), (752, "PRBS and PAM4 sources", T2),
          (765, "Bayesian optimization", T2), (908, "TXL and CPL lossy lines", T2)]
    y0 = TOP + 2.65
    rect(s, MX, y0 - 0.03, CW, 0.06, TC.ACCENT_3, 0.5, shape=MSO_SHAPE.RECTANGLE, name="Timeline axis")
    step = (CW - 1.8) / (len(ms) - 1)
    for i, (n, t, acc) in enumerate(ms):
        x = MX + 0.9 + i * step
        d = rect(s, x - 0.13, y0 - 0.13, 0.26, 0.26, acc, shape=MSO_SHAPE.OVAL, name="Milestone E-%d" % n)
        d.click_action.hyperlink.address = WRITEUP % n
        up = (i % 2 == 0)
        bx = x - 0.88
        ty = y0 - 2.15 if up else y0 + 0.4
        lab = text(s, bx, ty, 1.76, 0.38, "E-%d" % n, size=16, bold=True, tcol=acc, bright=-0.2,
                   align=PP_ALIGN.CENTER, name="Milestone number E-%d" % n, check=False, head=True)
        text(s, bx, ty + 0.42, 1.76, 1.15, t, size=14, align=PP_ALIGN.CENTER,
             name="Milestone text E-%d" % n)
    for t, acc, x in (("compiler", T1, MX), ("simulator", T2, MX + 1.6)):
        d = rect(s, x, BOT - 0.3, 0.22, 0.22, acc, shape=MSO_SHAPE.OVAL, name="Legend dot " + t)
        text(s, x + 0.32, BOT - 0.35, 1.2, 0.3, t, size=12, tcol=TC.ACCENT_3, name="Legend " + t, check=False)

    # --- platforms
    s = new(prs, L, "Content", "Five platforms, prebuilt", sec,
            "CI builds both tools for five platforms and commits them under bin/. Each platform "
            "directory also ships XSPICE code models under codemodels/ with a portable "
            "scripts/spinit; export SPICE_LIB_DIR to load them. Building from source needs a Rust "
            "toolchain and exactly LLVM 18 for openvaf-r.", kick="Builds", acc=T4)
    rows = [["Platform", "Directory", "Notes"],
            ["Linux x86-64", [("bin/linux/intel/", {"mono": True})], "X11 and readline"],
            ["Linux ARM64", [("bin/linux/arm/", {"mono": True})], "X11 and readline"],
            ["macOS Apple Silicon", [("bin/macos/apple-silicon/", {"mono": True})], "XQuartz, Homebrew readline"],
            ["macOS Intel", [("bin/macos/intel/", {"mono": True})], "XQuartz, Homebrew readline"],
            ["Windows x86-64", [("bin/windows/intel/", {"mono": True})], "DLLs bundled; MSVC link.exe to compile Verilog-A"]]
    table(s, MX, TOP, 8.0, [2.0, 3.25, 2.75], rows, size=14, row_h=0.62, head_size=14, name="Platform table")
    code(s, MX, TOP + 4.0, 8.0, BOT - TOP - 4.0,
         "ngspice  openvaf-r  codemodels/*.cm  scripts/spinit",
         size=13, title="In every platform directory")
    items = [("From source", "openvaf-r: Rust and exactly LLVM 18. ngspice-46: configure and make, "
              "handbook section 1.3.", ()),
             ("XSPICE", "Code models under codemodels/ with a portable spinit; set SPICE_LIB_DIR "
              "to load them.", (223,)),
             ("Windows linking", "Every model links with MSVC on COFF since the weak-symbol "
              "fix.", (769,))]
    grid(s, MX + 8.3, TOP, CW - 8.3, BOT - TOP, 1, 3, items, T4)

    # ===================================================== Part 4
    sec = section("Part 4 · Using it")
    s = new(prs, L, "Section", "Using it", sec,
            "How to start, what is out of scope, and where the documentation lives.")
    s.placeholders[1].text = "Part 4 · Getting started in four steps, the scope and known limits, and the documentation."
    stat(s, 9.0, 2.6, 3.7, 2.3, str(F["examples"]), "example folders, each a working reference for a feature",
         TC.ACCENT_6, big_size=60, dark=True, label_size=16)

    # --- getting started
    s = new(prs, L, "Content", "Getting started in four steps", sec,
            "From a fresh clone: take the prebuilt binaries for your platform, compile a Verilog-A "
            "model, load it in a deck with pre_osdi, and run. Every example folder's verify script "
            "is a complete, tested reference; examples/analyses_examples is a tutorial with one "
            "commented deck per analysis.", kick="Quick start", acc=TC.ACCENT_3)
    steps = [("Get the binaries", "bin/<os>/<arch>/\n  ngspice\n  openvaf-r\n  codemodels/",
              "Prebuilt for five platforms, or build from source"),
             ("Compile a model", "openvaf-r myres.va \\\n  -o myres.osdi",
              "-I adds include paths and -D defines a macro"),
             ("Load it in a deck", "n1 in mid ra\n.model ra myres(r=1k)\n.control\npre_osdi myres.osdi\n.endc",
              "N devices; the card names the module"),
             ("Run and explore", "ngspice -b divider.cir\npython3 examples/\n  dowhile_examples/\n  verify_dowhile.py",
              "Each verify script checks exact numbers")]
    bw, g = (CW - 3 * 0.3) / 4, 0.3
    for i, (t, src, d) in enumerate(steps):
        x = MX + i * (bw + g)
        c = rect(s, x, TOP, 0.7, 0.7, TC.TEXT_2, shape=MSO_SHAPE.OVAL, name="Step number %d" % (i + 1))
        shape_text(c, str(i + 1), size=22, tcol=TC.BACKGROUND_1)
        text(s, x + 0.85, TOP + 0.12, bw - 0.85, 0.45, t, size=17, bold=True, tcol=TC.TEXT_2,
             name="Step title " + t, check=False)
        rect(s, x, TOP + 0.95, bw, 1.6, TC.TEXT_2, radius=0.04, name="Step code panel " + t)
        text(s, x + 0.2, TOP + 1.1, bw - 0.4, 1.35, src, size=12, tcol=TC.BACKGROUND_1, mono=True,
             name="Step code " + t, line=1.0)
        text(s, x, TOP + 2.7, bw, 0.6, d, size=14, name="Step note " + t)
    code(s, MX, TOP + 3.45, 6.4, BOT - TOP - 3.45,
         "`include \"disciplines.vams\"\n"
         "module myres(p, n);\n"
         "  inout p, n; electrical p, n;\n"
         "  parameter real r = 1k from (0:inf);\n"
         "  analog I(p, n) <+ V(p, n) / r;\n"
         "endmodule", size=12, title="myres.va, the model the steps use")
    code(s, MX + 6.7, TOP + 3.45, CW - 6.7, BOT - TOP - 3.45,
         "$ ngspice -b divider.cir\n"
         "v(mid) = 1.000000e+00", size=12, title="What the run prints")

    # --- limits
    s = new(prs, L, "Content", "Scope and known limits", sec,
            "From docs/handbook/04-limitations-and-gotchas.md and the open findings of the analyses "
            "correctness campaign (docs/bug_hunts/2026-10-16_...). The open findings are in stock "
            "ngspice devices, not in the OSDI path: .disto treats a device without a distortion "
            "routine as linear, the built-in BJT's .disto is wrong with rb or tr, TXL has no AC model, "
            "and CPL loses its resistance below its RC corner (both lines now say so, E-908).",
            kick="What it does not do", acc=TC.ACCENT_5)
    cols = [("Out of scope by design", TC.ACCENT_5,
             ["Digital and mixed-signal Verilog-AMS: the Annex C boundary",
              "SPICE primitives instantiated from Verilog-A: put them in the netlist",
              "Vector branches over whole buses: declare per-bit branches",
              "`default_discipline and out-of-module discipline declarations"]),
            ("Design decisions", TC.ACCENT_3,
             ["Structure binds at compile time: a generate bound cannot read a parameter",
              "An untyped parameter takes its default's type",
              "limexp is stateless, a documented decision",
              "$simprobe returns its default; node aliases return 0"]),
            ("Open findings, stock devices", TC.ACCENT_2,
             [".disto gives zeros for devices without a distortion routine",
              "The built-in BJT's .disto with rb or tr",
              "TXL has no AC model; CPL loses its resistance below its RC corner",
              "LTRA can stop with 'timestep too small' on a long lossy line"])]
    colw = (CW - 2 * 0.3) / 3
    for i, (t, acc, bl) in enumerate(cols):
        x = MX + i * (colw + 0.3)
        rect(s, x, TOP, colw, BOT - TOP, TC.BACKGROUND_2, name="Limits " + t)
        dot = rect(s, x + 0.25, TOP + 0.3, 0.32, 0.32, acc, shape=MSO_SHAPE.OVAL, name="Limits dot " + t)
        text(s, x + 0.72, TOP + 0.25, colw - 0.95, 0.42, t, size=18, bold=True, tcol=TC.TEXT_2,
             name="Limits title " + t, check=False)
        text(s, x + 0.25, TOP + 1.0, colw - 0.5, BOT - TOP - 1.25, bl, size=16, bullets=True,
             space_after=12, name="Limits bullets " + t)

    # --- docs map
    s = new(prs, L, "Content", "Where to read more", sec,
            "Every tile links to the document on GitHub. The handbook is also one linked PDF with "
            "the complete text of every enhancement write-up: docs/Ngspice-OpenVAF-Handbook.pdf.",
            kick="Documentation", acc=TC.ACCENT_3)
    tiles = [("Feature catalog", "docs/index.html", "every enhancement in 19 areas, searchable",
              GH.replace("github.com/javaNoviceProgrammer", "javanoviceprogrammer.github.io") + "/", T1),
             ("User handbook", "docs/handbook/", "start, language matrix, workflows, limits; PDF too",
              GH + "/blob/main/docs/handbook/README.md", T1),
             ("LRM compliance", "docs/compliance/", "clause by clause, with verified code examples",
              GH + "/blob/main/docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md", T1),
             ("Change reports", "docs/change_log/", "every change to either tool, by subsystem",
              GH + "/tree/main/docs/change_log", T1),
             ("Compiler internals", "docs/internals/\nopenvaf_internals/", "lexing to OSDI, robustness, compile time",
              GH + "/tree/main/docs/internals/openvaf_internals", T2),
             ("Simulator internals", "docs/internals/\nngspice_internals/", "parser to Newton loop; the gap analysis",
              GH + "/tree/main/docs/internals/ngspice_internals", T2),
             ("Topic guides", "docs/internals/\nngspice_internals/", "statistics, transient noise, temperature",
              GH + "/blob/main/docs/internals/ngspice_internals/ngspice_statistics.md", T2),
             ("Hunts & proposals", "docs/bug_hunts/\ndocs/proposals/", "%d campaign pages, %d proposals" % (F["hunts"], F["proposals"]),
              GH + "/tree/main/docs/bug_hunts", T2)]
    cwid, chgt, g = (CW - 3 * 0.25) / 4, (BOT - TOP - 0.25) / 2, 0.25
    for i, (t, path, d, url, acc) in enumerate(tiles):
        r, c = divmod(i, 4)
        x, y = MX + c * (cwid + g), TOP + r * (chgt + g)
        tile = rect(s, x, y, cwid, chgt, TC.BACKGROUND_2, name="Doc " + t)
        tile.click_action.hyperlink.address = url
        dot = rect(s, x + 0.22, y + 0.25, 0.3, 0.3, acc, shape=MSO_SHAPE.OVAL, name="Doc dot " + t)
        text(s, x + 0.65, y + 0.2, cwid - 0.85, 0.4, t, size=17, bold=True, tcol=TC.TEXT_2,
             name="Doc title " + t, check=False)
        text(s, x + 0.22, y + 0.8, cwid - 0.44, 0.65, path, size=12, mono=True, tcol=acc, bright=-0.3,
             name="Doc path " + t)
        text(s, x + 0.22, y + 1.5, cwid - 0.44, chgt - 1.7, d, size=14, name="Doc text " + t)

    # --- closing
    s = new(prs, L, "Title", "One toolchain, verified end to end", sec,
            "openvaf-r compiles the Verilog-A language with correct values and derivatives; ngspice-46 "
            "runs those models through every analysis, the RF suite, statistics and optimization "
            "included; %d verify suites and five CI platforms check every change, and every change " % F["sweep_total"] +
            "has a write-up.")
    s.placeholders[1].text = "github.com/javaNoviceProgrammer/\nNgspice_OpenVAF_Enhancements"
    s.placeholders[1].click_action.hyperlink.address = GH
    lines = [("openvaf-r", "compiles the Verilog-A language: values and derivatives", T1),
             ("ngspice-46", "runs those models through every analysis, RF and statistics included", T2),
             ("%d suites" % F["sweep_total"], "and five CI platforms check every change; each change has a write-up", T4)]
    for i, (h_, d, acc) in enumerate(lines):
        y = 1.95 + i * 1.2
        rect(s, 8.0, y, 4.73, 1.0, TC.TEXT_2, 0.12, name="Closing " + h_)
        text(s, 8.25, y + 0.1, 4.3, 0.36, h_, size=17, bold=True, tcol=acc, name="Closing title " + h_,
             check=False)
        text(s, 8.25, y + 0.46, 4.3, 0.5, d, size=13, tcol=TC.BACKGROUND_1, name="Closing text " + h_)

    write_sections(prs)
    prs.save(out)
    print("wrote %s: %d slides" % (os.path.relpath(out), len(prs.slides)))
    print("read: E-%d latest, %d write-ups, %d areas (%d compiler, %d simulator), sweep %d/%d at E-%d, "
          "VA_TEST %d/%d, %d hunt pages, %d proposals, %d example folders"
          % (F["latest"], F["writeups"], len(F["areas"]), F["comp"], F["sim"], F["sweep_pass"],
             F["sweep_total"], F["sweep_at"], F["va_ok"], F["va_standalone"], F["hunts"], F["proposals"],
             F["examples"]))
    for w_ in warnings:
        print("FIT?", w_)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the features deck of the enhanced ngspice + openvaf-r.")
    ap.add_argument("-o", "--out", default=OUT, help="output .pptx (default: %(default)s)")
    ap.add_argument("--month", default=datetime.date.today().strftime("%B %Y"),
                    help='the date on the title slide (default: this month, e.g. "October 2026")')
    a = ap.parse_args()
    facts(REPO, a.month)
    build(a.out)
