#!/usr/bin/env python3
"""Build the single-file PDF edition of the handbook.

Assembles Part I (the five handbook chapters) and Part II (every
enhancements_doc/Enhancement-N.md) into one pandoc/xelatex document:

- headings are demoted one level so the two Part headings sit at the top
  of the table of contents; each chapter / enhancement starts a new page;
- links between documents that are *inside* the PDF (handbook chapters,
  enhancement docs) become internal anchors;
- links to anything else in the repository (example folders, README
  sections, workflow files) become absolute GitHub URLs so they stay
  clickable in the PDF.

Requires: pandoc + xelatex (TeX Live / MacTeX), STIX Two Text (bundled
with macOS; on other systems change MAINFONT below).

Usage:  python3 docs/handbook/build_pdf.py
Output: docs/Ngspice-OpenVAF-Handbook.pdf
"""
import datetime
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))            # docs/handbook
ROOT = os.path.dirname(os.path.dirname(HERE))                # repo root
GITHUB = "https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements"
OUT = os.path.join(ROOT, "docs", "Ngspice-OpenVAF-Handbook.pdf")
MAINFONT = "STIX Two Text"
MONOFONT = "Menlo"

CHAPTERS = [
    ("README.md", "hb-home"),
    ("01-getting-started.md", "ch1"),
    ("02-verilog-a-language.md", "ch2"),
    ("03-ngspice-workflows.md", "ch3"),
    ("04-limitations-and-gotchas.md", "ch4"),
    ("05-enhancement-index.md", "ch5"),
]
CHAPTER_IDS = {name: cid for name, cid in CHAPTERS}

LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def enh_docs():
    docs = []
    for fn in os.listdir(os.path.join(ROOT, "enhancements_doc")):
        m = re.fullmatch(r"Enhancement-(\d+)\.md", fn)
        if m:
            docs.append((int(m.group(1)), fn))
    return [fn for _, fn in sorted(docs)]


def rewrite_target(target, src_dir):
    """Map one link target to an internal anchor or a GitHub URL."""
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return target
    frag = ""
    if "#" in target:
        target, frag = target.split("#", 1)
    rel = os.path.normpath(os.path.join(src_dir, target))     # repo-relative
    m = re.fullmatch(r"enhancements_doc/Enhancement-(\d+)\.md", rel)
    if m:
        return f"#enh-{m.group(1)}"
    if rel.startswith("docs/handbook/") and rel.endswith(".md"):
        base = os.path.basename(rel)
        if base in CHAPTER_IDS:
            return f"#{frag}" if frag else f"#{CHAPTER_IDS[base]}"
    kind = "tree" if os.path.isdir(os.path.join(ROOT, rel)) else "blob"
    url = f"{GITHUB}/{kind}/main/{rel}" if rel != "." else GITHUB
    return f"{url}#{frag}" if frag else url


def process(path, first_heading_id):
    """Demote headings, tag the first heading, rewrite links (fence-aware)."""
    src_dir = os.path.relpath(os.path.dirname(path), ROOT)
    out, in_fence, tagged = [], False, False
    for line in open(path).read().splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence:
            m = re.match(r"^(#{1,5})\s+(.*)$", line)
            if m:
                # the enhancement docs' historical "(versionN)" title tags
                # are development-workflow detail; keep them out of the PDF
                line = "#" + re.sub(r"\s*\(version\d+\)", "", line)
                if not tagged:
                    line += f" {{#{first_heading_id}}}"
                    tagged = True
            line = LINK.sub(
                lambda mm: f"[{mm.group(1)}]({rewrite_target(mm.group(2), src_dir)})",
                line,
            )
        out.append(line)
    return "\n".join(out)


