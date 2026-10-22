#!/usr/bin/env python3
"""Enhancement-915: `.option scale` is applied to compiled instances.

F2 of the 2026-09-26 options-and-convergence hunt. `.option scale` multiplies
the geometry of every built-in MOSFET in its parameter setter -- w, l, ps and
pd by the scale, as and ad by its square -- and nothing scaled a compiled
instance: a deck written for scale=1e-6 simulated a compiled BSIM4 with
`w=1 l=0.1` as a transistor one metre wide, silently.

The compiled layer now scales the instance parameters of those names that
declare metres (square metres), or no units and a description that says
length, width, perimeter (area). One that declares neither is used as written,
with a warning; a model with its own `scale` parameter, the CMC convention,
applies the scale itself and is left alone. The value reads back as written,
so a `.dc` sweep of it restores what it found.

Checks (both solvers):
  [1] each of w, l, ps, pd and as, ad under scale=1e-6 gives what the unscaled
      metres give
  [2] the parameter reads back as written, and a `.dc` sweep of it restores it
  [3] `alter` under scale is scaled as the instance line is
  [4] an `l` in henries is not scaled
  [5] a `w` with no units and no description: used as written, warned once
  [6] a model with its own `scale` parameter is not scaled twice
  [7] the VA-Models BSIM4 with `w=1 l=0.1` and junction geometry: the point of
      `w=1u l=100n`, and the built-in BSIM4's
  [8] PSP103 likewise
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

ROOT = os.path.dirname(os.path.dirname(HERE))
CORPUS = os.path.join(ROOT, "VA_TEST", "VA-Models-main", "code")
REAL = {"bsim4va": os.path.join(CORPUS, "bsim4", "vacode", "bsim4.va"),
        "psp103": os.path.join(CORPUS, "psp103", "vacode", "psp103.va")}
MODULES = ["geo", "henry", "nounits", "selfscale"]

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_all():
    jobs = [(m + ".va", m + ".osdi") for m in MODULES] + \
           [(os.path.relpath(va, HERE), n + ".osdi") for n, va in REAL.items()]
    for src, out in jobs:
        if os.path.exists(os.path.join(HERE, out)):
            os.remove(os.path.join(HERE, out))
        subprocess.run([OPENVAF, src, "-o", out], cwd=HERE, capture_output=True, text=True,
                       timeout=600)
    return all(os.path.exists(os.path.join(HERE, out)) for _, out in jobs)


def run(osdi, body, ctl, scale=None, tag="t"):
    deck = (f"* scaleoption {tag}\n{body}\n" + (f".option scale={scale}\n" if scale else "") +
            f".control\npre_osdi {osdi}\nset numdgt=12\n{ctl}\n.endc\n.end\n")
    with open(os.path.join(HERE, f"_{tag}.cir"), "w") as f:
        f.write(deck)
    p = subprocess.run([NGSPICE, "-b", f"_{tag}.cir"], cwd=HERE, capture_output=True, text=True,
                       timeout=120, errors="replace")
    return p.stdout + p.stderr


def vals(out, name):
    return [abs(float(x)) for x in re.findall(rf"^{re.escape(name)} = (\S+)", out, re.M)]


def first(v):
    return v[0] if v else None


def near(a, b, rel=1e-9):
    return a is not None and b is not None and abs(a - b) <= rel * abs(b)


def geo(params, scale=None, ctl="op\nprint i(v1)", tag="geo"):
    body = f"V1 a 0 1\nN1 a 0 mg {params}\n.model mg geo"
    return run("geo.osdi", body, ctl, scale, tag)


print("Enhancement-915: `.option scale` is applied to compiled instances\n")
if not check("compile the four pattern modules, the VA-Models BSIM4 and PSP103", compile_all()):
    print(f"\n{passed}/{checks} checks passed")
    sys.exit(1)

rows = []
for name, scaled, metres in [("w", "w=1", "w=1u"), ("l", "l=2", "l=2u"), ("ps", "ps=3", "ps=3u"),
                             ("pd", "pd=4", "pd=4u"), ("as", "as=1", "as=1p"), ("ad", "ad=2", "ad=2p")]:
    a = first(vals(geo(scaled, 1e-6, tag="g_" + name), "i(v1)"))
    b = first(vals(geo(metres, tag="gm_" + name), "i(v1)"))
    rows.append((name, a, b, near(a, b)))
check("[1] under scale=1e-6, w, l and ps, pd (no units, a description) are scaled by 1e-6 and "
      "as, ad by 1e-12: each gives the current its value in metres gives (was 1e6 and 1e12 "
      "times it)", all(r[3] for r in rows),
      " ".join(f"{r[0]}:{r[1]:.4g}/{r[2]:.4g}" for r in rows))

A = "@"
W = A + "n1[w]"
ctl = f"op\nprint i(v1) {W}\ndc {W} 1 3 1\nop\nprint i(v1) {W}"
out = geo("w=1", 1e-6, ctl, tag="readback")
i, w = vals(out, "i(v1)"), vals(out, W)
check(f"[2] `{W}` reads back 1, as written, and after `dc {W} 1 3 1` the operating point "
      "and the parameter are what they were", len(i) == 2 and near(i[0], i[1]) and
      w == [1.0, 1.0] and near(i[0], 1e-3), f"{i} {w}")

out = geo("w=1", 1e-6, "op\nprint i(v1)\nalter n1 w=2\nop\nprint i(v1)", tag="alter")
i = vals(out, "i(v1)")
check("[3] `alter n1 w=2` under scale=1e-6 is 2 um, as `w=2` on the line would be",
      len(i) == 2 and near(i[0], 1e-3) and near(i[1], 2e-3), f"{i}")

out = run("henry.osdi", "V1 a 0 1\nN1 a 0 mh l=1n\n.model mh henry", "op\nprint i(v1)", 1e-6,
          "henry")
check("[4] an instance parameter `l` in henries is not scaled", near(first(vals(out, "i(v1)")),
                                                                    1e-3), f"{first(vals(out, 'i(v1)'))}")

body = "V1 a 0 1\nN1 a 0 mu w=1u\nN2 a 0 mu w=2u\n.model mu nounits"
out = run("nounits.osdi", body, "op\nprint i(v1)", 1e-6, "nounits")
warn = [ln for ln in out.splitlines() if "is not applied to the compiled model" in ln]
check("[5] a `w` with no units and no description is used as written, and one warning says why",
      near(first(vals(out, "i(v1)")), 3e-3) and len(warn) == 1 and
      "instance parameter 'w': it declares no units, so ngspice cannot tell it is a length" in warn[0],
      warn[0][:110] if warn else "no warning")

out = run("selfscale.osdi", "V1 a 0 1\nN1 a 0 ms w=1\n.model ms selfscale", "op\nprint i(v1)", 1e-6,
          "self")
check("[6] a model with its own `scale` parameter applies $simparam(\"scale\") itself and is not "
      "scaled twice", near(first(vals(out, "i(v1)")), 1e-3), f"{first(vals(out, 'i(v1)'))}")


def mos(osdi, model, inst, scale=None, builtin="", tag="m"):
    body = (f"vdd vdd 0 dc 1.2\nvin in 0 dc 0.6\nnm1 out in 0 0 mos_va {inst}\nR1 vdd out 20k\n"
            f".model mos_va {model}\n" +
            (f"m1 outb in 0 0 mos_bi {inst}\nR2 vdd outb 20k\n.model mos_bi {builtin}\n"
             if builtin else ""))
    out = run(osdi, body, "op\nprint v(out)" + (" v(outb)" if builtin else ""), scale, tag)
    return first(vals(out, "v(out)")), first(vals(out, "v(outb)"))


B4BI = "nmos level=14 version=4.8"
s_va, s_bi = mos("bsim4va.osdi", "bsim4va", "w=1 l=0.1 as=0.2 ad=0.2 ps=2.4 pd=2.4", 1e-6, B4BI,
                 "b4s")
u_va, u_bi = mos("bsim4va.osdi", "bsim4va", "w=1u l=100n as=0.2p ad=0.2p ps=2.4u pd=2.4u", None,
                 B4BI, "b4u")
check("[7] the VA-Models BSIM4 with `w=1 l=0.1` and junction geometry under scale=1e-6 is the "
      "point of the same device in metres (was 0.019067 V: a transistor 1 m wide with 0.2 m^2 "
      "junctions)",
      near(s_va, u_va, 1e-12), f"{s_va} / {u_va}")
check("[7] ... 4e-5 from the built-in BSIM4 4.8, which the option scales the same way",
      near(s_bi, u_bi, 1e-12) and near(s_va, s_bi, 1e-4), f"{s_va} / {s_bi}")

ps, _ = mos("psp103.osdi", "psp103va", "W=1 L=0.1 AS=0.2 AD=0.2 PS=2.4 PD=2.4", 1e-6, tag="psps")
pu, _ = mos("psp103.osdi", "psp103va", "W=1u L=0.1u AS=0.2p AD=0.2p PS=2.4u PD=2.4u", tag="pspu")
check("[8] PSP103 (W, L, PS, PD in m, AS, AD in m^2) likewise", near(ps, pu, 1e-12), f"{ps} / {pu}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
