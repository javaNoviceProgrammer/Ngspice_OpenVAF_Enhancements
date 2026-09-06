#!/usr/bin/env python3
"""
verify_paramsetlrm.py -- paramsets per LRM 6.4 (Enhancement-563, from the
2026-09-05 book audit), end-to-end through the committed openvaf-r + ngspice:

  1. a paramset REUSES its module's parameter names (`parameter real L; .L = L;`)
     and binds through a "constant module" of localparams (`fab.rsh_eff`)
  2. a paramset of a paramset assigns the parent's own parameters (`.KIND`, `.L`)
     and its `aliasparam` names the parent's parameter on the card
  3. output variables (LRM 6.4.3): a paramset variable replaces the module's of
     the same name, a new one is computed by paramset statements from `.reff`
  4. the same paramsets INSTANTIATED inside a module (the book's divider): the
     bindings, the chain, the alias, `.$mfactor` composed with the instance's,
     and the paramset's output variables under the instance prefix
  5. the refusals: a contribution / event control / named block / access
     function in a paramset statement (6.4.1), a paramset name that is a net
     of the module, assigning a `localparam` or a parameter an earlier paramset
     fixed, a hierarchical reference to a non-local parameter, an instance
     overriding a parameter its paramset fixes

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


def refused(src, needles):
    r = subprocess.run([OPENVAF, os.path.join("refused", src)],
                       cwd=HERE, capture_output=True, text=True)
    log = r.stdout + r.stderr
    missing = [n for n in needles if n not in log]
    return r.returncode != 0 and not missing, log, missing


def op(osdi, card, prints, nodes="a 0"):
    deck = ("* paramsetlrm\nvin a 0 dc 1\n"
            f"n1 {nodes} dm\n.model dm {card}\n"
            f".control\npre_osdi {osdi}\nop\nprint {' '.join(prints)}\n.endc\n.end\n")
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=120).stdout
    vals = {}
    for line in out.splitlines():
        s = line.strip()
        for p in prints:
            if s.lower().startswith(p.lower() + " "):
                try:
                    vals[p] = float(s.split("=", 1)[1])
                except ValueError:
                    pass
    return vals


def close(a, b, rel=1e-6):
    return a is not None and abs(a - b) <= rel * max(1.0, abs(b))


# the module: reff = RSH (L - DL) / (W - DW)
def reff(rsh, l, w, dl=0.0, dw=0.0):
    return rsh * (l - dl) / (w - dw)


RSH_EFF = 120.0 * 0.8        # fab.rsh_eff


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[0] the model file compiles")
    built, log = compile_va("vres_ps.va", "vres_ps.osdi")
    check("openvaf-r vres_ps.va", built, "" if built else log.strip().splitlines()[0])
    if not built:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[1] rp: same-name parameters, a constant-module localparam, .$mfactor = 2")
    r = reff(RSH_EFF, 3e-6, 1e-6, 30e-9, 20e-9)
    v = op("vres_ps.osdi", "rp", ["i(vin)", "@n1[reff]"])
    check(f"defaults: reff = {r:.6g}, i = -2/reff (m = 2)",
          close(v.get("@n1[reff]"), r) and close(v.get("i(vin)"), -2.0 / r), f"{v}")
    r = reff(RSH_EFF, 6e-6, 2e-6, 30e-9, 20e-9)
    v = op("vres_ps.osdi", "rp L=6u W=2u", ["i(vin)", "@n1[reff]"])
    check(f"card L=6u W=2u sets the paramset's L and W: reff = {r:.6g}",
          close(v.get("@n1[reff]"), r) and close(v.get("i(vin)"), -2.0 / r), f"{v}")
    v = op("vres_ps.osdi", "rp RSH=5", ["@n1[reff]"])
    check("the bound module parameter RSH is not settable from the card",
          "@n1[reff]" not in v or close(v.get("@n1[reff]"), reff(RSH_EFF, 3e-6, 1e-6, 30e-9, 20e-9)),
          f"{v}")

    print("[2] rmetal: a paramset of rp, assigning rp's KIND and L; alias LL on the card")
    r = reff(RSH_EFF, 2e-6, 1e-6, 30e-9, 20e-9)
    v = op("vres_ps.osdi", "rmetal", ["i(vin)", "@n1[reff]"])
    check(f"defaults: L = LEN = 2u, W = rp's 1u: reff = {r:.6g}, m = 2",
          close(v.get("@n1[reff]"), r) and close(v.get("i(vin)"), -2.0 / r), f"{v}")
    r = reff(RSH_EFF, 5e-6, 1e-6, 30e-9, 20e-9)
    v = op("vres_ps.osdi", "rmetal LL=5u", ["@n1[reff]"])
    check(f"LL=5u through the alias: reff = {r:.6g}", close(v.get("@n1[reff]"), r), f"{v}")

    print("[3] rpd: output variables and statements (LRM 6.4.3)")
    r = reff(150.0, 2e-6, 1e-6)
    v = op("vres_ps.osdi", "rpd", ["i(vin)", "@n1[reff]", "@n1[pdis]", "@n1[fig]"])
    check(f"reff = {r:g} still the module's", close(v.get("@n1[reff]"), r), f"{v}")
    check(f"pdis = 2e-6 reff = {2e-6 * r:g} (paramset statements through `.reff`)",
          close(v.get("@n1[pdis]"), 2e-6 * r), f"{v}")
    check(f"fig = reff/100 = {r / 100:g}: the paramset's replaces the module's -1",
          close(v.get("@n1[fig]"), r / 100), f"{v}")
    r = reff(150.0, 2e-6, 2e-6)
    v = op("vres_ps.osdi", "rpd WID=2u", ["@n1[pdis]"])
    check(f"WID=2u: pdis = {2e-6 * r:g}", close(v.get("@n1[pdis]"), 2e-6 * r), f"{v}")

    print("[4] the divider: the paramsets instantiated inside a module")
    ra = reff(RSH_EFF, 4e-6, 1e-6, 30e-9, 20e-9)            # rmetal #(.LL(LA=4u)), m = 2
    rb = reff(RSH_EFF, 4e-6, 2e-6, 30e-9, 20e-9)            # rp #(.W(2u), .L(4u), .$mfactor(3)), m = 6
    rc = reff(150.0, 2e-6, 2e-6)                            # rpd #(.WID(2u))
    g_a = 2.0 / ra
    g_out = 6.0 / rb + 1.0 / rc
    i = 1.0 / (1.0 / g_a + 1.0 / g_out)
    vout = i / g_out
    v = op("vres_ps.osdi", "divider", ["i(vin)", "v(out)", "@n1[rc__pdis]", "@n1[rc__fig]",
                                        "@n1[ra__reff]", "@n1[rb__reff]"], nodes="a out 0")
    check(f"i(vin) = -{i:.6g} (ra: alias + chain, m = 2; rb: m = 2*3; rc)",
          close(v.get("i(vin)"), -i, 1e-5), f"{v.get('i(vin)')}")
    check(f"v(out) = {vout:.6g}", close(v.get("v(out)"), vout, 1e-5), f"{v.get('v(out)')}")
    check(f"ra__reff = {ra:.6g}, rb__reff = {rb:.6g}",
          close(v.get("@n1[ra__reff]"), ra) and close(v.get("@n1[rb__reff]"), rb), f"{v}")
    check(f"rc__pdis = {2e-6 * rc:g}, rc__fig = {rc / 100:g}: the paramset's output variables",
          close(v.get("@n1[rc__pdis]"), 2e-6 * rc) and close(v.get("@n1[rc__fig]"), rc / 100),
          f"{v}")

    print("[5] the refusals")
    for src, needles in (
        ("forbidden_stmts.va", ["a contribution is not allowed in a paramset",
                                "an event control is not allowed in a paramset",
                                "a named block is not allowed in a paramset",
                                "an access function is not allowed in a paramset"]),
        ("net_clash.va", ["paramset declares 'mid', the name of a net of its target"]),
        ("fixed_param.va", ["paramset assigns 'R', which is not a parameter of 'base'",
                            "paramset assigns 'K', which is not a parameter of 'base'"]),
        ("nonlocal_hier.va", ["`fab.rsh` refers to a parameter of module 'fab' that is not a `localparam`"]),
        ("instance_fixed.va", ["instance of paramset 'rp' overrides 'R', which the paramset fixes"]),
    ):
        r, log, missing = refused(src, needles)
        check(f"refused/{src}", r, "" if r else (missing or log.strip().splitlines()[:1]))

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
