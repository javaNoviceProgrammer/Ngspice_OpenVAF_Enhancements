#!/usr/bin/env python3
"""Regenerate the PDF editions of the two full change reports.

Usage:  python3 docs/change_log/build_pdfs.py
Needs pandoc + xelatex (and STIX Two Text; adjust MAINFONT elsewhere).
Repo-relative links inside the markdown become absolute GitHub URLs so
they stay clickable in the standalone PDFs.
"""
import datetime
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # docs/change_log
ROOT = os.path.dirname(os.path.dirname(HERE))              # repo root
GITHUB = "https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements"

REPORTS = [
    ("ngspice_changes_full-report", "ngspice-46 — Full Change Report"),
    ("openvaf_changes_full-report", "openvaf-r — Full Change Report"),
]

HEADER_TEX = r"""
\usepackage{titlesec}
\newcommand{\sectionbreak}{\clearpage}
\usepackage{fvextra}
\fvset{breaklines}
\usepackage{newunicodechar}
\newunicodechar{→}{\ensuremath{\rightarrow}}
\newunicodechar{↔}{\ensuremath{\leftrightarrow}}
\newunicodechar{≥}{\ensuremath{\geq}}
\newunicodechar{≤}{\ensuremath{\leq}}
\newunicodechar{≠}{\ensuremath{\neq}}
\newunicodechar{≈}{\ensuremath{\approx}}
\newunicodechar{≡}{\ensuremath{\equiv}}
\newunicodechar{≪}{\ensuremath{\ll}}
\newunicodechar{∝}{\ensuremath{\propto}}
\newunicodechar{​}{}
"""

INDEX_LUA = r"""
-- Render each report's per-enhancement index as a definition list rather than a
-- table.
--
-- WHY: a LaTeX table cell is a \parbox -- it cannot break across a page. These
-- index rows carry a full paragraph of provenance each (E-212's runs 4200
-- characters), so any row taller than one page silently OVERFLOWED and was
-- CLIPPED: the tail was simply dropped while pandoc, xelatex and this script all
-- reported success. 27 of 121 ngspice rows and 2 of 77 openvaf rows were losing
-- their endings -- E-207 and E-208 rendered about 7% of their text. A definition
-- list's definitions are ordinary paragraphs, so they flow across pages and
-- nothing can be lost. verify_index_rows() enforces it. Same defect and same fix
-- as the handbook's chapter 5 (docs/handbook/build_pdf.py).
--
-- Matched on the header, so the OSDI ABI history table (Change | Kind |
-- Enhancement | Why) keeps its tabular rendering and column widths.

local function header_of(t)
  local h = {}
  for _, row in ipairs(t.head.rows) do
    for i, cell in ipairs(row.cells) do
      h[i] = pandoc.utils.stringify(cell.contents)
    end
  end
  return h
end

local function is_index_table(t)
  if #t.colspecs ~= 3 then return false end
  local h = header_of(t)
  return h[1] == "Enhancement" and h[3] == "One line"
end

local function cell_inlines(cell)
  local out = {}
  for _, blk in ipairs(cell.contents) do
    if blk.content and (blk.t == "Plain" or blk.t == "Para") then
      for _, il in ipairs(blk.content) do out[#out + 1] = il end
    else
      out[#out + 1] = pandoc.Str(pandoc.utils.stringify(blk))
    end
  end
  return out
end

function Table(t)
  if not is_index_table(t) then return nil end
  local items = {}
  for _, body in ipairs(t.bodies) do
    for _, row in ipairs(body.body) do
      local term  = cell_inlines(row.cells[1])        -- E-N (a link)
      local files = cell_inlines(row.cells[2])        -- the files / pipeline areas
      local what  = cell_inlines(row.cells[3])        -- what changed and why
      local blocks = {}
      if #files > 0 then
        blocks[#blocks + 1] = pandoc.Para({pandoc.Emph(files)})
      end
      blocks[#blocks + 1] = pandoc.Para(what)
      items[#items + 1] = {term, {blocks}}
    end
  end
  return pandoc.DefinitionList(items)
end
"""


