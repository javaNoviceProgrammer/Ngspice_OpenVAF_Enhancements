#!/usr/bin/env python3
"""Cross-analysis STATE fuzzing for ngspice.

Every prior campaign in this project fuzzed the INPUT: netlists, model cards,
commands, expressions, rawfiles, .snp, the OSDI loader. This one fuzzes the
SEQUENCE instead. The netlist is fixed and valid; what varies is the order of
analyses and state-mutating commands run against it inside one session.

Why this class is worth a campaign of its own: Enhancement-360 was exactly this
shape -- a second Verilog-A model silenced the first in `.disto`, because the
tensor cache was global while `DEVdisto` dispatches per device TYPE. Nothing was
wrong with either deck alone; the bug lived in what the first analysis left
behind for the second. Input fuzzing cannot reach that, because each input is
run in a fresh process.

What is varied:
  * analysis order and repetition (op, dc, ac, tran, noise, disto, tf, pz,
    sens, sp, four, fft, pss, hb, meas ...)
  * state mutators between them: alter / altermod / reset / destroy / setplot,
    and occasionally `remcirc` -- after which a following analysis must produce
    a clean error, not a crash (the Enhancement-341 class)
  * transient noise on or off, since that adds per-instance generators whose
    lifetime spans analyses (Enhancement-364)

Run against an ASan/UBSan build; a clean error is a PASS, the findings are
sanitizer reports, signals, and hangs.
"""
import argparse
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NG = os.environ.get("NGSPICE_BIN")
OSDI = os.environ.get("SEQFUZZ_OSDI", "")

NETLIST = """seqfuzz
V1 in 0 dc 0.5 ac 1 distof1 1 distof2 1 sin(0.5 0.05 1meg) portnum 1 z0 50
V2 out 0 dc 0 ac 0 portnum 2 z0 50
Rs in mid 1k
N1 mid 0 mylin
.model mylin valin(r=1k c=1n)
Rl mid out 1k
D1 mid 0 dm
.model dm d(is=1e-14 n=1 rs=0 cjo=1p tt=0)
"""

# analyses that make sense on the circuit above
ANALYSES = [
    "op", "dc V1 0 1 0.2", "ac dec 5 1e3 1e7", "tran 50n 5u",
    "noise v(mid) V1 dec 5 1e3 1e6", "disto dec 5 1e3 1e5 0.9",
    "tf v(mid) V1", "pz in 0 mid 0 vol pz", "sens v(mid)",
    "sp lin 3 1e6 1e8", "four 1meg v(mid)", "fft v(mid)",
    "pss 1meg 2u 0 512 5 50 3u", "hb 1meg 3",
    "meas tran vm MAX v(mid)", "op",
]

# state mutators
MUTATORS = [
    "alter V1 dc = 0.6", "alter Rs = 900", "altermod dm is = 2e-14",
    "reset", "destroy all", "setplot new", "save v(mid)",
    "unset numdgt", "set numdgt=8",
]

# deliberately hostile: after this, later analyses must error cleanly
NUKES = ["remcirc"]

SAN = re.compile(r"AddressSanitizer|runtime error:|UndefinedBehaviorSanitizer|LeakSanitizer", re.I)
CRASH = re.compile(r"Segmentation fault|Bus error|Abort trap|signal \d+|stack smashing|assertion failed", re.I)


def build(rng):
    trn = rng.random() < 0.35
    lines = ["option noacct", "pre_osdi %s" % OSDI]
    n = rng.randrange(3, 12)
    for _ in range(n):
        r = rng.random()
        if r < 0.62:
            lines.append(rng.choice(ANALYSES))
        elif r < 0.95:
            lines.append(rng.choice(MUTATORS))
        else:
            lines.append(rng.choice(NUKES))
    net = NETLIST
    if trn:
        net += "Vn nz 0 dc 0 trnoise(0 1e-8 0 0)\nRz nz 0 1k\n"
    return net + ".control\n" + "\n".join(lines) + "\n.endc\n.end\n", lines


def run(src, tag, timeout=90):
    p = os.path.join(HERE, "_sq_%s.cir" % tag)
    open(p, "w").write(src)
    try:
        r = subprocess.run([NG, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                           text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", ""
    out = r.stdout + r.stderr
    if SAN.search(out):
        m = re.search(r"([A-Za-z_0-9./]+\.[ch]:\d+:\d+: runtime error: [^\n]*)", out) \
            or re.search(r"(ERROR: AddressSanitizer[^\n]*)", out)
        return "SANITIZER", (m.group(1) if m else out[:160])
    if r.returncode < 0 or CRASH.search(out):
        return "CRASH", "rc=%s" % r.returncode
    return "ok", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260729)
    a = ap.parse_args()
    if not NG or not os.path.exists(NG):
        print("set NGSPICE_BIN to a sanitizer build")
        return 2

    rng = random.Random(a.seed)
    tally, seen = {}, {}
    for i in range(a.iters):
        src, lines = build(rng)
        v, d = run(src, str(i % 6))
        tally[v] = tally.get(v, 0) + 1
        if v != "ok":
            key = (v, d)
            if key not in seen:
                seen[key] = lines
                print("  %-10s %s" % (v, d[:110]), flush=True)
                print("             seq: %s" % " ; ".join(lines[2:]), flush=True)
        if (i + 1) % 50 == 0:
            print("  ... %d/%d %s" % (i + 1, a.iters,
                  " ".join("%s=%d" % kv for kv in sorted(tally.items()))), flush=True)
    print("\n%d runs: %s" % (a.iters, " ".join("%s=%d" % kv for kv in sorted(tally.items()))))
    print("distinct findings: %d" % len(seen))
    for j in os.listdir(HERE):
        if j.startswith("_sq_"):
            os.remove(os.path.join(HERE, j))
    return 1 if seen else 0


sys.exit(main())
