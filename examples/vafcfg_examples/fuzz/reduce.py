#!/usr/bin/env python3
"""Structural reducer for Verilog-A crash inputs.

The line-at-a-time minimizer stalls as soon as every remaining line is
structurally load-bearing (you cannot delete a `begin` without breaking the
`end`). This one only ever deletes BALANCED ranges -- a whole statement subtree,
brace-matched over begin/end and case/endcase -- so it keeps the file parseable
while collapsing whole constructs at once. It also applies a set of
value-simplifying rewrites (complex expression -> constant, etc.).

Iterates to a fixpoint. Requires the panic signature to stay identical.
"""
import os
import re
import subprocess
import sys

NG = os.environ["OPENVAF_BIN"]
SIG = os.environ.get("SIG", "")
TMPD = os.environ.get("TMPDIR", "/tmp").rstrip("/")

OPEN = re.compile(r"\bbegin\b|\bcase[xz]?\s*\(")
CLOSE = re.compile(r"\bend\b|\bendcase\b")


def bal(lines):
    o = sum(len(OPEN.findall(l)) for l in lines)
    c = sum(len(CLOSE.findall(l)) for l in lines)
    return o == c


def repro(lines, tmp):
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    try:
        r = subprocess.run([NG, tmp, "-o", tmp + ".osdi"], capture_output=True,
                           text=True, timeout=60, errors="replace")
    except subprocess.TimeoutExpired:
        return False
    if r.returncode != 101:
        return False
    if not SIG:
        return True
    if SIG in (r.stdout + r.stderr):
        return True
    logs = [p for p in os.listdir(TMPD) if p.startswith("openvaf-crash-")]
    if not logs:
        return False
    newest = max(logs, key=lambda p: os.path.getmtime(os.path.join(TMPD, p)))
    return SIG in open(os.path.join(TMPD, newest), errors="replace").read()


REWRITES = [
    (re.compile(r"\$rtoi\(\$itor\(([^()]*)\)\)"), r"\1"),
    (re.compile(r"\(\(([a-z0-9_]+) < \([^()]*\)\) \? ([0-9]+) : ([0-9]+)\)"), r"\2"),
    (re.compile(r"casex|casez"), "case"),
    (re.compile(r"'b[01xz?]+"), "1"),
    (re.compile(r"\$discontinuity\(\d\)"), "$discontinuity(0)"),
    (re.compile(r"V\(n0, n1\)"), "V(n0)"),
]


def main():
    cur = open(sys.argv[1]).read().rstrip("\n").split("\n")
    tmp = sys.argv[2]
    assert repro(cur, tmp), "input does not reproduce"

    changed = True
    while changed:
        changed = False
        # 1. delete balanced ranges, largest first
        n = len(cur)
        for span in range(n, 0, -1):
            for i in range(0, n - span + 1):
                seg = cur[i:i + span]
                if not bal(seg):
                    continue
                cand = cur[:i] + cur[i + span:]
                if cand and repro(cand, tmp):
                    cur = cand
                    n = len(cur)
                    changed = True
                    break
            if changed:
                break
        if changed:
            continue
        # 2. simplify expressions in place
        for k, (pat, rep) in enumerate(REWRITES):
            cand = [pat.sub(rep, l) for l in cur]
            if cand != cur and repro(cand, tmp):
                cur = cand
                changed = True
                break
        if changed:
            continue
        # 3. strip now-unused declarations
        for i, l in enumerate(cur):
            m = re.match(r"\s*(real|integer)\s+([a-z_0-9]+);", l)
            if m and sum(l2.count(m.group(2)) for l2 in cur) <= 1:
                cand = cur[:i] + cur[i + 1:]
                if repro(cand, tmp):
                    cur = cand
                    changed = True
                    break

    print("\n".join(cur))
    sys.stderr.write("reduced to %d lines\n" % len(cur))


main()
