#!/usr/bin/env python3
"""Enhancement-453: the LRM's null argument was rejected, and printing a
comparison crashed the compiler.

NULL ARGUMENT. LRM 4.5.11 and 4.5.12 both state that the zeros argument of a
Laplace/Z-transform filter "may be represented as a null argument ...
characterized by two adjacent commas (,,)", and the LRM's own worked example is

    V(out) <+ laplace_zp(white_noise(k), , '{1,0,1,0,-1,0,-1,0});

which did not compile: "unexpected token ','", followed by a bogus arity
complaint ("at least 3 arguments but found 1") caused by the failed parse. The
capability was there -- `'{}` expresses "no zeros" and is numerically exact --
only the LRM's spelling of it was missing.

The empty slot now parses as the same empty-vector node `'{}` produces, so the
two spellings are the SAME filter. That is checked here numerically, not just by
exit code: a spelling fix that quietly produced a different filter would be a
worse defect than the one it replaced.

The parser sees token kinds only, never text, so it cannot tell which function
is being called; a null argument outside a filter is therefore left to type
inference, and every illegal use below must still be refused (LRM 4.6: "It is
illegal to specify a null argument in the argument list of an analog operator,
except as specified elsewhere"). In particular the Enhancement-423 trailing
comma stays an error.

PRINTING. An argument that no % conversion consumes is rendered from its own
type. Only real, integer and string had a case, and the fallback was
`unreachable!()` -- so `$strobe("x", 1 > 0)` (a Bool) and `$strobe("x", '{1.0})`
(an array) exited 101 with a crash banner and a request to file a bug. A named
array was already caught cleanly; these were not. `$strobe("%d", 1 > 0)` always
worked, so a Bool IS printable -- it simply never reached the cast on the
default path.
"""
import cmath
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0
F = 1000.0                       # AC probe frequency
WP = 1e4                         # the pole, rad/s
HEAD = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_src(text, tag):
    """Compile a snippet; returns (rc, output, osdi_path_or_None)."""
    src = os.path.join(HERE, f"_na_{tag}.va")
    osdi = os.path.join(HERE, f"_na_{tag}.osdi")
    with open(src, "w") as f:
        f.write(text)
    r = subprocess.run([OPENVAF, src, "-o", osdi], capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out, (osdi if r.returncode == 0 and os.path.isfile(osdi) else None)


def crashed(rc, out):
    """Enhancement-28: the panic HOOK exits 101 and prints a banner -- the word
    'panicked' never appears, so rc and the banner are what identify a crash."""
    return rc == 101 or "has crashed" in out or "open an issue" in out


def module(body, ports="in,out", extra=""):
    return (HEAD + f"module m({ports}); inout {ports.replace(',', ',')}; "
            f"electrical {ports};\n{extra} analog begin {body} end\nendmodule\n")


def ac_response(osdi, model):
    """|H| and phase (degrees) of `model` at F, driven through a 1 V AC source."""
    deck = os.path.join(tempfile.gettempdir(), f"na_{model}.cir")
    with open(deck, "w") as f:
        f.write(f"""* nullarg {model}
V1 in 0 dc 0 ac 1
N1 in out {model}
.model {model} {model}()
Rl out 0 1e12
.control
pre_osdi {osdi}
ac lin 1 {F} {F}
print mag(v(out)) ph(v(out))
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    m = re.search(r"mag\(v\(out\)\)\s*=\s*(-?[\d.eE+-]+)", out)
    p = re.search(r"ph\(v\(out\)\)\s*=\s*(-?[\d.eE+-]+)", out)
    if not m or not p:
        return None
    # ngspice reports phase in RADIANS unless told otherwise
    return float(m.group(1)), math.degrees(float(p.group(1)))


print("Enhancement-453: the LRM null argument, and printing a comparison\n")

# ------------------------------------------------- the LRM's own example ---
print("the LRM's worked example compiles")
rc, out, _ = compile_src(
    HEAD + "module m(in,out); inout in,out; electrical in,out;\n"
    "  parameter real k = 1e-18;\n"
    "  analog begin\n"
    "    V(out) <+ laplace_zp(white_noise(k), , '{1,0,1,0,-1,0,-1,0});\n"
    "  end\nendmodule\n", "lrm")
check("[E-453] LRM 4.5.11's laplace_zp example compiles", rc == 0,
      out.strip().splitlines()[0][:60] if rc != 0 and out.strip() else "")

# --------------------------------- the null argument across both families ---
print("\nthe null argument is accepted wherever the LRM allows it")
for label, body in [
    ("laplace_zp(x, , poles)", "V(out) <+ laplace_zp(V(in), , '{-1e4,0});"),
    ("laplace_zd(x, , den)", "V(out) <+ laplace_zd(V(in), , '{1,1e-4});"),
    ("laplace_nd(x, , den)", "V(out) <+ laplace_nd(V(in), , '{1,1e-4});"),
    ("laplace_np(x, , poles)", "V(out) <+ laplace_np(V(in), , '{-1e4,0});"),
    ("zi_zp(x, , poles, T)", "V(out) <+ zi_zp(V(in), , '{0.5,0}, 1e-5);"),
    ("zi_zd(x, , den, T)", "V(out) <+ zi_zd(V(in), , '{1,-0.5}, 1e-5);"),
]:
    tag = re.sub(r"[^a-z0-9]", "", label.lower())[:10]
    rc, out, _ = compile_src(module(body), tag)
    check(f"[E-453] {label}", rc == 0,
          out.strip().splitlines()[0][:52] if rc != 0 and out.strip() else "")

# ------------------------------- and it means the SAME THING as '{} does ---
print("\nthe null argument is the same filter as '{} -- checked numerically")
demo = os.path.join(HERE, "nullarg_demo.va")
osdi = os.path.join(HERE, "_na_demo.osdi")
r = subprocess.run([OPENVAF, demo, "-o", osdi], capture_output=True, text=True,
                   timeout=300, cwd=HERE)
built = r.returncode == 0 and os.path.isfile(osdi)
check("[E-453] nullarg_demo.va compiles", built,
      (r.stdout + r.stderr).strip().splitlines()[0][:60] if not built else "")

if built:
    s = 1j * 2 * math.pi * F
    want = 1.0 / (1.0 + s / WP)
    wm, wp_deg = abs(want), math.degrees(cmath.phase(want))
    got = {name: ac_response(osdi, name)
           for name in ("nullarg_demo", "nullarg_ref", "nullarg_zd")}
    for name, r_ in got.items():
        if r_ is None:
            check(f"[E-453] {name} responds in ac", False, "no ac result")
            continue
        mag, ph = r_
        check(f"[E-453] {name} matches 1/(1+s/1e4)",
              abs(mag - wm) / wm < 1e-6 and abs(ph - wp_deg) < 1e-4,
              f"|H|={mag:.10f} want {wm:.10f}, ph={ph:.5f} want {wp_deg:.5f}")
    if all(v is not None for v in got.values()):
        check("[E-453] null argument and '{} give the IDENTICAL response",
              got["nullarg_demo"] == got["nullarg_ref"],
              f"{got['nullarg_demo']} vs {got['nullarg_ref']}")
        check("[E-453] ...and laplace_zd with a null argument agrees too",
              got["nullarg_zd"] == got["nullarg_ref"],
              f"{got['nullarg_zd']} vs {got['nullarg_ref']}")

# ------------------------------------ what must STILL be refused, and how ---
print("\na null argument outside the filters is still an error (and never a crash)")
for label, body, extra in [
    ("max(1,,2)", "I(in,out) <+ max(1.0,,2.0);", ""),
    ("max(1,2,)  [E-423 trailing comma]", "I(in,out) <+ max(1.0,2.0,);", ""),
    ("ddt(,)", "I(in,out) <+ ddt(,);", ""),
    ('$strobe("a",,"b")', '$strobe("a",,"b"); I(in,out) <+ V(in,out)*1e-3;', ""),
    ("laplace_zp(, zeros, poles)", "V(out) <+ laplace_zp(, '{-1e5,0}, '{-1e4,0});", ""),
]:
    tag = re.sub(r"[^a-z0-9]", "", label.lower())[:10]
    rc, out, _ = compile_src(module(body, extra=extra), tag)
    check(f"[E-453] {label} is refused", rc != 0, f"rc={rc}")
    check(f"[E-453] ...and does not crash the compiler", not crashed(rc, out), f"rc={rc}")

# ------------------------------------------------- printing by value type ---
print("\nan argument no conversion consumes is printed, or refused -- never a crash")
for label, body in [
    ('$strobe("x", 1>0)', '$strobe("x", 1>0); I(in,out) <+ V(in,out)*1e-3;'),
    ('$strobe("x", V(in,out)>0.5)',
     '$strobe("x", V(in,out)>0.5); I(in,out) <+ V(in,out)*1e-3;'),
    ('$display("x", 1>0)', '$display("x", 1>0); I(in,out) <+ V(in,out)*1e-3;'),
]:
    tag = re.sub(r"[^a-z0-9]", "", label.lower())[:10]
    rc, out, _ = compile_src(module(body), tag)
    check(f"[E-453] {label} compiles", rc == 0,
          out.strip().splitlines()[0][:52] if rc != 0 and out.strip() else "")

for label, body in [
    ('$strobe("x", \'{1.0})', "$strobe(\"x\", '{1.0}); I(in,out) <+ V(in,out)*1e-3;"),
    ('$display("x", \'{})', "$display(\"x\", '{}); I(in,out) <+ V(in,out)*1e-3;"),
    ('$fatal(0, "x", \'{1.0})', "$fatal(0, \"x\", '{1.0}); I(in,out) <+ V(in,out)*1e-3;"),
]:
    tag = re.sub(r"[^a-z0-9]", "", label.lower())[:10]
    rc, out, _ = compile_src(module(body), tag)
    check(f"[E-453] an ARRAY at {label} is refused", rc != 0, f"rc={rc}")
    check(f"[E-453] ...and does not crash the compiler", not crashed(rc, out), f"rc={rc}")

# ------------------------------------- and the Bool prints the RIGHT value ---
print("\nthe printed comparison carries the right value")
if built:
    deck = os.path.join(tempfile.gettempdir(), "na_disp.cir")
    with open(deck, "w") as f:
        f.write(f"""* nullarg display
V1 in 0 dc 1
Rs in mid 1k
N1 mid 0 nullarg_disp
.model nullarg_disp nullarg_disp()
.control
pre_osdi {osdi}
op
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", deck], capture_output=True, text=True, timeout=300)
    dout = r.stdout + r.stderr
    check("[E-453] a true comparison prints 1", re.search(r"cmp_true=\s*1\b", dout) is not None,
          "not found in output")
    check("[E-453] a false comparison prints 0", re.search(r"cmp_false=\s*0\b", dout) is not None,
          "not found in output")
    check("[E-453] a real still prints as a real", "real= 1.5" in dout, "not found")
    check("[E-453] an integer still prints as an integer",
          re.search(r"int=\s*7\b", dout) is not None, "not found")
    check("[E-453] a string still prints as a string",
          re.search(r"str=\s*s\b", dout) is not None, "not found")

# ------------------------------------------------------------- housekeeping ---
for junk in os.listdir(HERE):
    if junk.startswith("_na_"):
        os.remove(os.path.join(HERE, junk))

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