def main():
    parts = ["# Part I — The User Handbook {#part-i}", ""]
    for name, cid in CHAPTERS:
        parts += [process(os.path.join(HERE, name), cid), ""]
    parts += ["# Part II — The Enhancements, One by One {#part-ii}", "",
              "The complete engineering record: for every enhancement, what "
              "was broken or missing, how it was fixed, and how the fix was "
              "verified. These are the detailed documents the handbook's "
              "matrix rows and the top-level README summaries point at.", ""]
    for fn in enh_docs():
        n = re.search(r"\d+", fn).group()
        parts += [process(os.path.join(ROOT, "enhancements_doc", fn), f"enh-{n}"), ""]
    combined = "\n".join(parts)

    header_tex = r"""
\usepackage{titlesec}
\newcommand{\sectionbreak}{\clearpage}
\newcommand{\subsectionbreak}{\clearpage}
\usepackage{fvextra}
\fvset{breaklines}
% STIX Two Text lacks these; take them from the math font instead.
\usepackage{newunicodechar}
\newunicodechar{✅}{\checkmark}
\newunicodechar{❌}{\ensuremath{\times}}
\newunicodechar{⚠}{\ensuremath{\triangle}}
\newunicodechar{∝}{\ensuremath{\propto}}
\newunicodechar{∫}{\ensuremath{\int}}
\newunicodechar{✓}{\checkmark}
\newunicodechar{️}{}
\newunicodechar{→}{\ensuremath{\rightarrow}}
\newunicodechar{↔}{\ensuremath{\leftrightarrow}}
\newunicodechar{⇒}{\ensuremath{\Rightarrow}}
\newunicodechar{⇔}{\ensuremath{\Leftrightarrow}}
\newunicodechar{≥}{\ensuremath{\geq}}
\newunicodechar{≤}{\ensuremath{\leq}}
\newunicodechar{≠}{\ensuremath{\neq}}
\newunicodechar{≈}{\ensuremath{\approx}}
\newunicodechar{≡}{\ensuremath{\equiv}}
\newunicodechar{∠}{\ensuremath{\angle}}
\newunicodechar{√}{\ensuremath{\surd}}
\newunicodechar{∈}{\ensuremath{\in}}
\newunicodechar{∥}{\ensuremath{\parallel}}
\newunicodechar{‖}{\ensuremath{\Vert}}
\newunicodechar{␄}{\texttt{<EOF>}}
"""

    # pandoc's gfm reader emits pipe tables with no column widths, which
    # xelatex renders as single-line cells running off the page. Assign
    # proportional widths (from the longest cell per column) to any wide
    # table that has none.
    widths_lua = r"""
function Table(t)
  local ncols = #t.colspecs
  for _, cs in ipairs(t.colspecs) do
    if cs[2] ~= nil then return nil end   -- already has widths
  end
  local maxlen = {}
  for i = 1, ncols do maxlen[i] = 3 end
  local function scan(rows)
    for _, row in ipairs(rows) do
      for i, cell in ipairs(row.cells) do
        local s = pandoc.utils.stringify(cell.contents)
        if #s > maxlen[i] then maxlen[i] = #s end
      end
    end
  end
  scan(t.head.rows)
  for _, body in ipairs(t.bodies) do scan(body.body) end
  local total = 0
  for i = 1, ncols do
    maxlen[i] = math.min(maxlen[i], 220)
    total = total + maxlen[i]
  end
  if total < 75 then return nil end       -- narrow tables look better as-is
  for i = 1, ncols do
    local w = maxlen[i] / total
    if w < 0.08 then w = 0.08 end
    t.colspecs[i] = {t.colspecs[i][1], w * 0.96}
  end
  return t
end
"""
    with tempfile.TemporaryDirectory() as td:
        md = os.path.join(td, "combined.md")
        hdr = os.path.join(td, "header.tex")
        lua = os.path.join(td, "widths.lua")
        open(md, "w").write(combined)
        open(hdr, "w").write(header_tex)
        open(lua, "w").write(widths_lua)
        cmd = [
            "pandoc", md, "-f", "gfm+attributes", "-o", OUT,
            "--pdf-engine=xelatex", "--toc", "--toc-depth=2",
            "-H", hdr, "--lua-filter", lua,
            "-V", "documentclass=article",
            "-V", "papersize=a4",
            "-V", "geometry:margin=2.2cm",
            "-V", f"mainfont={MAINFONT}",
            "-V", f"monofont={MONOFONT}",
            "-V", "fontsize=11pt",
            "-V", "colorlinks=true",
            "-V", "title=Ngspice + OpenVAF Enhancements",
            "-V", "subtitle=User Handbook and Enhancement Reference",
            "-V", "author=Dr. Meisam Bahadori",
            "-V", f"date={datetime.date.today():%B %Y}",
            "--metadata", "lang=en",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        sys.stderr.write(r.stderr)
        if r.returncode != 0:
            sys.exit(r.returncode)
    print(f"wrote {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
