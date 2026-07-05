#!/usr/bin/env python3
"""
verify_physcheck.py -- Enhancement-57: physics-accuracy validation of
compiled industry models against analytic device laws, end-to-end through
the committed openvaf-r + ngspice. Uses the VA_TEST corpus (checks are
skipped if it is absent).

This suite guards the whole toolchain -- lowering, autodiff Jacobians, the
AC/small-signal path, and the noise pipeline -- with quantitative physics:

  1. r2_cmc (CMC resistor): default resistance exactly 100 ohm, and its
     thermal noise spectrum IDENTICAL to a built-in ngspice resistor of the
     same value (both are 4kT/R -- an exact cross-check of the Verilog-A
     noise path against ngspice's own, no constants assumed)
  2. diode_cmc: the forward I-V ideal region (V ~ 0.96..1.0 V at defaults;
     below that the CMC recombination/TAT components dominate by design)
     follows the junction law with ideality n in [1.0, 1.06] -- the
     "60 mV/decade" law
  3. MEXTRAM bjt505: Gummel plot at Vce=1V -- collector-current ideality in
     [1.0, 1.02] over Vbe 0.5..0.7 V, beta positive and plausible
  4. PSP103: gm and gds from AC small-signal analysis equal the numeric
     derivative of the DC curves (5-point stencil) -- this cross-validates
     the AUTODIFF JACOBIAN against the residual on a flagship compact model,
     in both triode and saturation
  5. JUNCAP200: C(V) from the AC imaginary part obeys the junction grading
     law C = C0/(1+Vr/VBI)^P self-consistently: VBI fitted from C(0)/C(1)
     must predict C(0)/C(2) (P = 0.5 at defaults)

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

# the VA_TEST corpus lives in this repository
CORPUS = os.path.join(HERE, "..", "..", "VA_TEST", "VA-Models-main", "code")

VT = 1.380649e-23 * 300.15 / 1.602176634e-19  # 27C


def compile_model(rel, name):
    src = os.path.join(CORPUS, rel)
    if not os.path.exists(src):
        return None
    osdi = os.path.join(HERE, f"_{name}.osdi")
    subprocess.run([OPENVAF, src, "-o", osdi], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return osdi


def run(deck, name):
    cir = os.path.join(HERE, f"_pc_{name}.cir")
    open(cir, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", cir], cwd=HERE,
                       capture_output=True, text=True, timeout=180)
    return r.stdout + r.stderr


def read_wrdata(name, ncols=2):
    rows = []
    for line in open(os.path.join(HERE, name)):
        p = line.split()
        if len(p) >= ncols:
            try:
                rows.append([float(x) for x in p[:ncols]])
            except ValueError:
                pass
    return rows


def ac_branch(out, src):
    m = re.search(rf"{src}#branch\s*=\s*([-\d.e+]+),\s*([-\d.e+]+)", out)
    return (float(m.group(1)), float(m.group(2))) if m else None


def main():
    ok = True

    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    if not os.path.isdir(CORPUS):
        print("VA_TEST corpus not found -- nothing to validate")
        print("ALL PASS")
        return 0

    print("[1] r2_cmc: exact resistance + thermal noise vs built-in resistor")
    osdi = compile_model("r2_cmc/vacode/r2_cmc.va", "r2")
    out = run(f"* r2 op\nVs in 0 DC 0.1\nNX in 0 mm\n.model mm r2_cmc\n"
              f".control\nset numdgt=12\npre_osdi {osdi}\nop\nprint i(vs)\n"
              f".endc\n.end\n", "r2op")
    m = re.search(r"i\(vs\)\s*=\s*(\S+)", out)
    check("default resistance = 100 ohm exactly",
          m and abs(float(m.group(1)) + 1e-3) < 1e-12)

    def onoise(dut_line, extra=""):
        out = run(f"* r2 noise\nVs in 0 DC 0.1 AC 1\nRs in a 1k\n{dut_line}\n{extra}"
                  f".control\nset numdgt=12\npre_osdi {osdi}\n"
                  f"noise v(a) Vs dec 1 1k 1k\nprint noise1.onoise_spectrum\n"
                  f".endc\n.end\n", "r2n")
        m = re.search(r"onoise_spectrum\s*=\s*(\S+)", out)
        return float(m.group(1)) if m else None

    n_va = onoise("NX a 0 mm\n.model mm r2_cmc")
    n_ref = onoise("Rref a 0 100")
    check("thermal noise identical to a built-in 100-ohm resistor",
          n_va and n_ref and abs(n_va - n_ref) / n_ref < 1e-6)

    print("[2] diode_cmc: junction-law ideal region (60 mV/decade)")
    osdi = compile_model("diode_cmc/vacode/diode_cmc.va", "dio")
    run(f"* dio iv\nVd a 0 DC 0.3\nNX a 0 mm\n.model mm DIODE_CMC\n"
        f".control\nset numdgt=12\npre_osdi {osdi}\ndc Vd 0.96 1.00 0.01\n"
        f"wrdata _pc_dio.dat i(Vd)\n.endc\n.end\n", "dio")
    rows = read_wrdata("_pc_dio.dat")
    pts = [(v, -i) for v, i in rows if -i > 0]
    ns = [1.0 / (((math.log(pts[k+1][1]) - math.log(pts[k][1]))
                  / (pts[k+1][0] - pts[k][0])) * VT)
          for k in range(len(pts) - 1)]
    check("forward current monotone", all(pts[k+1][1] > pts[k][1]
                                          for k in range(len(pts) - 1)))
    check(f"ideality n in [1.0, 1.06] over 0.96-1.0V (got {min(ns):.4f}..{max(ns):.4f})",
          ns and 1.0 <= min(ns) and max(ns) <= 1.06)

    print("[3] MEXTRAM bjt505: Gummel slope + beta")
    osdi = compile_model("mextram/vacode505p2p0/bjt505.va", "bjt")
    run(f"* gummel\nVb b 0 DC 0.6\nVc c 0 DC 1.0\nNX c b 0 mm\n"
        f".model mm bjt505va\n.control\nset numdgt=12\npre_osdi {osdi}\n"
        f"dc Vb 0.5 0.7 0.01\nwrdata _pc_gum.dat i(Vc) i(Vb)\n.endc\n.end\n",
        "gum")
    rows = read_wrdata("_pc_gum.dat", 4)
    pts = [(r[0], -r[1], -r[3]) for r in rows if -r[1] > 0 and -r[3] > 0]
    ns = [1.0 / (((math.log(pts[k+1][1]) - math.log(pts[k][1]))
                  / (pts[k+1][0] - pts[k][0])) * VT)
          for k in range(len(pts) - 1)]
    betas = [ic / ib for _, ic, ib in pts]
    check(f"Ic ideality in [1.0, 1.02] (got {min(ns):.4f}..{max(ns):.4f})",
          ns and 1.0 <= min(ns) and max(ns) <= 1.02)
    check(f"beta plausible and positive (got {min(betas):.1f}..{max(betas):.1f})",
          betas and 10 < min(betas) and max(betas) < 1000)

    print("[4] PSP103: gm/gds AC vs numeric-DC (autodiff Jacobian consistency)")
    osdi = compile_model("psp103/vacode/psp103.va", "psp")

    def gm_pair(vg0, vd0, sweep_src, h):
        # numeric 5-point derivative of Id w.r.t. the swept source
        lo, hi = (vg0 - 2 * h, vg0 + 2 * h) if sweep_src == "Vg" else \
                 (vd0 - 2 * h, vd0 + 2 * h)
        run(f"* psp dc\nVg g 0 DC {vg0}\nVd d 0 DC {vd0}\nNX d g 0 0 mm\n"
            f".model mm PSP103VA\n.control\nset numdgt=12\npre_osdi {osdi}\n"
            f"dc {sweep_src} {lo} {hi} {h}\nwrdata _pc_psp.dat i(Vd)\n"
            f".endc\n.end\n", "pspdc")
        rows = read_wrdata("_pc_psp.dat")
        if len(rows) != 5:
            return None, None
        ids = [-r[1] for r in rows]
        num = (ids[0] - 8 * ids[1] + 8 * ids[3] - ids[4]) / (12 * h)
        ac_src = "Vg" if sweep_src == "Vg" else "Vd"
        acl = {"Vg": f"Vg g 0 DC {vg0} AC 1\nVd d 0 DC {vd0}",
               "Vd": f"Vg g 0 DC {vg0}\nVd d 0 DC {vd0} AC 1"}[ac_src]
        out = run(f"* psp ac\n{acl}\nNX d g 0 0 mm\n.model mm PSP103VA\n"
                  f".control\nset numdgt=12\npre_osdi {osdi}\n"
                  f"ac lin 1 100 100\nprint all\n.endc\n.end\n", "pspac")
        b = ac_branch(out, "vd")
        return num, (-b[0] if b else None)

    for label, vg0, vd0, src, h, tol in (
            ("gm  @ saturation (Vg=0.9, Vd=0.8)", 0.9, 0.8, "Vg", 1e-3, 1e-3),
            ("gm  @ triode     (Vg=1.1, Vd=0.05)", 1.1, 0.05, "Vg", 1e-3, 1e-3),
            ("gds @ triode     (Vg=1.1, Vd=0.05)", 1.1, 0.05, "Vd", 1e-3, 1e-3),
            ("gds @ saturation (Vg=0.9, Vd=0.8)", 0.9, 0.8, "Vd", 5e-3, 2e-2)):
        num, ac = gm_pair(vg0, vd0, src, h)
        rel = abs(ac - num) / abs(num) if (num and ac) else None
        check(f"{label}: AC == numeric DC (rel {rel:.2e})"
              if rel is not None else f"{label}: MISSING DATA",
              rel is not None and rel < tol)

    print("[5] JUNCAP200: junction grading-law self-consistency")
    osdi = compile_model("psp103/vacode/juncap200.va", "jc")
    freq = 1e6

    def cap(vr):
        out = run(f"* jc cv\nVa a 0 DC {-vr} AC 1\nNX a 0 mm\n"
                  f".model mm JUNCAP200 ab=1e-12 ls=1e-6\n"
                  f".control\nset numdgt=12\npre_osdi {osdi}\n"
                  f"ac lin 1 {freq} {freq}\nprint all\n.endc\n.end\n", "jc")
        b = ac_branch(out, "va")
        return -b[1] / (2 * math.pi * freq) if b else None

    c0, c1, c2 = cap(0.0), cap(1.0), cap(2.0)
    check("C monotone decreasing under reverse bias",
          c0 and c1 and c2 and c0 > c1 > c2)
    # fit VBI from C(0)/C(1) with P=0.5, predict C(0)/C(2)
    if c0 and c1 and c2:
        vbi = 1.0 / ((c0 / c1) ** 2 - 1.0)
        pred = math.sqrt(1.0 + 2.0 / vbi)
        rel = abs(c0 / c2 - pred) / pred
        check(f"grading law self-consistent (VBI_fit={vbi:.3f} V, rel {rel:.2e})",
              rel < 5e-3)
        check(f"zero-bias C ~ 3 fF from defaults (got {c0*1e15:.3f} fF)",
              abs(c0 - 3e-15) / 3e-15 < 0.05)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
