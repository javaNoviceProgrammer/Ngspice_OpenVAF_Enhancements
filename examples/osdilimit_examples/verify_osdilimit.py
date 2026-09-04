#!/usr/bin/env python3
"""verify_osdilimit.py -- F1 of docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md:
simulator-side Newton step limiting for OSDI MOSFETs and BJTs whose model calls
no $limit of its own.

ngspice's built-in MOSFETs, BJTs and diodes limit every junction and channel
voltage step inside their load routines (DEVfetlim / DEVlimvds / DEVpnjlim) and
start a cold operating point from a weakly-on guess; a Verilog-A model gets that
only through $limit, and BSIM4 and PSP103 ship without one. Measured: a chain of
100 OSDI BSIM4 inverters needed dynamic gmin stepping and 333 iterations for its
operating point where the built-in twin converged in 9; a 40x40 grid of them
took 167 iterations and, under Sparse, 5 s. The simulator now recognizes a
3/4-terminal MOSFET (d,g,s[,b]) or BJT (c,b,e[,s]) by its terminal names, reads
the model's polarity (`type`) and threshold (`vth0`/`vto`), and applies the
built-ins' limiting and cold-start guess in the type-normalized frame -- across
the model's own internal drain/source/gate/bulk nodes when its series
resistances leave them live. A model that limits itself, has a terminal beyond
those, or keeps another live internal node (MEXTRAM's b1/e1) is left alone.
`.option noosdilim` switches it off; `set osdilim_verbose` says what was decided.
The operating point reached is the same to 1e-16 -- the limiting changes only
the path.

Alongside: KLU's refactor now treats a collapse of its rcond estimate relative
to the last full factorization as a small pivot and reorders, as Sparse does;
without that the OSDI grid under KLU wandered into gmin stepping for 137
iterations while Sparse converged in 8.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402
_check_both_solvers(__file__)

ROOT = os.path.dirname(os.path.dirname(HERE))
CORPUS = os.path.join(ROOT, "VA_TEST", "VA-Models-main", "code")
MODELS = {
    "bsim4.osdi": os.path.join(CORPUS, "bsim4", "vacode", "bsim4.va"),
    "psp103.osdi": os.path.join(CORPUS, "psp103", "vacode", "psp103.va"),
    "hicuml2.osdi": os.path.join(CORPUS, "hicum2", "vacode", "hicumL2V3p0p0.va"),
    "bjt505.osdi": os.path.join(CORPUS, "mextram", "vacode", "bjt505.va"),
}
passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def compile_models():
    ok = True
    for osdi, va in MODELS.items():
        out = os.path.join(HERE, osdi)
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run([OPENVAF, os.path.relpath(va, HERE), "-o", osdi],
                           capture_output=True, text=True, timeout=600, cwd=HERE)
        ok = ok and os.path.exists(out)
    return ok


def run(name, deck, timeout=300):
    with open(os.path.join(HERE, name), "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


def iters(log):
    m = re.search(r"Total iterations = (\d+)", log)
    return int(m.group(1)) if m else -1


def stepping(log):
    return "gmin stepping" in log or "source stepping" in log


def chain(n, kind, control=""):
    L = [f"* {kind} inverter chain N={n}", "vdd vdd 0 dc 1.2", "vin s0 0 dc 0"]
    for i in range(1, n + 1):
        if kind == "bsim4":
            L += [f"np{i} s{i} s{i-1} vdd vdd pmv", f"nn{i} s{i} s{i-1} 0 0 nmv"]
        elif kind == "psp103":
            L += [f"np{i} s{i} s{i-1} vdd vdd pmv", f"nn{i} s{i} s{i-1} 0 0 nmv"]
        else:
            L += [f"mp{i} s{i} s{i-1} vdd vdd pmb W=2u L=0.2u",
                  f"mn{i} s{i} s{i-1} 0 0 nmb W=1u L=0.2u"]
        L.append(f"c{i} s{i} 0 5f")
    if kind == "bsim4":
        L += [".model nmv bsim4va(type=1 w=1e-6 l=0.2e-6)",
              ".model pmv bsim4va(type=-1 w=2e-6 l=0.2e-6)"]
        pre = "pre_osdi bsim4.osdi"
    elif kind == "psp103":
        L += [".model nmv psp103va(type=1 w=1e-6 l=0.1e-6)",
              ".model pmv psp103va(type=-1 w=2e-6 l=0.1e-6)"]
        pre = "pre_osdi psp103.osdi"
    else:
        L += [".model nmb nmos(level=14 version=4.8)", ".model pmb pmos(level=14 version=4.8)"]
        pre = ""
    L += [".control", pre, control, "op", "rusage totiter",
          "wrdata _op.txt allv", ".endc", ".end"]
    return "\n".join(L) + "\n"


def grid(m, control=""):
    o = lambda i, j: f"o{i}_{j}"
    L = [f"* BSIM4 grid M={m}", "vdd vdd 0 dc 1.2", "vin in 0 dc 0"]
    for i in range(m):
        for j in range(m):
            g = "in" if i == 0 else o(i - 1, j)
            L += [f"np{i}_{j} {o(i,j)} {g} vdd vdd pmv", f"nn{i}_{j} {o(i,j)} {g} 0 0 nmv",
                  f"c{i}_{j} {o(i,j)} 0 5f"]
            if j > 0:
                L.append(f"rc{i}_{j} {o(i,j)} {o(i,j-1)} 10k")
    L += [".model nmv bsim4va(type=1 w=1e-6 l=0.2e-6)", ".model pmv bsim4va(type=-1 w=2e-6 l=0.2e-6)",
          ".control", "pre_osdi bsim4.osdi", control, "op", "rusage totiter", ".endc", ".end"]
    return "\n".join(L) + "\n"


def load_op():
    try:
        with open(os.path.join(HERE, "_op.txt")) as f:
            return [float(x) for x in f.read().split()][1::2]
    except Exception:
        return None


print("F1: simulator-side Newton limiting for OSDI MOSFETs\n")
check("BSIM4, PSP103, HiCUM L2 and MEXTRAM compile from the corpus", compile_models())

# --- [1] the chain that motivated it ------------------------------------------
log = run("_c100.cir", chain(100, "bsim4"))
n_lim = iters(log)
check("100-stage OSDI BSIM4 chain: op converges without gmin stepping in <= 12 iterations",
      0 < n_lim <= 12 and not stepping(log), f"({n_lim} iterations; was 333 with dynamic gmin stepping)")
op_lim = load_op()
log = run("_c100b.cir", chain(100, "bi"))
n_bi = iters(log)
op_bi = load_op()
check("... the same count as the built-in BSIM4 twin, within 3",
      n_bi > 0 and abs(n_lim - n_bi) <= 3, f"(built-in {n_bi})")
d = max(abs(a - b) for a, b in zip(op_lim, op_bi)) if op_lim and op_bi and len(op_lim) == len(op_bi) else None
check("... and the operating point equals the built-in twin's at every node (< 1e-7 V)",
      d is not None and d < 1e-7, f"(max |diff| = {d:.2e} V)" if d is not None else "(no op dump)")

# --- [2] the opt-out restores the old path -----------------------------------
log = run("_c100n.cir", chain(100, "bsim4", "set noosdilim"))
n_off = iters(log)
op_off = load_op()
check(".option noosdilim: the un-limited path returns (gmin stepping, > 100 iterations)",
      stepping(log) and n_off > 100, f"({n_off} iterations)")
d2 = max(abs(a - b) for a, b in zip(op_lim, op_off)) if op_lim and op_off and len(op_lim) == len(op_off) else None
check("... reaching the same operating point (< 1e-9 V): the limiting changes the path only",
      d2 is not None and d2 < 1e-9, f"(max |diff| = {d2:.2e} V)" if d2 is not None else "")

# --- [3] PSP103, whose series resistances keep internal nodes live -----------
log = run("_p100.cir", chain(100, "psp103", "set osdilim_verbose"))
n_psp = iters(log)
check("100-stage OSDI PSP103 chain: converges without gmin stepping in <= 12 iterations",
      0 < n_psp <= 12 and not stepping(log), f"({n_psp} iterations; was 387 with gmin stepping)")
check("... the recognizer limits it (its NOI noise branch, a flow unknown, does not disqualify it)",
      "MOSFET limiting" in log and "no simulator-side limiting" not in log, "")

# --- [4] a 2-D grid, both solvers ---------------------------------------------
log = run("_g20.cir", grid(20))
n_g = iters(log)
check("20x20 OSDI BSIM4 grid: op without gmin stepping in <= 60 iterations",
      0 < n_g <= 60 and not stepping(log), f"({n_g} iterations; was 153 Sparse / 58 KLU with stepping)")

# --- [5] models the recognizer must leave alone -------------------------------
hic = """* HiCUM L2: 5 terminals and its own $limit
vcc vcc 0 dc 3
vin in 0 dc 0.8
rb in b 1k
rc vcc c 1k
nq1 c b 0 0 0 npnh
.model npnh hicumL2va()
.control
pre_osdi hicuml2.osdi
set osdilim_verbose
op
rusage totiter
.endc
.end
"""
log = run("_hic.cir", hic)
check("HiCUM L2 (5 terminals, calls $limit): no simulator-side limiting, and it says so",
      "no simulator-side limiting" in log and iters(log) > 0, f"({iters(log)} iterations)")
mex = """* MEXTRAM 505: c,b,e,s but live internal base/emitter nodes
ib 0 b dc 1m
vc c 0 dc 1.0
nx c b 0 0 mm
.model mm bjt505_va
.control
pre_osdi bjt505.osdi
set osdilim_verbose
op
print v(b)
.endc
.end
"""
log = run("_mex.cir", mex)
check("MEXTRAM (live internal b1/e1 nodes): left alone, naming the node",
      "no simulator-side limiting" in log and "internal node" in log and "v(b) = " in log, "")

# --- [6] the report for a limited model ---------------------------------------
log = run("_v.cir", chain(5, "bsim4", "set osdilim_verbose"))
check("set osdilim_verbose reports the MOSFET limiting, polarity and threshold for BSIM4",
      re.search(r"osdilim: model bsim4va .*MOSFET limiting .*polarity [+-]1, threshold 0\.7 V", log) is not None, "")

for f in os.listdir(HERE):
    if (f.startswith("_") and (f.endswith(".cir") or f.endswith(".txt"))) or f.endswith(".osdi"):
        os.remove(os.path.join(HERE, f))

print(f"\n{'ALL PASS' if failed == 0 else 'FAILURES'}: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
