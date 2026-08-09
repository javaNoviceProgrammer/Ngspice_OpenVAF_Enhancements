#!/usr/bin/env python3
"""Enhancement-427: a swept parameter the device refused, and an event that
landed on the last timepoint.

[1] `.dc @inst[param]` APPLIED A VALUE THE MODEL'S `from` RANGE FORBIDS.

    With `(*type="instance"*) parameter real r = 1000 from (0:inf)`:

        dc @n1[r] -2000 -1000 500
          -> THREE data rows at R = -2000, -1500, -1000
             "Parameter r is out of bounds!" printed four times
             rc = 0

    Every other route to the same parameter refuses it: the instance line,
    `alter` + a run, and the `sweep` command all abort. `.dc @inst[param]` was
    the one path that applied it and published the answer.

    The range is NOT checked when the value is written -- `OSDIparam` has no
    range check at all, which is why `alter @n1[r]=-5` stores -5 happily. It is
    checked when the device is set up again, inside `DEVtemperature`
    (`OSDItemp` -> `setup_instance`). `DCTsetInstParam` was `void` and threw
    away BOTH return values, so the failure never reached the sweep loop.

    The test is deliberately "the DEVICE refused this value", never "the value
    looks wrong": a negative resistance is legitimate for a built-in resistor
    (`resparam.c` has an explicit branch for one), and that sweep still works.

[2] ...AND THE SWEEP HANDED THE DEVICE ONE VALUE PAST `stop`.

    `.dc` advances the parameter and only then tests the stop criterion, so it
    always sets one value beyond the end -- harmless while failures were
    ignored, but it means a sweep that legitimately ENDS AT the edge of a range
    steps one point outside it. `parameter real k = 0.5 from [0:1]` with
    `dc @n1[k] 0 1 0.25` printed "Parameter k is out of bounds!" once while
    producing five correct rows, even before this enhancement. Refusing the
    refusal without fixing this would have broken that valid sweep -- so the
    past-stop value is no longer applied at all. The TEMP_CODE arm has always
    declined its own overshoot for exactly this reason.

[3] AN `@(timer)` EVENT LANDING EXACTLY ON `tstop` NEVER FIRED.

        dt = 1e-8, tstop = 1e-6  ->  100 ticks, want 101

    Independent of the transient step. `next` is built by REPEATED ADDITION,
    one `fadd` per fire, so after N periods it carries N roundings and sits a
    couple of ULP past the exact N*period. When tstop is an exact multiple of
    the period -- the ordinary case -- the schedule lands just beyond it and
    `abstime >= next` is false at the final timepoint. Measured: dt = 1e-8,
    2e-8, 3e-8 and 4e-8 accumulate 3e-22..6e-22 OVER and lost their last event,
    while 5e-9, 1e-7 and 1e-9 landed at or below tstop and were correct -- which
    is why it looked sporadic. `@(final_step)` fires at that same instant, so
    the timepoint is genuinely reached.

[4] AN INTEGER INSTANCE PARAMETER COULD NOT BE SWEPT, AND THE REFUSAL LIED.

    `dc @n1[n] 1 4 1` over `parameter integer n` reported "Voltage source,
    current source, or resistor named "@n1[n]" is not in the circuit" -- a
    sentence that is false in every particular: the device is in the circuit and
    the parameter is settable. The cause was an explicit `IF_REAL` test folded
    into the keyword match, so a wrong-type hit was indistinguishable from a
    miss. Integer sweeps now work; a FRACTIONAL one is refused, because the
    accumulator has to stay real and rounding it at the device boundary would
    publish duplicate operating points under an abscissa that disagrees with the
    value applied.

[5] NOT FIXED, AND WHY: `.ic`/`.nodeset` ON A DEVICE-INTERNAL NODE.

    `.ic v(n1#mid)=0.5` is ignored, while a built-in `C1 mid 0 1n ic=0.5` works.
    This is NOT an OSDI gap. `INPpas3` resolves .ic/.nodeset names before
    `CKTsetup()`, which is when EVERY device -- built-in and OSDI alike --
    creates its internal nodes, and inppas3.c's own header comment says so:
    "All circuit nodes will have been created by now, (except for internal
    device nodes)". A built-in diode's `d1#internal` is rejected identically.
    Pinned below so the symmetry is not mistaken for a regression later.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    if ok:
        passed += 1
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} {detail}")


def build(src, tag):
    va = os.path.join(HERE, tag + ".va")
    with open(va, "w") as fh:
        fh.write(src)
    r = subprocess.run([OPENVAF, va, "-o", os.path.join(HERE, tag + ".osdi")],
                       capture_output=True, text=True, cwd=HERE, timeout=300)
    if r.returncode:
        print(r.stdout + r.stderr)
    return r.returncode == 0


def run(deck, name="_sp.cir", timeout=120):
    """Run a deck; return (rc, stdout+stderr). BOTH streams, deliberately."""
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -99, "TIMEOUT"


def rows(out, ncols=2):
    """Numeric rows of a printed table, told how many columns to expect.

    A reader that guesses reads a single-row plot -- and a 3-column sweep
    table -- as 'no output', which is how two round-34 findings were briefly
    mis-scored.
    """
    got = []
    for line in out.splitlines():
        p = line.split()
        if len(p) == ncols + 1 and p[0].isdigit():
            try:
                got.append(tuple(float(x) for x in p[1:]))
            except ValueError:
                pass
    return got


def scalars(out, name):
    return [float(x) for x in
            re.findall(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)]


def sweep_vals(out):
    """i(v1) from a .dc, whether printed as a table or as a single scalar."""
    r = rows(out, 2)
    return [x[1] for x in r] if r else scalars(out, "i(v1)")


def close(a, b, tol=1e-6):
    return isinstance(a, float) and abs(a - b) <= tol * max(1.0, abs(b))


RANGED = """`include "disciplines.vams"
module sp_res(a,c);
  inout a,c; electrical a,c;
  (*type="instance"*) parameter real r = 1000.0 from (0:inf);
  analog I(a,c) <+ V(a,c)/r;
endmodule
"""

EDGE = """`include "disciplines.vams"
module sp_edge(a,c);
  inout a,c; electrical a,c;
  (*type="instance"*) parameter real k = 0.5 from [0:1];
  analog I(a,c) <+ V(a,c)*(1.0+k)/1000.0;
