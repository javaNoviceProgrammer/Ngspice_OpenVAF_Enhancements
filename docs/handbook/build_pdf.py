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

# image links (![alt](target)) are handled separately -- embedded from a local
# path -- so the LINK rewriter (which turns links into GitHub URLs) skips them
# via the negative lookbehind for the leading '!'.
IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)\)")


def image_local(alt, target, src_dir):
    """Resolve a relative figure path to an absolute local path so pandoc
    embeds the actual image (rather than the LINK rewriter turning it into a
    GitHub blob URL, which is an HTML page xelatex cannot size)."""
    if target.startswith(("http://", "https://")):
        return f"![{alt}]({target})"
    absp = os.path.normpath(os.path.join(ROOT, src_dir, target))
    return f"![{alt}]({absp})"


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
            line = IMG.sub(
                lambda mm: image_local(mm.group(1), mm.group(2), src_dir), line)
            line = LINK.sub(
                lambda mm: f"[{mm.group(1)}]({rewrite_target(mm.group(2), src_dir)})",
                line,
            )
        out.append(line)
    return "\n".join(out)


INDEX_LUA = r"""
-- Render the enhancement index (chapter 5) as a definition list rather than a
-- table.
--
-- WHY: a LaTeX table cell is a \parbox -- it cannot break across a page. The
-- index's "What it delivered" cells run to thousands of characters, so any row
-- taller than one page silently OVERFLOWED and was CLIPPED: the tail of the cell
-- was simply dropped while pandoc and xelatex both reported success. Rows 210
-- through 214 lost their endings that way (~2300 chars still fit; >=2500 did
-- not). A definition list's definitions are ordinary paragraphs, so they flow
-- across pages and nothing can be lost. verify_index_rows() enforces it.
--
-- Only THIS table is rewritten (matched on its header); every other table in the
-- handbook keeps its tabular rendering and its column widths (see WIDTHS_LUA).

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
  if #t.colspecs ~= 4 then return false end
  local h = header_of(t)
  return h[1] == "#" and h[2] == "What it delivered"
end

-- A cell holds Blocks; flatten them to a single inline list.
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

local function append(dst, src)
  for _, x in ipairs(src) do dst[#dst + 1] = x end
end

function Table(t)
  if not is_index_table(t) then return nil end
  local items = {}
  for _, body in ipairs(t.bodies) do
    for _, row in ipairs(body.body) do
      local term = cell_inlines(row.cells[1])          -- the enhancement number
      local def = cell_inlines(row.cells[2])           -- what it delivered
      local links = {}                                 -- Doc / Examples close the entry
      for i = 3, 4 do
        local l = cell_inlines(row.cells[i])
        if #l > 0 then
          if #links > 0 then
            append(links, {pandoc.Space(), pandoc.Str("·"), pandoc.Space()})
          end
          append(links, l)
        end
      end
      if #links > 0 then
        append(def, {pandoc.Space(), pandoc.Str("—"), pandoc.Space()})
        append(def, links)
      end
      items[#items + 1] = {term, {{pandoc.Para(def)}}}
    end
  end
  return pandoc.DefinitionList(items)
end
"""


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

    Everything else is noise for this purpose and actively harmful: markdown
    syntax (`` ` ``, ``*``, ``\\``), TeX's intra-word line breaks
    (``mir_opt::const_eval::eval_`` + ``binary``), hyphenation, smart dashes and
    quotes, and math glyphs rewritten by ``newunicodechar`` (``‖`` → ``\\Vert``)
    all differ between the source and the PDF's text layer while the letters do
    not. A naive probe that strips only ``[`*\\]`` reports false clipping on rows
    where ``*`` is a literal glob (``laplace_*`` → ``laplace_``), which is
    exactly how this check was first got wrong.
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
            out.append("\n".join(lines))
    return _sig("".join(out))


#  [text](target) -> text.  A link's TARGET never reaches the PDF's text layer,
#  only its text does, so the target must go before signing.
LINK_TEXT_ONLY = re.compile(r"\[([^\]]*)\]\([^)\s]*\)")


def index_rows():
    """[(number, what-it-delivered cell)] from the enhancement-index chapter."""
    rows = []
    for line in open(os.path.join(HERE, "05-enhancement-index.md")):
        if not line.startswith("| "):
            continue
        cells = line.split("|")
        if len(cells) > 2 and cells[1].strip().isdigit():
            rows.append((int(cells[1].strip()), cells[2]))
    return rows


def verify_index_rows():
    """Assert every enhancement-index row reached the PDF *in full*.

    A LaTeX table cell cannot break across a page, so a long index row used to
    overflow and be silently CLIPPED -- its tail dropped, with pandoc, xelatex
    and this script all reporting success (rows 210-214 were cut mid-sentence
    before INDEX_LUA rendered the index as a definition list instead). Nothing
    surfaced it: the PDF is a binary, so a shortened row is invisible in review.

    This is that class of failure's guard. It is deliberately end-anchored --
    clipping drops the END of a cell -- and it fails the BUILD, because a doc is
    not built until it is proven built. See the doc-pdf-build-verification rule.
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

    text = _pdf_text(OUT)
    rows = index_rows()
    # A guard that silently matches nothing always passes. If the chapter's table
    # is reformatted so the rows stop parsing, say so instead of reporting OK.
    if len(rows) < 100:
        sys.exit(f"ERROR: only parsed {len(rows)} enhancement-index rows from "
                 "05-enhancement-index.md -- the check cannot be trusted; fix "
                 "index_rows() to match the chapter's format.")

    clipped = []
    for n, cell in rows:
        tail = _sig(LINK_TEXT_ONLY.sub(r"\1", cell))[-40:]
        if tail and tail not in text:
            clipped.append(n)

    if clipped:
        sys.exit(f"ERROR: {len(clipped)} enhancement-index row(s) are CLIPPED in "
                 f"{os.path.relpath(OUT, ROOT)} -- their text is missing from the "
                 f"PDF: {clipped}\n"
                 "       Content is being silently dropped. See INDEX_LUA.")
    print(f"verified {len(rows)} enhancement-index rows render in full")


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
% em/en dashes: force the text font (mathspec would otherwise route a dash
% landing in a math-ish context through Latin Modern, which lacks U+2014).
\newunicodechar{—}{\textemdash}
\newunicodechar{–}{\textendash}
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
        # INDEX_LUA must be its OWN filter file, applied first: it also defines a
        # global `Table`, so sharing a file with widths_lua would simply have the
        # second definition overwrite the first. Once the index is a definition
        # list, widths_lua no longer sees it as a table.
        index_lua = os.path.join(td, "index.lua")
        open(md, "w").write(combined)
        open(hdr, "w").write(header_tex)
        open(index_lua, "w").write(INDEX_LUA)
        open(lua, "w").write(widths_lua + BREAKPATHS_LUA)
        cmd = [
            "pandoc", md, "-f", "gfm+attributes", "-o", OUT,
            "--pdf-engine=xelatex", "--toc", "--toc-depth=2",
            "-H", hdr, "--lua-filter", index_lua, "--lua-filter", lua,
            # Load `mathspec` instead of pandoc's default `unicode-math` for
            # the xelatex engine: unicode-math makes glyphs like the integral
            # sign math-active, which breaks the `newunicodechar` text-mode
            # mappings above (they render fine in prose under mathspec).
            "-V", "mathspec",
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
    verify_index_rows()
    print(f"wrote {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
