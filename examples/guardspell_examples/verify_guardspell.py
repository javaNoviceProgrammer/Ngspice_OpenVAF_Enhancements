#!/usr/bin/env python3
"""Enhancement-447: the guard that covered one spelling of a bad value.

Eight places where a degenerate or invalid input was accepted in silence -- and
in every one of them a working guard already sat a few lines away, covering a
*different* spelling of the same mistake.

  * `gmin=-1` was accepted silently and wrecked the operating point (a diode's
    0.63 V drop became -0.001 V), while reltol/abstol/vntol/chgtol/trtol/maxord/
    temp were all guarded
  * `scale=0` silently shorted a resistor while a resistance WRITTEN as 0 warned
    and was clamped
  * `trrandom` with a TYPE outside 1..4 was a silently dead source
  * an invalid diode `level=99` was accepted while `level=2` was fatally refused
  * `cshunt` set from `.control` was silently ignored (it is the only one of
    nineteen options that is card-only)
  * `show` claimed a source had all eight transient waveforms at once
  * E-438's checker flagged `savecurrents`, `seed` and `numdgt`
  * `snload`'s help documented one argument while the command required two
  * `pwl(... r=)` on a current source failed with a generic "unknown parameter"

Each check is paired with a control that must NOT move, because every fix here
narrows what is accepted.

TWO of the round's findings were NOT fixed, because Enhancement-426 had already
decided them the other way and its suite asserts the decisions: `m=0` is the
documented "disable this instance" idiom, and `@r[resistance]` is deliberately
the NOMINAL value with `1/@r1[conductance]` as the documented effective route.
Both are asserted below as controls so the conventions stay pinned.
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
        if junk.startswith("_gs_"):
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


def run(deck, tag, timeout=180):
    p = os.path.join(HERE, f"_gs_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    return r.returncode, r.stdout + r.stderr


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(\S+)", out, re.I)
    return float(m[-1]) if m else None


DIODE = "V1 in 0 dc 1\nR1 in nb 1k\nD1 nb 0 dm\n.model dm d(is=1e-14)"
DIV = "V1 in 0 dc 1\nRs in nb 1k"

print("Enhancement-447: the guard that covered one spelling of a bad value\n")

# ------------------------------------------------------------ negative gmin ---
print("a negative gmin is refused, like every sibling tolerance already was")
rc, out = run(f"e447\n{DIODE}\n.control\noption noacct\nset numdgt=10\nop\n"
              f"print v(nb)\n.endc\n.end\n", "gbase")
base = val(out, "v(nb)")
check("[E-447] the reference operating point", base is not None and abs(base - 0.629440782) < 1e-6, f"{base}")
for g in ("-1", "-1e6"):
    rc, out = run(f"e447\n{DIODE}\n.control\noption noacct\nset numdgt=10\noption gmin={g}\n"
                  f"op\nprint v(nb)\n.endc\n.end\n", "gn" + re.sub(r"\W", "", g))
    v = val(out, "v(nb)")
    check(f"[E-447] gmin={g} is refused and the answer is unharmed",
          "must not be negative" in out and v is not None and abs(v - base) < 1e-9, f"{v}")
for g in ("1e-12", "0", "1e-3"):
    rc, out = run(f"e447\n{DIODE}\n.control\noption noacct\nset numdgt=10\noption gmin={g}\n"
                  f"op\nprint v(nb)\n.endc\n.end\n", "gp" + re.sub(r"\W", "", g))
    check(f"[E-447] gmin={g} is still accepted (control)",
          rc == 0 and "must not be negative" not in out, "")

# ------------------------------------------------------------- m= and scale= ---
print("\na non-positive scale is called out; m=0 stays the documented idiom")
for spec, want, msg in (("R1 nb 0 1k scale=0", 0.5, "scale=0 is not positive"),
                        ("R1 nb 0 1k scale=-1", 0.5, "scale=-1 is not positive")):
    rc, out = run(f"e447\n{DIV}\n{spec}\n.control\noption noacct\nset numdgt=10\nop\n"
                  f"print v(nb)\n.endc\n.end\n", "ms" + re.sub(r"\W", "", spec))
    v = val(out, "v(nb)")
    check(f"[E-447] `{spec}` is reported", msg in out, "")
    check(f"[E-447] ...and falls back to 1 rather than shorting the node",
          v is not None and abs(v - want) < 1e-9, f"v(nb)={v}")
# E-426 established m=0 as the "disable this instance" idiom and its suite asserts
# the silence. E-447 considered warning on it and deliberately did not.
rc, out = run(f"e447\n{DIV}\nR1 nb 0 1k m=0\n.control\noption noacct\nset numdgt=10\nop\n"
              f"print v(nb)\n.endc\n.end\n", "mzero")
check("[E-447] m=0 stays SILENT -- E-426's 'disable this instance' idiom (control)",
      "multiplier" not in out, "")
rc, out = run(f"e447\n{DIV}\nR1 nb 0 1k m=-2\n.control\noption noacct\nop\nprint v(nb)\n"
              f".endc\n.end\n", "mneg")
check("[E-447] a negative multiplier still warns (control)", "is negative" in out, "")
rc, out = run(f"e447\n{DIV}\nR1 nb 0 1k\n.control\noption noacct\nset numdgt=10\nop\n"
              f"print v(nb)\n.endc\n.end\n", "mok")
v = val(out, "v(nb)")
check("[E-447] a plain resistor is unchanged and silent (control)",
      v is not None and abs(v - 0.5) < 1e-12 and "scale" not in out, f"{v}")

# ------------------------------------------------------------------ trrandom ---
print("\ntrrandom TYPE must be a distribution")
for ty in (1, 2, 3, 4):
    rc, out = run(f"e447\nV1 a 0 trrandom({ty} 10u 0 1 0)\nR1 a 0 1k\n.control\noption noacct\n"
                  f"tran 1u 200u\nlet s=sqrt(mean((v(a)-mean(v(a)))^2))\nprint s\n.endc\n.end\n",
                  f"tr{ty}")
    s = val(out, "s")
    check(f"[E-447] trrandom type {ty} still runs and makes noise (control)",
          rc == 0 and s is not None and s > 1e-3, f"rms={s}")
for ty in (0, 5, 9, -1):
    rc, out = run(f"e447\nV1 a 0 trrandom({ty} 10u 0 1 0)\nR1 a 0 1k\n.control\noption noacct\n"
                  f"tran 1u 200u\nprint v(a)[3]\n.endc\n.end\n", f"trb{abs(ty)}x")
    check(f"[E-447] trrandom type {ty} is refused, not a dead source",
          rc != 0 and "is not a distribution" in out, f"rc={rc}")
rc, out = run(f"e447\nI1 0 a trrandom(9 10u 0 1 0)\nR1 a 0 1k\n.control\noption noacct\n"
              f"tran 1u 200u\nprint v(a)[3]\n.endc\n.end\n", "trbi")
check("[E-447] ...on the current source too", rc != 0 and "is not a distribution" in out, f"rc={rc}")

# --------------------------------------------------------------- diode level ---
print("\nan invalid diode level is refused like the unimplemented one")
for L, ok_expected in ((1, True), (3, True), (99, False), (-1, False)):
    rc, out = run(f"e447\nV1 in 0 dc 0.7\nD1 in 0 dm\n.model dm d(is=1e-14 level={L})\n"
                  f".control\noption noacct\nop\nprint i(v1)\n.endc\n.end\n", f"dl{abs(L)}")
    if ok_expected:
        check(f"[E-447] diode level={L} still works (control)", rc == 0, f"rc={rc}")
    else:
        check(f"[E-447] diode level={L} is refused", rc != 0 and "does not exist" in out, f"rc={rc}")
rc, out = run(f"e447\nV1 in 0 dc 0.7\nD1 in 0 dm\n.model dm d(is=1e-14 level=2)\n"
              f".control\noption noacct\nop\n.endc\n.end\n", "dl2")
check("[E-447] level=2 keeps its own 'not supported' message (control)",
      "not supported" in out, "")

# --------------------------------------------------------------------- cshunt ---
print("\ncshunt says when it cannot take effect")
CS = "V1 in 0 pulse(0 1 0 1n 1n 10m 20m)\nR1 in b 1k\nRl b 0 1meg"
rc, out = run(f"e447\n{CS}\n.options cshunt=1e-6\n.control\noption noacct\nset numdgt=10\n"
              f"tran 5u 300u 0 5u\nprint v(b)[10]\n.endc\n.end\n", "csc")
vc = val(out, "v(b)[10]")
check("[E-447] the .options CARD still works and stays quiet",
      vc is not None and vc < 1e-5 and "must be given as a" not in out, f"{vc}")
rc, out = run(f"e447\n{CS}\n.control\noption noacct\nset numdgt=10\noption cshunt=1e-6\n"
              f"tran 5u 300u 0 5u\nprint v(b)[10]\n.endc\n.end\n", "cst")
check("[E-447] the .control form now says it is too late",
      "must be given as a" in out, "")
rc, out = run(f"e447\n{CS}\n.control\noption noacct\nset numdgt=10\ntran 5u 300u 0 5u\n"
              f"print v(b)[10]\n.endc\n.end\n", "csn")
check("[E-447] a deck with no cshunt is unaffected (control)",
      "must be given as a" not in out, "")

# --------------------------------------------- @r[resistance] stays NOMINAL ---
print("\n@r[resistance] stays nominal; @r[conductance] is the effective route")


def rq(spec, T, tag):
    rc, out = run(f"e447\nV1 in 0 dc 1\n{spec}\nR2 nb 0 1k\n.control\noption noacct\n"
                  f"set numdgt=12\noption temp={T}\nop\nprint v(nb)\nprint @r1[resistance]\n"
                  f"let reff=1/@r1[conductance]\nprint reff\n.endc\n.end\n", tag)
    return val(out, "v(nb)"), val(out, "@r1[resistance]"), val(out, "reff")


# E-426 settled this convention and documents 1/@r1[conductance] as the way to
# read what is actually stamped. E-447 considered flipping it and did not.
for T, eff in ((27, 1000.0), (100, 1073.0), (-50, 923.0)):
    v, r, reff = rq("R1 in nb 1k tc1=0.001", T, f"tc{abs(T)}")
    check(f"[E-447] at {T}C @r1[resistance] stays the nominal 1000 (E-426's convention)",
          r is not None and abs(r - 1000.0) < 1e-9, f"{r}")
    check(f"[E-447] ...while 1/@r1[conductance] gives the effective {eff:g}",
          reff is not None and abs(reff - eff) < 1e-6, f"{reff}")
    exp = 1000.0 / (eff + 1000.0)
    check(f"[E-447] ...and the circuit uses the effective value",
          v is not None and abs(v - exp) < 1e-9, f"v(nb)={v}")

# --------------------------------------------------------------------- show ---
print("\nshow names only the waveform the source actually has")


def shown(src, dev, tag):
    rc, out = run(f"e447\n{src}\nR1 in 0 1k\n.control\noption noacct\nop\nshow {dev}\n"
                  f".endc\n.end\n", tag)
    named = []
    for line in out.splitlines():
        m = re.match(r"^\s*(pulse|sin|exp|pwl|sffm|am|trnoise|trrandom)\s+(\S+)", line)
        if m:
            named.append((m.group(1), m.group(2)))
    return [n for n, v0 in named if v0 != "-"], len(named)


act, total = shown("V1 in 0 sin(0 2 3k)", "v1", "shsin")
check("[E-447] a sin-only source shows only sin", act == ["sin"], f"{act}")
check("[E-447] ...and the other seven are listed as absent", total == 8, f"{total} entries")
act, _ = shown("V1 in 0 pulse(0 1 0 1n 1n 2m 4m)", "v1", "shpul")
check("[E-447] a pulse-only source shows only pulse", act == ["pulse"], f"{act}")
act, _ = shown("I1 0 in sin(0 2m 3k)", "i1", "shi")
check("[E-447] the current source behaves the same", act == ["sin"], f"{act}")
act, _ = shown("V1 in 0 dc 1", "v1", "shdc")
check("[E-447] a dc-only source shows none (control)", act == [], f"{act}")
# the values themselves must still be readable
rc, out = run("e447\nV1 in 0 sin(0 2 3k)\nR1 in 0 1k\n.control\noption noacct\nop\n"
              "print @v1[sin]\n.endc\n.end\n", "askok")
check("[E-447] @v1[sin] still returns the coefficients (control)",
      "3.000000e+03" in out or "3000" in out, "")

# ------------------------------------------------------- .options registration ---
print("\nreal .options keywords are not called unknown")
for opt in ("savecurrents", "seed=7", "numdgt=8"):
    rc, out = run(f"e447\nV1 in 0 dc 1\nR1 in a 1k\nR2 a 0 1k\n.options {opt}\n.control\n"
                  f"option noacct\nop\nprint v(a)\n.endc\n.end\n", "op" + opt.split("=")[0])
    check(f"[E-447] `.options {opt}` is not reported unknown",
          f"unknown option '{opt.split('=')[0]}'" not in out, "")
rc, out = run("e447\nV1 in 0 dc 1\nR1 in a 1k\nR2 a 0 1k\n.options notanoption\n.control\n"
              "option noacct\nop\nprint v(a)\n.endc\n.end\n", "opbogus")
check("[E-447] a genuinely unknown option IS still flagged (control)",
      "unknown option 'notanoption'" in out, "")
# savecurrents must still do its job
rc, out = run("e447\nV1 in 0 dc 0 sin(0 1 1k)\nR1 in a 1k\nR2 a 0 2k\n.options savecurrents\n"
              ".control\noption noacct\nset numdgt=8\ntran 20u 400u\nprint @r1[i][5]\n"
              ".endc\n.end\n", "svc")
check("[E-447] ...and savecurrents still produces the current waveform (control)",
      val(out, "@r1[i][5]") is not None, "")

# ------------------------------------------------------------ snload / isrc pwl ---
print("\ndiagnostics that name the real reason")
rc, out = run("e447\nV1 a 0 dc 1\nR1 a 0 1k\n.control\nhelp snload\n.endc\n.end\n", "hsn")
check("[E-447] snload's help names BOTH files it requires",
      "netlist snapshot" in out, "")
rc, out = run("e447\nI1 0 a pwl(0 0 1m 1m 2m 0 r=0)\nR1 a 0 1k\n.control\noption noacct\n"
              "tran 50u 3m uic\nprint v(a)[5]\n.endc\n.end\n", "ipwlr")
check("[E-447] `pwl r=` on a current source says it is voltage-source-only",
      rc != 0 and "VOLTAGE sources only" in out, f"rc={rc}")
rc, out = run("e447\nV1 a 0 pwl(0 0 1m 1 2m 0 r=0)\nR1 a 0 1k\n.control\noption noacct\n"
              "tran 50u 3m uic\nprint v(a)[5]\n.endc\n.end\n", "vpwlr")
check("[E-447] ...while the voltage source still accepts it (control)", rc == 0, f"rc={rc}")
rc, out = run("e447\nI1 0 a pwl(0 0 1m 1m 2m 0)\nR1 a 0 1k\n.control\noption noacct\n"
              "tran 50u 3m uic\nprint v(a)[5]\n.endc\n.end\n", "ipwlok")
check("[E-447] ...and a plain current-source pwl is unaffected (control)", rc == 0, f"rc={rc}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
