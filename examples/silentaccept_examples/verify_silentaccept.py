#!/usr/bin/env python3
"""Enhancement-467: nine places where the deck said one thing and ngspice
quietly did another.

Every check below is a DIFFERENTIAL against a form of the same deck that
already worked, so a check cannot pass by coincidence, and each records the
number the pre-fix binary produced.

  1-3  `set sqrnoise=1` / `set interp=1` / `set autostop=1` were IGNORED.
       The spelling decides the published TYPE -- bare is a BOOL, `=1` a
       NUMBER, `=true` a STRING -- and cp_getvar's coercion table had no
       CP_BOOL case at all, so ~110 readers saw only the bare word. This is
       the root of the class Enhancements 450/451/454/466 each patched at one
       call site.
   4   `.option defas=` wrote TSKdefaultMosAD -- ONE WORD -- so the source-area
       default could never be set and the DRAIN area was silently overwritten.
  5-6  NOT a defect, and pinned here so it stays that way: a negative `defw`
       or instance `w=` IS already reported, by Enhancement-438's opt-in
       `.option warn_physics`, which deliberately KEEPS the value. A guard was
       written for these during this work and withdrawn when E-438's own suite
       caught it silencing that report.
   7   An instance `temp=`/`dtemp=` below absolute zero was accepted silently,
       though `.option temp=` has warned since E-426 and osdisetup.c makes the
       same check for OSDI. A resistor at -300 C answered -0.998 V from a
       +1 V source.
   8   Under `.option autobus=kicad` the SUBCIRCUIT formal detection still
       required the `a[k]` spelling, so formals written the way KiCad actually
       emits them (`a_0_`) matched nothing and the device was left floating.
   9   `.func sqrt(x) {...}` silently replaced the built-in for the whole deck.
  10   `.adapt` validated the adapter MODEL name but not its NODE list, so one
       typo switched the feature off with no diagnostic.
  11   Naming a model that is also a device model as the adapter did the same.
  12   `meas` looked its dc scale up from a fixed list of four names, so every
       WINDOW function (max/min/avg/rms/integ) failed on a `.dc` of a device
       parameter while the POINT functions worked on the same plot.
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

import atexit  # noqa: E402


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_sa_"):
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


def run(deck, tag):
    p = os.path.join(HERE, f"_sa_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=180, errors="replace")
    return r.stdout + r.stderr


def num(out, name):
    """the last printed value of `name`"""
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+e?[-+]?\d*)", out, re.I)
    return float(m[-1]) if m else None


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


print("Enhancement-467: silent acceptances\n")

# --------------------------------------------------------- 1-3 option spellings
print("the option spellings that meant nothing (root: cp_getvar had no CP_BOOL coercion)")

NOISE = ("sqrnoise spelling\nV1 in 0 dc 0 ac 1\nR1 in out 1k\nRl out 0 1k\n"
         ".control\noption noacct\nset numdgt=8\n{}\n"
         "noise v(out) V1 dec 1 1k 1k 1\nprint onoise_spectrum\n.endc\n.end\n")
bare = num(run(NOISE.format("set sqrnoise"), "sqrbare"), "onoise_spectrum")
one = num(run(NOISE.format("set sqrnoise=1"), "sqrone"), "onoise_spectrum")
true_ = num(run(NOISE.format("set sqrnoise=true"), "sqrtrue"), "onoise_spectrum")
zero = num(run(NOISE.format("set sqrnoise=0"), "sqrzero"), "onoise_spectrum")
off = num(run(NOISE.format("set sqrnoise=off"), "sqroff"), "onoise_spectrum")
none = num(run(NOISE.format("* unset"), "sqrnone"), "onoise_spectrum")
check("[1] `set sqrnoise` (bare) squares the spectrum",
      close(bare, none * none, 1e-3), f"{bare} vs {none}")
check("[1] `set sqrnoise=1` does the SAME (was ignored: it reported %g)" % (none or 0),
      close(one, bare, 1e-9), f"{one}")
check("[1] ...and so does `=true`", close(true_, bare, 1e-9), f"{true_}")
check("[1] while `=0` and `=off` stay OFF, exactly as before",
      close(zero, none, 1e-9) and close(off, none, 1e-9), f"{zero}/{off}")

INTERP = ("interp spelling\nV1 in 0 pulse(0 1 0 1n 1n 5u 10u)\nR1 in out 1k\nC1 out 0 1n\n"
          ".control\noption noacct\n{}\ntran 0.2u 20u\nprint length(v(out))\n.endc\n.end\n")
i_none = num(run(INTERP.format("* unset"), "ipnone"), "length(v(out))")
i_bare = num(run(INTERP.format("set interp"), "ipbare"), "length(v(out))")
i_one = num(run(INTERP.format("set interp=1"), "ipone"), "length(v(out))")
i_zero = num(run(INTERP.format("set interp=0"), "ipzero"), "length(v(out))")
check("[2] `set interp` (bare) interpolates onto the uniform grid",
      i_bare is not None and i_none is not None and i_bare < i_none,
      f"{i_bare} of {i_none}")
check("[2] `set interp=1` does the same (was ignored)", close(i_one, i_bare), f"{i_one}")
check("[2] `set interp=0` does NOT", close(i_zero, i_none), f"{i_zero}")

AUTOSTOP = ("autostop spelling\nV1 in 0 pulse(0 1 0 1n 1n 5u 10u)\nR1 in out 1k\nC1 out 0 1n\n"
            ".control\noption noacct\n{}\ntran 0.05u 20u\n"
            "meas tran tr TRIG v(out) VAL=0.1 RISE=1 TARG v(out) VAL=0.9 RISE=1\n"
            "print length(v(out))\n.endc\n.end\n")
a_bare = num(run(AUTOSTOP.format("set autostop"), "asbare"), "length(v(out))")
a_one = num(run(AUTOSTOP.format("set autostop=1"), "asone"), "length(v(out))")
a_none = num(run(AUTOSTOP.format("* unset"), "asnone"), "length(v(out))")
check("[3] `set autostop` (bare) stops the run at the measurement",
      a_bare is not None and a_none is not None and a_bare < a_none, f"{a_bare} of {a_none}")
check("[3] `set autostop=1` does the same (was ignored: ran to %s)" % a_none,
      close(a_one, a_bare), f"{a_one}")

# ------------------------------------------------------------- 4-5 defas/defw
print("\nthe MOSFET default-geometry options")
MOS = ("mos defaults\nVd d 0 dc 1\nVg g 0 dc 1\nM1 d g 0 0 nch w=1u l=1u\n"
       ".model nch nmos level=1 vto=0.4 kp=100u\n{}\n"
       ".control\noption noacct\nset numdgt=8\nop\nprint @m1[ad] @m1[as]\n.endc\n.end\n")
o = run(MOS.format(".option defas=7e-10"), "defas")
check("[4] `.option defas=` sets the SOURCE area (it set the DRAIN area: ad=7e-10, as=0)",
      close(num(o, "@m1[as]"), 7e-10) and close(num(o, "@m1[ad]"), 0.0),
      f"ad={num(o, '@m1[ad]')} as={num(o, '@m1[as]')}")
o = run(MOS.format(".option defad=3e-10 defas=7e-10"), "defboth")
check("[4] ...and the two are independent",
      close(num(o, "@m1[ad]"), 3e-10) and close(num(o, "@m1[as]"), 7e-10),
      f"ad={num(o, '@m1[ad]')} as={num(o, '@m1[as]')}")

MOSW = ("mos defw\nVd d 0 dc 1\nVg g 0 dc 1\nM1 d g 0 0 nch l=1u\n"
        ".model nch nmos level=1 vto=0.4 kp=100u\n{}\n"
        ".control\noption noacct\nset numdgt=8\nop\nprint i(vd) @m1[w]\n.endc\n.end\n")
o = run(MOSW.format(".option defw=-1e-5\n.option warn_physics"), "defwneg")
check("[5] a negative `defw` is left to E-438's `.option warn_physics`, which "
      "reports it and KEEPS the value -- that contract is unchanged",
      "cannot be negative" in o and num(o, "@m1[w]") is not None
      and num(o, "@m1[w]") < 0, f"{num(o, '@m1[w]')}")
o = run(MOSW.format(".option defw=1e-5"), "defwpos")
check("[5] a POSITIVE defw is untouched", close(num(o, "@m1[w]"), 1e-5),
      f"{num(o, '@m1[w]')}")

# ------------------------------------------------------------ 6-7 instance values
print("\nthe instance knobs beside them")
MOSI = ("mos instance w\nVd d 0 dc 1\nVg g 0 dc 1\nM1 d g 0 0 nch w={} l=1u\n"
        ".model nch nmos level=1 vto=0.4 kp=100u\n{}\n"
        ".control\noption noacct\nset numdgt=8\nop\nprint i(vd)\n.endc\n.end\n")
o = run(MOSI.format("-1e-5", ".option warn_physics"), "wneg")
check("[6] an instance `w=-1e-5` likewise stays with warn_physics",
      "cannot be negative" in o, "")

RES = ("instance temperature\nV1 in 0 dc 1\nR1 in out 1k tc1=0.01 {}\nRl out 0 1k\n"
       ".control\noption noacct\nset numdgt=8\nop\nprint v(out)\n.endc\n.end\n")
ref = num(run(RES.format(""), "tref"), "v(out)")
for tag, knob, was in (("t300", "temp=-300", "-0.998"),
                       ("t1e6", "temp=-1e6", "-0.998"),
                       ("dt400", "dtemp=-400", "-0.5")):
    o = run(RES.format(knob), tag)
    check(f"[7] `R1 ... {knob}` is refused (it answered {was} V from a +1 V source)",
          close(num(o, "v(out)"), ref) and "absolute zero" in o.lower(),
          f"v(out)={num(o, 'v(out)')}")
o = run(RES.format("temp=-25"), "tok")
check("[7] an ORDINARY sub-zero temperature still works (-25 C is not the line)",
      num(o, "v(out)") is not None and "absolute zero" not in o.lower(),
      f"v(out)={num(o, 'v(out)')}")

# --------------------------------------------------------------- 8 kicad formals
print("\nthe KiCad bit spelling, in the one place the option never reached")
r = subprocess.run([OPENVAF, "sa.va", "-o", "sa.osdi"], cwd=HERE,
                   capture_output=True, text=True)
check("[8] the Verilog-A model compiles",
      r.returncode == 0 and os.path.isfile(os.path.join(HERE, "sa.osdi")),
      (r.stdout + r.stderr).strip()[:60])

DRIVE = "V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in n{k} 1k" for k in range(4))
LOAD = "\n".join(f"Rg{k} m{k} 0 100" for k in range(4))


def busdeck(opt, formals, tag):
    fml = " ".join(formals)
    return run(
        f"kicad formals {tag}\n.option {opt}\n{DRIVE}\n{LOAD}\n"
        "X1 " + " ".join(f"n{k}" for k in range(4)) + " "
        + " ".join(f"m{k}" for k in range(4)) + " s\n"
        f".subckt s {fml}\nN1 a c m1\n.ends\n.model m1 chan r0=1k\n"
        ".control\npre_osdi sa.osdi\noption noacct\nset numdgt=8\nop\n"
        "print v(n0) v(n3)\n.endc\n.end\n", tag)


BR = [f"a[{k}]" for k in range(4)] + [f"c[{k}]" for k in range(4)]
KC = [f"a_{k}_" for k in range(4)] + [f"c_{k}_" for k in range(4)]
ref0 = num(busdeck("autobus", BR, "kfa"), "v(n0)")
check("[8] the bracket reference connects", close(ref0, 0.523809524, 1e-6), f"{ref0}")
v = num(busdeck("autobus=kicad", BR, "kfb"), "v(n0)")
check("[8] brackets under `autobus=kicad` still connect (E-462's suite pins this)",
      close(v, ref0), f"{v}")
v = num(busdeck("autobus=kicad", KC, "kfc"), "v(n0)")
check("[8] KiCad-spelled formals under `autobus=kicad` now connect (were 1.0, floating)",
      close(v, ref0), f"{v}")
v = num(busdeck("autobus", KC, "kfd"), "v(n0)")
check("[8] ...and are NOT read as a bus when the option was not asked for",
      v is not None and not close(v, ref0), f"{v}")

# ------------------------------------------------------------------- 9 .func
print("\n`.func` over a built-in")
FUNC = ("func shadow\n{}\nV1 in 0 dc 1\nR1 in out '{}'\nRl out 0 1k\n"
        ".control\noption noacct\nset numdgt=8\nop\nprint @r1[resistance]\n.endc\n.end\n")
o = run(FUNC.format(".func sqrt(x) {x*2}", "sqrt(500)*100"), "fsqrt")
check("[9] redefining `sqrt` warns (it silently returned 100000 for 2236.07)",
      "redefines the built-in" in o, "")
check("[9] ...and the user's definition still wins, as it always did",
      close(num(o, "@r1[resistance]"), 1e5), f"{num(o, '@r1[resistance]')}")
o = run(FUNC.format(".func myfun(x) {x*2}", "myfun(500)*2"), "fmine")
check("[9] an ordinary name does NOT warn",
      "redefines the built-in" not in o and close(num(o, "@r1[resistance]"), 2000.0),
      f"{num(o, '@r1[resistance]')}")

# ------------------------------------------------------------- 10-11 .adapt
print("\n`.adapt` and the adapter model")
ADAPT = (".option autobus autoadapt adapter={}\n{}"
         + "V1 in 0 dc 1\n" + "\n".join(f"Rs{k} in a[{k}] 1k" for k in range(4)) + "\n"
         + "\n".join(f"Rg{k} c[{k}] 0 100" for k in range(4)) + "\n"
         "N1 a b m1\nN2 b c m2\n"
         ".model m1 chan r0=1k\n.model m2 chan r0=2k\n.model adp adapter\n"
         ".control\npre_osdi sa.osdi\noption noacct\nset numdgt=8\nop\n"
         "print v(a[0])\n.endc\n.end\n")


def adeck(model, card, tag):
    return run("adapt " + tag + "\n" + ADAPT.format(model, card), tag)


ADAPTED, PLAIN = 0.759036145, 0.756097561
o = adeck("adp", "", "adnone")
check("[10] the reference circuit adapts", close(num(o, "v(a[0])"), ADAPTED, 1e-6),
      f"{num(o, 'v(a[0])')}")
o = adeck("adp", ".adapt b\n", "adgood")
check("[10] `.adapt b` selects it, silently", close(num(o, "v(a[0])"), ADAPTED, 1e-6)
      and "Error: autoadapt" not in o, f"{num(o, 'v(a[0])')}")
o = adeck("adp", ".adapt nosuchnode\n", "adbad")
check("[10] `.adapt nosuchnode` is REPORTED (it silently disabled the feature)",
      "Error: autoadapt" in o and "nosuchnode" in o, "")
o = adeck("adp", ".adapt b, nosuchnode\n", "admix")
check("[10] a good member still adapts, and only the bad one is named",
      close(num(o, "v(a[0])"), ADAPTED, 1e-6) and "nosuchnode" in o,
      f"{num(o, 'v(a[0])')}")
o = adeck("adp", ".adapt\n", "adempty")
check("[10] a `.adapt` with no names is reported", "Error: autoadapt" in o, "")
o = adeck("m1", "", "adinuse")
check("[11] an adapter model that is also a DEVICE model is reported "
      "(it silently left the deck unadapted)",
      "Error: autoadapt" in o and close(num(o, "v(a[0])"), PLAIN, 1e-6),
      f"{num(o, 'v(a[0])')}")

# ------------------------------------------------------------------ 12 meas
print("\n`meas` over a `.dc` of a device parameter")
MEAS = ("meas over a param sweep\nV1 in 0 dc 1\nR1 in out 1k\nRl out 0 1k\n"
        ".control\noption noacct\nset numdgt=8\ndc @r1[resistance] 1k 5k 1k\n"
        "meas dc f1 MAX v(out)\nmeas dc f2 MIN v(out)\nmeas dc f3 AVG v(out)\n"
        "meas dc f4 RMS v(out)\nmeas dc f5 INTEG v(out)\n"
        "meas dc f6 FIND v(out) WHEN v(out)=0.25\nmeas dc f7 WHEN v(out)=0.25\n"
        ".endc\n.end\n")
o = run(MEAS, "meas")
check("[12] no window function fails now (all five said 'out of interval')",
      "out of interval" not in o, "")
check("[12] MAX is the first point", close(num(o, "f1"), 0.5, 1e-4), f"{num(o, 'f1')}")
check("[12] MIN is the last", close(num(o, "f2"), 1.0 / 6.0, 1e-4), f"{num(o, 'f2')}")
check("[12] AVG, RMS and INTEG all report",
      all(num(o, n) is not None for n in ("f3", "f4", "f5")),
      f"{num(o, 'f3')}/{num(o, 'f4')}/{num(o, 'f5')}")
check("[12] the POINT functions are unchanged (they always worked)",
      close(num(o, "f6"), 0.25, 1e-4) and close(num(o, "f7"), 3000.0, 1e-4),
      f"{num(o, 'f6')}/{num(o, 'f7')}")

SRC = ("meas over a source sweep\nV1 in 0 dc 1\nR1 in out 1k\nRl out 0 1k\n"
       ".control\noption noacct\nset numdgt=8\ndc V1 0 2 0.5\n"
       "meas dc s1 MAX v(out)\n.endc\n.end\n")
o = run(SRC, "meassrc")
check("[12] a SOURCE sweep still measures exactly as before",
      close(num(o, "s1"), 1.0, 1e-4), f"{num(o, 's1')}")
TMP = ("meas over a temp sweep\nV1 in 0 dc 1\nR1 in out 1k tc1=0.01\nRl out 0 1k\n"
       ".control\noption noacct\nset numdgt=8\ndc temp 0 100 25\n"
       "meas dc t1 MAX v(out)\n.endc\n.end\n")
o = run(TMP, "meastmp")
check("[12] and so does a `.dc temp` sweep", num(o, "t1") is not None, f"{num(o, 't1')}")

# ---------------------------------------------------------------- the message
print("\nthe diagnostic that named the wrong thing")
DIODE = ("alter a model parameter\nV1 in 0 dc 0.7\nD1 in 0 dm\n.model dm d is=1e-14\n"
         ".control\noption noacct\n{}\n.endc\n.end\n")
o = run(DIODE.format("alter @dm[is]=4e-14"), "altmsg")
check("[13] `alter @dm[is]` names the real cause (it said 'no such parameter is')",
      "MODEL parameter" in o and "altermod" in o, "")
o = run(DIODE.format("alter @dm[nosuchp]=1"), "altabsent")
check("[13] a genuinely absent parameter still says so",
      "no parameter" in o and "altermod" not in o, "")
o = run(DIODE.format("altermod dm is=4e-14\nop\nprint @dm[is]"), "altok")
check("[13] `altermod` itself is unchanged", close(num(o, "@dm[is]"), 4e-14),
      f"{num(o, '@dm[is]')}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
