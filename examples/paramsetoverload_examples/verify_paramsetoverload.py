#!/usr/bin/env python3
"""
verify_paramsetoverload.py -- paramset overloading per LRM 6.4.2 (Enhancement-565,
from the 2026-09-05 book audit), end-to-end through the committed openvaf-r +
ngspice, on the LRM's own four-`nch` example (a conductance stand-in for nmos3;
the member selected is visible in the current and in `uu`):

  1. instances inside a module: m1 (`mm=1`) takes the mismatch paramset, m3
     (`l=1u, w=10u`) the default one (the mismatch member's `mm` default is
     outside its range, the long-channel member has two un-overridden
     parameters), m4 (`l=3u, ad, as`) the long-channel one -- the clause's
     worked example, exactly
  2. `.model` cards: the same selections from the card's parameters; a card
     naming a member directly (`nch__4`) is taken as written; the resolution
     is announced
  3. the refusals: a parameter no member declares; a value outside every
     member's range; two members that apply equally (ambiguous), on both routes

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def compile_va(src, dst):
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, dst)],
                       cwd=HERE, capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(os.path.join(HERE, dst)), \
        (r.stdout + r.stderr)


def refused(src, needle):
    r = subprocess.run([OPENVAF, os.path.join("refused", src)],
                       cwd=HERE, capture_output=True, text=True)
    log = r.stdout + r.stderr
    return r.returncode != 0 and needle in log, log


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def values(out, names):
    vals = {}
    for line in out.splitlines():
        s = line.strip()
        for n in names:
            if s.lower().startswith(n.lower() + " "):
                try:
                    vals[n] = float(s.split("=", 1)[1])
                except ValueError:
                    pass
    return vals


def card(model_card, prints=("i(vd)", "@n1[uu]")):
    deck = ("* paramsetoverload\nvd d 0 dc 1\nn1 d 0 0 0 dm\n"
            f".model dm {model_card}\n.control\npre_osdi nch_ps.osdi\nop\n"
            f"print {' '.join(prints)}\n.endc\n.end\n")
    out = ngspice(deck)
    return values(out, prints), out


def close(a, b, rel=2e-5):   # ngspice prints six significant digits
    return a is not None and abs(a - b) <= rel * max(1e-30, abs(b))


# I = kp (w/l) (u0/650) (nfs/0.8e12) at 1 V
def cur(l, w, u0, nfs=0.8e12):
    return 5e-5 * (w / l) * (u0 / 650.0) * (nfs / 0.8e12)


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[0] the four-member family compiles: nch, nch__2, nch__3, nch__4")
    built, log = compile_va("nch_ps.va", "nch_ps.osdi")
    check("openvaf-r nch_ps.va", built, "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[1] the LRM's instances inside a module: m1 mismatch, m3 default, m4 long-channel")
    deck = ("* paramsetoverload\nv1 d1 0 dc 1\nv3 d3 0 dc 1\nv4 d4 0 dc 1\nn1 d1 d3 d4 0 dm\n"
            ".model dm top\n.control\npre_osdi nch_ps.osdi\nop\n"
            "print i(v1) i(v3) i(v4) @n1[m1__uu] @n1[m3__uu] @n1[m4__uu]\n.endc\n.end\n")
    out = ngspice(deck)
    v = values(out, ["i(v1)", "i(v3)", "i(v4)", "@n1[m1__uu]", "@n1[m3__uu]", "@n1[m4__uu]"])
    check("m1 (.l(1u), .w(5u), .mm(1)) -> mismatch: u0 = 600",
          close(v.get("@n1[m1__uu]"), 600.0) and close(v.get("i(v1)"), -cur(1e-6, 5e-6, 600.0)), f"{v}")
    check("m3 (.l(1u), .w(10u)) -> default: u0 = 650",
          close(v.get("@n1[m3__uu]"), 650.0) and close(v.get("i(v3)"), -cur(1e-6, 10e-6, 650.0)), f"{v}")
    check("m4 (.l(3u), .w(5u), .ad(1.2p), .as(1.3p)) -> long-channel: u0 = 640, nfs = 0.7e12",
          close(v.get("@n1[m4__uu]"), 640.0) and close(v.get("i(v4)"), -cur(3e-6, 5e-6, 640.0, 0.7e12)), f"{v}")

    print("[2] the same selections on the .model route")
    for mc, want_u0, want_i, resolved in (
        ("nch mm=1", 600.0, cur(1e-6, 1e-6, 600.0), "nch__2"),
        ("nch l=1u w=10u", 650.0, cur(1e-6, 10e-6, 650.0), None),
        ("nch l=3u w=5u ad=1.2p as=1.3p", 640.0, cur(3e-6, 5e-6, 640.0, 0.7e12), "nch__4"),
        ("nch l=0.5u ad=1p", 700.0, cur(0.5e-6, 1e-6, 700.0), "nch__3"),
        ("nch(l=1u, w=2u)", 650.0, cur(1e-6, 2e-6, 650.0), None),
        ("nch__4", 640.0, cur(1e-6, 1e-6, 640.0, 0.7e12), None),
    ):
        v, out = card(mc)
        note = f"paramset 'nch' resolved to its member '{resolved}'" if resolved else None
        check(f".model dm {mc}: u0 = {want_u0:g}, i = -{want_i:.6g}" + (f", announced as {resolved}" if resolved else ""),
              close(v.get("@n1[uu]"), want_u0) and close(v.get("i(vd)"), -want_i)
              and (note is None or note in out),
              f"{v}")

    print("[3] the refusals")
    for mc, needle in (
        ("nch zz=1", "no paramset 'nch' applies to .model dm (LRM 6.4.2)"),
        ("nch l=0.1u", "no paramset 'nch' applies to .model dm (LRM 6.4.2)"),
    ):
        v, out = card(mc)
        check(f".model dm {mc} refused: {needle}", needle in out and "i(vd)" not in v, "")
    for src, needle in (
        ("ambiguous.va", "paramset 'rr' is ambiguous for instance 'u1' (LRM 6.4.2)"),
        ("none_applies.va", "no paramset 'rr' applies to instance 'u2' (LRM 6.4.2)"),
    ):
        r, log = refused(src, needle)
        check(f"refused/{src}: {needle}", r, "" if r else log.strip().splitlines()[0])

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
