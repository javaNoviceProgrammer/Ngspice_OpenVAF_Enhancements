#!/usr/bin/env python3
"""
verify_tempphys.py -- Enhancement-80: TEMPERATURE physics validation,
end-to-end through the committed openvaf-r + ngspice. Physcheck round 3:
E-57 validated the static laws, E-75 the charges -- this suite validates
the THERMAL axis: `$temperature`/`$vt` plumbing, the OSDI instance
temperature offset, and the classic junction/MOS temperature laws on
flagship corpus models. Uses the VA_TEST corpus (corpus checks skip
gracefully without it).

  [1] $vt tracks the simulator temperature: a module contributing V=$vt,
      swept with `.dc temp -50..150`, equals kT/q at every point to the
      compiler's constants (< 1e-6; the ~1e-7 residual is the documented
      E-59 CODATA vintage gap).
  [2] the OSDI instance temperature offset: `dtemp=10` at temp=17 gives
      the identical current (12 digits) to a plain instance at temp=27 --
      pinning both the OsdiExtraInstData dt plumbing and THE FIX: OSDI
      instances used to accept only the unconventional spelling `dt`;
      `dtemp` (every built-in device's spelling) is now an alias.
  [3] thermal noise is proportional to T: the nres 4kT/R twin's output
      noise POWER ratio between 127C and 27C equals T2/T1 exactly
      (ngspice spectra are amplitude densities -- square them), and the
      OSDI/built-in identity holds at the hot temperature too.
  [4] MEXTRAM 505 junction laws: dVbe/dT at 1 mA sits in the textbook
      -1..-2.5 mV/K window across -25..125C, and the Arrhenius activation
      energy extracted from Ic(T) at fixed Vbe is pair-consistent (< 5%)
      with an Eg estimate in the silicon range;
  [5] PSP103 has a zero-temperature-coefficient point: dId/dT > 0 in weak
      inversion (Vth drop wins) and < 0 in strong inversion (mobility
      wins) -- the sign flip that makes ZTC biasing possible.
  [6] the diode_cmc DEFAULT card's near-zero activation energy is pinned
      as documentation of the CMC default-off idiom (E-56): corpus
      defaults are placeholders, not silicon.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
CORPUS = os.path.join(HERE, "..", "..", "VA_TEST", "VA-Models-main", "code")

K_OVER_Q = 1.380649e-23 / 1.602176634e-19
K_EV = 8.617333262e-5

checks = []


def check(label, cond):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def compile_model(rel, name):
    src = os.path.join(CORPUS, rel)
    if not os.path.exists(src):
        return None
    subprocess.run([OPENVAF, os.path.relpath(src, HERE), "-o", f"_{name}.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"_{name}.osdi"


def compile_local(name):
    subprocess.run([OPENVAF, f"{name}.va", "-o", f"{name}.osdi"], cwd=HERE,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"{name}.osdi"


def run(deck, name):
    open(os.path.join(HERE, f"_tp_{name}.cir"), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", f"_tp_{name}.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=180)
    return r.stdout + r.stderr


def scalar(out, expr):
    m = re.search(rf"{re.escape(expr)}\s*=\s*([-\d.e+]+)", out)
    return float(m.group(1)) if m else None


def main():
    print("[1] $vt == kT/q across the temp sweep")
    vt = compile_local("vtprobe")
    run(f"* vt law\nnx p 0 mm\n.model mm vtprobe\n.control\nset numdgt=12\n"
        f"pre_osdi {vt}\ndc temp -50 150 10\nwrdata _tp_vt.txt v(p)\n"
        f".endc\n.end\n", "vt")
    worst = 0.0
    npts = 0
    for line in open(os.path.join(HERE, "_tp_vt.txt")):
        p = line.split()
        if len(p) >= 2:
            t, v = float(p[0]), float(p[1])
            worst = max(worst, abs(v - K_OVER_Q * (t + 273.15)) / v)
            npts += 1
    check(f"$vt = kT/q at all {npts} points (worst rel {worst:.2e} < 1e-6; "
          f"residual = the E-59 constants vintage)", npts >= 20 and worst < 1e-6)

    print("[3] thermal noise proportional to T (nres 4kT/R twin)")
    nres = compile_local("nres")

    def onoise(dut, osdi, tempc):
        out = run(f"* nz\nVs in 0 DC 0 AC 1\nRs in a 1k\n{dut}\n"
                  f".option temp={tempc}\n.control\nset numdgt=12\n"
                  f"{'pre_osdi ' + osdi if osdi else ''}\n"
                  f"noise v(a) Vs dec 1 1k 1k\nprint noise1.onoise_spectrum\n"
                  f".endc\n.end\n", "nz")
        return scalar(out, "onoise_spectrum")

    n27 = onoise("NX a 0 mm\n.model mm nres(r=1k)", nres, 27)
    n127 = onoise("NX a 0 mm\n.model mm nres(r=1k)", nres, 127)
    nb127 = onoise("Rb a 0 1k", None, 127)
    power_ratio = (n127 / n27) ** 2
    expect = (127 + 273.15) / (27 + 273.15)
    check(f"noise power ratio (127C/27C) = T2/T1 "
          f"(got {power_ratio:.6f} vs {expect:.6f}, rel "
          f"{abs(power_ratio-expect)/expect:.2e} < 1e-4)",
          abs(power_ratio - expect) / expect < 1e-4)
    check(f"OSDI == built-in resistor noise at 127C (rel "
          f"{abs(n127-nb127)/nb127:.2e} < 1e-5)",
          abs(n127 - nb127) / nb127 < 1e-5)

    if not os.path.isdir(CORPUS):
        print("[2][4][5][6] SKIP: VA_TEST corpus not found")
        print()
        print("ALL PASS" if all(checks) else "SOME CHECKS FAILED")
        return 0 if all(checks) else 1

    print("[2] OSDI instance temperature offset: dtemp == temp shift")
    dio = compile_model("diode_cmc/vacode/diode_cmc.va", "dio")

    def dio_i(tempc, inst_extra=""):
        out = run(f"* dtemp\nvd a 0 dc 0.7\nnx a 0 mm {inst_extra}\n"
                  f".model mm DIODE_CMC\n.option temp={tempc}\n"
                  f".control\nset numdgt=12\npre_osdi {dio}\nop\nprint i(vd)\n"
                  f".endc\n.end\n", "dt")
        return scalar(out, "i(vd)")

    i_plain = dio_i(27)
    i_dtemp = dio_i(17, "dtemp=10")
    i_dt = dio_i(17, "dt=10")
    check(f"dtemp=10 @ 17C == plain @ 27C (rel {abs(i_dtemp-i_plain)/abs(i_plain):.2e})",
          i_dtemp is not None and abs(i_dtemp - i_plain) / abs(i_plain) < 1e-10)
    check("the historic `dt` spelling still works too",
          i_dt is not None and abs(i_dt - i_plain) / abs(i_plain) < 1e-10)

    print("[4] MEXTRAM 505: dVbe/dT and Arrhenius activation energy")
    bjt = compile_model("mextram/vacode505p2p0/bjt505.va", "bjt")

    def vbe_at(tempc):
        out = run(f"* vbe\nib 0 b dc 1m\nVc c 0 DC 1.0\nNX c b 0 mm\n"
                  f".model mm bjt505va\n.option temp={tempc}\n"
                  f".control\nset numdgt=12\npre_osdi {bjt}\nop\nprint v(b)\n"
                  f".endc\n.end\n", "vbe")
        return scalar(out, "v(b)")

    vbes = {t: vbe_at(t) for t in (-25, 25, 75, 125)}
    slopes = [(vbes[b] - vbes[a]) / (b - a) * 1e3
              for a, b in ((-25, 25), (25, 75), (75, 125))]
    check(f"dVbe/dT at 1 mA in [-2.5, -1.0] mV/K over -25..125C "
          f"(got {min(slopes):.2f}..{max(slopes):.2f})",
          all(-2.5 <= s <= -1.0 for s in slopes))

    def ic_at(tempc):
        out = run(f"* gum\nVb b 0 DC 0.6\nVc c 0 DC 1.0\nNX c b 0 mm\n"
                  f".model mm bjt505va\n.option temp={tempc}\n"
                  f".control\nset numdgt=12\npre_osdi {bjt}\nop\nprint i(vc)\n"
                  f".endc\n.end\n", "gum")
        return -scalar(out, "i(vc)")

    ics = {t: ic_at(t) for t in (27, 77, 127)}

    def ea(t1, t2):
        T1, T2 = t1 + 273.15, t2 + 273.15
        return K_EV * math.log(ics[t2] / ics[t1]) / (1 / T1 - 1 / T2)

    e1, e2 = ea(27, 77), ea(77, 127)
    eg1, eg2 = e1 + 0.6, e2 + 0.6  # Ea_eff ~ Eg - q*Vbe at n ~ 1
    check(f"Arrhenius pairs consistent (Ea_eff {e1:.3f}/{e2:.3f} eV, "
          f"{abs(e1-e2)/abs(e1)*100:.1f}% < 5%)", abs(e1 - e2) / abs(e1) < 0.05)
    check(f"Eg estimate in the silicon range (got {eg1:.2f}/{eg2:.2f} eV in [1.0, 1.4])",
          1.0 <= eg1 <= 1.4 and 1.0 <= eg2 <= 1.4)

    print("[5] PSP103: zero-temperature-coefficient sign flip")
    psp = compile_model("psp103/vacode/psp103.va", "psp")

    def id_at(tempc, vg):
        out = run(f"* ztc\nVg g 0 DC {vg}\nVd d 0 DC 0.8\nNX d g 0 0 mm\n"
                  f".model mm PSP103VA\n.option temp={tempc}\n"
                  f".control\nset numdgt=12\npre_osdi {psp}\nop\nprint i(vd)\n"
                  f".endc\n.end\n", "ztc")
        return -scalar(out, "i(vd)")

    d_weak = id_at(75, 0.35) - id_at(0, 0.35)
    d_strong = id_at(75, 1.1) - id_at(0, 1.1)
    check(f"weak inversion warms up (dId/dT > 0: {d_weak:+.2e} A)", d_weak > 0)
    check(f"strong inversion slows down (dId/dT < 0: {d_strong:+.2e} A)",
          d_strong < 0)

    print("[6] diode_cmc defaults: the CMC default-off idiom, pinned")
    vfs = {t: None for t in (25, 125)}
    for t in vfs:
        out = run(f"* vf\nib 0 a dc 1m\nnx a 0 mm\n.model mm DIODE_CMC\n"
                  f".option temp={t}\n.control\nset numdgt=12\npre_osdi {dio}\n"
                  f"op\nprint v(a)\n.endc\n.end\n", "vf")
        vfs[t] = scalar(out, "v(a)")
    slope = (vfs[125] - vfs[25]) / 100 * 1e3
    check(f"default-card dVf/dT is NOT textbook silicon "
          f"(|{slope:.2f}| mV/K < 0.5 -- defaults are placeholders, not "
          f"devices; see E-56)", abs(slope) < 0.5)

    n_pass = sum(checks)
    n_fail = len(checks) - n_pass
    print()
    print(("ALL PASS" if n_fail == 0 else "FAILURES")
          + f": {n_pass} passed, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
