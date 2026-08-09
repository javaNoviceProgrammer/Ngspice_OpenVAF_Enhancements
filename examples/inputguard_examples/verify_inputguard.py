#!/usr/bin/env python3
"""Enhancement-426: inputs ngspice accepted without ever checking them.

Every item here shared one shape: a value or a name that could not mean what it
said was taken at face value, and the wrong answer that followed was reported
with total confidence -- or blamed on something else entirely.

[1] AN ANALYSIS CARD'S OUTPUT NODE, IN THE SESSION'S FIRST ANALYSIS.

    Enhancement-349 already made `.tf v(out) v1` and friends refuse a node that
    does not exist. It gated the check on `CKTisSetup`, reasoning that "from the
    .control section the circuit is already set up". That is false for the FIRST
    analysis of a session -- nothing has run, so CKTsetup() has not run either --
    and there the typo was still invented as a brand-new node:

        tf   v(nosuch) v1   ->  transfer_function = 0.0        (no diagnostic)
        tf   v(a,nosuch) v1 ->  transfer_function = 1.0        (no diagnostic)
        sens v(nosuch)      ->  EVERY sensitivity = -0.0       (no diagnostic)
        noise v(nosuch) ... ->  onoise_total = 0.0             (no diagnostic)

    The same typo after any `op` was diagnosed correctly, which is exactly what
    hid it. A card synthesised by `if_run()` from a .control command is by
    construction not deck parsing, so that path now says so explicitly instead
    of inferring it from CKTsetup.

[2] SWEEP ARGUMENTS: `.tran` VALIDATES, ALMOST NOTHING ELSE DID.

    `.ac` did not merely accept a bad value, it SUBSTITUTED a default and ran a
    different sweep, reporting all of it with one generic warning:
    `ac dec 10 100k 1k` silently became 1e5..1e8 (31 points) and
    `ac dec 10 -1k 100k` became 1..1e5 (51 points). `noise` with an inverted
    range published `onoise_total = 0.0` -- a plausible number, manufactured
    from a loop that never executed. `sp` had no validation at all. `.dc` with a
    step pointing away from stop produced a plot with no vector in it.

    Equal endpoints are LEGITIMATE in all four and are pinned here: 19 `.ac`,
    4 `.noise`, 9 `.sp` and 13 single-point `.dc` cards in this repo depend on
    them, as do 2 descending `.dc` sweeps.

[3] A `meas` OVER A VECTOR THAT HOLDS ONE POINT.

    `@device[param]` is a scalar snapshot of the most recent point unless it is
    named in a `.save` -- documented, and `save all` deliberately does not cover
    it. But every meas loop is `for (i = 0; i < d->v_length; i++)` against the
    full-length scale, so the loop ran once and MAX/MIN/PP/INTEG reported that
    one sample as the extremum. The `at= 0.00000e+00` was the tell.

[4] A TEMPERATURE BELOW ABSOLUTE ZERO, ON EVERY SUPPLY PATH.

    `.options temp`, the `.temp` card, `option temp=`, `set temp=`, an instance
    `dtemp=` and a `.dc temp` sweep all accepted a value that makes the Kelvin
    temperature negative, and ckttemp.c turned it straight into a NEGATIVE
    thermal voltage -- a Verilog-A model read `$vt = -0.0195 V` in silence.
    -25 C is ordinary and stays working; the line is absolute zero.

[5] TOLERANCES AND ITERATION LIMITS THAT ARE NOT POSITIVE.

    A tolerance <= 0 makes the convergence test unsatisfiable, and the run then
    blamed the CIRCUIT ("Dynamic gmin stepping failed"). `itl2=0` is the one
    with teeth: CKTdcTrcvMaxIter is used as an unfloored `/4` and `3*/4`
    continuation threshold by four gmin/source-stepping heuristics in cktop.c,
    so zero collapses the ramp to its slowest schedule -- a measured 736,920
    Newton iterations against 55. `itl6` is a table SYNONYM for srcsteps where
    0 is documented and four decks rely on it; the guard keys on the OPT_ enum,
    never on the name.

[6] A NEGATIVE INSTANCE MULTIPLIER, AND A DUPLICATE `.model`.

    `m=-1` does not scale a device, it INVERTS it: a 2k resistor stamps -2000
    ohm and a passive device becomes active. `m=0` is the ordinary "disable this
    instance" idiom and is deliberately left alone. Two `.model` cards with one
    name were silently reduced to one, first wins.

[7] NUMBERS THAT ARE NOT NUMBERS.

    `1e400` became inf (a resistor silently became an open circuit) and `0e400`
    became NaN, after which the operating point failed five levels away. The
    exponent was accumulated into a plain `int`, so `1e2147483648` was signed
    overflow. And an exponent marker with no digits was SWALLOWED, letting the
    next letter be read as a scale factor -- `10Emitter` came out as 0.01 and
    `1em` as 1e-3, both contradicting the manual's own rule.

    The documented forms are pinned unchanged: `1k2`, `2meg5`, `1e5x`, `1kk`,
    `0x10`, `5kohms`. src/ngspice.txt:499 sanctions all of them.

[8] A CRASH, FOUND WHILE REVIEWING THE FIX SCOPE.

    A model whose `setup_model` failed had its error overwritten by the next
    model's success, so OSDIsetup returned OK while that model's instances were
    never set up; ngspice then loaded them and dereferenced a NULL jacobian.
    Two `.model` cards, one good and one out of range, gave SIGSEGV and ZERO
    bytes of output.

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
    """Compile a Verilog-A source to <tag>.osdi in HERE."""
    va = os.path.join(HERE, tag + ".va")
    with open(va, "w") as fh:
        fh.write(src)
    r = subprocess.run([OPENVAF, va, "-o", os.path.join(HERE, tag + ".osdi")],
                       capture_output=True, text=True, cwd=HERE, timeout=300)
    return r.returncode == 0


def run(deck, name="_ig.cir", timeout=120):
    """Run a deck, returning (rc, combined stdout+stderr).

    BOTH streams are captured deliberately: ngspice writes its own $finish/$stop
    Notes to stdout while the OSDI log callback writes WARN/ERR/FATAL to stderr,
    and a check that watches only one of them scores the other as silent.
    """
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -99, "TIMEOUT"


def val(out, name):
    m = re.search(r"^%s\s*=\s*(\S+)" % re.escape(name), out, re.M)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return m.group(1)


def close(a, b, tol=1e-9):
    return isinstance(a, float) and abs(a - b) <= tol * max(1.0, abs(b))


# --------------------------------------------------------------------------
DIODE = """`include "disciplines.vams"
module ig_diode(a,c);
  inout a,c; electrical a,c;
  parameter real is = 1e-14;
  analog begin
    I(a,c) <+ is*(limexp(V(a,c)/$vt) - 1.0);
    $strobe("PROBE tk=%g vt=%g", $temperature, $vt);
  end
endmodule
"""

RANGED = """`include "disciplines.vams"
module ig_res(a,c);
  inout a,c; electrical a,c;
  parameter real r0 = 1k from (0:inf);
  analog I(a,c) <+ V(a,c)/r0;