endmodule
"""

INTP = """`include "disciplines.vams"
module sp_int(a,c);
  inout a,c; electrical a,c;
  (*type="instance"*) parameter integer n = 1 from [1:8];
  (*type="instance"*) parameter real    r = 1000.0 from (0:inf);
  analog I(a,c) <+ V(a,c)*n/r;
endmodule
"""

TIMER = """`include "disciplines.vams"
module sp_tmr(a,c);
  inout a,c; electrical a,c;
  parameter real dt = 1e-8;
  integer nticks;
  analog begin
    @(initial_step) nticks = 0;
    @(timer(0, dt)) nticks = nticks + 1;
    $bound_step(dt);
    I(a,c) <+ V(a,c)/1000.0;
    @(final_step) $strobe("TICKS=%d", nticks);
  end
endmodule
"""


def ctl(body, osdi):
    return (".control\npre_osdi %s.osdi\noption noacct\nset numdgt=12\n" % osdi
            + body + "\n.endc\n.end\n")


def main():
    for tag, src in (("sp_res", RANGED), ("sp_edge", EDGE),
                     ("sp_int", INTP), ("sp_tmr", TIMER)):
        if not build(src, tag):
            print(f"FATAL: {tag}.va did not compile")
            sys.exit(1)

    RDECK = "V1 a 0 dc 1\nN1 a 0 rm\n.model rm sp_res()\n"

    # ------------------------------------------------------------------ [1]
    print("\n[1] a .dc sweep into the range the model forbids is refused")
    for sw, label in (("-2000 -1000 500", "a sweep entirely inside the forbidden region"),
                      ("-5 -5 1", "a single forbidden point"),
                      ("0 0 1", "the open endpoint r = 0")):
        rc, out = run("* sp\n" + RDECK + ctl(f"dc @n1[r] {sw}\nprint i(v1)", "sp_res"))
        v = sweep_vals(out)
        check(f"{label} -> refused, nothing published",
              rc != 0 and len(v) == 0, f"rc={rc} vals={v}")
    rc, out = run("* sp\n" + RDECK
                  + ctl("dc @n1[r] 500 -500 -500\nprint i(v1)", "sp_res"))
    v = sweep_vals(out)
    check("a sweep that CROSSES into it publishes the valid point, then stops",
          rc != 0 and len(v) == 1 and close(-1.0 / v[0], 500.0), f"rc={rc} vals={v}")
    check("...and the message names the sweep, the parameter and the value",
          "the device refused @n1[r]" in out, out[-160:].replace("\n", " "))

    print("\n    every legitimate sweep still works, and restores the value")
    rc, out = run("* sp\n" + RDECK
                  + ctl("dc @n1[r] 500 2000 500\nprint i(v1)", "sp_res"))
    v = sweep_vals(out)
    check("r = 500..2000 -> four points",
          rc == 0 and [round(-1.0 / x) for x in v] == [500, 1000, 1500, 2000],
          str(v))
    rc, out = run("* sp\n" + RDECK
                  + ctl("dc @n1[r] 1000 1000 1\nprint i(v1)", "sp_res"))
    check("a single legitimate point", rc == 0 and len(sweep_vals(out)) == 1)
    rc, out = run("* sp\n" + RDECK
                  + ctl("dc v1 1 2 1 @n1[r] 1000 2000 1000\nprint i(v1)", "sp_res"))
    check("a nested sweep, both levels legitimate", rc == 0 and len(sweep_vals(out)) == 4)
    rc, out = run("* sp\n" + RDECK + ctl(
        "op\nprint i(v1)\ndc @n1[r] 500 2000 500\nop\nprint i(v1)", "sp_res"))
    sc = scalars(out, "i(v1)")
    check("the pre-sweep value is restored afterwards",
          len(sc) >= 2 and close(sc[0], sc[-1]), str(sc[:1] + sc[-1:]))
    rc, out = run("* sp\n" + RDECK
                  + ctl("dc v1 1 2 1 @n1[r] -2000 -1000 1000\nprint i(v1)", "sp_res"))
    check("a forbidden value on the INNER nest level is refused too",
          rc != 0 and len(sweep_vals(out)) == 0, f"rc={rc}")

    print("\n    a BUILT-IN resistor swept negative is UNAFFECTED (E-426 precedent)")
    rc, out = run("* sp\nV1 a 0 dc 1\nR1 a 0 1k\n.control\noption noacct\n"
                  "set numdgt=12\ndc @r1[resistance] -2000 -1000 500\n"
                  "print i(v1)\n.endc\n.end\n")
    v = sweep_vals(out)
    check("ngspice supports a negative resistor, and still does",
          rc == 0 and len(v) == 3, f"rc={rc} vals={v}")

    # ------------------------------------------------------------------ [2]
    print("\n[2] the value one step PAST stop is never handed to the device")
    EDECK = "V1 a 0 dc 1\nN1 a 0 em\n.model em sp_edge()\n"
    for sw, want in (("0 1 0.25", 5), ("0 1 0.5", 3), ("0 0.75 0.25", 4)):
        rc, out = run("* sp\n" + EDECK + ctl(f"dc @n1[k] {sw}\nprint i(v1)", "sp_edge"))
        v = sweep_vals(out)
        check(f"k = {sw} ends AT the range edge -> {want} rows, no complaint",
              rc == 0 and len(v) == want and "out of bounds" not in out,
              f"rc={rc} n={len(v)} oob={out.count('out of bounds')}")

    # ------------------------------------------------------------------ [3]
    print("\n[3] a timer event landing exactly on tstop now fires")

    def ticks(dt, tstop, step=None):
        step = step or tstop / 50
        rc, out = run("* sp\nV1 a 0 dc 1\nN1 a 0 tm\n"
                      f".model tm sp_tmr(dt={dt!r})\n"
                      + ctl(f"tran {step!r} {tstop!r}", "sp_tmr"), timeout=180)
        m = re.findall(r"TICKS=(\d+)", out)
        return int(m[-1]) if m else None

    for dt, tstop in ((1e-8, 1e-6), (2e-8, 1e-6), (4e-8, 1e-6),
                      (3e-8, 9e-7), (1e-8, 5e-7)):
        want = int(round(tstop / dt)) + 1
        check(f"dt={dt:g} tstop={tstop:g} -> {want} ticks", ticks(dt, tstop) == want,
              f"got {ticks(dt, tstop)}")
    for dt, tstop in ((5e-9, 1e-6), (1e-7, 1e-6), (1e-9, 1e-7)):
        want = int(round(tstop / dt)) + 1
        check(f"dt={dt:g} tstop={tstop:g} (was already right) -> {want}",
              ticks(dt, tstop) == want)
    check("a tstop just BEFORE the last event still gives one fewer",
          ticks(1e-8, 0.999e-6) == 100, f"got {ticks(1e-8, 0.999e-6)}")
    check("a tstop 1% before is unaffected", ticks(1e-8, 0.99e-6) == 100)
    check("the transient step still does not matter",
          all(ticks(1e-8, 1e-6, st) == 101 for st in (2e-8, 1e-8, 1e-7)))

    # ------------------------------------------------------------------ [4]
    print("\n[4] an INTEGER instance parameter is sweepable, and says so when not")
    IDECK = "V1 a 0 dc 1\nN1 a 0 im\n.model im sp_int()\n"
    rc, out = run("* sp\n" + IDECK + ctl("dc @n1[n] 1 4 1\nprint i(v1)", "sp_int"))
    v = sweep_vals(out)
    check("n = 1..4 -> the device sees 1, 2, 3, 4",
          rc == 0 and [round(-x * 1000) for x in v] == [1, 2, 3, 4], str(v))
    rc, out = run("* sp\n" + IDECK + ctl("dc @n1[n] 2 4 0.5\nprint i(v1)", "sp_int"))
    check("a FRACTIONAL sweep is refused rather than publishing a false abscissa",
          rc != 0 and "whole numbers" in out, out[-140:].replace("\n", " "))
    rc, out = run("* sp\n" + IDECK + ctl("dc @n1[n] 7 9 1\nprint i(v1)", "sp_int"))
    check("the range is enforced on the integer path too",
          rc != 0 and "out of bounds" in out)
    rc, out = run("* sp\n" + IDECK + ctl("dc @n1[nosuchparam] 1 2 1", "sp_int"))
    check("a device that exists with a parameter that does not says exactly that",
          "names a device that exists" in out, out[-160:].replace("\n", " "))
    rc, out = run("* sp\n" + IDECK + ctl("dc @nosuchdev[r] 1 2 1", "sp_int"))
    check("a device that does not exist keeps the original wording",
          "is not in the circuit" in out)

    # ------------------------------------------------------------------ [5]
    print("\n[5] .ic on a device-internal node: a UNIFORM limitation, pinned")
    rc, out = run("* sp\nV1 a 0 dc 1\nD1 a 0 dm\n.model dm d(is=1e-14 rs=10)\n"
                  ".ic v(d1#internal)=0.3\n.control\noption noacct\nop\n.endc\n.end\n")
    check("a BUILT-IN diode's internal node is rejected too -- not an OSDI gap",
          "non-existent node" in out and "d1#internal" in out)
    rc, out = run("* sp\nV1 a 0 dc 1\nR1 a mid 1k\nC1 mid 0 1n ic=0.5\n"
                  ".control\noption noacct\nset numdgt=10\n"
                  "tran 1n 100n uic\nprint v(mid)[0]\n.endc\n.end\n")
    check("the supported route -- a built-in `ic=` instance parameter -- works",
          close(scalars(out, "v(mid)[0]")[0] if scalars(out, "v(mid)[0]") else None,
                0.5, 1e-3))

    for j in os.listdir(HERE):
        if j.startswith("_sp") or j.endswith((".osdi", ".va")):
            p = os.path.join(HERE, j)
            (shutil.rmtree if os.path.isdir(p) else os.remove)(p)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
