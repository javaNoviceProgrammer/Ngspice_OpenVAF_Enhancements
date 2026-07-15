#!/usr/bin/env python3
"""Regenerate the single-file PDF of the globalized-Newton (line search) write-up.

Usage:  python3 docs/internals/ngspice_internals/build_linesearch_pdf.py
Needs pandoc + xelatex. Repo-relative links become GitHub URLs; math / arrow /
norm glyphs are mapped to symbols the text & mono fonts can render.
"""
import datetime
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # docs/internals/ngspice_internals
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # repo root
GITHUB = "https://github.com/javaNoviceProgrammer/Ngspice_OpenVAF_Enhancements"
STEM = "ngspice_linesearch_globalized_newton"

HEADER_TEX = r"""
\usepackage{titlesec}
\newcommand{\sectionbreak}{\clearpage}
\usepackage{fvextra}
\fvset{breaklines,breakanywhere}
\usepackage{amssymb}
\usepackage{amsmath}
\usepackage{newunicodechar}
\newunicodechar{‑}{-}
\newunicodechar{–}{--}
\newunicodechar{→}{\ensuremath{\rightarrow}}
\newunicodechar{←}{\ensuremath{\leftarrow}}
\newunicodechar{≤}{\ensuremath{\leq}}
\newunicodechar{≥}{\ensuremath{\geq}}
\newunicodechar{≠}{\ensuremath{\neq}}
\newunicodechar{≈}{\ensuremath{\approx}}
\newunicodechar{≡}{\ensuremath{\equiv}}
\newunicodechar{∝}{\ensuremath{\propto}}
\newunicodechar{∈}{\ensuremath{\in}}
\newunicodechar{·}{\ensuremath{\cdot}}
\newunicodechar{×}{\ensuremath{\times}}
\newunicodechar{−}{\ensuremath{-}}
\newunicodechar{∞}{\ensuremath{\infty}}
\newunicodechar{∂}{\ensuremath{\partial}}
\newunicodechar{√}{\ensuremath{\surd}}
\newunicodechar{Δ}{\ensuremath{\Delta}}
\newunicodechar{λ}{\ensuremath{\lambda}}
\newunicodechar{φ}{\ensuremath{\varphi}}
\newunicodechar{ε}{\ensuremath{\varepsilon}}
\newunicodechar{µ}{\ensuremath{\mu}}
\newunicodechar{Ω}{\ensuremath{\Omega}}
\newunicodechar{‖}{\ensuremath{\Vert}}
\newunicodechar{½}{\ensuremath{\tfrac{1}{2}}}
\newunicodechar{¼}{\ensuremath{\tfrac{1}{4}}}
\newunicodechar{²}{\textsuperscript{2}}
"""

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
  if total < 60 then return nil end
  for i = 1, ncols do
    local w = maxlen[i] / total
    if w < 0.07 then w = 0.07 end
    t.colspecs[i] = {t.colspecs[i][1], w * 0.96}
  end
  return t
end
"""


# Inside code (`inline` and ```fenced```), math glyphs can't go through the
# text-mode font mappings (they'd become \texttt{\ensuremath{...}} and break), so
# ASCII-ify them there. Prose keeps its unicode (handled by newunicodechar).
_UNI2ASCII = {"‖": "||", "λ": "lambda", "∈": " in ", "·": "*", "−": "-",
              "½": "1/2", "¼": "1/4", "…": "...", "Δ": "d", "→": "->",
              "≤": "<=", "∂": "d", "×": "x"}


def _ascii_code(text):
    def tr(s):
        for u, a in _UNI2ASCII.items():
            s = s.replace(u, a)
        return s
    text = re.sub(r"```.*?```", lambda m: tr(m.group(0)), text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", lambda m: tr(m.group(0)), text)
    return text


def githubify(text):
    def rewrite(m):
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "#")):
            return m.group(0)
        rel = os.path.relpath(
            os.path.normpath(os.path.join(HERE, target.split("#")[0])), ROOT)
        kind = "tree" if os.path.isdir(os.path.join(ROOT, rel)) else "blob"
        return f"[{label}]({GITHUB}/{kind}/main/{rel})"
    return re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", rewrite, text)


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
        open(md, "w").write(_ascii_code(githubify(open(os.path.join(HERE, STEM + ".md")).read())))
        open(hdr, "w").write(HEADER_TEX)
        open(lua, "w").write(WIDTHS_LUA + BREAKPATHS_LUA)
        r = subprocess.run([
            "pandoc", md, "-f", "gfm", "-o", os.path.join(HERE, STEM + ".pdf"),
            "--pdf-engine=xelatex", "--toc", "--toc-depth=2",
            "-H", hdr, "--lua-filter", lua,
            "-V", "documentclass=report", "-V", "papersize=a4",
            "-V", "geometry:margin=2.2cm",
            "-V", "mainfont=STIX Two Text", "-V", "monofont=Menlo",
            "-V", "fontsize=11pt", "-V", "colorlinks=true",
            "-V", "title=A Globalized (Damped) Newton for ngspice",
            "-V", "subtitle=Background, reasoning, implementation, and validation of the Armijo line search (Enhancement-111)",
            "-V", "author=Ngspice + OpenVAF Enhancements project",
            "-V", f"date={datetime.date.today():%B %Y}",
        ], capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stderr[-1500:])
            sys.exit(1)
        print(f"{STEM}.pdf written "
              f"({r.stderr.count('Missing character')} glyph warnings)")


if __name__ == "__main__":
    main()
