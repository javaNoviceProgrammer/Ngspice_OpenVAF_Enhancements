#!/usr/bin/env python3
"""
verify_noisecorr.py -- verifies Enhancement-42 correlated (same-named) noise
sources, end-to-end through the committed openvaf-r + ngspice.

Per Verilog-AMS LRM 4.6.4 noise functions with the SAME name argument are the
SAME source: perfectly correlated, so their contributions to the output sum as
complex AMPLITUDES, |sum_k f_k*sqrt(pwr_k)*T_k|^2, instead of as powers,
sum_k f_k^2*pwr_k*|T_k|^2. Before E-42 the name was used only for labelling the
per-source output vectors -- every source was treated as independent, and even
a NEGATED contribution of the same source added power instead of cancelling.

Two-sided fix:
  * OpenVAF (osdi/load.rs): the contribution factor is folded into the loaded
    power as fac*|fac| instead of fac^2 -- same magnitude, but the power now
    CARRIES THE FACTOR'S SIGN (plus a missing llvm.fabs.f64 intrinsic
    registration in mir_llvm).
  * ngspice (osdi/osdinoise.c): same-named sources within one instance are
    grouped; each group's signed amplitudes sum coherently against the complex
    transfer (CKTrhs/CKTirhs adjoint solution) before squaring. Uniquely-named
    sources reduce exactly to the classic |pwr|*|T|^2. The group total is
    reported on the group's first per-source vector; members report 0.

All checks drive PSD 1e-12 sources through a unity-transfer series chain, so
sqrt-PSD amplitudes are 1e-6 V/sqrt(Hz) each:

  1. same name twice           -> onoise = 2e-6      (power-sum reads 1.414e-6)
  2. distinct names            -> onoise = 1.414e-6  (independent, unchanged)
  3. same name, one negated    -> onoise = 0         (anti-phase cancellation)
  4. factors 2x + 1x same name -> onoise = 3e-6      (amplitude-weighted)
  5. two INSTANCES, same name  -> onoise = 2.828e-6  (instances stay independent)
  6. white + flicker same name -> onoise = 2e-6 at 1 Hz (kind-agnostic grouping)
  7. per-source vectors: device total on the group's first source, 0 on members

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE


def run(deck, *names):
    with open(os.path.join(HERE, "_n.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_n.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                vals[nm] = float(line.split("=", 1)[1].strip())
    return vals


def noise_deck(model, freq="1k", extra_ctrl="", instances=None):
    instances = instances or ["NDUT out 0 nm"]
    return ("* E-42 noise correlation\n" + "\n".join(instances) + "\n"
            "R1 out 0 1G\nVin in 0 DC 0 AC 1\nR2 in 0 1k\n"
            f".model nm {model}\n"
            ".control\npre_osdi noisecorr_demo.osdi\n"
            f"noise v(out) vin lin 1 {freq} {freq} 1\n"
            "setplot noise1\nprint all\n"
            f"{extra_ctrl}.endc\n.end\n")


def main():
    subprocess.run([OPENVAF, "noisecorr_demo.va", "-o", "noisecorr_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=1e-9):
        nonlocal ok
        good = abs(got - want) < tol
        ok = ok and good
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {got:.6e}, want {want:.6e}")

    print("[1] same-named pair: amplitudes add coherently (was power-summed)")
    v = run(noise_deck("ncorr"), "onoise_spectrum")
    check("onoise = 2e-6", v["onoise_spectrum"], 2e-6, 1e-12)

    print("[2] distinct names stay independent (classic power sum, unchanged)")
    v = run(noise_deck("nuncorr"), "onoise_spectrum")
    check("onoise = sqrt(2)*1e-6", v["onoise_spectrum"], 2**0.5 * 1e-6, 1e-12)

    print("[3] same name, one contribution negated: anti-phase CANCELLATION")
    v = run(noise_deck("nanti"), "onoise_spectrum")
    check("onoise = 0", v["onoise_spectrum"], 0.0, 1e-12)

    print("[4] scaled factors weight the amplitudes linearly: |2 + 1|*1e-6")
    v = run(noise_deck("nscale"), "onoise_spectrum")
    check("onoise = 3e-6", v["onoise_spectrum"], 3e-6, 1e-12)

    print("[5] same name in two INSTANCES: correlation never crosses instances")
    v = run(noise_deck("ncorr", instances=["NDUT1 out mid nm", "NDUT2 mid 0 nm"]),
            "onoise_spectrum")
    check("onoise = sqrt(8e-12)", v["onoise_spectrum"], 8e-12**0.5, 1e-12)

    print("[6] white_noise + flicker_noise under ONE name group across kinds")
    v = run(noise_deck("nmix", freq="1"), "onoise_spectrum")
    check("onoise = 2e-6 at 1 Hz", v["onoise_spectrum"], 2e-6, 1e-12)

    print("[7] per-source vectors: group total on first source, 0 on members")
    v = run(noise_deck("ncorr"), "onoise_ndut", "onoise_spectrum")
    check("onoise_ndut (device total) = 2e-6 density",
          v["onoise_ndut"], 2e-6, 1e-12)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
