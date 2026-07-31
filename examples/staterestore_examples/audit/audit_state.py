#!/usr/bin/env python3
"""State-restoration audit campaign (Enhancement-385).

Usage:  python3 examples/staterestore_examples/audit/audit_state.py [command ...]
        NGSPICE_BIN overrides the binary (point it at a pre-fix build to check
        the harness can still SEE a defect -- see the positive-control note).

The compact form of this lives in verify_staterestore.py and runs with the
regular suite; this is the full 31-command sweep, kept runnable for the next
audit round.

State-restoration audit: a command must not change the user's DECLARED INPUTS.

Class being hunted -- four shipped bugs share it exactly:
  E-380  .dc inherited integration coefficients from a preceding pss
  E-381  stb handed its probe sources back zeroed
  E-382  loadpull left the tuner at the last swept grid point
  E-384  sens flipped every source's waveform to PORT and left it there

Oracle: for every (instance, settable parameter) pair in a deck, the value after
running command X must equal the value before. SETTABLE is the operative word --
computed outputs (i, v, p, gd, charge, ...) legitimately reflect the last
analysis and are excluded BY CONSTRUCTION, because the snapshot is built only
from parameters the device tables mark IF_SET. Nothing is calibrated away by
name, so a command that corrupts a settable parameter cannot hide behind a
volatile one that happens to share its name.

The baseline is WARM (an `op` runs first): several settable parameters -- temp,
m, area, scale, w, l -- hold their unset sentinel until setup materialises the
default, and that one-time transition is not a restoration failure.
"""
import os
import re
import glob
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# HERE is examples/<name>_examples/audit -> three levels up is the repo root
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "examples"))
from _setup import NG                                   # noqa: E402
SRC = os.path.join(ROOT, "ngspice-46", "src")

# device table file -> the instance prefix it serves in our deck
TABLES = {
    "res/res.c": "r", "cap/cap.c": "c", "ind/ind.c": "l", "dio/dio.c": "d",
    "vsrc/vsrc.c": "v", "isrc/isrc.c": "i", "bjt/bjt.c": "q", "mos1/mos1.c": "m",
    "vccs/vccs.c": "g", "vcvs/vcvs.c": "e",
}


def settable_keywords(relpath):
    """Keywords the device's INSTANCE table marks IF_SET (the IOP* macros).

    Only the instance table: model parameters are reached through .model cards
    and are not what a command perturbs per-instance.
    """
    p = os.path.join(SRC, "spicelib/devices", relpath)
    if not os.path.isfile(p):
        return []
    txt = re.sub(r'/\*.*?\*/', ' ', open(p, errors="replace").read(), flags=re.S)
    m = re.search(r'IFparm\s+\w*pTable\s*\[\]\s*=\s*\{(.*?)\n\};', txt, re.S)
    if not m:
        return []
    kws = []
    # ALL queryable parameters, not just IF_SET ones. E-384's `sens` bug
    # corrupted `function` (the waveform selector), which is OPU -- ask-only.
    # A settable-only snapshot would have missed the very class being hunted.
    for e in re.finditer(r'\b(I?OP[A-Z]*)\s*\(\s*"([^"]+)"', m.group(1)):
        k = e.group(2).lower()
        if k not in kws:
            kws.append(k)
    return kws


# A deck spanning the device types a command is most likely to disturb.
NET = """staterestore audit
V1 in 0 dc 1.5 ac 1 SIN(0.5 0.3 1meg)
I1 0 nc dc 1e-3 ac 0.5
R1 in mid 2k
C1 mid 0 2.2n
L1 mid m2 1.5m
D1 m2 out dm
R2 out 0 3k
R3 nc 0 4k
Q1 out mid 0 qm
M1 nc mid 0 0 nm w=2u l=1u
G1 0 nc mid 0 1e-3
E1 ne 0 mid 0 2
R4 ne 0 5k
.model dm d(is=1e-14 cjo=1p rs=2)
.model qm npn(bf=100 rb=10)
.model nm nmos(vto=0.7 kp=1e-4)
"""
INSTANCES = [("v1", "vsrc/vsrc.c"), ("i1", "isrc/isrc.c"), ("r1", "res/res.c"),
             ("c1", "cap/cap.c"), ("l1", "ind/ind.c"), ("d1", "dio/dio.c"),
             ("q1", "bjt/bjt.c"), ("m1", "mos1/mos1.c"),
             ("g1", "vccs/vccs.c"), ("e1", "vcvs/vcvs.c")]

