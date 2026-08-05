#!/usr/bin/env python3
"""verify_opvarac.py -- Enhancement-412: an OSDI operating-point variable read
after `.ac` or `.noise` reported the small-signal solution, not the bias.

WHAT WENT WRONG. Enhancement-53 fires `@(final_step)` by issuing one dedicated
evaluation per instance once an analysis completes, at `CKTrhsOld`. After a
frequency sweep that vector holds the SMALL-SIGNAL solution at the last swept
frequency -- not a bias point. The evaluation therefore recomputed every opvar
from a complex response and left the result in the instance, so
`print @nd1[gm]` after an `.ac` returned a frequency-dependent number with no
diagnostic of any kind.

THE TELL, and why it is not a rounding argument: the reported "operating point"
CHANGED WITH FREQUENCY -- 1k, 10k and 1meg each gave a different value, and a
multi-point sweep gave the last point's. An operating point cannot depend on
frequency.

WHAT WAS **NOT** WRONG, established before fixing anything: the analyses
themselves. A bias-dependent `white_noise(kf*V^2)` source integrated to
onoise_spectrum = 1.342573180366e-01, matching the DC-bias prediction exactly
and not the ac-bias one (7.21e-02). This was a READBACK defect; the numbers the
analyses produced were always right.

WHY IT COULD NOT SIMPLY BE SKIPPED. That evaluation is the only thing that fires
`@(final_step)`, and `@(final_step("ac"))` and the noise variant are supported
and tested (finalstep_examples). The instance data is therefore snapshotted
around the call and restored: the event bodies still run and their $strobe side
effects stand, while the values the evaluation wrote are discarded -- which is
correct, since those results are deliberately never loaded into the matrix.

WHY A NATURAL TEST MISSES IT: with a purely resistive device the dc and ac
solutions coincide. The device here is reactive on purpose.

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
OSDI = os.path.join(tempfile.gettempdir(), "opvar_ac.osdi")
# rs = 1k, device g0 = 1e-3 (1k) and 1 nF: dc bias solves 1 - 2V - 0 = 0 -> 0.5 V
TRUE = 0.5


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(name, ctrl):
    path = os.path.join(tempfile.gettempdir(), f"oa_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"""* opvarac {name}
v1 a 0 dc 1 ac 1
rs a b 1k
nd1 b 0 mm
.model mm opvar_ac()
.options reltol=1e-10 abstol=1e-16 vntol=1e-14
.control
pre_osdi {OSDI}
set numdgt=10
{ctrl}
.endc
.end
""")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "TEMP =" not in l)


def opvars(out):
    return {k: float(v) for k, v in
            re.findall(r"@nd1\[(vplain|vaffine|vsq|kconst)\]\s*=\s*(-?[\d.eE+-]+)", out)}


PRINT = "print @nd1[vplain] @nd1[vaffine] @nd1[vsq] @nd1[kconst]"


def main():
    print("Enhancement-412: an opvar read after .ac must be the operating point\n")
    r = subprocess.run([OPENVAF, os.path.join(HERE, "opvar_ac.va"), "-o", OSDI],
                       capture_output=True, text=True, timeout=600)
    if not check("opvar_ac.va compiles", r.returncode == 0 and os.path.exists(OSDI),
                 (r.stdout + r.stderr).strip().splitlines()[:1]):
        print(f"\n{passed}/{checks} checks passed")
        return 1

    # the reference: what the bias actually is
    base = opvars(run("op", "op\n" + PRINT))
    check(f"op gives the dc bias {TRUE}", abs(base.get("vplain", -9) - TRUE) < 1e-9,
          f"vplain={base.get('vplain')}")

    print("\n  every analysis must report the SAME operating point")
    ANALYSES = {
        "dc": "dc v1 1 1 1", "tran": "tran 1u 5u",
        "ac 1k": "ac lin 1 1k 1k", "ac 10k": "ac lin 1 10k 10k",
        "ac 1meg": "ac lin 1 1meg 1meg", "ac sweep 3pt": "ac lin 3 1k 100k",
        "noise": "noise v(b) v1 lin 1 10k 10k",
        "op then ac": "op\nac lin 1 100k 100k",
        "tf": "tf v(b) v1", "pz": "pz a 0 b 0 cur pol",
        "disto": "disto dec 2 1k 10k", "sens": "sens v(b)",
    }
    for lab, a in ANALYSES.items():
        got = opvars(run(re.sub(r"\W", "", lab), a + "\n" + PRINT))
        ok = (got and abs(got["vplain"] - TRUE) < 1e-9
              and abs(got["vaffine"] - (3 * TRUE + 1)) < 1e-9
              and abs(got["vsq"] - TRUE * TRUE) < 1e-9
              and got["kconst"] == 42.0)
        check(f"{lab:<14} -> vplain {got.get('vplain')}", ok, "" if ok else str(got))

    print("\n  the tell: the reading must NOT depend on frequency")
    vals = [opvars(run("f" + f, f"ac lin 1 {f} {f}\n" + PRINT))["vplain"]
            for f in ("1k", "10k", "100k", "1meg")]
    check("ac at 1k / 10k / 100k / 1meg all identical", len(set(vals)) == 1, str(vals))

    print("\n  what the fix had to preserve: @(final_step) still fires")
    out = run("fsac", "ac lin 2 1k 10k\n" + PRINT)
    check("@(final_step(\"ac\")) fires", "FS_AC fired" in out)
    check("...exactly once", out.count("FS_AC fired") == 1, f"{out.count('FS_AC fired')}")
    out = run("fsnoise", "noise v(b) v1 lin 2 1k 10k\n" + PRINT)
    check("@(final_step(\"noise\")) fires", "FS_NOISE fired" in out)

    print("\n  and what was never broken: the analyses' own numbers")
    out = run("acnum", "ac lin 1 10k 10k\nprint mag(v(b)) ph(v(b))")
    mag = re.findall(r"mag\(v\(b\)\)\s*=\s*(-?[\d.eE+-]+)", out)
    # |v(b)| = |Z|/|1k+Z| with Y = 1e-3 + jw*1n
    import cmath
    Y = 1e-3 + 1j * 2 * cmath.pi * 1e4 * 1e-9
    want = abs((1 / Y) / (1000 + 1 / Y))
    check(f"ac magnitude still correct ({want:.9f})",
          mag and abs(float(mag[0]) - want) < 1e-7, f"got {mag[:1]}")

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
