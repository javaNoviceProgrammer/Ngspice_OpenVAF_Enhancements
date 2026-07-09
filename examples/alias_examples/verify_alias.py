#!/usr/bin/env python3
"""
verify_alias.py -- verify Enhancement-12's final system-function group
($simprobe, $analog_node_alias/$analog_port_alias, $test$plusargs/$value$plusargs)
end-to-end through version11's own openvaf-r + ngspice-46.

These functions have no underlying mechanism in the OSDI/ngspice target, so they
return their LRM "mechanism-unavailable" fallbacks (false / 0 / the supplied
default). `alias_demo` calls each and writes the results to `alias_out.txt`,
which this script checks. Runs via a Python subprocess (a bare ngspice heredoc
misbehaves in some shells -- a known project note); stdlib only.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(HERE))  # repo root, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def run():
    subprocess.run([OPENVAF, "alias_demo.va", "-o", "alias_demo.osdi"], cwd=HERE,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deck = ("* alias\nvin p 0 dc 2\nn1 p 0 mm\n.model mm alias_demo(R=1k)\n"
            ".control\npre_osdi alias_demo.osdi\nop\n.endc\n.end\n")
    with open(os.path.join(HERE, "_alias.cir"), "w") as fh:
        fh.write(deck)
    path = os.path.join(HERE, "alias_out.txt")
    if os.path.exists(path):
        os.remove(path)
    subprocess.run([NGSPICE, "-b", "_alias.cir"], cwd=HERE, capture_output=True, text=True)
    if not os.path.exists(path):
        sys.exit("no alias_out.txt produced")
    with open(path) as fh:
        return dict(ln.split("=", 1) for ln in fh.read().splitlines() if "=" in ln)


def check(desc, got, exp, results):
    ok = got == exp
    results.append(ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {desc:22s} got={got!r} expected={exp!r}")


def main():
    fields = run()
    results = []
    print("alias_demo results:")
    check("$test$plusargs", fields.get("test_plusargs"), "0", results)
    check("$value$plusargs", fields.get("value_plusargs"), "0", results)
    check("$analog_node_alias", fields.get("node_alias"), "0", results)
    check("$analog_port_alias", fields.get("port_alias"), "0", results)
    check("$simprobe (no default)", fields.get("simprobe"), "0", results)
    check("$simprobe (default 3.5)", fields.get("simprobe_default"), "3.5", results)

    ok = all(results)
    print(f"\n{'ALL PASS' if ok else 'SOME CHECKS FAILED'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