# pandoc's gfm reader emits pipe tables without column widths, which
# xelatex renders as single-line cells running off the page
WIDTHS_LUA = r"""
function Table(t)
  local ncols = #t.colspecs
  for _, cs in ipairs(t.colspecs) do
    if cs[2] ~= nil then return nil end
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
  if total < 75 then return nil end
  for i = 1, ncols do
    local w = maxlen[i] / total
    if w < 0.08 then w = 0.08 end
    t.colspecs[i] = {t.colspecs[i][1], w * 0.96}
  end
  return t
end
"""


def githubify(src_text):
    def rewrite(m):
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "#")):
            return m.group(0)
        rel = os.path.relpath(
            os.path.normpath(os.path.join(HERE, target.split("#")[0])), ROOT)
        kind = "tree" if os.path.isdir(os.path.join(ROOT, rel)) else "blob"
        return f"[{label}]({GITHUB}/{kind}/main/{rel})"
    return re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", rewrite, src_text)


BREAKPATHS_LUA = r"""
-- Insert zero-cost line-break opportunities after path/command separators inside
-- text and inline code, so long file paths and commands WRAP within their table
-- column instead of overflowing. \allowbreak only breaks when a line would overflow,
-- so adding them liberally is harmless.
local BREAK_AFTER = { ['/']=true, ['_']=true, ['.']=true, ['-']=true, [':']=true, ['(']=true, [',']=true }
local function split_breaks(s, mk)
  local out, buf = {}, ""
  for i = 1, #s do
    local c = s:sub(i, i)
    buf = buf .. c
    if BREAK_AFTER[c] and i < #s then
      out[#out+1] = mk(buf)
      out[#out+1] = pandoc.RawInline('latex', '\\allowbreak{}')
      buf = ""
    end
  end
  if #buf > 0 then out[#out+1] = mk(buf) end
  return out
end
local function long_enough(s) return #s >= 8 end
function Str(el)
  if not long_enough(el.text) then return nil end
  return split_breaks(el.text, pandoc.Str)
end
function Code(el)
  if not long_enough(el.text) then return nil end
  return split_breaks(el.text, function(t) return pandoc.Code(t) end)
end
"""


def _sig(s):
    """A comparison signature: alphanumerics only, lowercased.

    Everything else is noise here and actively misleading: markdown syntax, TeX's
    intra-word line breaks, hyphenation, smart dashes and quotes, and math glyphs
    remapped by newunicodechar all differ between the source and the PDF's text
    layer while the letters do not. (Stripping only ``[`*\\]`` instead reports
    false clipping wherever ``*`` is a literal glob -- ``laplace_*`` -> ``laplace_``.)
    """
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _pdf_text(path):
    """The PDF's text, with each page's page-number footer removed.

    Concatenating raw page text splices the footer into the middle of any
    sentence that straddles a page break -- "... E-133" + "48" + "(11/11)
    unaffected ..." -- so a signature spanning that break fails while nothing is
    actually wrong. That cost one false "clipped" verdict before it was noticed.
    """
    import fitz                                       # pymupdf
    out = []
    with fitz.open(path) as doc:
        for page in doc:
            lines = page.get_text().splitlines()
            while lines and re.fullmatch(r"\s*\d+\s*", lines[-1]):
                lines.pop()
            # ...and at the FRONT: pymupdf does not always return the page
            # number last. On a page whose body starts mid-sentence the number
            # came back first -- "a metric" / "207" / "that never varies" --
            # splicing it into the sentence just the same and reporting two
            # complete rows as clipped. Both ends, or the guard cries wolf and
            # teaches the next person to reach for SKIP_PDF_VERIFY.
            while lines and re.fullmatch(r"\s*\d+\s*", lines[0]):
                lines.pop(0)
            out.append("\n".join(lines))
    return _sig("".join(out))


LINK_TEXT_ONLY = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")   # a link TARGET never reaches the PDF


