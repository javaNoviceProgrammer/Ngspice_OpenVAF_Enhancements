#!/usr/bin/env python3
"""Enhancement-434: five places where ngspice lost data or answered with a
number it had no business giving, plus one it destroyed outright.

Round-35's hunt found these. What they share is that none of them announced
itself: four returned a plausible value, one ran a command the user did not
type, and one deleted an entire simulation over a typo.

  1. FOUND, NOT FIXED. `save` whose whole list fails to resolve ABORTS the
     analysis ("no data saved ... analysis not run") and every result is lost --
     `save` alone does this, while .probe/.print/print/wrdata diagnose and carry
     on and a bad `@dev[param]` inside `save` merely warns (Enhancement-418).
     The obvious fix -- fall back to recording everything, as when no save list
     is given -- was written, and it turned a benign abort into a SIGTRAP: the
     abort is LOAD-BEARING, stopping execution before a latent long-name stack
     overflow on the `.four`/gettoks path that Enhancement-237 did not reach.
     `.four 1k i(<600 chars>)` goes rc=1 -> rc=133 with the fallback in place.
     Removing the abort therefore requires fixing that overflow first, which is
     its own change. The current behaviour is pinned below so the day it is
     fixed, the pin has to be updated deliberately.
  2. `$simparam("temp")` was not supplied although `tnom` was, so it returned
     the caller's default (the wrong temperature) or, with no default, killed
     the run with OSDI(fatal).
  3. `$simparam("abstime")` returned the DC SWEEP VALUE during `.dc`, because
     ngspice reuses CKTtime as the sweep abscissa. A model asking for a time got
     a voltage.
  4. montecarlo/highsigma/wcd assembled `-analysis` into a fixed 512-byte
     buffer with strncat, so a longer command was silently shortened and a
     DIFFERENT command ran.
  5. `.tf` computed an operating point and reported a result while saying
     nothing about a model's $finish -- the one analysis that produces a result
     and stays silent. (dcop, dctrcurv, acan, noisean and dctran all report it.)
  6. WITHDRAWN. A top-level model named `<instance>:<model>` does collide with
     a subcircuit's own flattened model name and silently wins, changing the
     answer -- but ngspice ALREADY says so ("model \"x1:rmod\" is already
     defined; keeping the first definition"). The hunt missed it by checking
     only values on that probe. Adding a second warning would duplicate a
     diagnostic, which is the very thing Enhancement-430 fixed for `.probe`, so
     nothing was changed. The existing warning is pinned below so it cannot be
     lost.

DELIBERATE NON-FIXES, asserted here so they are not mistaken for regressions:
`$finish` at an operating point is REPORTED but not acted on -- Enhancement-426
decided that, because an operating point is a single already-computed point and
discarding it would delete a legitimate result. (6) was withdrawn outright -- see above.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

OSDI = os.path.join(HERE, "_silentloss.osdi")
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(deck, tag, timeout=120):
    p = os.path.join(HERE, f"_sl_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout,
                       errors="replace")
    return r.returncode, r.stdout + r.stderr


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m[-1]) if m else None


def vectors(out):
    return [l.split(":")[0].strip() for l in out.splitlines()
            if "real," in l or "notype" in l]


# A plain deck (no OSDI) for the save and collision checks.
PLAIN = """* silentloss plain
V1 a 0 dc 1
R1 a b 1k
R2 b 0 1k
.control
option noacct
{ctl}
.endc
.end
"""

OSDIDECK = """* silentloss osdi
.model sm silentloss {mp}
V1 a 0 dc 1 ac 1
N1 a 0 sm
Rp a 0 1k
.control
pre_osdi {osdi}
option noacct
{ctl}
.endc
.end
"""


def osdi_deck(ctl, mp=""):
    return OSDIDECK.format(ctl=ctl, osdi=OSDI, mp=mp)


def main():
    print("Enhancement-434: silent wrong values, a silent truncation, "
          "and a destroyed run\n")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "silentloss.va"), "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    if not check("silentloss.va compiles", r.returncode == 0 and os.path.exists(OSDI),
                 (r.stdout + r.stderr).strip().splitlines()[:1]):
        return 1

    # ---------------------------------------------------------------- 1. save
    print("\n1. FOUND NOT FIXED: a save list resolving to nothing aborts the run")
    rc, out = run(PLAIN.format(ctl="save v(nosuchnode)\nop\nprint v(b)"), "save_bad")
    check("[E-434] current behaviour pinned: the analysis is aborted",
          "analysis not run" in out, f"rc={rc}")
    # WHY it is not fixed: the abort stops execution before a latent overflow.
    Q = "q" * 600
    rc2, _ = run("* gettoks\nv1 1 0 dc 1 sin(0 1 1k)\nr1 1 0 1k\n"
                 f".tran 1u 1m\n.four 1k i({Q})\n.end\n", "ovf")
    check("[E-434] ...and the long-name path it protects does not crash today",
          rc2 >= 0, f"rc={rc2}")

    # the two directions that must not move
    rc, out = run(PLAIN.format(ctl="save v(a) v(nosuch) v(b)\nop\ndisplay"), "save_mix")
    check("[E-434] a bad name among good ones still keeps the good ones",
          sorted(vectors(out)) == ["a", "b"], str(vectors(out)))
    rc, out = run(PLAIN.format(ctl="save v(b)\nop\ndisplay"), "save_ok")
    check("[E-434] an ordinary save still records exactly what was asked",
          vectors(out) == ["b"], str(vectors(out)))

    # ------------------------------------------------------- 2. simparam temp
    print("\n2. $simparam(\"temp\") is supplied, in Celsius, like tnom beside it")
    for t in (27, 100):
        rc, out = run(osdi_deck(f"option temp={t}\nop\nprint @n1[p_temp] @n1[p_tnom]"),
                      f"temp{t}")
        check(f"[E-434] option temp={t} reaches $simparam(\"temp\")",
              val(out, "@n1[p_temp]") == float(t),
              f"got {val(out,'@n1[p_temp]')}")
    check("[E-434] ...and tnom is unchanged beside it",
          val(out, "@n1[p_tnom]") == 27.0, f"got {val(out,'@n1[p_tnom]')}")

    # $simparam("temp") is the GLOBAL/analysis temperature and must NOT follow an
    # instance-line temp=/dtemp= -- that is $temperature's job (Enhancement-397).
    # get_simparams() takes the circuit and its result is shared by every
    # instance, so a per-device answer here is not merely unimplemented, it is
    # the wrong layer. Pinned so it is not "fixed" into per-instance later.
    INST = """* per-instance temp
