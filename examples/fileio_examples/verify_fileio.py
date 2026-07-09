#!/usr/bin/env python3
"""
verify_fileio.py -- verify Enhancement-11's file-output system functions
($fopen/$fdisplay/$fwrite/$fstrobe/$ftell/$fflush/$fclose and $rewind/$fseek)
end-to-end through version11's own openvaf-r + ngspice-46.

`fileio_demo` writes a parameter-derived characterization report (its
parameters and a computed I = V/R table) to `fileio_out.txt` at initialization;
we run a `.op` and check every line against the closed-form values, exercising
the %g/%d/%h/%s format specifiers, the newline-less $fwrite, and $ftell.

`fileio_seek` separately checks $rewind and $fseek by overwriting parts of a
file in place.

Everything runs via a Python subprocess (a bare ngspice heredoc misbehaves in
some shells -- a known project note); no dependencies beyond the stdlib.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

R, NPTS, VMAX = 1000.0, 5, 2.0


def compile_va(name):
    subprocess.run([OPENVAF, f"{name}.va", "-o", f"{name}.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_op(osdi, model_line, outfile):
    deck = (f"* fileio\nvin p 0 dc 2\nn1 p 0 mm\n{model_line}\n"
            f".control\npre_osdi {osdi}\nop\n.endc\n.end\n")
    with open(os.path.join(HERE, "_fio.cir"), "w") as fh:
        fh.write(deck)
    if os.path.exists(os.path.join(HERE, outfile)):
        os.remove(os.path.join(HERE, outfile))
    subprocess.run([NGSPICE, "-b", "_fio.cir"], cwd=HERE,
                   capture_output=True, text=True)
    path = os.path.join(HERE, outfile)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return fh.read()


def check(desc, cond, results):
    results.append(bool(cond))
    print(f"    {'PASS' if cond else 'FAIL'}  {desc}")


def fnum(x):
    # ngspice %g formatting -> float
    return float(x)


def main():
    results = []

    # ---- fileio_demo: characterization report ---------------------------
    print("fileio_demo (report + I-V table):")
    compile_va("fileio_demo")
    text = run_op("fileio_demo.osdi",
                  f".model mm fileio_demo(R={R:g} npts={NPTS} vmax={VMAX:g})",
                  "fileio_out.txt")
    if text is None:
        print("    FAIL  no fileio_out.txt produced")
        sys.exit(1)
    lines = text.splitlines()
    print("    ---- file contents ----")
    for ln in lines:
        print(f"      {ln}")
    print("    -----------------------")

    check("header line", lines[0] == "# fileio_demo characterization report",
          results)
    check("R (%g)", lines[1] == f"R = {R:g} ohm", results)
    check("G = 1/R (%g)", lines[2] == f"G = {1.0 / R:g} S", results)
    check("npts %d / %h / %s", lines[3] == f"npts={NPTS}  npts_hex={NPTS:x}  label=IV",
          results)
    check("table header", lines[4] == "# V[V]\tI[A]", results)

    # I-V table rows
    table_ok = True
    for k in range(NPTS):
        v = (VMAX * k) / (NPTS - 1)
        cols = lines[5 + k].split("\t")
        got_v, got_i = fnum(cols[0]), fnum(cols[1])
        row_ok = abs(got_v - v) < 1e-9 and abs(got_i - v / R) < 1e-12
        table_ok &= row_ok
    check(f"I=V/R table ({NPTS} rows)", table_ok, results)

    # $fwrite fragment join: "checksum=<R*npts>"
    csum_line = lines[5 + NPTS]
    check("$fwrite fragments joined (checksum)",
          csum_line == f"checksum={R * NPTS:g}", results)

    # $ftell byte offset == number of bytes written before that line
    tell_line = lines[6 + NPTS]
    prefix_len = len("\n".join(lines[:6 + NPTS])) + 1  # +1 for the trailing \n
    reported = int(tell_line.split("=")[1])
    check(f"$ftell offset ({reported} == {prefix_len} bytes written)",
          reported == prefix_len, results)

    # ---- fileio_seek: $rewind / $fseek ----------------------------------
    print("\nfileio_seek ($rewind + $fseek overwrite):")
    compile_va("fileio_seek")
    seek_text = run_op("fileio_seek.osdi", ".model mm fileio_seek(R=1k)",
                       "seek_out.txt")
    print(f"    seek_out.txt = {seek_text!r}")
    check("rewind+fseek overwrite -> 'XY234**789'", seek_text == "XY234**789",
          results)

    ok = all(results)
    print(f"\n{'ALL PASS' if ok else 'SOME CHECKS FAILED'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