# Commands under audit. Each must leave every settable parameter untouched.
COMMANDS = {
    # --- analyses -------------------------------------------------------
    "op":        "op",
    "dc":        "dc V1 1.0 2.0 0.5",
    "tran":      "tran 200n 4u",
    "ac":        "ac dec 4 1e3 1e7",
    "noise":     "noise v(out) V1 dec 4 1e3 1e6",
    "disto":     "disto dec 4 1e3 1e6",
    "pz":        "pz in 0 out 0 cur pz",
    "tf":        "tf v(out) V1",
    "sens":      "sens v(out)",
    "sens_ac":   "sens v(out) ac dec 3 1e3 1e6",
    "four":      "tran 200n 4u\nfour 1meg v(out)",
    "fft":       "tran 200n 4u\nlinearize\nfft v(out)",
    "spec":      "tran 200n 4u\nspec 0 5e6 5e5 v(out)",
    # --- RF / periodic --------------------------------------------------
    "hb":        "hb 1meg 3",
    "pss":       "pss 1meg 1u out 1024 10 50 5u",
    "envelope":  "envelope out 1meg 20u",
    "eye":       "tran 200n 8u\neye v(out) -ui 1u",
    # --- sweeps / optimisation / statistics -----------------------------
    "sweep":     "sweep @r1[resistance] 1800 2200 3 -analysis op",
    "montecarlo": "montecarlo 3 -analysis op -spec v(out) -max 99",
    "wcd":       "wcd -analysis op -spec v(out) -max 99",
    # --- utility / state mutators ---------------------------------------
    "reset":     "reset",
    "destroy":   "op\ndestroy all",
    "setplot":   "op\nsetplot new",
    "save":      "save v(out)",
    "rcreduce":  "op\nrcreduce",
    "checkpoint": "checkpoint _sr_ck.tmp",
    "show":      "show all : all",
    "showmod":   "showmod",
    "check_ifparm": "check_ifparm",
    "inventory": "inventory",
    "remzerovec": "remzerovec",
}


def settable_set(relpath):
    """Keywords the instance table marks IF_SET, i.e. the DECLARED INPUTS.

    Reported separately from the ask-only ones so a future round does not have to
    re-derive the distinction by hand: an ask-only parameter that moves is a
    computed output following the operating point (`von`, `gbd`, a source's
    readback `current`), while a SETTABLE one that moves is a restoration bug.
    `function` is the reminder that ask-only does NOT mean uninteresting -- it
    reflects a declared waveform, and E-384 corrupted exactly that.
    """
    path = os.path.join(SRC, "spicelib/devices", relpath)
    if not os.path.isfile(path):
        return set()
    txt = re.sub(r'/\*.*?\*/', ' ', open(path, errors="replace").read(), flags=re.S)
    m = re.search(r'IFparm\s+\w*pTable\s*\[\]\s*=\s*\{(.*?)\n\};', txt, re.S)
    if not m:
        return set()
    return {e.group(1).lower()
            for e in re.finditer(r'\bIOP[A-Z]*\s*\(\s*"([^"]+)"', m.group(1))}


def snapshot_cmds(pairs):
    return "\n".join("print @%s[%s]" % (i, k) for i, k in pairs)