.model sm silentloss
V1 a 0 dc 1
R1 a b 1k
N1 b 0 sm temp=100
R2 a c 1k
N2 c 0 sm
.control
pre_osdi {osdi}
option noacct
op
print @n1[p_temp] @n2[p_temp]
.endc
.end
"""
    rc, out = run(INST.format(osdi=OSDI), "inst_temp")
    n1 = val(out, "@n1[p_temp]")
    n2 = val(out, "@n2[p_temp]")
    check("[E-434] $simparam(\"temp\") is the GLOBAL temperature, not the instance's",
          n1 == 27.0 and n2 == 27.0, f"n1={n1} n2={n2} (instance temp=100 must not move it)")

    # ---------------------------------------------------------- 3. abstime
    print("\n3. abstime is a TIME: zero outside a transient, never the sweep value")
    rc, out = run(osdi_deck("dc V1 0 5 1\nprint @n1[p_abstime]"), "abs_dc")
    check("[E-434] .dc no longer hands the model its sweep value as a time",
          val(out, "@n1[p_abstime]") == 0.0, f"got {val(out,'@n1[p_abstime]')}")
    rc, out = run(osdi_deck("dc V1 -3 -1 1\nprint @n1[p_abstime]"), "abs_dcneg")
    check("[E-434] ...including a negative sweep",
          val(out, "@n1[p_abstime]") == 0.0, f"got {val(out,'@n1[p_abstime]')}")
    rc, out = run(osdi_deck("tran 1n 20n\nprint @n1[p_abstime]"), "abs_tran")
    check("[E-434] ...while a transient still reports the real time",
          abs((val(out, "@n1[p_abstime]") or 0) - 2e-8) < 1e-12,
          f"got {val(out,'@n1[p_abstime]')}")
    for an in ("op", "ac dec 2 1e3 1e5"):
        rc, out = run(osdi_deck(f"{an}\nprint @n1[p_abstime]"), "abs_" + an[:3])
        check(f"[E-434] ...and {an} still reports 0",
              val(out, "@n1[p_abstime]") == 0.0, f"got {val(out,'@n1[p_abstime]')}")

    # ------------------------------------------- 4. the 512-byte analysis buffer
    print("\n4. an over-long -analysis is refused, never silently shortened")
    toks = " ".join(f"t{i:03d}" for i in range(120))          # ~600 chars
    for cmd, tail in (("montecarlo 2", " -spec v(b) -max 9"),
                      ("highsigma 2", " -metric v(b) -max 9"),
                      ("wcd -metric v(b) -max 9", "")):
        name = cmd.split()[0]
        rc, out = run(PLAIN.format(ctl=f"{cmd} -analysis echo {toks}{tail}"), "long" + name)
        seen = [int(m) for m in re.findall(r"\bt(\d{3})\b", out)]
        check(f"[E-434] {name} refuses it instead of running a truncated command",
              "-analysis command is too long" in out and not seen,
              f"echoed up to t{max(seen):03d}" if seen else "nothing echoed")
    # and a normal-length one is completely unaffected
    rc, out = run(PLAIN.format(ctl="montecarlo 2 -analysis op -spec v(b) -max 9"), "short_mc")
    check("[E-434] a normal -analysis is untouched",
          "too long" not in out and "analysis 'op'" in out)

    # ------------------------------------------------------------- 5. .tf notice
    print("\n5. .tf reports a deferred $finish instead of silently swallowing it")
    rc, out = run(osdi_deck("tf v(a) V1\nprint transfer_function", mp="trip=0.5"), "tf_fin")
    check("[E-434] the notice is printed",
          "requested by a Verilog-A device during the transfer-function" in out)
    check("[E-434] ...and the result is still reported (E-426's decision)",
          val(out, "transfer_function") is not None,
          f"tf={val(out,'transfer_function')}")
    rc, out = run(osdi_deck("tf v(a) V1\nprint transfer_function"), "tf_quiet")
    check("[E-434] a model that does NOT call $finish stays quiet",
          "requested by a Verilog-A device" not in out)

    # -------------------------------------------------------- 6. name collision
    print("\n6. WITHDRAWN: the collision was already diagnosed -- pin that warning")
    COLLIDE = """* collide
.model x1:rmod r (res=7777)
V1 in 0 dc 1
X1 in out sub
R2 out 0 1k
Rz in z 1k
Rq z 0 x1:rmod
.subckt sub a b
Rx a b rmod
.model rmod r (res=1000)
.ends
.control
option noacct
op
print @x1.rx[resistance]
.endc
.end
"""
    rc, out = run(COLLIDE, "collide")
    check("[E-434] the collision is reported (pre-existing diagnostic, pinned)",
          'is already defined; keeping the first definition' in out,
          out[-140:].replace("\n", " "))
    # and the ordinary case must stay silent
    rc, out = run(COLLIDE.replace("x1:rmod", "plainmod"), "nocollide")
    check("[E-434] an ordinary deck raises no such warning",
          "is already defined" not in out)
    check("[E-434] ...and the subcircuit's own model is used (1000 ohm)",
          val(out, "@x1.rx[resistance]") == 1000.0,
          f"got {val(out,'@x1.rx[resistance]')}")

    for junk in os.listdir(HERE):
        if junk.startswith("_sl_") or junk == "_silentloss.osdi":
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    return 0 if passed == checks else 1


sys.exit(main())
