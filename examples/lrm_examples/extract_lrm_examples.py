#!/usr/bin/env python3
"""Extract code examples from the Verilog-AMS LRM PDF by font.

Code in the LRM is typeset in Courier New (regular + bold for keywords);
prose is Times New Roman and headers/footers are Arial.  A line whose text
is overwhelmingly Courier is a code line; consecutive code lines form a
block, and blocks that end a page with unbalanced module/begin structure
are joined with the first block of the next page.

Formal-syntax (BNF) boxes are also Courier; they are dropped by the
"::=" test.  Output: one .txt per block under raw_blocks/, named
block_<page>_<n>.txt, plus an index listing.
"""
import json
import os
import re
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = sys.argv[1] if len(sys.argv) > 1 else \
    os.path.join(HERE, "..", "..", "docs", "VAMS-LRM-2023.pdf")
OUT = os.path.join(HERE, "raw_blocks")

CODE_FONTS = ("CourierNewPSMT", "CourierNewPS-BoldMT", "CourierNewPS-ItalicMT",
              "CourierNewPS-BoldItalicMT")

# The PDF uses typographic glyphs inside code (en-dashes for minus, curly
# quotes); normalize to the ASCII the language actually uses.
UNICODE_FIXES = {
    "–": "-", "—": "-", "−": "-",   # en/em dash, minus sign
    "‘": "'", "’": "'",                  # curly single quotes
    "“": '"', "”": '"',                  # curly double quotes
    " ": " ", "…": "...",                # nbsp, ellipsis char
}


def normalize(text):
    for k, v in UNICODE_FIXES.items():
        text = text.replace(k, v)
    return text


def page_code_lines(page):
    """Return [(y0, x0, text, char_width)] for lines that are >=80% Courier."""
    lines = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            total = code = 0
            parts = []
            min_x = None
            widths = []
            for s in l["spans"]:
                t = s["text"]
                total += len(t.strip())
                if s["font"] in CODE_FONTS:
                    code += len(t.strip())
                    if t.strip():
                        widths.append((s["bbox"][2] - s["bbox"][0]) / max(len(t), 1))
                if min_x is None:
                    min_x = s["bbox"][0]
                parts.append(t)
            if total == 0 or code / total < 0.8:
                continue
            text = "".join(parts).rstrip()
            if not text.strip():
                continue
            cw = sum(widths) / len(widths) if widths else 5.4
            lines.append((l["bbox"][1], min_x, text, cw))
    lines.sort(key=lambda t: (round(t[0]), t[1]))

    # Merge segments that share a baseline (e.g. code with an aligned
    # trailing comment, which the PDF stores as separate line objects).
    merged = []
    for y, x, text, cw in lines:
        if merged and abs(y - merged[-1][0]) < 2.0:
            py, px, ptext, pcw = merged[-1]
            col = max(0, round((x - 90.0) / pcw))
            cur_len = round((px - 90.0) / pcw) + len(ptext)
            pad = max(1, col - cur_len)
            merged[-1] = (py, px, ptext + " " * pad + text.strip(), pcw)
        else:
            merged.append((y, x, text, cw))
    return merged


def main():
    doc = fitz.open(PDF)
    os.makedirs(OUT, exist_ok=True)

    # First pass: per-page code lines.
    per_page = {}
    for pno in range(doc.page_count):
        cl = page_code_lines(doc[pno])
        if cl:
            per_page[pno] = cl

    # Group into blocks: consecutive lines with vertical gap < 1.8 line
    # heights stay together.
    blocks = []  # (start_page, [text lines])
    for pno, lines in sorted(per_page.items()):
        cur = None
        prev_y = None
        for y, x, text, cw in lines:
            # Reconstruct indentation from x offset (left margin ~ 108pt for
            # example bodies, but varies; use 90pt as base).
            indent = max(0, round((x - 90.0) / cw))
            line = " " * indent + text.strip()
            if cur is not None and prev_y is not None and (y - prev_y) < 22:
                cur.append(line)
            else:
                if cur:
                    blocks.append((pno + 1, cur))
                cur = [line]
            prev_y = y
        if cur:
            blocks.append((pno + 1, cur))

    # Join across page breaks: a block whose module/endmodule (or
    # begin/end, function/endfunction, discipline/enddiscipline,
    # nature/endnature) balance is open joins the next block if it starts
    # on the following page.
    def open_balance(lines):
        text = "\n".join(lines)
        bal = 0
        for kw, endkw in (("module", "endmodule"), ("function", "endfunction"),
                          ("discipline", "enddiscipline"), ("nature", "endnature"),
                          ("connectmodule", "endconnectmodule"),
                          ("primitive", "endprimitive"), ("case", "endcase")):
            starts = len(re.findall(r"(?<![\w$`])" + kw + r"(?![\w$])", text))
            ends = len(re.findall(r"(?<![\w$`])" + endkw + r"(?![\w$])", text))
            # 'endmodule' also matches the 'module' pattern? No: lookbehind
            # blocks mid-word matches, and endmodule starts with 'e'.
            bal += starts - ends
        bal += text.count("begin") - len(re.findall(r"(?<![\w$`])end(?![\w$])", text))
        return bal > 0

    joined = []
    for page, lines in blocks:
        if joined and open_balance(joined[-1][1]) and page <= joined[-1][2] + 1:
            joined[-1][1].extend(lines)
            joined[-1][2] = page
        else:
            joined.append([page, lines, page])

    index = []
    n_by_page = {}
    for page, lines, endpage in joined:
        body = normalize("\n".join(lines))
        if "::=" in body:            # formal syntax box, not an example
            continue
        if len(lines) < 2 and ";" not in body and "module" not in body:
            continue                 # stray inline monospace fragment
        # Keyword / directive / attribute-name tables are Courier but carry
        # no statement punctuation at all; C code (VPI annex) is Courier but
        # not Verilog.  Stray end-keyword lines are page-break leftovers.
        if not re.search(r"[;(){}=`]", body):
            continue
        if "typedef struct" in body or "vpiHandle" in body:
            continue
        if all(re.fullmatch(r"\s*(endmodule|endnature|enddiscipline|endprimitive|end)\s*",
                            l) for l in lines):
            continue
        n = n_by_page.get(page, 0) + 1
        n_by_page[page] = n
        name = f"block_{page:03d}_{n}.txt"
        with open(os.path.join(OUT, name), "w") as f:
            f.write(body + "\n")
        index.append({"file": name, "page": page, "end_page": endpage,
                      "lines": len(lines)})

    with open(os.path.join(HERE, "raw_index.json"), "w") as f:
        json.dump(index, f, indent=1)
    print(f"{len(index)} candidate blocks -> {OUT}")


if __name__ == "__main__":
    main()