def run(body, tag):
    p = os.path.join(HERE, "_sr_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\nset numdgt=14\n" + body + "\n.endc\n.end\n")
    try:
        r = subprocess.run([NG, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=900, errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "__TIMEOUT__"


def same(a, b):
    """Numeric comparison. `-0.0` vs `0.0` is a printing artifact, not a state
    change, and it fired on four commands before this was added."""
    if a == b:
        return True
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if x == y:                      # catches -0.0 == 0.0
        return True
    return abs(x - y) <= 1e-12 * max(abs(x), abs(y))


def parse(out, marker, end=None):
    """Values printed between `marker` and `end`, keyed by @inst[param].

    The `end` bound is load-bearing. Without it the BEFORE scan ran to the end
    of the output, swallowed the AFTER block, and -- because this builds a dict
    -- the later AFTER values overwrote the BEFORE ones. before == after for
    every pair, so every command was reported clean. The positive control below
    (a binary with a KNOWN corruption) is what caught it; nothing in a green run
    would have.
    """
    i = out.find(marker)
    if i < 0:
        return {}
    seg = out[i:]
    if end:
        j = seg.find(end)
        if j >= 0:
            seg = seg[:j]
    d = {}
    for m in re.finditer(r"^@(\w+)\[(\w+)\]\s*=\s*(\S+)", seg, re.M):
        d[(m.group(1), m.group(2))] = m.group(3)
    return d


def main():
    pairs, SETTABLE = [], set()
    for inst, tbl in INSTANCES:
        st = settable_set(tbl)
        for kw in settable_keywords(tbl):
            pairs.append((inst, kw))
            if kw in st:
                SETTABLE.add((inst, kw))
    print("audit surface: %d instances, %d (instance, settable-parameter) pairs\n"
          % (len(INSTANCES), len(pairs)))
    snap = snapshot_cmds(pairs)

    # CONTROL: whatever a plain `op` moves is a computed output on THIS deck, so
    # it is subtracted per (instance, parameter) pair -- never by name. `p` is
    # settable on some devices and an output on others; excluding the NAME would
    # have masked a real change, excluding the PAIR does not.
    # CONTROL. A parameter is a COMPUTED OUTPUT if it moves merely because the
    # operating point moved. Measure that with benign analyses on an unmodified
    # circuit and take the UNION -- `op` vs `op` is not enough, because the same
    # analysis reproduces the same operating point and nothing appears to move,
    # while any DIFFERENT analysis legitimately shifts every terminal current.
    #
    # LIMITATION, stated rather than hidden: a command that corrupts a parameter
    # which is itself operating-point dependent is masked by this subtraction.
    # The inputs that matter -- resistance, dc, function, coeffs, ... -- are not
    # in the volatile set, which is what makes the audit useful.
    VOLATILE, cb = set(), {}
    for ctl in ("op", "dc V1 1.0 2.0 0.5", "tran 200n 4u", "ac dec 4 1e3 1e7"):
        cout = run("op\necho @@BEFORE\n" + snap + "\n" + ctl + "\necho @@AFTER\n" + snap,
                   "ctl")
        b, a = parse(cout, "@@BEFORE", "@@AFTER"), parse(cout, "@@AFTER")
        cb = cb or b
        VOLATILE |= {k for k in b if not same(b[k], a.get(k))}
    print("control (op/dc/tran/ac on an unmodified circuit): %d/%d pairs are "
          "operating-point dependent -> subtracted per-pair" % (len(VOLATILE), len(cb)))
    if VOLATILE:
        print("   " + ", ".join("@%s[%s]" % k for k in sorted(VOLATILE)[:14])
              + (" ..." if len(VOLATILE) > 14 else ""))
    print()

    only = sys.argv[1:]
    findings = []
    for name in sorted(COMMANDS):
        if only and name not in only:
            continue
        cmd = COMMANDS[name]
        out = run("op\necho @@BEFORE\n" + snap + "\n" + cmd +
                  "\necho @@AFTER\n" + snap, name)
        if out == "__TIMEOUT__":
            print("  %-13s TIMEOUT" % name)
            continue
        before, after = parse(out, "@@BEFORE", "@@AFTER"), parse(out, "@@AFTER")
        if not after and name in ("reset", "remcirc"):
            print("  %-13s n/a (tears the circuit down by design)" % name)
            continue
        if not before:
            print("  %-13s NO SNAPSHOT (command may have ended the session)" % name)
            findings.append((name, [("<session>", "<died>", "-", "-")]))
            continue
        diffs = [(i, k, before[(i, k)], after.get((i, k), "<gone>"))
                 for (i, k) in before
                 if not same(before[(i, k)], after.get((i, k)))
                 and (i, k) not in VOLATILE]
        if diffs:
            print("  %-13s CHANGED %d" % (name, len(diffs)))
            for i, k, b, a in diffs[:6]:
                print("      @%s[%s]%s  %s -> %s"
                      % (i, k, "  [INPUT]" if (i, k) in SETTABLE else " [output]", b, a))
            if len(diffs) > 6:
                print("      ... and %d more" % (len(diffs) - 6))
            findings.append((name, diffs))
        else:
            print("  %-13s clean (%d pairs)" % (name, len(before)))

    for f in os.listdir(HERE):
        if f.startswith("_sr_"):
            os.remove(os.path.join(HERE, f))
    print("\n== %d/%d commands changed a settable parameter ==" %
          (len(findings), len(only or COMMANDS)))
    for n, d in findings:
        print("   %-13s %s" % (n, ", ".join("@%s[%s]" % (i, k) for i, k, _, _ in d[:8])))


main()
