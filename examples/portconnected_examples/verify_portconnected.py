#!/usr/bin/env python3
"""
verify_portconnected.py -- `$port_connected` against LRM 9.19 and 6.5.6, end-to-end
through the committed openvaf-r + ngspice (the compliance check of 2026-09-06):

  1. the clause's own example (myclk / twoclk / top): each clock's vout_q is
     connected at its own instantiation line, vout_qbar is not, even though the
     top leaves vout_q2 open; the transition filter under a false guard is dropped
  2. the netlist route: a trailing terminal the instance line omits reads 0, a
     terminal tied to a dangling node or to ground reads 1 ("a net that has no
     other connections ... shall still return one"); `.option silentports=ground`
     turns the omitted terminal into a grounded one (E-482) and it then reads 1
  3. bits of a vector port, by bit-select and through a genvar loop, on both
     routes; a nested open named connection `.q()` and a dangling internal net;
     an instance array with an open port
  4. the refusals: a whole vector port, an internal net, an expression, a call
     inside an analog function, a parameter default or localparam

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
                    vals[n] = float(s.split("=", 1)[1].split()[0])
                except (ValueError, IndexError):
                    pass
    return vals


def op(osdi, lines, prints, extra=""):
    deck = ("* portconnected\n" + "\n".join(lines) + f"\n{extra}\n.control\npre_osdi {osdi}\nop\n"
            f"print {' '.join(prints)}\n.endc\n.end\n")
    out = ngspice(deck)
    return values(out, prints), out


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[0] the models compile")
    for m in ("lrm_p251_clocks", "netlist_terminals", "bus_bits", "nested_open", "instance_array"):
        built, log = compile_va(f"{m}.va", f"{m}.osdi")
        check(f"openvaf-r {m}.va", built, "" if built else log.strip().splitlines()[0])
    if not ok:
        print("\nSOME FAILED")
        sys.exit(1)

    print("[1] the LRM 9.19 example: connected at the instantiation line, whatever the top leaves open")
    deck = ("* portconnected\nn1 q1 dm\n.model dm top\nr1 q1 0 1k\n.control\npre_osdi lrm_p251_clocks.osdi\n"
            "tran 1u 30u\nprint @n1[topclk1__clk1__cq] @n1[topclk1__clk1__cqb] @n1[topclk1__clk2__cq] "
            "@n1[topclk1__clk2__cqb]\nmeas tran vmax MAX v(q1)\n.endc\n.end\n")
    out = ngspice(deck)
    v = values(out, ["@n1[topclk1__clk1__cq]", "@n1[topclk1__clk1__cqb]", "@n1[topclk1__clk2__cq]",
                     "@n1[topclk1__clk2__cqb]", "vmax"])
    check("clk1: vout_q 1, vout_qbar 0", v.get("@n1[topclk1__clk1__cq]") == 1.0 and v.get("@n1[topclk1__clk1__cqb]") == 0.0, f"{v}")
    check("clk2: vout_q 1 (its own line connects it; the top leaves vout_q2 open), vout_qbar 0",
          v.get("@n1[topclk1__clk2__cq]") == 1.0 and v.get("@n1[topclk1__clk2__cqb]") == 0.0, f"{v}")
    check("the connected clock toggles to 1 V through its transition filter",
          v.get("vmax") is not None and abs(v["vmax"] - 1.0) < 0.01, f"vmax = {v.get('vmax')}")

    print("[2] the netlist route: omitted, dangling and grounded terminals")
    WARN = "1 of the 3 terminals of model type 'netterm' are not connected"     # E-402's warning
    for term, want, warned, why in (("0 q qb", (1, 1), False, "both given"),
                                    ("0 q", (1, 0), True, "trailing terminal omitted, E-402 warns"),
                                    ("0 q nc", (1, 1), False, "a dangling node still counts as connected (LRM 9.19)"),
                                    ("0 q 0", (1, 1), False, "ground counts as connected")):
        v, out = op("netlist_terminals.osdi", [f"n1 {term} dm", ".model dm netterm", "v1 q 0 1"],
                    ["@n1[cq]", "@n1[cqb]"])
        check(f"n1 {term} dm: {why} -> {want}",
              (v.get("@n1[cq]"), v.get("@n1[cqb]")) == want and (WARN in out) == warned, f"{v}")
    v, out = op("netlist_terminals.osdi", ["n1 0 q dm", ".model dm netterm", "v1 q 0 1"],
                ["@n1[cq]", "@n1[cqb]"], extra=".option silentports=ground")
    check("`.option silentports=ground`: the omitted terminal is grounded by the option and reads 1 (E-482)",
          (v.get("@n1[cq]"), v.get("@n1[cqb]")) == (1, 1) and WARN not in out, f"{v}")

    print("[3] vector-port bits, nesting, instance arrays")
    for term, want in (("0 a b", (1, 1, 2)), ("0 a", (1, 0, 1))):
        v, out = op("bus_bits.osdi", [f"n1 {term} dm", ".model dm leaf", "v1 a 0 1"],
                    ["@n1[c0]", "@n1[c1]", "@n1[nb]"])
        check(f"leaf n1 {term} dm: p[0], p[1], genvar count -> {want}",
              (v.get("@n1[c0]"), v.get("@n1[c1]"), v.get("@n1[nb]")) == want, f"{v}")
    v, out = op("bus_bits.osdi", ["n1 0 a b dm", ".model dm top2", "v1 a 0 1"],
                ["@n1[u2__c0]", "@n1[u2__c1]", "@n1[u2__nb]", "@n1[u3__c0]", "@n1[u3__c1]", "@n1[u3__nb]"])
    check("top2: positional and named `{x, y}` connections give 1, 1 and a count of 2 on both instances",
          all(v.get(k) == 1.0 for k in ("@n1[u2__c0]", "@n1[u2__c1]", "@n1[u3__c0]", "@n1[u3__c1]"))
          and v.get("@n1[u2__nb]") == 2.0 and v.get("@n1[u3__nb]") == 2.0, f"{v}")
    v, out = op("nested_open.osdi", ["n1 0 a dm", ".model dm top3", "v1 a 0 1"],
                ["@n1[m1__u1__cp]", "@n1[m1__u1__cq]", "@n1[m1__u2__cp]", "@n1[m1__u2__cq]"])
    check("two levels down: `.q()` reads 0; a dangling internal net of the parent reads 1",
          (v.get("@n1[m1__u1__cp]"), v.get("@n1[m1__u1__cq]"), v.get("@n1[m1__u2__cp]"), v.get("@n1[m1__u2__cq]"))
          == (1, 0, 1, 1), f"{v}")
    v, out = op("instance_array.osdi", ["n1 0 a dm", ".model dm top4", "v1 a 0 1"],
                ["@n1[u_0__cq]", "@n1[u_1__cq]"])
    check("instance array `leaf u[0:1] (..., .q())`: 0 on each element",
          (v.get("@n1[u_0__cq]"), v.get("@n1[u_1__cq]")) == (0, 0), f"{v}")

    print("[4] the refusals")
    for src, needle in (
        ("vector_port.va", "'p' requires a bit-select [i]"),
        ("not_a_port.va", "expected a port reference but no direction was declared for net 'mid'"),
        ("not_a_port.va", "expected net reference but found real value"),
        ("in_function.va", "'a' was not found in the current scope"),
        ("constant_context.va", "system function '$port_connected' is not allowed in constants"),
    ):
        r, log = refused(src, needle)
        check(f"refused/{src}: {needle}", r, "" if r else log.strip().splitlines()[0])

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
