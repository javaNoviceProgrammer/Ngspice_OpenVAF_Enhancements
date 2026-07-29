#!/usr/bin/env python3
"""Delta-debug a .va file down to a minimal input that still reproduces a
specific panic. Greedy: try deleting each line (and each contiguous run),
keep the deletion whenever the panic signature survives."""
import os
import subprocess
import sys

NG = os.environ.get("OPENVAF_BIN")
SIG = os.environ.get("SIG", "")          # substring that must appear (panic site)


def panics(lines, tmp):
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
    # confirm it is the SAME panic, not a different one
    D = os.environ.get("TMPDIR", "/tmp").rstrip("/")
    logs = sorted([p for p in os.listdir(D) if p.startswith("openvaf-crash-")],
                  key=lambda p: os.path.getmtime(os.path.join(D, p)))
    if not logs:
        return False
    txt = open(os.path.join(D, logs[-1]), errors="replace").read()
    return SIG in txt


def main():
    src = open(sys.argv[1]).read().split("\n")
    tmp = sys.argv[2]
    assert panics(src, tmp), "input does not reproduce"
    cur = src
    chunk = max(1, len(cur) // 4)
    while chunk >= 1:
        i = 0
        while i < len(cur):
            cand = cur[:i] + cur[i + chunk:]
            if cand and panics(cand, tmp):
                cur = cand
            else:
                i += chunk
        chunk //= 2
    # final single-line pass until fixpoint
    changed = True
    while changed:
        changed = False
        for i in range(len(cur) - 1, -1, -1):
            cand = cur[:i] + cur[i + 1:]
            if cand and panics(cand, tmp):
                cur = cand
                changed = True
    print("\n".join(cur))
    sys.stderr.write("minimized %d -> %d lines\n" % (len(src), len(cur)))


main()
