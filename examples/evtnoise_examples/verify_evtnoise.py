#!/usr/bin/env python3
"""verify_evtnoise.py -- Enhancement-415: an event the solver stepped over, a
noise total that was the wrong quantity, and one knob counted twice.

[1] A @(timer) EVENT THAT NEVER HAPPENED. `cross`/`above` watch a signal, so a
sign change across an accepted interval is still noticed and the event is only
reported late. A timer watches nothing -- if the solver never stops near the
scheduled instant, the event does not occur at all. Nothing told the simulator
when the next one was due, and a compact model cannot register a breakpoint, so
a 10 ns timer over a 10 us run fired 109 times out of 1000 at a 1 us step: 891
events silently dropped, and a model implementing a clock or a sampled system
ran at whatever rate the step controller happened to pick. The contrast that
identified it: for ngspice's OWN pulse edge at 1 us the nearest timepoint is
exactly 0 away; for the OSDI timer it was 5.6e-08 away -- no breakpoint at all.

The fix needs no ABI change. `lower_timer` already computes the next event time,
and Enhancement-24's `$bound_step` channel already reaches `osditrunc.c`, so the
model now asks for at most `next_event - now`. It is combined with `min`, never
an overwrite, so a model's own `$bound_step` and a second timer both still hold;
a one-shot that has already fired has a pending time of INFINITY and changes
nothing.

[2] A NOISE TOTAL THAT WAS THE WRONG QUANTITY. Each of the NSTATVARS noise state
variables needs one slot per source PLUS one for the whole-device total, and the
registry allocates exactly that -- but the indexing macro used the source count
alone as its stride. With n sources, nVar(OUTNOIZ, n) and nVar(INNOIZ, 0) are
then the same address, so `onoise_total_<dev>` came out bit-identical to
`inoise_total_<dev>_<first source>`. Built-in devices were always self-consistent.
THE SPECTRA AND THE GRAND TOTALS WERE NEVER AFFECTED, which is why this survived:
`onoise_spectrum` matched two real resistors to 9e-08 relative.

[3] ONE KNOB COUNTED TWICE. `m` is registered as an alias of `$mfactor` with the
same parameter id, so `sens` listed both `<inst>_m` and `<inst>__mfactor` with
identical sensitivities. Flagged IF_REDUNDANT, the marking built-in devices give
their alias keywords.

Exit code 0 = pass.
"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
TMP = tempfile.gettempdir()


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def build(name):
    osdi = os.path.join(TMP, f"e415_{name}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, f"{name}.va"), "-o", osdi],
                       capture_output=True, text=True, timeout=600)
    return (r.returncode == 0 and os.path.exists(osdi)), osdi, (r.stdout + r.stderr)


def run(name, deck, ctrl, osdi, timeout=300):
    path = os.path.join(TMP, f"e415_{name}.cir")
    with open(path, "w") as fh:
        fh.write(f"* e415 {name}\n{deck}\n.control\npre_osdi {osdi}\nset numdgt=12\n"
                 f"{ctrl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=timeout)
    return "\n".join(l for l in (r.stdout + r.stderr).splitlines() if "TEMP =" not in l)


def _bin_subdir_name():
    import platform
    m = platform.machine().lower()
    if platform.system() == "Darwin":
        return os.path.join("macos", "apple-silicon" if m in ("arm64", "aarch64") else "intel")
    if platform.system() == "Windows":
        return os.path.join("windows", "intel")
    return os.path.join("linux", "arm" if m in ("arm64", "aarch64") else "intel")


def num(out, expr):
    m = re.findall(re.escape(expr) + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m[0]) if m else None


def totals(out):
    return {m.group(1): float(m.group(2)) for m in
            (re.match(r"\s*((?:in|on)oise_total\S*)\s*=\s*(-?[\d.eE+-]+)", l)
             for l in out.splitlines()) if m}


def main():
    print("Enhancement-415: a stepped-over event, a mis-strided noise total, "
          "a double-counted knob\n")

    # ---------------------------------------------------------------- [1] timer
    print("  a @(timer) must fire every time it is due, whatever the step")
    ok, osdi, log = build("evt_timer")
    if not check("evt_timer.va compiles", ok, "; ".join(log.strip().splitlines()[:1])):
        print(f"\n{passed}/{checks} checks passed")
        return 1
    DECK = "v1 a 0 dc 1\nn1 a 0 mm\n.model mm evt_timer({p})"
    # 10 ns period from 1 ns over 10 us == 1000 events; a DC source forces no steps
    for step in ("1u", "0.1u", "10n"):
        out = run(f"t{step}", DECK.format(p=""), f"tran {step} 10u\nprint @n1[n]", osdi)
        n = num(out, "@n1[n]")
        check(f"1000 events at tran step {step}", n == 1000, f"got {n}")

    print("\n  the step bound is combined with min, so other demands still hold")
    out = run("tb", DECK.format(p="bstep=5e-9"),
              "tran 1u 10u\nprint @n1[n]\nprint length(v(a))", osdi)
    n, pts = num(out, "@n1[n]"), num(out, "length(v(a))")
    check("a model's own $bound_step(5ns) survives beside the timer",
          n == 1000 and pts is not None and pts > 1900, f"n={n} timepoints={pts}")
    out = run("tone", DECK.format(p="period=1e30"),
              "tran 1u 10u\nprint @n1[n]\nprint length(v(a))", osdi)
    check("a one-shot timer does not pin the step for the rest of the run",
          num(out, "@n1[n]") == 1 and (num(out, "length(v(a))") or 1e9) < 400,
          f"n={num(out,'@n1[n]')} timepoints={num(out,'length(v(a))')}")

    # ---------------------------------------------------------------- [2] noise
    print("\n  a device's noise total must be the sum of its OWN sources")
    ok, osdi_n, log = build("evt_noise")
    check("evt_noise.va compiles", ok, "; ".join(log.strip().splitlines()[:1]))
    NZ = "v1 in 0 dc 0 ac 1\nr1 in a 1k\nn1 a 0 mm\n.model mm evt_noise()"
    g = totals(run("nz", NZ, "noise v(a) v1 lin 9 1k 100k 1\nprint all", osdi_n))
    for side in ("onoise", "inoise"):
        tot = g.get(f"{side}_total_n1")
        quad = math.hypot(g.get(f"{side}_total_n1_big", 0.0),
                          g.get(f"{side}_total_n1_small", 0.0))
        check(f"{side}_total_n1 == quadrature of its two sources",
              tot is not None and abs(tot - quad) <= 1e-9 * max(tot, quad),
              f"{tot:.9e} vs {quad:.9e}")
    check("the device's OUT total is no longer the first source's IN total",
          g.get("onoise_total_n1") != g.get("inoise_total_n1_big"),
          f"{g.get('onoise_total_n1'):.9e}")
    check("a built-in resistor in the same deck stays self-consistent",
          abs(g.get("onoise_total_r1", 0.0) - g.get("onoise_total_r1_thermal", 0.0)) < 1e-18)

    print("\n  and the spectrum itself is unchanged -- it was never wrong")
    # The summary indexing is all that moved, so the SPECTRUM must be bit-identical
    # to the pre-415 binary on the very same deck. Compared against the shipped
    # binary rather than against a hand-derived value, because that is the claim:
    # the analysis results were never affected, only the summary rollup.
    # ONE frequency point: a multi-row print renders a TABLE, not `name = value`
    SPEC = "noise v(a) v1 lin 1 10k 10k\nprint onoise_spectrum\nprint inoise_spectrum"
    fixed_o = num(run("sf", NZ, SPEC, osdi_n), "onoise_spectrum")
    fixed_i = num(run("sf", NZ, SPEC, osdi_n), "inoise_spectrum")
    prev = os.path.join(os.path.dirname(os.path.dirname(HERE)), "bin", _bin_subdir_name(), "ngspice")
    if os.path.exists(prev):
        path = os.path.join(TMP, "e415_spec_prev.cir")
        with open(path, "w") as fh:
            fh.write(f"* e415 prev\n{NZ}\n.control\npre_osdi {osdi_n}\nset numdgt=12\n"
                     f"{SPEC}\n.endc\n.end\n")
        r = subprocess.run([prev, "-b", path], capture_output=True, text=True, timeout=300)
        out_prev = r.stdout + r.stderr
        po, pi = num(out_prev, "onoise_spectrum"), num(out_prev, "inoise_spectrum")
        check("onoise_spectrum identical to the pre-415 binary",
              po is not None and fixed_o == po, f"{fixed_o} vs {po}")
        check("inoise_spectrum identical to the pre-415 binary",
              pi is not None and fixed_i == pi, f"{fixed_i} vs {pi}")
    else:
        check("a spectrum value is produced", fixed_o is not None, f"{fixed_o}")

    # ----------------------------------------------------------------- [3] sens
    print("\n  the instance multiplier is one knob, not two")
    ok, osdi_m, log = build("evt_mult")
    check("evt_mult.va compiles", ok, "; ".join(log.strip().splitlines()[:1]))
    SD = "vd dd 0 dc 2\nrload dd d 1k\nn1 d 0 mm\n.model mm evt_mult()"
    out = run("sens", SD, "op\nsens v(d)\nprint all", osdi_m)
    knobs = [m.group(1) for m in
             (re.match(r"\s*(n1[:_]\S*)\s*=", l) for l in out.splitlines()) if m]
    check("sens lists the multiplier exactly once",
          sum(1 for k in knobs if k in ("n1_m", "n1__mfactor")) == 1, str(sorted(knobs)))

    print("\n  ...and it is still settable by every route")
    base = num(run("m1", SD, "op\nprint i(vd)", osdi_m), "i(vd)")
    inst = num(run("m2", "vd dd 0 dc 2\nrload dd d 1k\nn1 d 0 mm m=3\n.model mm evt_mult()",
                   "op\nprint i(vd)", osdi_m), "i(vd)")
    alt = re.findall(r"i\(vd\)\s*=\s*(-?[\d.eE+-]+)",
                     run("m3", SD, "op\nprint i(vd)\nalter @n1[m]=3\nop\nprint i(vd)", osdi_m))
    check("m=3 on the instance line changes the current", inst != base, f"{base} -> {inst}")
    check("alter @n1[m]=3 gives the identical answer",
          len(alt) > 1 and abs(float(alt[1]) - inst) < 1e-15, f"alter -> {alt[1:2]}")
    check("@n1[m] still reads back", num(run("m4", SD, "op\nprint @n1[m]", osdi_m),
                                         "@n1[m]") == 1.0)

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
