#!/usr/bin/env python3
"""Enhancement-465: `sweep` stops tearing the circuit down for subcircuit params.

`sweep` has two ways to move a `.param` knob. Enhancement-320's FAST path writes
each point's values straight into the live circuit; the fallback stages
`alterparam` and issues a **`reset`**, which re-sources the whole deck once per
point. Measured on a 3000-element deck at 201 points: 0.50 s against 1.58 s, the
gap widening with both deck size and point count.

The fast path used to disarm on almost anything involving a subcircuit or a
derived parameter, so realistic decks fell off it silently -- there is a banner
when it arms and nothing at all when it does not. Every case below now stays on
it, and each is checked against an ANALYTIC value, not against the other code
path: a divider `Rin=10` / `Rtop=R` reads `R/(R+10)`, so the expected voltage is
known independently of how ngspice got there.

  1  a derived `.param`                            R = 2*rv
  2  a derived CHAIN                               R = 6*rv
  3  passed on the X line                          R = rv
  4  two instances, different expressions          R = 0.8*rv  (rv || 4rv)
  5  a NESTED X call                               R = rv
  6  a swept param in a `.subckt` header default   R = rv
  7  a derived `.param` INSIDE a subcircuit        R = 2*rv
  8  a local shadow beside a real dependence       R = rv || 2000

numparam has already rewritten the call by the time the original deck is
readable -- `X1 a 0 sub r={rv}` arrives as a POSITIONAL `x1 a 0 sub {rv}` -- so
the `.subckt` header supplies the parameter ORDER (Enhancement-442 met the same
rewrite from the other side). Resolution walks the instance's scope chain
outward: a subcircuit's own `.param`s first (they may reference its formals),
then the formals bound to that call's actuals or to the header default, then the
enclosing frame, then globals.

THE SECOND HALF is a state-restoration bug of the kind Enhancement-385 exists
for. `alterparam` rewrites the DECK TEXT; on the fast path E-385 also pushes the
nominals into the live circuit, but the reset path did neither -- nothing
re-sourced the restored deck, so the devices kept the LAST POINT's values and
every later analysis was quietly wrong:

    after `sweep rv 900 1100`, a fresh `op` read v(a) = 0.99099099
    with @rtop = 1100, where nominal rv = 1000 gives 0.9900990099

Two name collisions are pinned as well. They are not hypothetical: both were hit
while building this, because the matching set grew from the swept names alone to
the whole derived closure.
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
        if junk.startswith("_sf_"):
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


PTS = [900.0, 1000.0, 1100.0]


def run(body, tag, ctl=None, title=None):
    ctl = ctl or ("sweep rv 900 1100 100 -output v(a) -analysis op\nprint v(a)")
    deck = (f"{title or ('sweep subckt fast ' + tag)}\n{body}\n.control\n"
            f"option noacct\nset numdgt=10\n{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_sf_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=180, errors="replace")
    return r.stdout + r.stderr


def rows(out):
    return [float(m.group(1)) for m in
            re.finditer(r"^\d+\s+(-?[\d.]+e[-+]\d+)\s*$", out, re.M)]


def armed(out):
    return "fast .param path armed" in out


def divider(rfun):
    """expected v(a) for Rin=10 in series with R(rv) to ground"""
    return [rfun(v) / (rfun(v) + 10.0) for v in PTS]


def near(got, want, tol=1e-9):
    return len(got) == len(want) and all(
        abs(g - w) <= tol * max(1.0, abs(w)) for g, w in zip(got, want))


CASES = [
    ("1 derived .param", lambda v: 2 * v,
     ".param rv=1000\n.param rd={rv*2}\nV1 in 0 dc 1\nRin in a 10\nRtop a 0 {rd}"),
    ("2 derived chain", lambda v: 6 * v,
     ".param rv=1000\n.param rd={rv*2}\n.param rd2={rd*3}\n"
     "V1 in 0 dc 1\nRin in a 10\nRtop a 0 {rd2}"),
    ("3 passed on the X line", lambda v: v,
     ".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nX1 a 0 sub r={rv}\n"
     ".subckt sub p n r=1000\nR1 p n {r}\n.ends"),
    ("4 two instances, different exprs", lambda v: (v * 4 * v) / (v + 4 * v),
     ".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nX1 a 0 sub r={rv}\n"
     "X2 a 0 sub r={rv*4}\n.subckt sub p n r=1000\nR1 p n {r}\n.ends"),
    ("5 nested X call", lambda v: v,
     ".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nX1 a 0 outer\n"
     ".subckt outer p n\nX2 p n inner r={rv}\n.ends\n"
     ".subckt inner p n r=1000\nR1 p n {r}\n.ends"),
    ("6 swept param in a header default", lambda v: v,
     ".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nX1 a 0 sub\n"
     ".subckt sub p n r={rv}\nR1 p n {r}\n.ends"),
    ("7 derived .param inside a subckt", lambda v: 2 * v,
     ".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nX1 a 0 sub\n"
     ".subckt sub p n\n.param rl={rv*2}\nR1 p n {rl}\n.ends"),
    ("8 shadow beside a real dependence", lambda v: (v * 2000.0) / (v + 2000.0),
     ".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nRtop a 0 {rv}\nX1 a 0 sub\n"
     ".subckt sub p n\n.param rv=2000\nR1 p n {rv}\n.ends"),
]

print("Enhancement-465: sweep on the fast path for subcircuit params\n")
print("every case stays on the fast path, and matches the analytic value")
for label, rfun, body in CASES:
    out = run(body, "c" + label.split()[0])
    got, want = rows(out), divider(rfun)
    check(f"[E-465] {label}: fast path armed", armed(out), "")
    check(f"[E-465] ...and v(a) is exact", near(got, want),
          f"{got} vs {[round(w, 10) for w in want]}")

print("\nthe shadowed device really is held at its local value")
out = run(CASES[7][2], "shadowval",
          "sweep rv 900 1100 100 -output v(a) -analysis op\n"
          "print @r.x1.r1[resistance]")
check("[E-465] a local shadow resolves to 2000, not to the sweep",
      "2.0000000000e+03" in out, "")

print("\nname collisions -- both were hit while building this")
out = run(".param rv=1000\n.param rd={rv*2}\nV1 in 0 dc 1\nRin in a 10\n"
          "Rtop a 0 {rd}\nRd in c 1k\nRe c 0 1k", "devcollide")
check("[E-465] a DEVICE named like a derived param: value still exact",
      near(rows(out), divider(lambda v: 2 * v)), f"{rows(out)}")
out = run(".param rv=1000\n.param rd={rv*2}\nV1 in 0 dc 1\nRin in a 10\n"
          "Rtop a 0 {rd}\nRx in rd 1k\nRy rd 0 2k", "nodecollide")
check("[E-465] a NODE named like a derived param: value still exact",
      near(rows(out), divider(lambda v: 2 * v)), f"{rows(out)}")
out = run(".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nX1 a 0 sub r={rv}\n"
          ".subckt sub p n r=1000\nR1 p n {r}\n.ends", "xtitle",
          title="X-line param deck, titled with an X")
check("[E-465] a deck TITLE starting with 'X' is not read as a call",
      armed(out) and near(rows(out), divider(lambda v: v)), f"{rows(out)}")

print("\nwhat must still fall back")
out = run(".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nRtop a 0 {rv}\n"
          ".temp {rv*0+27}", "structural")
check("[E-465] a structural dot-card still uses the reset path",
      not armed(out) and near(rows(out), divider(lambda v: v)), f"{rows(out)}")
out = run(".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nX1 a 0 sub\n"
          ".subckt sub p n\n.param rv=2000\nR1 p n {rv}\n.ends", "isoshadow")
check("[E-465] an isolated local shadow still falls back (E-321)",
      not armed(out), "")

print("\nthe knob goes back afterwards -- on BOTH paths")
CTL = ("sweep rv 900 1100 100 -output v(a) -analysis op\nprint v(a)\n"
       "op\nprint v(a) @rtop[resistance]")
RESETDECK = (".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nRtop a 0 {rv}\n"
             ".temp {rv*0+27}")
FASTDECK = ".param rv=1000\nV1 in 0 dc 1\nRin in a 10\nRtop a 0 {rv}"
for tag, body, want_fast in (("reset", RESETDECK, False), ("fast", FASTDECK, True)):
    out = run(body, "restore_" + tag, CTL)
    check(f"[E-465] {tag} path: the sweep itself is still correct",
          near(rows(out)[:3], divider(lambda v: v)), f"{rows(out)[:3]}")
    check(f"[E-465] {tag} path: @rtop is back at the nominal 1000",
          "1.0000000000e+03" in out and "1.1000000000e+03" not in out, "")
    m = re.search(r"^v\(a\)\s*=\s*(-?[\d.]+e[-+]\d+)", out, re.M)
    check(f"[E-465] {tag} path: a later op uses nominal, not the last point",
          bool(m) and abs(float(m.group(1)) - 1000.0 / 1010.0) <= 1e-9,
          m.group(1) if m else "no op result")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