endmodule
"""

OPVAR = """`include "disciplines.vams"
module ig_opv(a,c);
  inout a,c; electrical a,c;
  (*desc="terminal voltage"*) real vv;
  analog begin
    vv = V(a,c);
    I(a,c) <+ V(a,c)/1000.0;
  end
endmodule
"""

FIN = """`include "disciplines.vams"
module ig_fin(a,c);
  inout a,c; electrical a,c;
  analog begin
    I(a,c) <+ V(a,c)/1000.0;
    if (V(a,c) > 0.55) $finish(1);
  end
endmodule
"""

# a plain resistive OSDI device used as the circuit under test
CUT = "N1 b 0 ig_res\n.model ig_res ig_res(r0=1000)\n"
BASE = "V1 a 0 dc 0.5 ac 1\nRS a b 1k\n" + CUT


def ctl(body, load="ig_res"):
    return (".control\npre_osdi %s.osdi\noption noacct\nset numdgt=10\n"
            % load) + body + "\n.endc\n.end\n"


def main():
    for tag, src in (("ig_diode", DIODE), ("ig_res", RANGED),
                     ("ig_opv", OPVAR), ("ig_fin", FIN)):
        if not build(src, tag):
            print(f"FATAL: {tag}.va did not compile")
            sys.exit(1)

    # ---------------------------------------------------------------- [1]
    print("\n[1] an analysis card's output node, as the session's FIRST analysis")
    for cmd, label in (("tf v(nosuch) v1\nprint all", "tf v(nosuch)"),
                       ("tf v(a,nosuch) v1\nprint all", "tf v(a,nosuch) (returned exactly 1.0)"),
                       ("sens v(nosuch)\nprint all", "sens v(nosuch) (every sensitivity -0.0)"),
                       ("noise v(nosuch) v1 dec 5 1k 10k 1\nsetplot noise2\nprint onoise_total",
                        "noise v(nosuch) (onoise_total 0.0)")):
        rc, out = run("* ig\n" + BASE + ctl(cmd))
        check(f"{label} is refused", "no such node: nosuch" in out,
              f"rc={rc}")
    # ...and every legitimate spelling still works
    rc, out = run("* ig\n" + BASE + ctl("tf v(b) v1\nprint all"))
    check("tf v(b) still computes", close(val(out, "transfer_function"), 0.5, 1e-6),
          str(val(out, "transfer_function")))
    rc, out = run("* ig\n" + BASE + ctl("sens v(b)\nprint all"))
    check("sens v(b) still computes", close(val(out, "v1"), 0.5, 1e-6),
          str(val(out, "v1")))
    rc, out = run("* ig\n" + BASE + ctl(
        "noise v(b) v1 dec 5 1k 10k 1\nsetplot noise2\nprint onoise_total"))
    check("noise v(b) still computes",
          isinstance(val(out, "onoise_total"), float) and val(out, "onoise_total") > 0)
    rc, out = run("* ig\n" + BASE + ctl("op\ntf v(nosuch) v1"))
    check("the E-349 case (after an op) still refused", "no such node" in out)

    # ---------------------------------------------------------------- [2]
    print("\n[2] sweep arguments")
    for cmd, label, want in (
            ("ac dec 10 1k 100k", "ac ascending", 21),
            ("ac lin 1 1k 1k", "ac fstart == fstop (19 cards rely on it)", 1)):
        rc, out = run("* ig\n" + BASE + ctl(
            cmd + "\nlet np=length(frequency)\nprint np"))
        check(f"{label} still runs", close(val(out, "np"), want), str(val(out, "np")))
    for cmd, label, msg in (
            ("ac dec 10 100k 1k", "ac fstop < fstart", "stop frequency is invalid"),
            ("ac dec 10 -1k 100k", "ac negative fstart", "start frequency is invalid"),
            ("ac dec 0 1k 100k", "ac zero points", "number of points is invalid"),
            ("ac dec -5 1k 100k", "ac negative points", "number of points is invalid"),
            ("ac lin 0 1k 100k", "ac lin zero points", "number of points is invalid")):
        rc, out = run("* ig\n" + BASE + ctl(cmd + "\nprint all"))
        check(f"{label} is refused", msg in out, out[-160:].replace("\n", " "))

    rc, out = run("* ig\n" + BASE + ctl(
        "noise v(b) v1 dec 10 1k 100k 1\nsetplot noise2\nprint onoise_total"))
    check("noise ascending still runs",
          isinstance(val(out, "onoise_total"), float) and val(out, "onoise_total") > 0)
    rc, out = run("* ig\n" + BASE + ctl("noise v(b) v1 dec 10 100k 1k 1"))
    check("noise inverted range is refused (was onoise_total = 0.0)",
          "less than the start frequency" in out)

    # .dc -- the boundary that 13 single-point and 2 descending decks depend on
    DC = "V1 a 0 dc 0.5\nRS a b 1k\nRB b 0 1k\n"
    for sw, label, want in (("v1 0.4 0.6 0.05", "dc ascending", 5),
                            ("v1 1 1 1", "dc start == stop (13 decks)", 1),
                            ("v1 1 1 0.1", "dc start == stop, small step", 1),
                            ("v1 0 1 1.5", "dc step wider than the span", 1),
                            ("v1 2 0 -0.5", "dc descending (2 decks)", 5),
                            ("v1 0 -2 -0.5", "dc descending into negatives", 5),
                            ("v1 1 0 -0.1", "dc reverse, sweepguard's NORMAL case", 11)):
        rc, out = run("* ig\n" + DC + ".control\noption noacct\nset numdgt=10\ndc "
                      + sw + "\nlet n=length(v(b))\nprint n\n.endc\n.end\n")
        check(f"{label} still runs", close(val(out, "n"), want), str(val(out, "n")))
    for sw, label in (("v1 0.6 0.4 0.05", "dc start>stop with a POSITIVE step"),
                      ("v1 0.4 0.6 -0.05", "dc start<stop with a NEGATIVE step")):
        rc, out = run("* ig\n" + DC + ".control\noption noacct\ndc " + sw
                      + "\nprint i(v1)\n.endc\n.end\n")
        check(f"{label} is refused", "moves away from stop" in out)

    # ---------------------------------------------------------------- [3]
    print("\n[3] meas over a one-point @device[param] vector")
    PULSE = "pulse(0 1 0 1u 1u 3u 100u)"
    MEAS = ("meas tran m1 MAX @n1[vv]\nmeas tran m2 MIN @n1[vv]\n"
            "meas tran m3 AVG @n1[vv]\nmeas tran m4 RMS @n1[vv]\n"
            "meas tran m5 INTEG @n1[vv]\nmeas tran m6 FIND @n1[vv] AT=2u\n")
    OPVDECK = (f"* ig\nV1 a 0 dc 0 {PULSE}\nRS a b 1k\nN1 b 0 ig_opv\n"
               ".model ig_opv ig_opv()\n")
    rc, out = run(OPVDECK + ctl("tran 10n 10u\n" + MEAS, "ig_opv"))
    check("an unsaved @dev[param] meas is refused, not answered with 0.0",
          out.count("holds 1 point(s)") >= 6 and val(out, "m1") is None,
          f"m1={val(out,'m1')}")
    rc, out = run(OPVDECK + ctl("save all\ntran 10n 10u\n" + MEAS, "ig_opv"))
    check("`save all` alone is still not enough (documented, manual 11.6.1)",
          "holds 1 point(s)" in out)
    rc, out = run(OPVDECK + ctl("save all @n1[vv]\ntran 10n 10u\n" + MEAS, "ig_opv"))
    check("an explicitly saved @dev[param] measures correctly",
          close(val(out, "m1"), 0.5, 1e-4) and close(val(out, "m2"), 0.0, 1e-9),
          f"max={val(out,'m1')} min={val(out,'m2')}")
    check("...and its AVG/RMS/INTEG/FIND all produce values",
          all(isinstance(val(out, k), float) for k in ("m3", "m4", "m5", "m6")))
    rc, out = run(f"* ig\nV1 a 0 dc 0 {PULSE}\nRS a b 1k\nRB b 0 1k\n"
                  ".control\noption noacct\ntran 10n 10u\n"
                  "meas tran q1 MAX v(b)\nmeas tran q2 MIN v(b)\n.endc\n.end\n")
    check("a plain node voltage meas is untouched",
          close(val(out, "q1"), 0.5, 1e-4) and close(val(out, "q2"), 0.0, 1e-9),
          f"{val(out,'q1')} {val(out,'q2')}")

    # ---------------------------------------------------------------- [4]
    print("\n[4] temperature below absolute zero")
    DEV = "V1 a 0 dc 0.7\nN1 a 0 ig_diode\n.model ig_diode ig_diode(is=1e-14)\n"

    def temp_probe(pre, body="op\nprint i(v1)"):
        rc, out = run("* ig\n" + DEV + pre + ctl(body, "ig_diode"))
        m = re.findall(r"PROBE tk=(\S+) vt=(\S+)", out)
        return out, (float(m[0][0]), float(m[0][1])) if m else (None, None)

    out, tk = temp_probe(".options temp=27\n")
    check("temp=27 unaffected", close(tk[0], 300.15, 1e-6), str(tk))
    out, tk = temp_probe(".options temp=-25\n")
    check("temp=-25 C is ordinary and still works", close(tk[0], 248.15, 1e-6), str(tk))
    out, tk = temp_probe(".options temp=-273.14\n")
    check("temp=-273.14 C (0.01 K) is physical and still works",
          isinstance(tk[0], float) and tk[0] > 0, str(tk))
    for pre, body, label in (
            (".options temp=-500\n", "op\nprint i(v1)", ".options temp=-500"),
            (".temp -500\n", "op\nprint i(v1)", ".temp -500"),
            ("", "set temp=-500\nop\nprint i(v1)", "set temp=-500"),
            ("", "option temp=-500\nop\nprint i(v1)", "option temp=-500"),
            (".options temp=-273.15\n", "op\nprint i(v1)", "temp = exactly 0 K")):
        out, tk = temp_probe(pre, body)
        check(f"{label} is refused and the model keeps a positive $vt",
              "at or below absolute zero" in out and tk[1] is not None and tk[1] > 0,
              str(tk))
    rc, out = run("* ig\nV1 a 0 dc 0.7\nN1 a 0 ig_diode dtemp=-1000\n"
                  ".model ig_diode ig_diode(is=1e-14)\n" + ctl("op\nprint i(v1)", "ig_diode"))
    m = re.findall(r"PROBE tk=(\S+) vt=(\S+)", out)
    check("an instance dtemp below absolute zero is refused",
          "at or below absolute zero" in out and m and float(m[0][1]) > 0,
          str(m[:1]))
    RT = "V1 a 0 dc 1\nR1 a 0 rm 1k\n.model rm r(tc1=0.001)\n"
    rc, out = run("* ig\n" + RT + ".control\noption noacct\ndc temp 0 100 25\n"
                  "let n=length(i(v1))\nprint n\n.endc\n.end\n")
    check("a .dc temp sweep in range still runs", close(val(out, "n"), 5))
    rc, out = run("* ig\n" + RT + ".control\noption noacct\ndc temp -600 100 100\n"
                  "print i(v1)\n.endc\n.end\n")
    check("a .dc temp sweep through absolute zero is refused",
          "at or below absolute zero" in out)

    # ---------------------------------------------------------------- [5]
    print("\n[5] tolerances and iteration limits")
    for opt, label in (("reltol=0", "reltol=0"), ("reltol=-1", "reltol=-1"),
                       ("abstol=0", "abstol=0"), ("abstol=-1", "abstol=-1"),
                       ("vntol=-1", "vntol=-1"), ("chgtol=-1", "chgtol=-1"),
                       ("trtol=-1", "trtol=-1"),
                       ("itl1=0", "itl1=0"), ("itl2=0", "itl2=0 (13,400x blow-up)"),
                       ("itl4=-5", "itl4=-5")):
        rc, out = run("* ig\n" + DEV + f".options {opt}\n" + ctl("op\nprint i(v1)", "ig_diode"))
        check(f"{label} refused, and the run still converges",
              "must be greater than zero" in out
              and close(val(out, "i(v1)"), -5.6703103e-3, 1e-3),
              f"i={val(out,'i(v1)')}")
    rc, out = run("* ig\n" + DEV + ".options reltol=1e-4 abstol=1e-13 itl1=200\n"
                  + ctl("op\nprint i(v1)", "ig_diode"))
    check("legitimate tolerance values are silent",
          "must be greater than zero" not in out
          and close(val(out, "i(v1)"), -5.6703103e-3, 1e-3))
    rc, out = run("* ig\n" + DEV + ".options itl6=0 gminsteps=0\n"
                  + ctl("op\nprint i(v1)", "ig_diode"))
    check("itl6=0 (a SYNONYM for srcsteps, documented, 4 decks) is untouched",
          "must be greater than zero" not in out
          and close(val(out, "i(v1)"), -5.6703103e-3, 1e-3))

    # ---------------------------------------------------------------- [6]
    print("\n[6] instance multiplier and duplicate .model")
    MDEV = "V1 a 0 dc 1\nN1 a 0 rm %s\n.model rm ig_res(r0=2000)\n"
    for mm, label, want in (("m=1", "m=1", -5e-4), ("m=2", "m=2", -1e-3)):
        rc, out = run("* ig\n" + (MDEV % mm) + ctl("op\nprint i(v1)"))
        check(f"{label} unaffected", close(val(out, "i(v1)"), want, 1e-6))
    rc, out = run("* ig\n" + (MDEV % "m=0") + ctl("op\nprint i(v1)"))
    check("m=0 stays SILENT -- it is the 'disable this instance' idiom",
          "multiplier" not in out and close(val(out, "i(v1)"), 0.0, 1e-12))
    for mm, label in (("m=-1", "m=-1"), ("m=-2.5", "m=-2.5"),
                      ("_mfactor=-1", "_mfactor=-1 (the other spelling)")):
        rc, out = run("* ig\n" + (MDEV % mm) + ctl("op\nprint i(v1)"))
        check(f"{label} is reported", "is negative" in out, out[-120:].replace("\n", " "))
    rc, out = run("* ig\nV1 a 0 dc 1\nR1 a 0 2k m=-1\n"
                  ".control\noption noacct\nop\nprint i(v1)\n.endc\n.end\n")
    check("a negative m on a BUILT-IN device is reported too", "is negative" in out)
    rc, out = run("* ig\nV1 a 0 dc 1\nR1 a 0 rmod 2k\n.model rmod r(m=3)\n"
                  ".control\noption noacct\nop\nprint i(v1) @r1[m]\n.endc\n.end\n")
    check("`m` on a .model card is announced, and still ignored",
          "on a .model card is ignored" in out and close(val(out, "@r1[m]"), 1.0))
    DUP = ("* ig\nV1 a 0 dc 0.7\nD1 a 0 dm\n.model dm d(is=1e-14)\n"
           "%s.control\noption noacct\nset numdgt=8\nop\nprint i(v1)\n.endc\n.end\n")
    rc, out = run(DUP % "")
    check("a single .model card is silent", "already defined" not in out)
    rc, out = run(DUP % ".model dm d(is=1e-9)\n")
    check("a duplicate .model name is reported (first still wins)",
          "already defined" in out and "keeping the first" in out)

    # ---------------------------------------------------------------- [7]
    print("\n[7] numbers")
    NUM = ("* ig\nV1 a 0 dc 1\nRA a mid %s\nRB mid 0 1k\n"
           ".control\noption noacct\nset numdgt=12\nop\n"
           "print @ra[resistance]\n.endc\n.end\n")
    for tok, want, label in (("1k", 1000.0, "1k"),
                             ("1k2", 1000.0, "1k2 -> 1000 (documented)"),
                             ("2meg5", 2e6, "2meg5 -> 2e6 (documented)"),
                             ("1e5x", 1e5, "1e5x -> 1e5 (documented)"),
                             ("1kk", 1000.0, "1kk -> 1000 (the manual's own MMhos shape)"),
                             ("5kohms", 5000.0, "5kohms (documented unit suffix)"),
                             ("1e3", 1000.0, "1e3"), ("1e-3", 1e-3, "1e-3")):
        rc, out = run(NUM % tok)
        check(f"{label} unchanged", close(val(out, "@ra[resistance]"), want, 1e-9),
              str(val(out, "@ra[resistance]")))
    for tok, want, label in (("10Emitter", 10.0, "10Emitter -> 10 (was 0.01)"),
                             ("1em", 1.0, "1em -> 1 (was 1e-3)")):
        rc, out = run(NUM % tok)
        check(f"{label}", close(val(out, "@ra[resistance]"), want, 1e-9),
              str(val(out, "@ra[resistance]")))
    for tok, label in (("1e400", "1e400 (was inf)"), ("0e400", "0e400 (was NaN)"),
                       ("1e2147483648", "1e2147483648 (was signed overflow)"),
                       ("1e21474836480", "1e21474836480 (wrapped to 1)")):
        rc, out = run(NUM % tok)
        check(f"{label} is refused", "not a representable number" in out,
              out[-140:].replace("\n", " "))

    # ---------------------------------------------------------------- [8]
    print("\n[8] a failing OSDI setup_model must not be masked by a later success")
    CRASH = ("* ig\nV1 a 0 dc 1\nN1 a 0 rm_ok\nN2 a 0 rm_bad\n"
             "%s.control\npre_osdi ig_res.osdi\noption noacct\nop\nprint i(v1)\n.endc\n.end\n")
    for order, label in (
            (".model rm_ok ig_res(r0=1000)\n.model rm_bad ig_res(r0=-5)\n",
             "good .model first, out-of-range second (was SIGSEGV, 0 bytes)"),
            (".model rm_bad ig_res(r0=-5)\n.model rm_ok ig_res(r0=1000)\n",
             "out-of-range .model first")):
        rc, out = run(CRASH % order)
        check(f"{label}", rc >= 0 and "out of bounds" in out, f"rc={rc} bytes={len(out)}")

    # ---------------------------------------------------------------- [9]
    print("\n[9] the effective resistance is reachable, the nominal is unchanged")
    rc, out = run("* ig\nV1 a 0 dc 1\nR1 a 0 rm 1k\n.model rm r(tc1=0.001)\n"
                  ".options temp=227\n.control\noption noacct\nset numdgt=10\nop\n"
                  "print @r1[resistance] @r1[conductance]\nlet reff=1/@r1[conductance]\n"
                  "print reff\n.endc\n.end\n")
    check("@r1[resistance] still returns the NOMINAL value it was given",
          close(val(out, "@r1[resistance]"), 1000.0, 1e-9))
    check("1/@r1[conductance] is the value actually stamped (1200 at 227 C)",
          close(val(out, "reff"), 1200.0, 1e-6), str(val(out, "reff")))

    # --------------------------------------------------------------- [10]
    print("\n[10] $finish reaches the analyses that were dropping it")
    FDEV = "V1 a 0 dc 0.6\nN1 a 0 fm\n.model fm ig_fin()\n"
    for body, label in (("op\nprint i(v1)", ".op"),
                        ("ac dec 3 1 1k\nprint length(frequency)", ".ac")):
        rc, out = run("* ig\n" + FDEV + ctl(body, "ig_fin"))
        check(f"a $finish during {label} is reported", "$finish requested" in out,
              out[-140:].replace("\n", " "))
    rc, out = run("* ig\nV1 a 0 dc 0\nN1 a 0 fm\n.model fm ig_fin()\n"
                  + ctl("dc v1 0.5 0.6 0.02\nprint i(v1)", "ig_fin"))
    check("the .dc case E-55 already handled is unchanged", "$finish requested" in out)

    # --------------------------------------------------------------- [11]
    print("\n[11] a node no device ever stamped is out of the RHS array's bounds")
    OOB = "I1 0 a dc 1m ac 1\nR1 a 0 1k\n"
    rc, out = run("* ig\n" + OOB + ".tf v(nosuch) i1\n.print tf all\n.end\n")
    check("a .tf DECK card on an unstamped node is refused, not answered with heap garbage",
          ("not connected to any device" in out or "does not exist" in out)
          and "3.999110e+252" not in out,
          out[-140:].replace("\n", " "))

    # Enhancement-429: the bounds test above only fires when the invented node's
    # equation number lands PAST the matrix, which happens on the .control
    # command path. A CARD is parsed before CKTsetup, so its phantom sits INSIDE
    # the matrix and every unknown output node was answered `0.000000e+00` with
    # no diagnostic at all. `devRef` records whether anything other than the card
    # itself ever referred to the node.
    DIV = "V1 a 0 dc 1\nR1 a b 1k\nR2 b 0 3k\n"
    for card, label in ((".tf v(nosuch) i1", "a plain typo"),
                        (".tf v(x1.n1#mid) i1", "a device-internal node")):
        rc, out = run("* ig\nV1 a 0 dc 1\nR1 a b 1k\nR2 b 0 3k\n"
                      + card.replace("i1", "v1") + "\n.print tf all\n.end\n")
        check(f"a .tf CARD naming {label} is refused (was 0.0, silent)",
              "does not exist" in out and "transfer_function" not in out,
              out[-140:].replace("\n", " "))
    rc, out = run("* ig\n" + DIV + ".tf v(b) v1\n.print tf all\n.end\n")
    check("...while a real node still answers 0.75",
          "7.500000e-01" in out, out[-120:].replace("\n", " "))
    rc, out = run("* ig\n.tf v(b) v1\n" + DIV + ".print tf all\n.end\n")
    check("...and E-349's case -- the card BEFORE its devices -- still answers",
          "7.500000e-01" in out, out[-120:].replace("\n", " "))
    rc, out = run("* ig\n" + DIV + ".noise v(nosuch) v1 dec 5 1k 10k\n"
                  ".control\noption noacct\nrun\n.endc\n.end\n")
    check("a .noise CARD naming a node that does not exist is refused",
          "does not exist" in out, out[-120:].replace("\n", " "))
    rc, out = run("* ig\n" + OOB + ".noise v(nosuch) i1 dec 5 1k 10k\n.end\n")
    check("a .noise DECK card on an unstamped node is refused",
          "not connected to any device" in out or "incomplete or empty netlist" in out)
    rc, out = run("* ig\n.tf v(out) v1\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 3k\n"
                  ".print tf all\n.end\n")
    check("a .tf card placed BEFORE its devices still resolves (E-349's case [3])",
          close(val(out, "transfer_function"), 0.75, 1e-6),
          str(val(out, "transfer_function")))

    for j in os.listdir(HERE):
        if j.startswith("_ig") or j.endswith((".osdi", ".va")):
            p = os.path.join(HERE, j)
            (shutil.rmtree if os.path.isdir(p) else os.remove)(p)

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
