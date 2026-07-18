#!/usr/bin/env python3
"""
verify_parserfuzz.py -- Enhancement-222: ngspice netlist-parser hardening.

Fuzzing ngspice's netlist parser (mutating real decks and running `ngspice -b`)
found seven ways to make the parser CRASH (SIGSEGV/SIGABRT -- real memory-safety
bugs, since ngspice is C) or HANG on malformed input. Every one is now a clean,
bounded error. The seven root causes, all fixed:

  [osdi-terminals] frontend/inpcom.c get_number_terminals() -- the OSDI ('n')
        case was the only multi-token case with no iteration cap, and
        misc/string.c gettok_instance() returns an empty token WITHOUT advancing
        when it sits on '(' or ')'. A line starting with 'n' containing '(' (e.g.
        "nan.func f(x)=...") spun forever, tmalloc-ing each pass. Fixed: gettok_
        instance() always advances; the 'n' loop gained a cap.

  [model-macro]   frontend/inpcom.c inp_expand_macro_in_str() -- a truncated
        ".model m" (no model type) ran nexttok off the end, leaving the scan
        pointer NULL, then strchr(NULL). Guarded.

  [subckt-blowup] frontend/subckt.c doit() -- MAXNEST bounds subcircuit
        DEPTH, but a subckt that instantiates itself with branching factor >= 2
        blows up to 2^MAXNEST instances (an effective hang). A total-
        instantiation cap catches recursive subcircuits.

  [subckt-underflow] frontend/subckt.c doit() -- a bare "X" invocation (nothing
        after the refdes) made the find-last-token walk run off the FRONT of the
        line buffer, ending in strcmp(NULL). Guarded.

  [modexp-overflow] frontend/inpcom.c inp_modify_exp() -- two copies into a fixed
        buf[512] with no bound: an unterminated "v(" and a long identifier token
        (a run of '[' is accepted) overran the stack buffer (stack smashing).
        Both loops are now bounded.

  [subckt-name]   frontend/subckt.c doit() -- a malformed ".subckt" can register
        a NULL name; the invoked-name match eq(su_name, ...) then strcmp(NULL).
        Guarded.

  [poly-name]     frontend/subckt.c translate() -- gettok_noparens() returns NULL
        at the end of a malformed controlled-source line, then strcmp(NULL,
        "POLY"). Guarded.

Each check confirms the pathological deck now yields a clean, bounded outcome
(no signal/abort, no hang) and that valid decks still parse and simulate.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

checks = passed = 0
D = tempfile.mkdtemp(prefix="parserfuzz222_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def verdict(text, timeout=25):
    """Return 'CRASH' / 'HANG' / 'CLEAN' for a deck run under `ngspice -b`."""
    p = os.path.join(D, "f.cir")
    with open(p, "w") as f:
        f.write(text)
    wd = tempfile.mkdtemp(dir=D)
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                           timeout=timeout, cwd=wd, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG"
    rc = r.returncode
    if rc is not None and (rc < 0 or (rc >= 128 and rc != 142)):
        return "CRASH"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if "segmentation" in out:
        return "CRASH"
    return "CLEAN"


# --- the seven pathological inputs: each must be CLEAN (no crash, no hang) ---
cases = {
    "osdi-terminals: 'nan.func' infinite loop":
        "* t\nnan.func f(x)=-{x}\n.end\n",
    "model-macro: '.model m' (no type) in .control":
        "* t\n.control\n.model m\n.endc\n.end\n",
    "subckt-blowup: self-recursive subckt (branching)":
        "* t\n.subckt rect a b\nX1 a b rect\nX1 a b rect\n.ends\n"
        "X1 a b rect\nX1 a b rect\n.op\n.end\n",
    "subckt-underflow: bare 'X' invocation":
        "* t\nX\nV1 1 0 1\nR1 1 0 1k\n.op\n.end\n",
    "modexp-overflow: unterminated v( in a B-source":
        "* t\nV1 1 0 1\nB1 2 0 v={v(" + "a" * 2000 + "\nR1 2 0 1k\n.op\n.end\n",
    "modexp-overflow: 4000x '[' identifier in a B-source":
        "* t\nV1 1 0 1\nB1 2 0 v={" + "[" * 4000 + "\nR1 2 0 1k\n.op\n.end\n",
    "poly-name: 4000x '{' in a subckt E-source":
        "* t\n.subckt amp in out\nE1 out " + "{" * 4000 + " in 0 x\nRl out 0 1k\n"
        ".ends\nV1 in 0 1\nX1 in out amp\n.op\n.end\n",
}

print("Enhancement-222: seven ngspice parser crashes/hangs -> clean errors")
for name, deck in cases.items():
    v = verdict(deck)
    check(f"{name} -> {v}", v == "CLEAN", v)

# --- valid decks still parse and simulate (no regression) ---
valid = {
    "subckt hierarchy (E-source, param)":
        ("* v\n.subckt amp in out gain=10\nE1 out 0 in 0 {gain}\nRl out 0 1k\n.ends\n"
         "V1 in 0 dc 0.1\nX1 in out amp gain=5\n.op\n.end\n", "out", 0.5),
    "B-source v(x)*v(x)+... expression":
        ("* v\nVx x 0 2\nB1 y 0 v={v(x)*v(x)+3}\nRy y 0 1k\n.op\n.end\n", "y", 7.0),
    "POLY controlled source in a subckt":
        ("* v\n.subckt blk a b\nE1 b 0 poly(1) a 0 0 2\nRl b 0 1k\n.ends\n"
         "V1 a 0 1.5\nX1 a b blk\n.op\n.end\n", "b", 3.0),
}


def node_v(text, node):
    p = os.path.join(D, "v.cir")
    with open(p, "w") as f:
        f.write("* v\n.control\nop\nprint v(%s)\n.endc\n" % node
                if False else text)
    wd = tempfile.mkdtemp(dir=D)
    r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                       timeout=30, cwd=wd, errors="replace")
    for line in (r.stdout + r.stderr).splitlines():
        s = line.strip()
        if s.startswith(node + " ") or s.startswith(node + "\t"):
            for tok in s.split():
                try:
                    return float(tok)
                except ValueError:
                    continue
    return None


print("valid decks still parse + simulate correctly:")
for name, (deck, node, expect) in valid.items():
    v = node_v(deck, node)
    check(f"{name}: V({node}) = {expect}",
          v is not None and abs(v - expect) < 1e-6 * max(1, abs(expect)), f"{v}")

print(f"\n{passed}/{checks} checks passed")
print("ALL PASS" if passed == checks else "SOME FAILED")
sys.exit(0 if passed == checks else 1)
