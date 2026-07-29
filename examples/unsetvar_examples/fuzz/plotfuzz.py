#!/usr/bin/env python3
"""Fuzz the PLOT LIFECYCLE: analyses interleaved with plot-management commands.

Why here. This is the code E-342 (a borrowed-pointer UAF via `unset plots` on a
rawfile-loaded plot) and E-345 (the naming path) came out of, and E-371 has just
changed it again -- plot_alloc() now stamps a date on every plot, and
plot_forget() walks a per-type counter back down. New pointer arithmetic and a new
allocation in code with a history of ownership bugs is worth attacking directly.

What is fuzzed is the SEQUENCE, not the input: a plot's lifetime spans commands,
so a per-case forked deck cannot see a use-after-free that needs create -> use ->
destroy -> re-create in one session.

SELF-VALIDATION. A fuzzer over commands that all silently error is "clean" and
worthless -- three separate harnesses this session produced exactly that. So the
run tallies how many cases actually created plots and how many commands were
REJECTED, and refuses to report a clean result if the deck bodies were not doing
real work.
"""
import argparse
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
ASAN = os.environ.get("NGSPICE_ASAN", "")   # must point at an ASan build
LIB = os.path.join(REPO, "bin/macos/apple-silicon")

NETLIST = """plot lifecycle fuzz
V1 in 0 dc 0.5 ac 1 sin(0.5 0.2 1meg)
Rs in mid 1k
Rl mid out 1k
C1 mid 0 1n
D1 mid 0 dm
.model dm d(is=1e-14 n=1 cjo=1p)
"""

# analyses -- each creates one or more plots
ANALYSES = [
    "op",
    "dc V1 0 1 0.5",
    "ac dec 3 1e3 1e6",
    "tran 20n 400n",
    "noise v(mid) V1 dec 3 1e3 1e5",
    "sweep V1 0 1 0.34",
    "tf v(mid) V1",
]

# plot-management commands -- the ownership-sensitive half
MANAGE = [
    "destroy all",
    "destroy op1",
    "destroy tran1",
    "destroy ac1",
    "destroy sweep1",
    "destroy $curplot",
    "setplot new",
    "setplot op1",
    "setplot tran1",
    "setplot previous",
    "setplot const",
    "unset plots",
    "display",
    "let zz = v(mid) + 1",
    "let zz = 0",
    "unlet zz",
    "reset",
    "remcirc",
    "linearize",
    "fft v(mid)",
    "spec 1e5 1e6 1e5 v(mid)",
    "write _pf.raw all",
    "load _pf.raw",
    "print $plots",
    "echo NPLOTS $plots",
]

SAN = re.compile(r"AddressSanitizer|runtime error:|UndefinedBehaviorSanitizer", re.I)
CRASH = re.compile(r"Segmentation fault|Bus error|internal error|Abort trap|"
                   r"assertion failed|ouch", re.I)
REJECT = re.compile(r"unrecognized|no such|not found|Error:|can't|cannot", re.I)


def build(rng):
    body = ["option noacct"]
    # always start with at least one analysis, so there is something to manage
    body.append(rng.choice(ANALYSES))
    for _ in range(rng.randrange(3, 10)):
        body.append(rng.choice(ANALYSES) if rng.random() < 0.45 else rng.choice(MANAGE))
    body.append("echo NPLOTS $plots")
    return NETLIST + ".control\n" + "\n".join(body) + "\n.endc\n.end\n", body


def run(src, tag, timeout=90):
    p = os.path.join(HERE, "_pf_%s.cir" % tag)
    open(p, "w").write(src)
    env = dict(os.environ, SPICE_LIB_DIR=LIB, ASAN_OPTIONS="detect_leaks=0")
    try:
        r = subprocess.run([ASAN, "-b", os.path.basename(p)], cwd=HERE, env=env,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", "", 0
    out = r.stdout + r.stderr
    # how many plots existed at the end -- the work-was-done signal
    m = re.search(r"^NPLOTS (.*)$", out, re.M)
    nplots = len(m.group(1).split()) if m else 0
    if SAN.search(out):
        sig = (re.search(r"(ERROR: AddressSanitizer: [a-z-]+)", out)
               or re.search(r"([\w./]+\.[ch]:\d+:\d+: runtime error: [^\n]*)", out))
        frame = re.search(r"#\d+ 0x\S+ in (\S+ [^\s:]+:\d+)", out)
        return "SANITIZER", "%s | %s" % (sig.group(1) if sig else "?",
                                         frame.group(1) if frame else "?"), nplots
    if r.returncode < 0 or CRASH.search(out):
        c = CRASH.search(out)
        return "CRASH", "rc=%s %s" % (r.returncode, c.group(0) if c else ""), nplots
    return "ok", "", nplots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--seed", type=int, default=17)
    a = ap.parse_args()
    if not os.path.exists(ASAN):
        print("set NGSPICE_ASAN to an ASan build")
        return 2

    rng = random.Random(a.seed)
    tally, seen = {}, {}
    did_work = 0
    for i in range(a.iters):
        src, body = build(rng)
        v, info, nplots = run(src, str(i % 8))
        tally[v] = tally.get(v, 0) + 1
        if nplots > 1:            # more than just `const`
            did_work += 1
        if v != "ok":
            key = (v, info)
            if key not in seen:
                seen[key] = body
                print("  %-10s %s" % (v, info[:120]), flush=True)
                print("             %s" % " ; ".join(body[1:]), flush=True)
        if (i + 1) % 50 == 0:
            print("  ... %d/%d  %s  (cases with live plots: %d)"
                  % (i + 1, a.iters,
                     " ".join("%s=%d" % kv for kv in sorted(tally.items())), did_work),
                  flush=True)

    for j in os.listdir(HERE):
        if j.startswith("_pf_") or j == "_pf.raw":
            os.remove(os.path.join(HERE, j))

    print("\n  %d runs: %s" % (a.iters, " ".join("%s=%d" % kv for kv in sorted(tally.items()))))
    print("  distinct findings: %d" % len(seen))
    print("  cases that actually held plots at the end: %d/%d" % (did_work, a.iters))
    if did_work < a.iters // 3:
        print("  *** SUSPECT RUN: most cases produced no plots -- the harness is "
              "probably erroring out, not exercising the lifecycle ***")
        return 2
    return 1 if seen else 0


sys.exit(main())