def index_rows(stem):
    """[(enhancement, one-line cell)] from a report's per-enhancement index."""
    rows = []
    for line in open(os.path.join(HERE, stem + ".md")):
        if not line.startswith("| [E-"):
            continue
        # split on UNESCAPED pipes only: a cell containing `\|` (as E-214's does)
        # is otherwise truncated at the escape
        cells = re.split(r"(?<!\\)\|", line)
        if len(cells) > 3:
            rows.append((re.match(r"\| \[E-(\d+)\]", line).group(1), cells[3]))
    return rows


def verify_index_rows(stem):
    """Assert every per-enhancement index row reached the PDF *in full*.

    A LaTeX table cell cannot break across a page, so a long row used to overflow
    and be silently CLIPPED -- tail dropped, build reporting success, and invisible
    in review because the PDF is a binary. End-anchored, because clipping drops the
    END. See INDEX_LUA, and the same guard in docs/handbook/build_pdf.py.
    """
    if os.environ.get("SKIP_PDF_VERIFY"):
        print("WARNING: SKIP_PDF_VERIFY set -- the PDF is NOT verified; "
              "silently clipped rows will go undetected")
        return
    try:
        import fitz                                   # noqa: F401  (pymupdf)
    except ImportError:
        sys.exit("ERROR: pymupdf is required to verify the build "
                 "(pdftotext is not available here).\n"
                 "       pip install pymupdf   -- or run with SKIP_PDF_VERIFY=1 "
                 "to bypass, which leaves silent clipping undetected.")

    text = _pdf_text(os.path.join(HERE, stem + ".pdf"))
    rows = index_rows(stem)
    # A guard that silently matches nothing always passes.
    if len(rows) < 50:
        sys.exit(f"ERROR: only parsed {len(rows)} index rows from {stem}.md -- "
                 "the check cannot be trusted; fix index_rows() to match the "
                 "report's format.")

    clipped = [n for n, cell in rows
               if _sig(LINK_TEXT_ONLY.sub(r"\1", cell))[-40:]
               and _sig(LINK_TEXT_ONLY.sub(r"\1", cell))[-40:] not in text]
    if clipped:
        sys.exit(f"ERROR: {len(clipped)} index row(s) are CLIPPED in {stem}.pdf -- "
                 f"their text is missing from the PDF: {clipped}\n"
                 "       Content is being silently dropped. See INDEX_LUA.")
    print(f"  verified {len(rows)} index rows render in full")


def main():
    with tempfile.TemporaryDirectory() as td:
        hdr = os.path.join(td, "h.tex")
        lua = os.path.join(td, "w.lua")
        # INDEX_LUA needs its OWN filter file, applied first: it also defines a
        # global `Table`, so sharing a file would let the second definition
        # overwrite the first.
        index_lua = os.path.join(td, "index.lua")
        open(hdr, "w").write(HEADER_TEX)
        open(index_lua, "w").write(INDEX_LUA)
        open(lua, "w").write(WIDTHS_LUA + BREAKPATHS_LUA)
        for stem, title in REPORTS:
            md_in = os.path.join(HERE, stem + ".md")
            md_tmp = os.path.join(td, stem + ".md")
            open(md_tmp, "w").write(githubify(open(md_in).read()))
            r = subprocess.run([
                "pandoc", md_tmp, "-f", "gfm",
                "-o", os.path.join(HERE, stem + ".pdf"),
                "--pdf-engine=xelatex", "--toc", "--toc-depth=2",
                "-H", hdr, "--lua-filter", index_lua, "--lua-filter", lua,
                "-V", "documentclass=article", "-V", "papersize=a4",
                "-V", "geometry:margin=2.2cm",
                "-V", "mainfont=STIX Two Text", "-V", "monofont=Menlo",
                "-V", "fontsize=11pt", "-V", "colorlinks=true",
                "-V", f"title={title}",
                "-V", "subtitle=Every modification and its reason (original → current)",
                "-V", "author=Ngspice + OpenVAF Enhancements project",
                "-V", f"date={datetime.date.today():%B %Y}",
            ], capture_output=True, text=True)
            if r.returncode != 0:
                sys.stderr.write(r.stderr[-800:])
                sys.exit(1)
            warn = r.stderr.count("Missing character")
            print(f"{stem}.pdf written ({warn} glyph warnings)")
            verify_index_rows(stem)


if __name__ == "__main__":
    main()
