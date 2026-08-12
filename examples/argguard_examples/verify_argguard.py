#!/usr/bin/env python3
"""Enhancement-440: the arguments and diagnostics that were not checked.

Six independent guards, each found by the same test: do the SIBLINGS already do
this? In every case all but one of a family behaved correctly, and the odd one
out was silent.

* `pss` was the only analysis that validated none of its numeric arguments.
  `tran`, `ac`, `dc`, `hb`, `sp` and `noise` all reject a negative or inverted
  argument and name the offending value. A negative `stabtime` sets CKTfinalTime
  behind the current time, so the stabilization transient integrates toward a
  final time it has already passed: `pss 1k -1m 0 1024 5 50 1u` ran past 100
  seconds with no output and no diagnostic at all.

* `.meas` accepted an inverted window. Because m_to == 0.0 doubles as "no upper
  limit", `FROM=1m TO=0` did not measure nothing -- it measured [1m, end] and
  returned a confident number for a window nobody asked for.

* `pow(0,-1)` and `0**-1` returned a raw infinity. Every other singular case in
  ptfuncs.c is clamped to HUGE, which ifeval.c reports as a named error --
  x/0, sqrt(-x), log(0), and `pwr(0,-1)` since Enhancement-256. These two were
  the exceptions, so an inf reached the matrix, the operating point reported
  success, and a transient carried it to maximum(v(nb)) = inf.

* The temperature guard was one-sided: below absolute zero was refused
  (Enhancement-426), above nothing was checked, and `.temp 1e6` silently gave a
  diode divider an answer of -2.7e-15 V.

* `set curplotname=x` before the first analysis called FREE() on a string
  LITERAL -- plot_cur is the statically initialised `constantplot` until an
  analysis runs -- and ngspice died with a heap abort and no message. `unset`
  reached the same code and performed the assignment as well, so an unset
  silently renamed the plot.

* PP_mkfnode() copied an unbounded function name into a fixed BSIZE_SP buffer.
  `fourier 1k <600-char-name>(v(a))` smashed the stack; the same through `meas`
  died on the fortify check.

Plus one defect in Enhancement-438's own warn_physics: it reported from
dosim(), i.e. once per analysis RUN, so the loop drivers repeated an identical
warning once per sample (montecarlo) or per point (sweep).
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

# Remove the generated decks at process exit rather than at the end of main.
# check_both_solvers pins a solver by editing each deck and registers an atexit
# handler that writes the ORIGINAL text back -- which RE-CREATES any deck the
# script deleted before exiting. atexit runs handlers last-registered-first, so
# registering here, before the first deck is written, puts this one last.
import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_ag_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, ctl, tag, cards="", timeout=180):
    deck = (f"argguard {tag}\n{body}\n{cards}\n.control\noption noacct\n"
            f"set numdgt=12\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_ag_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    t0 = time.time()
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.returncode, r.stdout + r.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return None, "", time.time() - t0


RC = "V1 in 0 dc 1 ac 1 sin(0 1 1k)\nR1 in nb 1k\nC1 nb 0 1n\nR2 nb 0 1k"
PULSE = "V1 in 0 dc 0 pulse(0 1 0 1n 1n 1m 2m)\nR1 in nb 1k\nR2 nb 0 1k"

print("Enhancement-440: unchecked arguments and missing diagnostics\n")

# ---------------------------------------------------------------------------
print("pss argument validation -- the one analysis that checked nothing")
for tag, ctl, want in (
        ("tstab", "pss 1k -1m 0 1024 5 50 1u", "stabtime must be"),
        ("steady", "pss 1k 2m 0 1024 5 50 -1u", "steady_coeff must be"),
        ("sciter", "pss 1k 2m 0 1024 5 -50 1u", "sc_iter must be")):
    rc, out, dt = run(RC, ctl, "pss" + tag, timeout=60)
    check(f"[E-440] pss rejects a negative {tag} instead of running forever",
          rc == 1 and want in out and dt < 20,
          f"rc={rc} {dt:.1f}s")
# the guards must not have broken a valid pss
rc, out, dt = run(RC, "pss 1k 2m 0 1024 5 50 1u", "pssok", timeout=300)
check("[E-440] a valid pss still runs", rc == 0, f"rc={rc}")

# the sibling analyses that already validated must be unchanged
print("\n  ...and the siblings that already validated still do")
for tag, ctl, want in (
        ("tran", "tran -1u 200u", "TSTEP is invalid"),
        ("ac", "ac dec 5 1meg 1", "stop frequency is invalid"),
        ("hb", "hb 1k 0", "need f0 > 0")):
    rc, out, _ = run(RC, ctl, "sib" + tag, timeout=60)
    check(f"[E-440] {tag} still names its bad argument", want in out, f"rc={rc}")

# ---------------------------------------------------------------------------
print("\n.meas measurement windows")
rc, out, _ = run(PULSE, "tran 5u 2m\nmeas tran m AVG v(nb) FROM=1m TO=0", "minv")
check("[E-440] an inverted FROM/TO window is refused, not reinterpreted",
      "is above" in out and not re.search(r"^\s*m\s*=", out, re.M),
      "")
rc, out, _ = run(PULSE, "tran 5u 2m\nmeas tran m AVG v(nb) FROM=1m TO=1m", "mzero")
check("[E-440] a zero-width window is refused",
      "zero width" in out and not re.search(r"^\s*m\s*=", out, re.M), "")
# the valid windows must still measure, and measure the RIGHT thing: the pulse
# is low over [0,1m] and high over [1m,2m], so a full-span average is 0.25 and
# the second-half average is 0.5.
for tag, ctl, want in (
        ("full", "tran 5u 2m\nmeas tran m AVG v(nb)", 0.25),
        ("first half", "tran 5u 2m\nmeas tran m AVG v(nb) FROM=0 TO=1m", 0.5)):
    rc, out, _ = run(PULSE, ctl, "mok" + tag.replace(" ", ""))
    m = re.search(r"^\s*m\s*=\s*(\S+)", out, re.M)
    check(f"[E-440] a valid window still measures ({tag}, expect {want})",
          bool(m) and abs(float(m.group(1)) - want) < 1e-3,
          f"m={m.group(1) if m else None}")
# dc may legitimately sweep downward, so there the window is normalised, not
# refused -- but it now says so.
rc, out, _ = run("V1 in 0 dc 1\nR1 in nb 1k\nR2 nb 0 1k",
                 "dc V1 0 1 0.1\nmeas dc m AVG v(nb) FROM=0.8 TO=0.2", "mdc")
m = re.search(r"^\s*m\s*=\s*(\S+)", out, re.M)
check("[E-440] dc still normalises an inverted window, and now reports it",
      bool(m) and "treating the window as" in out,
      f"m={m.group(1) if m else None}")

# ---------------------------------------------------------------------------
print("\nsingular arithmetic in a B-source -- pow() joins its siblings")
BS = "V1 in 0 dc 1\nB1 nb 0 v='{}'\nR1 nb 0 1k"
for tag, expr in (("pow", "pow(0,-1)"), ("starstar", "0**-1")):
    rc, out, _ = run(BS.format(expr), "op\nprint v(nb)", "sing" + tag)
    check(f"[E-440] {expr} is a named error, not a silent infinity",
          "out of range" in out and not re.search(r"(?i)v\(nb\)\s*=\s*[-+]?inf", out),
          f"rc={rc}")
# ... exactly as pwr() has behaved since E-256
rc, out, _ = run(BS.format("pwr(0,-1)"), "op\nprint v(nb)", "singpwr")
check("[E-440] and pwr(0,-1) behaves the same way (the sibling it now matches)",
      "out of range" in out, f"rc={rc}")
# an expression that merely OVERFLOWS is reported but deliberately not clamped
rc, out, _ = run(BS.format("1e300*1e300"), "op\nprint v(nb)", "ovf")
check("[E-440] an overflow to infinity is reported instead of passing silently",
      re.search(r"(?i)evaluated to (infinity|nan)", out) is not None, "")
# CONTROLS: ordinary powers must be untouched
for expr, want in (("pow(2,3)", 8.0), ("pow(0,2)", 0.0), ("pow(0.5,-1)", 2.0),
                   ("1/0", 1e32)):
    rc, out, _ = run(BS.format(expr), "op\nprint v(nb)",
                     "ok" + re.sub(r"\W", "", expr))
    m = re.search(r"v\(nb\)\s*=\s*(\S+)", out, re.I)
    check(f"[E-440] {expr} is unchanged (expect {want:g})",
          bool(m) and abs(float(m.group(1)) - want) <= abs(want) * 1e-9 + 1e-12,
          f"v(nb)={m.group(1) if m else None}")

# ---------------------------------------------------------------------------
print("\ntemperature -- the guard was only checked on one side")
DIODE = "V1 in 0 dc 0.7\nR1 in nb 1k\nD1 nb 0 dm\n.model dm d(is=1e-14)"
rc, out, _ = run(DIODE, "op\nprint v(nb)", "thot", cards=".temp 1e6")
check("[E-440] an absurdly high .temp is reported", "far above" in out, "")
rc, out, _ = run(DIODE, "op\nprint v(nb)", "tcold", cards=".temp -300")
check("[E-440] below absolute zero is still refused (E-426, unchanged)",
      "absolute zero" in out, "")
for tag, card in (("27", ".temp 27"), ("125", ".temp 125"), ("-40", ".temp -40")):
    rc, out, _ = run(DIODE, "op\nprint v(nb)", "tok" + tag.replace("-", "m"),
                     cards=card)
    check(f"[E-440] an ordinary temperature ({tag} C) warns about nothing",
          "far above" not in out and "absolute zero" not in out, "")

# ---------------------------------------------------------------------------
print("\nthe current plot's descriptive strings")
DIV = "V1 in 0 dc 1\nR1 in nb 1k\nR2 nb 0 1k"
for tag, what in (("name", "curplotname"), ("title", "curplottitle"),
                  ("date", "curplotdate")):
    rc, out, _ = run(DIV, f"set {what}=x\nop", "set" + tag)
    check(f"[E-440] set {what} before an analysis is refused, not a heap abort",
          rc == 0 and "constants" in out, f"rc={rc}")
    rc, out, _ = run(DIV, f"unset {what}\nop", "unset" + tag)
    check(f"[E-440] unset {what} before an analysis does not abort either",
          rc == 0, f"rc={rc}")
# after an analysis the plot is heap-allocated and setting it must still work
rc, out, _ = run(DIV, "op\nset curplotname=renamed\necho $curplotname", "setok")
check("[E-440] after an analysis, setting the plot name still works",
      rc == 0 and "renamed" in out, f"rc={rc}")

# ---------------------------------------------------------------------------
print("\nan over-long function name must not smash the stack")
for n in (600, 1200, 4000):
    fn = "g" + "q" * n
    rc, out, _ = run(RC, f"tran 5u 4m\nfourier 1k {fn}(v(nb))", f"fn{n}")
    check(f"[E-440] fourier survives a {n}-character function name",
          rc in (0, 1), f"rc={rc}")
    rc, out, _ = run(RC, f"tran 5u 4m\nmeas tran m MAX {fn}(v(nb))", f"mn{n}")
    check(f"[E-440] meas survives a {n}-character function name",
          rc in (0, 1), f"rc={rc}")
# a real function of a real vector must still evaluate
rc, out, _ = run(RC, "tran 5u 4m\nlet z=maximum(v(nb))\nprint z", "fnok")
m = re.search(r"^\s*z\s*=\s*(\S+)", out, re.M)
check("[E-440] and an ordinary function call still works",
      rc == 0 and m is not None and float(m.group(1)) > 0.1,
      f"rc={rc} z={m.group(1) if m else None}")

# ---------------------------------------------------------------------------
print("\nEnhancement-438's warn_physics says each thing once, not once per run")
SW = ("V1 in 0 dc 1\nVc c 0 dc 1\nR1 in nb 1k\nS1 nb 0 c 0 sm\n"
      ".model sm sw vt=0.5 ron=-1 roff=1e9")


def warn_count(ctl, tag, timeout=300):
    rc, out, _ = run(SW, ctl, tag, cards=".option warn_physics", timeout=timeout)
    return len([ln for ln in out.splitlines() if "ron = -1" in ln])


base = warn_count("op", "w1")
check("[E-440] a plain op still reports it exactly once", base == 1, f"{base}")
n_dc = warn_count("dc V1 0 1 0.025", "w2")
check("[E-440] a 41-point dc sweep still reports once", n_dc == 1, f"{n_dc}")
n_sw = warn_count("sweep @r1[resistance] 1k 6k 1k -analysis op", "w3")
check("[E-440] a 6-point sweep reports once, not once per point", n_sw == 1,
      f"{n_sw}")
# montecarlo rebuilds the circuit once, and the memo is per circuit build, so
# the count is a small constant -- the point is that it does NOT scale with the
# sample count, which is what made the diagnostic unusable.
mc = {n: warn_count(f"montecarlo {n} -analysis op -spec v(nb) -max 10",
                    f"w4_{n}", timeout=600) for n in (3, 20)}
check("[E-440] montecarlo's count does not grow with the sample count",
      mc[3] == mc[20] and mc[20] <= 2, f"3 samples -> {mc[3]}, 20 -> {mc[20]}")
# and a clean circuit must still say nothing at all
rc, out, _ = run(DIV, "op", "wclean", cards=".option warn_physics")
check("[E-440] a healthy circuit still warns about nothing",
      "Warning: model" not in out and "Warning: instance" not in out, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
