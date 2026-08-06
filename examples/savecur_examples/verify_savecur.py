#!/usr/bin/env python3
"""verify_savecur.py -- Enhancement-413: `.options savecurrents` produces real
per-terminal waveforms for an OSDI device with more than two terminals.

WHAT WENT WRONG. `.options savecurrents` is a TEXTUAL pre-pass over the deck
(`inp_savecurrents`), running long before any `.osdi` is loaded, so it cannot
know a compact model's terminal names -- it emits the bare `@dev[i]` that R, C
and L use. Enhancement-394 defines that alias only for TWO-terminal devices, so
for anything wider the save named a parameter that does not exist: ngspice
registered the vector and left it EMPTY, with no diagnostic, while a built-in
BJT in the same deck produced `@q1[ic]`, `@q1[ie]`, `@q1[ib]`, `@q1[is]`.

THE VALUES WERE NEVER WRONG -- only uncapturable. Read as scalars after `op` the
terminal currents were always exact, and an explicit `.save @nd1[i_d]` always
worked. What was missing was the waveform, which is the thing `savecurrents`
exists to provide.

THE FIX RESOLVES NAMES LATER. `ft_getSaves()` runs at analysis start, when the
circuit is set up and the descriptor is known, so a bare `@dev[i]` belonging to
an OSDI instance that does not define it is expanded there into one entry per
terminal. The two-terminal case is deliberately untouched, since `@dev[i]` is
real there.

Each terminal draws a distinct current, so a waveform identifies its terminal,
and the four must sum to zero by KCL.

Exit code 0 = pass.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
OSDI = os.path.join(tempfile.gettempdir(), "savecur.osdi")
# vd=1, vg=2, vb=3, s grounded: i_d = 1e-3, i_g = 2*2e-3, i_b = 3*4e-3
WANT = {"i_d": 1e-3, "i_g": 4e-3, "i_b": 12e-3, "i_s": -17e-3}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(name, body, ctrl):
    path = os.path.join(tempfile.gettempdir(), f"sc_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* savecur {name}
{body}
.control
pre_osdi {OSDI}
set numdgt=12
{ctrl}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "TEMP =" not in l)


def num(out, expr):
    m = re.findall(re.escape(expr) + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


FOUR = """vd d 0 pulse(0 1 0 1n 1n 10u 20u)
vg g 0 dc 2
vb b 0 dc 3
nd1 d g 0 b m4
q1 d g 0 qmod
.model m4 savecur4()
.model qmod npn(is=1e-16 bf=100)
.options savecurrents reltol=1e-11"""

TWO = """v1 a 0 pulse(0 1 0 1n 1n 10u 20u)
nd1 a 0 m2
.model m2 savecur2()
.options savecurrents reltol=1e-11"""


def main():
    print("Enhancement-413: savecurrents gives per-terminal waveforms for OSDI\n")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "savecur.va"), "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    if not check("savecur.va compiles", r.returncode == 0 and os.path.exists(OSDI),
                 (r.stdout + r.stderr).strip().splitlines()[:1]):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    print("\n  four-terminal device: one filled vector per terminal")
    out = run("four", FOUR, "tran 200n 4u\n"
              + "\n".join(f"print length(@nd1[{k}])" for k in WANT))
    lens = {k: num(out, f"length(@nd1[{k}])") for k in WANT}
    for k in WANT:
        check(f"@nd1[{k}] is a waveform, not a scalar",
              lens[k] is not None and lens[k] > 1, f"length={lens[k]}")
    check("all four have the same length",
          len(set(v for v in lens.values() if v)) == 1, str(lens))

    print("\n  the built-in beside it is unaffected")
    out_b = run("bjt", FOUR, "tran 200n 4u\nprint length(@q1[ic])\nprint length(@q1[ib])")
    check("@q1[ic] still saved", (num(out_b, "length(@q1[ic])") or 0) > 1)
    check("@q1[ib] still saved", (num(out_b, "length(@q1[ib])") or 0) > 1)

    print("\n  the saved values are the real terminal currents")
    out_v = run("vals", FOUR.replace("pulse(0 1 0 1n 1n 10u 20u)", "dc 1"),
                "tran 1u 3u\n" + "\n".join(f"print @nd1[{k}][0]" for k in WANT)
                + "\nop\n" + "\n".join(f"print @nd1[{k}]" for k in WANT))
    tot = 0.0
    for k, want in WANT.items():
        wave = num(out_v, f"@nd1[{k}][0]")
        check(f"{k} waveform[0] = {want}", wave is not None and abs(wave - want) < 1e-12,
              f"got {wave}")
        vals = re.findall(re.escape(f"@nd1[{k}]") + r"\s*=\s*(-?[\d.eE+-]+)", out_v)
        if vals:
            tot += float(vals[-1])
    check("the four terminal currents satisfy KCL", abs(tot) < 1e-12, f"sum={tot:.3e}")

    print("\n  the two-terminal case is deliberately unchanged")
    out2 = run("two", TWO, "tran 200n 4u\nprint length(@nd1[i])")
    check("@nd1[i] still works for a 2-terminal device",
          (num(out2, "length(@nd1[i])") or 0) > 1,
          f"length={num(out2, 'length(@nd1[i])')}")

    print("\n  a BUS terminal current, whose name itself contains brackets")
    # `.save @nd1[i_a[1]]` was dropped SILENTLY -- no vector, no diagnostic --
    # because the output path split `@dev[param]` at the FIRST ']', leaving
    # `i_a[1`. The scalar read of the same name was always correct, which is
    # exactly what hid it. Guarded here because Enhancement-413 is what makes
    # these names reachable from savecurrents in the first place.
    BUS = """v0 n[0] 0 pulse(0 1 0 1n 1n 10u 20u)
v1 n[1] 0 dc 1
v2 n[2] 0 dc 1
v3 n[3] 0 dc 1
nd1 n[0:3] 0 mbus
.model mbus savecur_bus()
.options savecurrents reltol=1e-11"""
    out = run("bus", BUS, "tran 200n 2u\n"
              + "\n".join(f"print length(@nd1[i_a[{k}]])" for k in range(4))
              + "\nprint length(@nd1[i_c])\nprint @nd1[i_a[1]][3]")
    for k in range(4):
        n = num(out, f"length(@nd1[i_a[{k}]])")
        check(f"@nd1[i_a[{k}]] is a waveform", n is not None and n > 1, f"length={n}")
    check("the scalar terminal @nd1[i_c] is saved too",
          (num(out, "length(@nd1[i_c])") or 0) > 1)
    check("and its value is right (bit 1 at 1 V -> 2 mA)",
          abs((num(out, "@nd1[i_a[1]][3]") or 0) - 2e-3) < 1e-12,
          f"got {num(out, '@nd1[i_a[1]][3]')}")
    out = run("busx", BUS.replace(".options savecurrents", ".save @nd1[i_a[2]] all\n.options"),
              "tran 200n 2u\nprint length(@nd1[i_a[2]])")
    check("an explicit .save of a bracketed name works",
          (num(out, "length(@nd1[i_a[2]])") or 0) > 1)

    print("\n  explicit .save still works, and is not disturbed")
    out3 = run("expl", FOUR.replace(".options savecurrents", ".save @nd1[i_d] all\n.options"),
               "tran 200n 4u\nprint length(@nd1[i_d])")
    check("explicit .save @nd1[i_d] gives a waveform",
          (num(out3, "length(@nd1[i_d])") or 0) > 1)

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
