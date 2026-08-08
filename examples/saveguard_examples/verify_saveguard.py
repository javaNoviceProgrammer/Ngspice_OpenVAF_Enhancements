#!/usr/bin/env python3
"""verify_saveguard.py -- Enhancement-418: three things nobody checked.

[1] AN OPERATOR WHOSE VALUE WAS STRUCTURALLY ZERO. `absdelay()` and
`last_crossing()` are the only two analog operators whose OUTPUT row the compiler
deliberately leaves empty -- OpenVAF emits no residual for it because the
simulator fills that row itself, from its own history buffer, through matrix
elements ngspice allocates during setup. So the output node appeared in no
descriptor Jacobian entry, Enhancement-116 concluded it was structurally
decoupled and tied it to ground, and eval() then read node 0: exactly 0.0,
forever. The delayed value was right only when the model also CONTRIBUTED it
somewhere, because that contribution is what put the node into a Jacobian entry.
Every other operator (ddt, idt, transition, slew, laplace_nd) is a pure function
of existing unknowns and was never affected -- and `transition()` shares the very
same lowering, working only because its output feeds the slew tracking residual.
Enhancement-415 looked for this in the compiler and found the descriptor
byte-identical; nothing was ever wrong in the descriptor.

[2] `.save` NEVER VALIDATED A DEVICE NAME. Nothing between `settrace` and the
PER-POINT read looked one up: `addSpecialDesc` only interns the string, and the
caller of `getSpecial` discards INPaName's E_NODEV/E_BADPARM. A misspelled
device, a bogus parameter or an unexpanded wildcard therefore produced a
registered vector that stayed 0 long, in silence -- while `print`, `meas` and
`wrdata` all report the same name loudly. A hierarchical spelling failed the same
way: `@x1.r1[i]` is what Enhancement-410 made work for `print`, `alter` and
`show`, but the save needed ngspice's flattened `r.x1.r1`.

[3] `meas ... when` INVENTED A TIME. The first "interval" runs from the operating
point to the first timepoint, so it routinely straddles a threshold for reasons
unrelated to the waveform -- which is why the evaluation deliberately starts one
sample in. But the initialisation counted that crossing anyway, and the loop then
applied the leftover count to a LATER, crossing-free interval, dividing by a
difference that was exactly zero or a single ULP. Out came `-inf`,
`1.15292e+05` seconds in a 3 us run, and negative times, with no diagnostic.

[4] AND THE SAME EMPTY ROW BROKE `pz`. Because those rows are filled by the
simulator rather than by the descriptor, every load path has to fill them --
osdiload.c does for dc/tran and osdiacld.c for ac, but osdipzld.c did for
neither. The row was therefore identically zero, the matrix singular at EVERY
trial `s`, and every trial looked like a root, so pz blamed the netlist: "the
input signal is shorted on the way to the output". That predates [1] for a model
that CONTRIBUTES the value (its row was already live), and [1] would have widened
it to every observed-only model. pz cannot stamp the delay exactly the way ac
does -- e^-s*td overflows across pz's own search range and a transport delay has
infinitely many roots -- so it stamps the zero-delay wire and says so.

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
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

checks = passed = 0
TMP = tempfile.gettempdir()


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(name):
    osdi = os.path.join(TMP, f"_{name}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, f"{name}.va"), "-o", osdi],
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        print(r.stdout + r.stderr)
        sys.exit(f"compiling {name}.va failed")
    return osdi


def run(tag, deck, ctrl, osdi=None):
    path = os.path.join(TMP, f"_sg_{tag}.cir")
    pre = f"pre_osdi {osdi}\n" if osdi else ""
    with open(path, "w") as fh:
        fh.write(f"* {tag}\n{deck}\n.control\n{pre}set numdgt=12\n{ctrl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def num(out, expr):
    m = re.search(re.escape(expr) + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m.group(1)) if m else None


def meas_val(out, nm):
    m = re.search(rf"^\s*{re.escape(nm)}\s*=\s*(-?[\d.eE+-]+|-?inf|nan)", out, re.M | re.I)
    return m.group(1) if m else None


def failed(out):
    return any("failed" in ln.lower() for ln in out.splitlines())


def lengths(out):
    """{vector name: length} from `display`."""
    return {n: int(L) for n, L in
            re.findall(r"^\s*(\S+)\s*:\s*\S+,\s*\S+,\s*(\d+)\s+long", out, re.M)}


def main():
    osdi_d = compile_va("sg_delay")
    osdi_2 = compile_va("sg_two")

    # ---------------------------------------------- [1] absdelay / last_crossing
    print("\n    [1] absdelay / last_crossing when the result is only OBSERVED")
    print("        0->1 V ramp, td = 0.1 us, read at t = 1 us, so dv must be 0.9")
    print("        and the 0.5 V crossing must be at 5e-07.")

    DECK = "v1 a 0 pwl(0 0 1u 1)\nn1 a 0 out mm\nro out 0 1k"
    for mod, why in (("sg_obs", "value never used again"),
                     ("sg_cond", "live only in an `if` condition"),
                     ("sg_opvar", "live only via another opvar"),
                     ("sg_contrib", "contributed (the path that always worked)")):
        out = run(mod, DECK + f"\n.model mm {mod}(td=1e-7 thr=0.5)",
                  "tran 10n 1u\nprint @n1[dv]\nprint @n1[lc]", osdi_d)
        dv, lc = num(out, "@n1[dv]"), num(out, "@n1[lc]")
        check(f"{mod}: absdelay reads the delayed value ({why})",
              dv is not None and abs(dv - 0.9) < 1e-6, f"dv={dv}")
        check(f"{mod}: last_crossing reads the crossing time",
              lc is not None and abs(lc - 5e-7) < 1e-9, f"lc={lc}")

    # the node must now exist as a circuit node, which is the actual mechanism
    out = run("nodes", DECK + "\n.model mm sg_obs(td=1e-7 thr=0.5)", "op\ndisplay", osdi_d)
    impl = sorted(set(re.findall(r"(n1#implicit_equation_\d+)", out)))
    check("the absdelay output is a real circuit node, not grounded",
          len(impl) >= 2, f"{impl}")

    # ------------------------------------------------------- [2] .save validation
    print("\n    [2] `.save` now resolves the name, and says so when it cannot")

    TOP = ("v1 a 0 pulse(0 1 1n 1n 1n 1u 2u)\nn1 a 0 mm\n"
           ".model mm sg_two(r=1000 c=1e-9)")
    for extra, label, want_warn in (
            (".save @n1[i_p]", "a valid device+parameter", False),
            (".save @nosuchdev[i]", "a device that does not exist", True),
            (".save @n1[nosuchparam]", "a parameter the device lacks", True),
            (".save @*[i_p]", "an unexpanded wildcard", True)):
        out = run("v" + re.sub(r"\W", "", label)[:8], TOP + "\n" + extra,
                  "tran 2n 200n\ndisplay", osdi_2)
        warned = "Warning: save '" in out
        check(f"{label}: {'warned' if want_warn else 'silent'}",
              warned == want_warn, "warned" if warned else "no warning")

    lens = lengths(run("valid", TOP + "\n.save @n1[i_p]", "tran 2n 200n\ndisplay", osdi_2))
    check("the valid save still yields a full waveform",
          lens.get("@n1[i_p]", 0) > 1, f"{lens.get('@n1[i_p]')} long")

    print("\n        a hierarchical spelling now resolves (Enhancement-410's form)")
    SUB = ("v1 a 0 pulse(0 1 1n 1n 1n 1u 2u)\nx1 a 0 sub\n.subckt sub p q\nn1 p q mm\n.ends\n"
           ".model mm sg_two(r=1000 c=1e-9)")
    lens = lengths(run("hier", SUB + "\n.save @x1.n1[i_p]", "tran 2n 200n\ndisplay", osdi_2))
    check("`.save @x1.n1[i_p]` is a full waveform under the user's own spelling",
          lens.get("@x1.n1[i_p]", 0) > 1, f"{lens.get('@x1.n1[i_p]')} long")
    lens = lengths(run("flat", SUB + "\n.save @n.x1.n1[i_p]", "tran 2n 200n\ndisplay", osdi_2))
    check("the flattened spelling is unchanged",
          lens.get("@n.x1.n1[i_p]", 0) > 1, f"{lens.get('@n.x1.n1[i_p]')} long")

    print("\n        and nothing legitimate is warned about")
    for deck, label in (
            (TOP + "\nr1 a 0 1k\nc1 a 0 1n\nl1 a 0 1m\nd1 a 0 dm\n"
             ".model dm d(is=1e-14)\n.options savecurrents", "savecurrents, mixed deck"),
            (SUB + "\n.options savecurrents", "savecurrents inside a subckt"),
            (TOP + "\n.save @totiter", "a bracket-less simulator statistic"),
            (TOP + "\n.save v(a) i(v1)", "plain node and branch saves")):
        out = run("q" + re.sub(r"\W", "", label)[:8], deck, "tran 2n 200n\ndisplay", osdi_2)
        n = len([ln for ln in out.splitlines() if "Warning: save '" in ln])
        check(f"{label}: no spurious warning", n == 0, f"{n} warnings")

    # ------------------------------------------------------------- [3] meas when
    print("\n    [3] `meas ... when` no longer invents a time")
    print("        The crossing lies in the first interval, which spans the")
    print("        operating point -> first timepoint jump.")

    MD = ("v1 a 0 pwl(0 0 1u 1 2u 1 3u 0)\nn1 a 0 mm\nc1 a 0 1n\nr1 a 0 1k\n"
          ".model mm sg_two(r=1000 c=1e-9)\n.options savecurrents")
    for mm, label in (
            ("meas tran m when @c1[i]=0.5m rise=1", "built-in capacitor, rise=1"),
            ("meas tran m when @n1[i_p]=0.5m rise=1", "OSDI terminal current, rise=1"),
            ("meas tran m trig @c1[i] val=0.5m rise=1 targ @c1[i] val=0.9m rise=1",
             "trig/targ")):
        out = run("m" + re.sub(r"\W", "", label)[:8], MD, f"tran 5n 3u\n{mm}", osdi_2)
        v = meas_val(out, "m")
        inwin = v is not None and v.lower() not in ("inf", "-inf", "nan") \
            and 0.0 <= float(v) <= 3e-6
        check(f"{label}: reports failure or an in-window time, never 1e5 s / -inf",
              failed(out) or inwin, f"m={v}" + (" (failed)" if failed(out) else ""))

    out = run("mcross", MD, "tran 5n 3u\nmeas tran m when @c1[i]=0.5m cross=1", osdi_2)
    v = meas_val(out, "m")
    check("`cross=1` now finds the REAL later crossing instead of garbage",
          v is not None and 0.0 <= float(v) <= 3e-6, f"m={v}")

    print("\n        crossings away from the first interval are untouched")
    MID = "v1 a 0 pwl(0 0 1u 0 2u 1 3u 1)\nc1 a 0 1n\nr1 a 0 1k\n.options savecurrents"
    out = run("mmid", MID, "tran 5n 3u\nmeas tran m when @c1[i]=0.5m rise=1")
    v = meas_val(out, "m")
    check("a mid-run jump still measures at the jump",
          v is not None and abs(float(v) - 1e-6) < 1e-8, f"m={v}")
    out = run("msmooth", MID, "tran 5n 3u\nmeas tran m when v(a)=0.5 rise=1")
    v = meas_val(out, "m")
    check("a smooth crossing is unchanged",
          v is not None and abs(float(v) - 1.5e-6) < 1e-8, f"m={v}")

    # ------------------------------------------------------------------ [4] pz
    print("\n    [4] `pz` on a simulator-stamped row")
    print("        Those rows live in no descriptor Jacobian entry, and pz filled")
    print("        them nowhere -- so the row was identically zero, the matrix was")
    print("        singular at EVERY trial s, every trial looked like a root, and")
    print("        pz blamed the netlist: \"the input signal is shorted on the way")
    print("        to the output\". Two of these three aborted before E-418 too.")

    PZ = ("v1 a 0 dc 0.5 ac 1\nn1 a 0 out mm\nro out 0 1k\nco out 0 1n\n"
          ".model mm {}({})")
    PZC = "op\npz a 0 out 0 cur pol\nprint all"
    for mod, args, want_warn in (("sg_contrib", "td=1e-7 thr=0.5", True),
                                 ("sg_obs", "td=1e-7 thr=0.5", True),
                                 ("sg_cond", "td=1e-7 thr=0.5", True),
                                 ("sg_lcross", "thr=0.5", False)):
        out = run("pz" + mod, PZ.format(mod, args), PZC, osdi_d)
        broke = "shorted on the way" in out or "aborted" in out
        check(f"{mod}: pz completes instead of blaming the netlist", not broke,
              "aborted" if broke else "ran")
        # the delay-free pole is -G/C at `out`; G is 1/ro plus whatever small
        # conductance the module itself contributes there.
        pole = num(out, "all")
        check(f"{mod}: reports the delay-free pole -1/(ro*co)",
              pole is not None and abs(pole + 1e6) / 1e6 < 1e-3, f"pole={pole}")
        n = len([ln for ln in out.splitlines() if "as a ZERO delay" in ln])
        check(f"{mod}: {'warns once' if want_warn else 'does NOT warn'} about the delay",
              n == (1 if want_warn else 0), f"{n} warnings")

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    _check_both_solvers(__file__)
    sys.exit(main())
