#!/usr/bin/env python3
"""Enhancement-451: an option matched by substring, and three that worked while
being called unknown.

TWO OPTIONS WERE FOUND BY A BARE SUBSTRING SEARCH over the option line --
`strstr(line, "seed=")` and `strstr(line, "cshunt=")` in eval_opt() -- so any
option whose NAME MERELY ENDED in the watched text was taken as that option:

    .options seed=7        sets the RNG seed   (correct)
    .options myseed=7      sets it too
    .options noseed=7      sets it too -- the spelling that reads as "off"
    .options xseed=7       sets it too

For `cshunt` the answer moves by six orders of magnitude: a node reading 1.0 V
reads 6.92e-07 under `.options nocshunt=1e-6`. Each of these ALSO prints
"Warning: unknown option 'nocshunt'", which makes it worse rather than better --
the user is told the option was not recognised, and it changes the answer anyway.

Enhancement-450 fixed exactly this shape for `savecurrents`; these are two more
in the same file. `seedinfo` is matched as a whole token now as well, so
`noseedinfo` no longer switches it on.

AND THREE OPTIONS TOOK EFFECT WHILE BEING REPORTED UNKNOWN. Asking which flagged
names demonstrably change a run turned up `scale` (@m1[w] 1e-6 -> 2e-6),
`rseries` and `autostop` (a transient truncated from 567 rows to 2). That is the
case Enhancement-447 fixed for savecurrents/seed/numdgt, with names it did not
cover. `scalm` is flagged too and is deliberately NOT registered: it could not be
shown to change anything, and this list is for options that demonstrably work.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_on_"):
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


def run(deck, tag, timeout=120):
    p = os.path.join(HERE, f"_on_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.stdout + r.stderr


def num(out, tag):
    m = re.findall(re.escape(tag) + r"\s*=\s*(-?[\d.]+e[-+]\d+)", out)
    return m[-1] if m else None


def seed(opt, tag):
    """first uniform random -- identical => same seed"""
    return num(run(f"optname\nV1 a 0 dc 1\nR1 a 0 1k\n{opt}\n.control\noption noacct\n"
                   f"set numdgt=10\nop\nlet r=sunif(0)\nprint r\n.endc\n.end\n", tag), "r")


def cshunt(opt, tag):
    """cshunt adds C to every node, so a fast edge is visibly slowed"""
    return num(run(f"optname\nV1 in 0 pulse(0 1 0 1n 1n 1m 2m)\nR1 in b 1k\n{opt}\n"
                   f".control\noption noacct\nset numdgt=10\ntran 1u 20u\n"
                   f"print v(b)[10]\n.endc\n.end\n", tag), "v(b)[10]")


def flagged(opt, tag):
    out = run(f"optname\nV1 a 0 dc 1\nR1 a 0 1k\n.options {opt}\n.control\n"
              f"option noacct\nop\n.endc\n.end\n", tag)
    return f"unknown option '{opt.split('=')[0]}'" in out


print("Enhancement-451: option names matched by substring, and three called unknown\n")

# ------------------------------------------------------- the two baselines ---
base_seed, on_seed = seed("", "s0"), seed(".options seed=7", "s1")
base_csh, on_csh = cshunt("", "c0"), cshunt(".options cshunt=1e-6", "c1")
check("[E-451] the seed baseline and `seed=7` are distinguishable",
      base_seed is not None and on_seed is not None and base_seed != on_seed,
      f"{base_seed} vs {on_seed}")
check("[E-451] the cshunt baseline and `cshunt=1e-6` are distinguishable",
      base_csh is not None and on_csh is not None and base_csh != on_csh,
      f"{base_csh} vs {on_csh}")

# ---------------------------------------------- the real option still works ---
print("\nthe option itself still applies (controls)")
check("[E-451] `.options seed=7` sets the seed",
      seed(".options seed=7", "k1") == on_seed)
check("[E-451] `.options cshunt=1e-6` sets cshunt",
      cshunt(".options cshunt=1e-6", "k2") == on_csh)
check("[E-451] ...beside other options on the same line",
      seed(".options reltol=1e-3 seed=7", "k3") == on_seed)
check("[E-451] `.options seedinfo seed=7` still reports the seed",
      "random number generator is set to 7" in
      run("optname\nV1 a 0 dc 1\nR1 a 0 1k\n.options seedinfo seed=7\n.control\n"
          "option noacct\nop\n.endc\n.end\n", "k4"))

# --------------------------------------- a name that merely ENDS in it must not ---
print("\na different option whose name merely ends in the watched text must NOT apply")
for pre in ("my", "no", "x"):
    check(f"[E-451] `.options {pre}seed=7` leaves the seed alone",
          seed(f".options {pre}seed=7", f"n{pre}s") == base_seed,
          f"{seed(f'.options {pre}seed=7', f'm{pre}s')}")
    check(f"[E-451] `.options {pre}cshunt=1e-6` leaves cshunt alone",
          cshunt(f".options {pre}cshunt=1e-6", f"n{pre}c") == base_csh)
check("[E-451] `.options noseedinfo seed=7` does not report the seed",
      "random number generator is set to 7" not in
      run("optname\nV1 a 0 dc 1\nR1 a 0 1k\n.options noseedinfo seed=7\n.control\n"
          "option noacct\nop\n.endc\n.end\n", "nsi"))

# --------------------------- an option that takes effect is not called unknown ---
print("\nan option that demonstrably takes effect is not reported unknown")
for o in ("scale=2", "rseries=100", "autostop", "savecurrents", "seed=1", "numdgt=8"):
    check(f"[E-451] `.options {o}` is not flagged unknown",
          not flagged(o, "f" + re.sub(r"\W", "", o)[:8]))

print("\n...and a genuinely unknown name still is (controls)")
for o in ("notanoption", "bogusxyz", "myseed=7"):
    check(f"[E-451] `.options {o}` IS still flagged",
          flagged(o, "g" + re.sub(r"\W", "", o)[:8]))

# ------------------------------------------- the three really do take effect ---
print("\nthe three registered names really do change a run")
w0 = num(run("optname\nV1 in 0 dc 1\nM1 out in 0 0 nch w=1u l=1u\n"
             ".model nch nmos level=1 vto=0.5\nRd out 0 1k\n.control\noption noacct\n"
             "set numdgt=8\nop\nprint @m1[w]\n.endc\n.end\n", "w0"), "@m1[w]")
w2 = num(run("optname\nV1 in 0 dc 1\nM1 out in 0 0 nch w=1u l=1u\n"
             ".model nch nmos level=1 vto=0.5\nRd out 0 1k\n.options scale=2\n.control\n"
             "option noacct\nset numdgt=8\nop\nprint @m1[w]\n.endc\n.end\n", "w2"), "@m1[w]")
check("[E-451] scale=2 doubles @m1[w]", w0 is not None and w2 is not None and
      abs(float(w2) - 2 * float(w0)) < 1e-15, f"{w0} -> {w2}")

TR = ("optname\nV1 in 0 pulse(0 1 0 1u 1u 5u 10u)\nR1 in out 1k\nC1 out 0 1n\n%s\n"
      ".control\noption noacct\ntran 100n 50u\nprint length(v(out))\n.endc\n.end\n")
n0 = num(run(TR % "", "t0"), "length(v(out))")
n1 = num(run(TR % ".options autostop", "t1"), "length(v(out))")
check("[E-451] autostop truncates the transient", n0 and n1 and float(n1) < float(n0),
      f"{n0} -> {n1} rows")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
