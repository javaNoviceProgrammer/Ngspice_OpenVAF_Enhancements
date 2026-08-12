#!/usr/bin/env python3
"""Enhancement-445: nine silent failures made loud.

A round of adversarial probing turned up a crash and a set of paths that gave a
wrong answer, or refused a correct deck, without saying anything. Each check
below is written as a differential -- the broken input against a sibling that
was always handled correctly -- because in every one of these cases "it ran" was
exactly the problem.

  * a bare `.four` card dereferenced NULL (SIGSEGV); `.print`/`.plot` take the
    identical "no nodes given" path in the same function and were always safe
  * `.four 1e400` overflows to +INF and produced a full report, THD 201.971 %,
    every harmonic frequency printed `inf`; literal `inf`, `nan`, `0` and even
    `1e-400` (which underflows to 0) were all already refused
  * `R1 a b 1,5k` silently built a 5 k resistor -- `,` is a token separator, so
    the trailing unlabeled number overwrote the value.  Every other separator
    (`1;5`, `1:5`, `1_000`) is ignored as trailing text
  * an array instance wider than 8192 collapsed to ONE device, 9x-21x wrong; the
    same over-wide range in a NODE field already got E-443's warning
  * `.option autobus` indexed tokens that cannot carry an index -- ground became
    five floating `0[0]`..`0[4]` nodes, and the device contributed nothing while
    the option being OFF would have produced E-402's warning
  * a failed `sweep` point published the PREVIOUS solution as its value
  * a legal 20-deep hierarchy was refused as "infinite subckt recursion"
  * itl1/itl2/itl4 below the solver floor were stored and echoed back but never
    applied, with no notice
  * four working `.four` options were reported as unknown on a `.options` line
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
        if junk.startswith("_gg_"):
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


MODELS = ("gapbus", "gapres")
compiled = {}
for m in MODELS:
    r = subprocess.run([OPENVAF, f"{m}.va", "-o", f"{m}.osdi"], cwd=HERE,
                       capture_output=True, text=True)
    compiled[m] = r.returncode == 0 and os.path.isfile(os.path.join(HERE, f"{m}.osdi"))


def run(deck, tag, timeout=180):
    p = os.path.join(HERE, f"_gg_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    return r.returncode, r.stdout + r.stderr


def num(out, pat):
    m = re.findall(pat, out, re.I)
    return m[-1] if m else None


print("Enhancement-445: nine silent failures made loud\n")
check("[E-445] the Verilog-A models compile", all(compiled.values()),
      f"{[m for m, ok in compiled.items() if not ok]}")

RLC = "V1 in 0 dc 0.5 sin(0.5 0.2 1k)\nRs in nb 1k\nRl nb 0 1k"

# ------------------------------------------------ a bare .four used to crash ---
print("\na bare `.four` card (was a NULL-deref SIGSEGV)")
rc, out = run(f"gg\n{RLC}\n.tran 1u 5m\n.four\n.print tran v(nb)\n.end\n", "bare")
check("[E-445] a bare `.four` no longer crashes", rc == 0, f"rc={rc}")
check("[E-445] ...and says the frequency is missing",
      "no fundamental frequency" in out or "no nodes given" in out, "")
# it must survive in every shape that used to kill it
for tag, card in (("twobare", ".four\n.four"),
                  ("mixed", ".four\n.four 1000 v(nb)"),
                  ("aftergood", ".four 1000 v(nb)\n.four")):
    rc, _ = run(f"gg\n{RLC}\n.tran 1u 5m\n{card}\n.print tran v(nb)\n.end\n", tag)
    check(f"[E-445] ...also with `{tag}`", rc == 0, f"rc={rc}")
# inside a subcircuit it survived flattening and still reached fourier()
rc, _ = run(f"gg\n{RLC}\nXs nb 0 s1\n.subckt s1 a b\nR9 a b 1k\n.four\n.ends\n"
            f".tran 1u 5m\n.print tran v(nb)\n.end\n", "insub")
check("[E-445] ...and inside a .subckt", rc == 0, f"rc={rc}")
# the sibling that was always fine must stay fine
rc, out = run(f"gg\n{RLC}\n.tran 1u 5m\n.four 1000 v(nb)\n.print tran v(nb)\n.end\n",
              "good")
check("[E-445] a valid `.four` still produces its analysis (control)",
      rc == 0 and "Fourier analysis for" in out, f"rc={rc}")

# ------------------------------------------- an overflowing fundamental freq ---
print("\nthe `.four` fundamental frequency must be finite")


def four_ok(freq, tag):
    rc, out = run(f"gg\n{RLC}\n.tran 1u 5m\n.four {freq} v(nb)\n"
                  f".print tran v(nb)\n.end\n", tag)
    return "Fourier analysis for" in out, out


for freq in ("1e400", "1e309"):
    ok, out = four_ok(freq, "ovf" + freq[-3:])
    check(f"[E-445] `.four {freq}` is refused (overflows to +INF)",
          not ok and "bad fundamental freq" in out, "")
# the guard already caught these -- they must not regress
for freq in ("0", "-1000", "inf", "nan", "1e-400"):
    ok, out = four_ok(freq, "old" + re.sub(r"\W", "", freq))
    check(f"[E-445] `.four {freq}` still refused (control)",
          not ok and "bad fundamental freq" in out, "")
# and a large but representable fundamental must still work
ok, _ = four_ok("1e30", "big")
check("[E-445] a large but FINITE fundamental still works (control)", ok, "")

# ------------------------------------------------- a comma in a device value ---
print("\na comma in a device value is two fields, not a decimal point")


def rval(lit, tag):
    rc, out = run(f"gg\nV1 in 0 dc 1\nR1 in nb {lit}\nR2 nb 0 1k\n.control\n"
                  f"option noacct\nset numdgt=10\nop\nprint @r1[resistance]\n"
                  f".endc\n.end\n", tag)
    return num(out, r"@r1\[resistance\]\s*=\s*(\S+)"), out


for lit, want in (("1,5k", 1.0), ("9,1k", 9.0), ("1k,9", 1000.0)):
    v, out = rval(lit, "cma" + re.sub(r"\W", "", lit))
    check(f"[E-445] `R1 a b {lit}` keeps the value position ({want:g}), not the "
          f"trailing field", v is not None and abs(float(v) - want) < 1e-9, f"{v}")
    check(f"[E-445] ...and says the value was given twice",
          "value given twice" in out, "")
# the unlabeled trailing number is how `R1 a b rmod 1k` works -- must be intact
rc, out = run("gg\nV1 in 0 dc 1\nR1 in nb rmod 2k\nR2 nb 0 1k\n"
              ".model rmod r(r=1)\n.control\noption noacct\nset numdgt=10\nop\n"
              "print @r1[resistance]\n.endc\n.end\n", "lead")
vlead = num(out, r"@r1\[resistance\]\s*=\s*(\S+)")
check("[E-445] a model name plus a trailing value still works (control)",
      vlead is not None and abs(float(vlead) - 2000.0) < 1e-6
      and "value given twice" not in out, f"{vlead}")
# every OTHER separator is documented as ignored trailing text -- unchanged
for lit, want in (("1k", 1000.0), ("1;5", 1.0), ("1:5", 1.0), ("1_000", 1.0)):
    v, out = rval(lit, "sep" + re.sub(r"\W", "", lit))
    check(f"[E-445] `{lit}` unchanged, and not warned about (control)",
          v is not None and abs(float(v) - want) < 1e-9
          and "value given twice" not in out, f"{v}")

# ------------------------------------------------ the array-instance width cap ---
print("\nan array instance wider than the cap is refused, not collapsed")
ARR = ("gg\nV1 in 0 dc 1\nRs in a 1k\nR[{r}] a 0 1k\n.control\noption noacct\n"
       "set numdgt=8\nop\nprint v(a)\n.endc\n.end\n")
rc, out = run(ARR.format(r="0:3"), "arr4")
v4 = num(out, r"v\(a\)\s*=\s*(\S+)")
check("[E-445] a 4-wide array still expands (control)",
      rc == 0 and v4 is not None and abs(float(v4) - 0.2) < 1e-6, f"{v4}")
rc, out = run(ARR.format(r="0:8191"), "arrmax", timeout=300)
v8 = num(out, r"v\(a\)\s*=\s*(\S+)")
check("[E-445] the widest legal array (8192) still expands (control)",
      rc == 0 and v8 is not None and abs(float(v8) - 1.0 / 8193.0) < 1e-6, f"{v8}")
for rng in ("0:8192", "0:19999"):
    rc, out = run(ARR.format(r=rng), "arrbad" + rng.split(":")[1])
    check(f"[E-445] `R[{rng}]` is refused rather than built as ONE device",
          rc != 0 and "not a usable index range" in out, f"rc={rc}")
# a lone scalar bit is NOT a list -- E-443's compatibility rule
rc, out = run(ARR.format(r="2"), "arrscalar")
v = num(out, r"v\(a\)\s*=\s*(\S+)")
check("[E-445] a lone `R[2]` is still one ordinary instance (control)",
      rc == 0 and v is not None and abs(float(v) - 0.5) < 1e-6, f"{v}")

# --------------------------------------------------------- hierarchy depth ---
print("\na legal deep hierarchy is not 'infinite recursion'")


def chain(n):
    s = ["gg", "V1 in 0 dc 1", "Xs0 in 0 s0"]
    for i in range(n):
        s.append(f".subckt s{i} a b")
        s.append(f"Xs{i + 1} a b s{i + 1}" if i < n - 1 else "R1 a b 1k")
        s.append(".ends")
    s += [".control", "option noacct", "op", "print v(in)", ".endc", ".end"]
    return "\n".join(s) + "\n"


for n in (20, 25, 60, 200):
    rc, out = run(chain(n), f"deep{n}")
    check(f"[E-445] a {n}-deep hierarchy is accepted",
          rc == 0 and "recursion" not in out, f"rc={rc}")
rc, out = run(chain(5), "deep5")
check("[E-445] a shallow hierarchy still works (control)", rc == 0, f"rc={rc}")
# a genuinely recursive subcircuit must still be refused, and must terminate
rc, out = run("gg\nV1 in 0 dc 1\nXa in 0 r1\n.subckt r1 a b\nXi a b r1\n.ends\n"
              ".control\noption noacct\nop\n.endc\n.end\n", "recur")
check("[E-445] a self-recursive subcircuit is still refused (control)",
      rc != 0, f"rc={rc}")

# --------------------------------------------- failed sweep points are NaN ---
print("\na sweep point that never solved is NaN, not the previous solution")
SW = ("gg\nV1 in 0 dc 1\nRs in nb {rs}\nN1 nb 0 mo\n.model mo gapres n=1 r=1k\n"
      ".control\noption noacct\nset numdgt=8\npre_osdi gapres.osdi\nop\n"
      "sweep @mo[n] -2 2 1 -output vo=v(nb)\nprint vo\n"
      "wrdata _gg_sw.dat vo\n.endc\n.end\n")
rc, out = run(SW.format(rs="1k"), "sweep")
rows = re.findall(r"^\s*\d+\s+(\S+)", out, re.M)
nans = [r for r in rows if r.lower().startswith("nan")]
check("[E-445] the sweep still runs and reports the failures",
      rc == 0 and "did not converge" in out, f"rc={rc}")
check("[E-445] the 3 forbidden points are NaN, not a value",
      len(nans) == 3, f"{rows}")
check("[E-445] ...and the 2 legal points keep real values",
      len(rows) == 5 and not rows[3].lower().startswith("nan")
      and abs(float(rows[3]) - 0.5) < 1e-6, f"{rows}")
try:
    dat = open(os.path.join(HERE, "_gg_sw.dat")).read()
except OSError:
    dat = ""
check("[E-445] `wrdata` writes them as nan, so a data file is honest too",
      dat.lower().count("nan") == 3, dat.replace("\n", " | ")[:70])
# the previous solution must no longer leak in: a different prior, same NaNs
rc, out = run(SW.format(rs="250"), "sweep2")
rows2 = re.findall(r"^\s*\d+\s+(\S+)", out, re.M)
check("[E-445] a DIFFERENT prior operating point gives the same NaNs "
      "(the stale value is gone)",
      len([r for r in rows2 if r.lower().startswith("nan")]) == 3, f"{rows2}")

# ---------------------------------------------------- autobus token guards ---
print("\n`.option autobus` refuses a token that cannot carry an index")
GND = ("gg\nVb bb 0 dc 1\n{inst}\n.model bd gapbus r=1k{opt}\n.control\n"
       "option noacct\nset numdgt=10\npre_osdi gapbus.osdi\nop\nprint i(vb)\n"
       ".endc\n.end\n")
GSUM = sum(1e-3 / 2 ** i for i in range(5))
rc, out = run(GND.format(inst="N1 0 0 0 0 0 bb bd", opt="\n.option autobus"), "gexp")
iexp = num(out, r"i\(vb\)\s*=\s*(\S+)")
check("[E-445] an explicitly grounded bus is the reference",
      iexp is not None and abs(float(iexp) + GSUM) < 1e-9, f"{iexp}")
rc, out = run(GND.format(inst="N1 0 bb bd", opt="\n.option autobus"), "ggnd")
check("[E-445] `N1 0 bb bd` says ground cannot be indexed",
      "ground cannot be indexed" in out, "")
DRV = "\n".join(f"V{i} q[{i}] 0 dc {0.1 * (i + 1):.1f}" for i in range(5))
rc, out = run(GND.format(inst=DRV + "\nN1 q[0] bb bd", opt="\n.option autobus"),
              "gidx")
check("[E-445] an already-indexed token says so",
      "already carries an index" in out, "")
# the feature itself must be untouched
rc, out = run(GND.format(inst=DRV + "\nN1 q bb bd", opt="\n.option autobus"),
              "gok")
iok = num(out, r"i\(vb\)\s*=\s*(\S+)")
want = sum((0.1 * (k + 1) - 1.0) * (1e-3 / 2 ** k) for k in range(5))
check("[E-445] a normal autobus expansion is unchanged (control)",
      iok is not None and abs(float(iok) - want) < 1e-9, f"{iok} want {want:.9e}")
# a SCALAR port may legitimately be tied to ground -- the guard must not fire
rc, out = run(GND.format(inst=DRV + "\nN1 q 0 bd", opt="\n.option autobus"),
              "gscalar")
check("[E-445] a scalar port tied to ground is untouched (control)",
      rc == 0 and "cannot be indexed" not in out, f"rc={rc}")

# --------------------------------------------------- the itl floor is stated ---
print("\nan iteration limit below the solver floor is announced")
for opt, below in (("itl1=3", True), ("itl2=5", True), ("itl4=1", True),
                   ("itl1=200", False), ("itl1=100", False)):
    rc, out = run(f"gg\n{RLC}\n.option {opt}\n.tran 1u 200u\n"
                  f".print tran v(nb)\n.end\n", "itl" + re.sub(r"\W", "", opt))
    said = "below the solver's minimum" in out
    check(f"[E-445] `.option {opt}` " + ("is announced" if below else
                                         "is silent (control)"),
          said == below, f"said={said}")

# ------------------------------------- the .four options are not 'unknown' ---
print("\nthe `.four` controls are registered with E-438's .options check")
for opt in ("nfreqs=3", "fourgridsize=10", "polydegree=3", "nperiods=2"):
    rc, out = run(f"gg\n{RLC}\n.option {opt}\n.tran 1u 5m\n.four 1000 v(nb)\n"
                  f".print tran v(nb)\n.end\n", "opt" + opt.split("=")[0])
    name = opt.split("=")[0]
    check(f"[E-445] `.option {opt}` is not reported unknown",
          f"unknown option '{name}'" not in out, "")
# ...and each really does take effect, which is why the warning was wrong
rc, out = run(f"gg\n{RLC}\n.option fourgridsize=10\n.tran 1u 5m\n"
              f".four 1000 v(nb)\n.print tran v(nb)\n.end\n", "optfx")
check("[E-445] ...and `fourgridsize` really does change the analysis",
      "Gridsize: 10" in out, "")
rc, out = run(f"gg\n{RLC}\n.option notanoption=1\n.tran 1u 200u\n"
              f".print tran v(nb)\n.end\n", "optbogus")
check("[E-445] a genuinely unknown option IS still flagged (control)",
      "unknown option 'notanoption'" in out, "")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
