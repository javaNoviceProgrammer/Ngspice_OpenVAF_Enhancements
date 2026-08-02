#!/usr/bin/env python3
"""Validate docs/index.html, the feature catalog served by GitHub Pages.

Usage:  python3 docs/check_catalog.py

WHY THIS EXISTS. The catalog's chip data lives in one inline `<script>`. A single
bad character anywhere in it is a SyntaxError, and a SyntaxError does not degrade
the page -- it stops the whole script from parsing, so every chip vanishes while
the header, the stat line and the filter buttons still render perfectly. The page
looks fine and is empty.

That is exactly what happened: the Enhancement-399 chip described the bug it
shipped by quoting `analysis("tarn")`, and those raw double quotes closed the
JS string early. The catalog rendered ZERO chips from Enhancement-399 until
Enhancement-404 -- five releases -- and nothing caught it, because nothing here
had ever parsed the data rather than pattern-matching it.

So this script PARSES: the array is converted to JSON and handed to json.loads,
which fails on precisely the class of damage a regex sweep reads straight past.
A raw `"` in a chip label breaks the page twice over, since the label is also
interpolated into `title="..."` -- use single quotes in labels.

It also checks the count invariant. Every number on the page that claims to count
enhancements must equal the number of DISTINCT chips, and there are three of them
in two different phrasings; two had been stale for 68 and 245 enhancements
respectively while the one in the lede was kept current by hand.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PAGE = os.path.join(HERE, "index.html")

# every place the page states a count of enhancements, and what it looks like
COUNT_PATTERNS = [
    (r'project: (\d+) enhancements', "meta description"),
    (r'<b>(\d+) enhancements</b>', "header lede"),
    (r'<div class="n">(\d+)</div><div class="l">enhancements</div>', "stat block"),
    (r'catalog of (\d+) implemented features', "screen-reader summary"),
]


def extract_array(text):
    """Return the `var F=[...]` array literal, matched by bracket depth."""
    start = text.index("var F=[")
    i = text.index("[", start)
    depth, in_str, j = 0, False, i
    while j < len(text):
        c = text[j]
        if in_str:
            if c == "\\":
                j += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    raise SystemExit("FAIL: the chip data array is not bracket-balanced")


def to_json(js):
    """JS object literal -> JSON. Only the shapes this file actually uses."""
    # bare keys d:/n:/x:/c: -> quoted. Done on the literal, not inside strings:
    # the keys always follow `{` or `,`, which a string body never does here.
    out = re.sub(r'([{,])\s*([dnxc]):', r'\1"\2":', js)
    # JS allows \' inside a double-quoted string; JSON does not.
    return out.replace("\\'", "'")


def main():
    text = open(PAGE, encoding="utf-8").read()
    errors = []

    array = extract_array(text)
    try:
        areas = json.loads(to_json(array))
    except json.JSONDecodeError as e:
        ctx = array[max(0, e.pos - 120):e.pos + 60].replace("\n", " ")
        print(f"FAIL: the chip data is not valid -- the page will render NO chips.\n"
              f"  {e.msg} at offset {e.pos}\n"
              f"  ...{ctx}...\n"
              f"  (a raw double quote inside a chip label is the usual cause; "
              f"use single quotes)")
        return 1

    chips = [c for a in areas for c in a["c"]]
    nums = [c[0] for c in chips]
    distinct = sorted(set(nums))
    print(f"chip data parses: {len(areas)} areas, {len(chips)} entries, "
          f"{len(distinct)} distinct enhancements")

    # a label with a raw " parses fine as JSON but breaks title="..." in the page
    for a in areas:
        for num, label in a["c"]:
            if '"' in label:
                errors.append(f'E-{num} label contains a raw double quote; it '
                              f'breaks title="..." -- use single quotes')

    for pattern, what in COUNT_PATTERNS:
        found = re.findall(pattern, text)
        if len(found) != 1:
            errors.append(f"{what}: expected one count, found {found}")
        elif int(found[0]) != len(distinct):
            errors.append(f"{what}: says {found[0]}, but there are "
                          f"{len(distinct)} distinct chips")

    missing = [n for n in distinct
               if not os.path.exists(os.path.join(ROOT, "enhancements_doc",
                                                  f"Enhancement-{n}.md"))]
    if missing:
        errors.append(f"chips link to missing write-ups: {missing}")

    if errors:
        print("\nFAIL:")
        for e in errors:
            print("  -", e)
        return 1
    print(f"counts agree at {len(distinct)} in all {len(COUNT_PATTERNS)} places; "
          f"every chip has a write-up")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
