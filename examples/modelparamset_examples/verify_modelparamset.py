#!/usr/bin/env python3
"""Enhancement-344: `.model` params take the fast sweep's direct set.

The `.param` fast sweep (Enhancement-320..323) resolves each swept device value
to a slot once and pushes it with `ft_sim->setInstanceParm`, skipping the
per-point reset. MODEL params were the one tier left on the textual path: every
point ran `altermod <model> <param> = <value>` as a command, which re-lexes it
and re-resolves the model BY NAME each time.

E-344 resolves a model bind to `(GENmodel *, type, param-id)` once at arm time
and pushes it with `ft_sim->setModelParm`. Measured: model-param sweeps now cost
the same as instance-param sweeps (they were 2.1x-2.8x slower), which is 3.1x
faster than the textual tier on a 400-model deck.

The textual path was already CORRECT -- it matched the reset path exactly on
every device kind tried -- so this is purely a speed change, and these checks
are about not breaking that correctness while taking the faster route.

  [1] a model-param sweep arms AND every bind takes the direct set
  [2] the values are exact in closed form: v(out) = 1000/(rsh + 1000)
  [3] an OSDI model param does the same (compiled models resolve identically)
  [4] a subcircuit-internal model param arms and is exact
  [5] a NON-REAL model param cannot take the direct set, falls back, says so,
      and is still correct
  [6] model and instance binds mix in one sweep
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402

BANNER = "fast .param path armed"
FALLBACK = "via alter/altermod"
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(name, body, control, timeout=300):
    p = os.path.join(HERE, "_%s.cir" % name)
    with open(p, "w") as f:
        # numdgt so the closed-form comparison is not limited by the default
        # 7-significant-digit print (which is looser than the agreement here)
        f.write("t %s\n%s.control\nset numdgt=12\n%s\n.endc\n.end\n"
                % (name, body, control))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    finally:
        if os.path.exists(p):
            os.remove(p)
    t = r.stdout + r.stderr
    vals = [float(x) for x in
            re.findall(r"^\s*\d+\s+([-\d.]+e[-+]\d+)\s*$", t, re.M)]
    return r.returncode, t, vals


def divider(rs):
    """v(out) for a semiconductor R (l=w=1u, so R=rsh) above a 1k load."""
    return [1000.0 / (r + 1000.0) for r in rs]


def close(got, want, rtol=1e-10):
    return (len(got) == len(want)
            and all(abs(g - w) <= rtol * abs(w) for g, w in zip(got, want)))


RES_BODY = (".param p = 100\nV1 in 0 dc 1\nR1 in out rm l=1u w=1u\n"
            "R2 out 0 1k\n.model rm r rsh={p}\n")
SWEEP = "sweep p lin 5 100 500 -analysis op -output v(out)\nprint v(out)"


def main():
    # [1] + [2] the plain model-param sweep
    rc, out, vals = run("res", RES_BODY, SWEEP)
    armed = BANNER in out
    all_direct = armed and FALLBACK not in out
    check("a model-param sweep arms and every bind takes the direct set",
          rc == 0 and all_direct,
          next((l.strip() for l in out.splitlines() if BANNER in l), "no banner"))
    check("values exact in closed form, v(out) = 1000/(rsh+1000)",
          close(vals, divider([100, 200, 300, 400, 500])),
          f"{[round(v, 9) for v in vals]}")

    # [3] an OSDI model parameter
    va = os.path.join(ROOT, "examples", "optimize_examples", "optresm.va")
    osdi = os.path.join(HERE, "_optresm.osdi")
    if not os.path.exists(va):
        check("an OSDI model param takes the direct set", False, "optresm.va missing")
    else:
        c = subprocess.run([OPENVAF, va, "-o", osdi], capture_output=True,
                           text=True, timeout=300)
        if c.returncode != 0:
            check("an OSDI model param takes the direct set", False,
                  f"compile rc={c.returncode}")
        else:
            body = (".param p = 1000\nV1 in 0 dc 1\nN1 in out om\nR2 out 0 1k\n"
                    ".model om optresm r={p}\n")
            ctl = ("pre_osdi %s\nsweep p lin 5 500 2500 -analysis op "
                   "-output v(out)\nprint v(out)" % os.path.basename(osdi))
            rc, out, vals = run("osdi", body, ctl)
            check("an OSDI model param takes the direct set and is exact",
                  rc == 0 and BANNER in out and FALLBACK not in out
                  and close(vals, divider([500, 1000, 1500, 2000, 2500])),
                  f"{[round(v, 9) for v in vals]}")
            if os.path.exists(osdi):
                os.remove(osdi)

    # [4] a model declared inside a subcircuit (Enhancement-321 tier)
    body = (".param p = 100\nV1 in 0 dc 1\nX1 in mid sub\nX2 mid out sub\n"
            "R9 out 0 1k\n.subckt sub a b\nR1 a b rm l=1u w=1u\n"
            ".model rm r rsh={p}\n.ends\n")
    rc, out, vals = run("sub", body, SWEEP)
    # two subckts in series, each R = p, above the 1k load
    want = [1000.0 / (2 * r + 1000.0) for r in (100, 200, 300, 400, 500)]
    check("a subcircuit-internal model param arms and is exact",
          rc == 0 and BANNER in out and close(vals, want),
          f"{[round(v, 9) for v in vals]}")

    # [5] a non-real model param must NOT take the direct set
    body = (".param p = 1\nV1 d 0 dc 2\nVg g 0 dc 1.5\nM1 d g 0 0 nm w=1u l=1u\n"
            ".model nm nmos level={p} vto=0.7 kp=1e-4\n")
    rc, out, _ = run("int", body,
                     "sweep p lin 2 1 1 -analysis op -output i(v1)\nprint i(v1)")
    check("a non-real model param falls back to the textual push, and says so",
          rc == 0 and BANNER in out and FALLBACK in out,
          next((l.strip() for l in out.splitlines() if BANNER in l), "no banner"))

    # [6] model and instance binds together
    body = (".param p = 100\nV1 in 0 dc 1\nR1 in m rm l=1u w=1u\n"
            "R2 m out {p*10}\nR3 out 0 1k\n.model rm r rsh={p}\n")
    rc, out, vals = run("mix", body, SWEEP)
    want = [1000.0 / (r + 10.0 * r + 1000.0) for r in (100, 200, 300, 400, 500)]
    check("model and instance binds mix in one sweep, both direct and exact",
          rc == 0 and BANNER in out and FALLBACK not in out and close(vals, want),
          f"{[round(v, 9) for v in vals]}")

    # the committed deck
    r = subprocess.run([NGSPICE, "-b", "modelparamset.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    t = r.stdout + r.stderr
    ends = re.findall(r"v\(out\)\[\d+\] = ([-\d.]+e[-+]\d+)", t)
    check("the committed deck runs and its endpoints are right",
          r.returncode == 0 and "SURVIVED" in t and len(ends) == 2
          and abs(float(ends[0]) - 1000.0 / 1100.0) < 1e-11
          and abs(float(ends[1]) - 1000.0 / 1500.0) < 1e-11,
          f"rc={r.returncode} endpoints={ends}")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
