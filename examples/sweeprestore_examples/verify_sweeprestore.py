#!/usr/bin/env python3
"""Enhancement-350: a sweep puts its `.param` back when it finishes.

Sweeping a `.param` twice used to leave the parameter stuck at the last swept
value in a way `reset` could not undo:

    .param rload = 3k
    sweep rload lin 3 1k 5k  -analysis op -output v(out)
    sweep rload lin 3 2k 10k -analysis op -output v(out)
    reset
    op            ->  v(out) = 0.909   (rload still 10k; the deck says 3k)

Two paths, disagreeing about the state they leave behind. The reset path drives
each point with `alterparam`, which edits the parameter PERMANENTLY, so a later
`reset` re-sources a deck that now carries the last swept value. The E-320 fast
path never touches the deck, so `reset` did restore. Which path you got decided
what your circuit was worth afterwards -- and E-320's whole guarantee is that it
cannot.

It compounded: arming self-checks each captured expression against the value
numparam baked into the flattened card at nominal, so a dico still holding the
previous sweep's value could never pass. The second sweep silently dropped to the
reset path -- no error, just the fast path quietly gone, and then the permanent
edit above.

The sweep now restores both the deck text and the numparam dico on the way out.

  [1] reset restores the .param after ONE sweep (this always worked -- guards it)
  [2] reset restores it after TWO, and after THREE -- the actual bug
  [3] every sweep arms the fast path, not just the first (the silent fallback)
  [4] restoring is exact for a derived param and a subckt-internal value
  [5] the swept RESULTS are unchanged -- a sweep still computes what it did
  [6] the committed reproducer deck survives
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

# 1 V across 1k + rload; v(out) = rload/(1k+rload). Nominal 3k -> exactly 0.75.
DECK = ("sweeprestore\n.param rload = 3k\n"
        "V1 in 0 dc 1\nR1 in out 1k\nR2 out 0 {rload}\n")
NOMINAL = 0.75

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(control, deck=None, timeout=120):
    p = os.path.join(HERE, "_sr.cir")
    with open(p, "w") as f:
        f.write("%s.control\noption noacct\nset numdgt=10\n%s\n.endc\n.end\n"
                % (deck or DECK, control))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return None, "HANG"
    finally:
        if os.path.exists(p):
            os.remove(p)
    return r.returncode, r.stdout + r.stderr


def last_val(out, tag="v(out)"):
    m = re.findall(re.escape(tag) + r"\s*=\s*([-\d.]+e?[-+]?\d*)", out)
    return float(m[-1]) if m else None


SW = "sweep rload %s -analysis op -output v(out)"
LIN = SW % "lin 3 1k 5k"          # last point 5k
LIST = SW % "list 2k 10k"         # last point 10k
DEC = SW % "dec 2 1k 10k"         # last point 10k


def main():
    # ---- [1]/[2] reset restores, however many sweeps ran --------------------
    bad = []
    for label, body in (("one", LIN),
                        ("two", LIN + "\n" + LIST),
                        ("three", LIN + "\n" + LIST + "\n" + DEC),
                        ("mixed spec forms", LIST + "\n" + DEC + "\n" + LIN)):
        rc, out = run(body + "\nreset\nop\nprint v(out)")
        v = last_val(out)
        if v is None or abs(v - NOMINAL) > 1e-9:
            bad.append(f"{label}: {v}")
    check("reset restores the .param after any number of sweeps",
          not bad, "; ".join(bad) if bad else "1/2/3/mixed all 0.75")

    # ---- [3] the fast path arms EVERY time, not only the first --------------
    rc, out = run(LIN + "\n" + LIST + "\n" + DEC)
    n = out.count("fast .param path armed")
    check("every sweep arms the fast path (no silent fallback)", n == 3,
          f"{n} of 3 armed")

    # ---- [4] derived and subckt-internal params restore too -----------------
    derived = ("sr derived\n.param base = 1k\n.param rload = 'base*3'\n"
               "V1 in 0 dc 1\nR1 in out 1k\nR2 out 0 {rload}\n")
    rc, out = run("sweep base lin 3 500 2k -analysis op -output v(out)\n"
                  "sweep base lin 3 600 4k -analysis op -output v(out)\n"
                  "reset\nop\nprint v(out)", deck=derived)
    v_der = last_val(out)          # base 1k -> rload 3k -> 0.75
    subckt = ("sr subckt\n.param rval = 3k\n"
              "V1 in 0 dc 1\nR1 in mid 1k\nX1 mid 0 div\n"
              ".subckt div a b\nRa a b {rval}\n.ends\n")
    rc2, out2 = run("sweep rval lin 3 1k 5k -analysis op -output v(mid)\n"
                    "sweep rval lin 3 2k 9k -analysis op -output v(mid)\n"
                    "reset\nop\nprint v(mid)", deck=subckt)
    v_sub = last_val(out2, "v(mid)")
    check("a derived param and a subckt-internal value restore exactly",
          v_der is not None and abs(v_der - NOMINAL) < 1e-9
          and v_sub is not None and abs(v_sub - NOMINAL) < 1e-9,
          f"derived={v_der} subckt={v_sub}")

    # ---- [5] the sweep still computes what it always did --------------------
    rc, out = run("sweep rload lin 5 1k 5k -analysis op -output v(out)\nprint v(out)")
    # a swept analysis prints an index table, not `tag = value`; the row is
    # "<index> <value>" with the scale implicit, so take the last column
    got = []
    for line in out.splitlines():
        m = re.match(r"^\s*\d+\s+([-\d.]+e[-+]\d+)\s*$", line)
        if m:
            got.append(float(m.group(1)))
    want = [r / (1000.0 + r) for r in (1000, 2000, 3000, 4000, 5000)]
    ok = len(got) == 5 and all(abs(a - b) < 1e-9 for a, b in zip(got, want))
    check("the swept values are unchanged (closed form rload/(1k+rload))",
          ok, f"{len(got)} points" if ok else f"got {got}")

    # ---- [6] the committed deck ---------------------------------------------
    r = subprocess.run([NGSPICE, "-b", "sweeprestore.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=180,
                       errors="replace")
    txt = r.stdout + r.stderr
    v = last_val(txt)
    check("the committed reproducer deck ends at the nominal value",
          r.returncode == 0 and v is not None and abs(v - NOMINAL) < 1e-9,
          f"rc={r.returncode} v(out)={v}")

    # ---- [7] a BARE device knob is captured and restored too ----------------
    # `sweep V1 0 5 1` sets the knob through `alter V1=<val>`, which resolves a
    # NULL parameter to the device's IF_PRINCIPAL one. The capture side read the
    # name as a VECTOR expression instead, which only `@v1[dc]` satisfies -- so
    # the bare spelling could be set but never read back, the sweep ran to the
    # end, and the device was left at its LAST swept value. The same guard, and
    # one spelling that never reached it (the E-437 shape).
    print("\n[7] a bare device knob is restored, not left at the last point")
    ELEM = ("sweeprestore-elem\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 3k\n"
            "I1 0 out dc 0\n")
    for knob, rng, probe, want in (("V1", "0 5 1", "@v1[dc]", 1.0),
                                   ("R1", "1k 5k 1k", "@r1[resistance]", 1000.0),
                                   ("I1", "0 1m 0.5m", "@i1[dc]", 0.0)):
        rc, out = run(f"op\nsweep {knob} {rng} -analysis op -output v(out)\n"
                      f"setplot new\nop\nprint {probe}", deck=ELEM)
        got = last_val(out, probe)
        check(f"bare `{knob}` is put back ({probe} = {want:g})",
              rc == 0 and got is not None and abs(got - want) <= 1e-9 * max(1.0, abs(want)),
              f"got {got}")
        check(f"...and `sweep {knob}` no longer warns it could not be read",
              "could not be read" not in out)
    # the spelling that always worked must keep working
    rc, out = run("op\nsweep @v1[dc] 0 5 1 -analysis op -output v(out)\n"
                  "setplot new\nop\nprint @v1[dc]", deck=ELEM)
    check("the @v1[dc] spelling still restores (control)",
          rc == 0 and (last_val(out, "@v1[dc]") or 0) == 1.0,
          f"{last_val(out, '@v1[dc]')}")
    # and the sweep's own OUTPUT is unchanged: v(out) = V1 * 3k/4k
    rc, out = run("sweep V1 0 4 1 -analysis op -output vo=v(out)\nprint vo",
                  deck=ELEM)
    rows = re.findall(r"^\s*\d+\t(\S+)", out, re.M)
    check("the swept values themselves are still right (0 .. 3 V)",
          rc == 0 and len(rows) == 5 and abs(float(rows[-1]) - 3.0) < 1e-6,
          f"{rows}")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
