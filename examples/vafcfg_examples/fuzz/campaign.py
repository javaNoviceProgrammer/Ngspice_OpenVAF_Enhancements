#!/usr/bin/env python3
"""openvaf-r fuzzing campaign driver.

Classifies every compile as ok / diag / PANIC / CRASH / HANG / OVERFLOW /
ASSERT, deduplicates findings by panic SITE (file:line from the crash log, not
the input), and keeps one reproducer per distinct site.

A clean diagnostic is a PASS -- rejecting bad input is correct behaviour. The
findings are: a panic, a signal, a hang, or (on the amplified build) an
arithmetic overflow or a failed debug assertion.
"""
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMPD = os.environ.get("TMPDIR", "/tmp").rstrip("/")

PANIC_SITE = re.compile(r"Panic occurred in file '([^']+)' at line (\d+)")
PANIC_MSG = re.compile(r"at line \d+\n(.+)")


def crash_site(before):
    """Read the newest crash log written after `before`; return (site, msg)."""
    try:
        logs = [(os.path.getmtime(os.path.join(TMPD, p)), p)
                for p in os.listdir(TMPD) if p.startswith("openvaf-crash-")]
    except OSError:
        return ("?", "")
    logs = [(t, p) for t, p in logs if t >= before - 1]
    if not logs:
        return ("?", "")
    txt = open(os.path.join(TMPD, max(logs)[1]), errors="replace").read()
    m = PANIC_SITE.search(txt)
    site = "%s:%s" % (m.group(1), m.group(2)) if m else "?"
    m2 = PANIC_MSG.search(txt)
    return (site, (m2.group(1).strip() if m2 else "")[:90])


def run_one(binary, path, timeout):
    t0 = time.time()
    try:
        r = subprocess.run([binary, path, "-o", path + ".osdi"],
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", "", time.time() - t0
    dt = time.time() - t0
    out = r.stdout + r.stderr
    if r.returncode == 0:
        return "ok", "", dt
    if r.returncode < 0:
        return "CRASH", "signal %d" % (-r.returncode), dt
    if r.returncode == 101 or "has crashed" in out:
        site, msg = crash_site(t0)
        if "with overflow" in msg:
            return "OVERFLOW", "%s  %s" % (site, msg), dt
        if "assertion" in msg.lower():
            return "ASSERT", "%s  %s" % (site, msg), dt
        return "PANIC", "%s  %s" % (site, msg), dt
    return "diag", "", dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", default="gen_cross.py")
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--seed0", type=int, default=1)
    ap.add_argument("--bin", required=True)
    ap.add_argument("--timeout", type=float, default=25.0)
    ap.add_argument("--tag", default="c")
    a = ap.parse_args()

    tally = {}
    seen = {}
    slow = []
    work = os.path.join(HERE, "work_%s" % a.tag)
    os.makedirs(work, exist_ok=True)
    src = os.path.join(work, "in.va")

    for k in range(a.iters):
        seed = a.seed0 + k
        gen = subprocess.run([sys.executable, os.path.join(HERE, a.gen),
                              "--seed", str(seed)], capture_output=True, text=True)
        if gen.returncode != 0:
            continue
        open(src, "w").write(gen.stdout)
        verdict, detail, dt = run_one(a.bin, src, a.timeout)
        tally[verdict] = tally.get(verdict, 0) + 1
        if dt > 8.0 and verdict == "ok":
            slow.append((round(dt, 1), seed))
        if verdict in ("PANIC", "CRASH", "HANG", "OVERFLOW", "ASSERT"):
            key = (verdict, detail.split("  ")[0])
            if key not in seen:
                seen[key] = seed
                keep = os.path.join(work, "repro_%s_%d.va" % (verdict, seed))
                open(keep, "w").write(gen.stdout)
                print("  %-9s seed=%-6d %s" % (verdict, seed, detail), flush=True)
        if (k + 1) % 100 == 0:
            print("  ... %d/%d  %s" % (k + 1, a.iters,
                  " ".join("%s=%d" % kv for kv in sorted(tally.items()))), flush=True)

    print("\n%d runs: %s" % (a.iters, " ".join("%s=%d" % kv for kv in sorted(tally.items()))))
    print("distinct findings: %d" % len(seen))
    for (v, site), seed in sorted(seen.items()):
        print("   %-9s %-46s seed=%d" % (v, site, seed))
    if slow:
        slow.sort(reverse=True)
        print("slowest clean compiles: %s" % slow[:5])


main()
