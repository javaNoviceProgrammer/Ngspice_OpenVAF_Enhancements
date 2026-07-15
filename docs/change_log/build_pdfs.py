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


def main():
    with tempfile.TemporaryDirectory() as td:
        hdr = os.path.join(td, "h.tex")
        lua = os.path.join(td, "w.lua")
        open(hdr, "w").write(HEADER_TEX)
        open(lua, "w").write(WIDTHS_LUA + BREAKPATHS_LUA)
        for stem, title in REPORTS:
            md_in = os.path.join(HERE, stem + ".md")
            md_tmp = os.path.join(td, stem + ".md")
            open(md_tmp, "w").write(githubify(open(md_in).read()))
            r = subprocess.run([
                "pandoc", md_tmp, "-f", "gfm",
                "-o", os.path.join(HERE, stem + ".pdf"),
                "--pdf-engine=xelatex", "--toc", "--toc-depth=2",
                "-H", hdr, "--lua-filter", lua,
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


if __name__ == "__main__":
    main()
