#!/usr/bin/env python3
"""Regenerate the PDF edition of the transient-noise analysis note.

Usage:  python3 docs/internals/ngspice_internals/build_trnoise_pdf.py
Needs pandoc + xelatex, and the figures under ngspice_trnoise_figs/ that
make_trnoise_figs.py produces. Repo-relative *links* become GitHub URLs; *image*
paths stay local so xelatex embeds the PNGs.

This document carries real LaTeX math, so the reader is gfm+tex_math_dollars and
the preamble pulls in amsmath for \\boxed.
"""
import datetime
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GITHUB = "https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements"
STEM = "ngspice_transient_noise_analysis"

HEADER_TEX = r"""
\usepackage{fvextra}
\fvset{breaklines,breakanywhere}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{newunicodechar}
\newunicodechar{→}{\ensuremath{\rightarrow}}
\newunicodechar{×}{\ensuremath{\times}}
\newunicodechar{·}{\ensuremath{\cdot}}
\newunicodechar{−}{\ensuremath{-}}
\newunicodechar{≈}{\ensuremath{\approx}}
\newunicodechar{µ}{\ensuremath{\mu}}
\newunicodechar{Ω}{\ensuremath{\Omega}}
\newunicodechar{√}{\ensuremath{\surd}}
\newunicodechar{²}{\ensuremath{^2}}
\newunicodechar{–}{--}
\newunicodechar{—}{---}
% keep figures from overflowing the text width
\usepackage{graphicx}
\setkeys{Gin}{width=0.85\linewidth,keepaspectratio}
"""

# force wrapping table columns proportional to their content (pandoc otherwise
# lets a wide cell run off the right margin)
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
  if total < 40 then return nil end
  for i = 1, ncols do
    local w = maxlen[i] / total
    if w < 0.10 then w = 0.10 end
    t.colspecs[i] = {t.colspecs[i][1], w * 0.96}
  end
  return t
end
"""


def githubify(text):
    """Rewrite repo-relative *links* to GitHub URLs, but leave *images* (![]())
    with their local relative path so the PDF engine embeds the PNG."""
    def rewrite(m):
        bang, label, target = m.group(1), m.group(2), m.group(3)
        if bang == "!":                                   # image: keep local
            return m.group(0)
        if target.startswith(("http://", "https://", "#")):
            return m.group(0)
        rel = os.path.relpath(
            os.path.normpath(os.path.join(HERE, target.split("#")[0])), ROOT)
        kind = "tree" if os.path.isdir(os.path.join(ROOT, rel)) else "blob"
        return f"[{label}]({GITHUB}/{kind}/main/{rel})"
    return re.sub(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)", rewrite, text)


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
        md = os.path.join(td, "c.md")
        hdr = os.path.join(td, "h.tex")
        lua = os.path.join(td, "w.lua")
        open(md, "w").write(githubify(open(os.path.join(HERE, STEM + ".md")).read()))
        open(hdr, "w").write(HEADER_TEX)
        open(lua, "w").write(WIDTHS_LUA + BREAKPATHS_LUA)
        r = subprocess.run([
            "pandoc", md, "-f", "gfm+tex_math_dollars", "-o", os.path.join(HERE, STEM + ".pdf"),
            "--pdf-engine=xelatex", "--toc", "--toc-depth=2",
            "-H", hdr, "--resource-path", HERE, "--lua-filter", lua,
            "-V", "documentclass=article", "-V", "papersize=a4",
            "-V", "geometry:margin=2.2cm",
            "-V", "mainfont=STIX Two Text", "-V", "monofont=Menlo",
            "-V", "fontsize=11pt", "-V", "colorlinks=true",
            "-V", "title=Transient Noise in ngspice",
            "-V", "subtitle=Built-in sources and OSDI (Verilog-A) devices: mechanism, amplitude law, and verification",
            "-V", "author=Ngspice + OpenVAF Enhancements project",
            "-V", f"date={datetime.date.today():%B %Y}",
        ], capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stderr[-2000:])
            sys.exit(1)
        print(f"{STEM}.pdf written "
              f"({r.stderr.count('Missing character')} glyph warnings)")


if __name__ == "__main__":
    main()
