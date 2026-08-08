#!/usr/bin/env python3
"""verify_collapsestate.py -- Enhancement-417: the node collapse is decided once,
and three things went on reporting as though it could not change.

A Verilog-A node collapse (`V(d,di) <+ 0`) is decided inside setup_instance, and
everything that matters is built from that one decision: the node mapping, the
matrix element pointers, the state layout, Enhancement-416's collapse-owner map.
`OSDItemp` re-runs setup_instance on every temperature update -- so the decision
can be RE-MADE -- but it cannot rebuild any of them. The mismatch was silent.

[1] `sens` REPORTED ROUNDOFF AS A DERIVATIVE. Perturbing a parameter that selects
the collapse leaves the perturbed device stamping a topology the matrix does not
have: the collapsed pair still shares one matrix element, so the branch's +g and
-g land on the same diagonal and cancel. What survived was the roundoff of that
cancellation divided by the perturbation -- `eps*E/(Y*delta^2)`, a number with no
relation to the derivative, whose magnitude tracked 1/rd and whose SIGN moved
with unrelated parameters. It cannot be computed correctly here (DEVsetup runs
only at the base value, and re-running it would allocate nodes and trip
cktsens.c's own CKTlastNode guard), so it is now reported as 0 and said out loud.

[2] A `.dc temp` SWEEP RAN THE WHOLE RANGE ON ONE TOPOLOGY. Sweeping into a
collapse left the terminal floating -- exactly 0 A. Sweeping out of one kept the
collapsed topology, so the series element never appeared: 1 mA where the truth is
500 uA, a plausible-looking 2x error. `.temp` and `set temp` were always correct,
because each re-does the setup. The sweep now warns, naming the instance and the
temperature; rebuilding the topology mid-sweep is not possible (the matrix is
ordered and factored, and every other device caches raw element pointers).

[3] `savecurrents` SKIPPED PER-TERMINAL NAMES AT TWO TERMINALS. It expanded
`@dev[i_<term>]` for three or more terminals but left only the bare `@dev[i]` for
two, so `@dev[i_p]` was a length-1 SCALAR and `meas`/`plot` silently used one
point. The expansion is now unconditional, and the bare `i` is kept beside it.

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


def run(tag, deck, ctrl, osdi, extra=""):
    path = os.path.join(TMP, f"_cs_{tag}.cir")
    with open(path, "w") as fh:
        fh.write(f"* {tag}\n{deck}\n{extra}\n.control\npre_osdi {osdi}\n"
                 f"set numdgt=12\n{ctrl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def num(out, expr):
    m = re.search(re.escape(expr) + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m.group(1)) if m else None


def named(out, name):
    """A `print all` row, e.g. `n1:rd = -2.59e-02`."""
    m = re.search(rf"^{re.escape(name)}\s*=\s*(-?[\d.eE+-]+)\s*$", out, re.M)
    return float(m.group(1)) if m else None


def rows(out):
    """(scale, value) pairs of a printed sweep table."""
    return [(float(a), float(b)) for a, b in
            re.findall(r"^\s*\d+\s+([\d.eE+-]+)\s+(-?[\d.eE+-]+)", out, re.M)]


def main():
    osdi_gate = compile_va("cs_gate")
    osdi_two = compile_va("cs_two")

    # ---------------------------------------------------------------- [1] sens
    print("\n    [1] `sens` on a parameter that SELECTS the collapse")
    print("        Perturbing rd off zero moves the collapse, so the perturbed")
    print("        stamp lands on a matrix built for the collapsed topology.")

    SENS = ("v1 s 0 dc 1\nrs s d 1k\nn1 d 0 mm\nrl d 0 10k")

    def sdeck(rd):
        return f".model mm cs_gate(g=1e-3 gsr=1e-3 rd={rd})"

    out = run("sens0", SENS, "sens v(d)\nprint all", osdi_gate, sdeck(0))
    rd0 = named(out, "n1:rd")
    check("collapsed rd=0: sensitivity reported as 0, not roundoff",
          rd0 == 0.0, f"n1:rd={rd0}")
    check("collapsed rd=0: and it says so", "node collapse" in out and "sens:" in out,
          "warning present" if "node collapse" in out else "SILENT")

    # the true derivative, from rewriting the deck -- never from `alter`, which
    # does not reach a model-only parameter at all.
    def vd(rd):
        o = run(f"fd{str(rd).replace('.','p').replace('-','m')}", SENS,
                "op\nprint v(d)", osdi_gate, sdeck(rd) + "\n.options reltol=1e-12")
        return num(o, "v(d)")

    base, hi = vd(0), vd(1e-2)
    fd = (hi - base) / 1e-2 if (base is not None and hi is not None) else None
    check("the true derivative is small and positive, not the negative roundoff once printed",
          fd is not None and 0 < fd < 1e-2, f"deck-rewrite FD={fd:.6e}")

    # negative control: away from the boundary sens must be untouched AND correct.
    # NOTE the warning is checked per PARAMETER, not per run: `tsw` also selects
    # the collapse (0 -> 1e-6 switches cs_gate to its temperature branch), so a
    # run-wide "no warning" assertion would be testing the wrong thing.
    out = run("sens2", SENS, "sens v(d)\nprint all", osdi_gate, sdeck(1e-2))
    rd2 = named(out, "n1:rd")
    check("uncollapsed rd=1e-2: sens still computes the real sensitivity",
          rd2 is not None and abs(rd2 - fd) / abs(fd) < 1e-3, f"n1:rd={rd2}")
    check("uncollapsed rd=1e-2: rd itself is no longer flagged",
          "n1:rd changes" not in out,
          "not flagged" if "n1:rd changes" not in out else "still flagged")

    # the other rows of the same table must not be disturbed
    g0 = named(run("sensg0", SENS, "sens v(d)\nprint all", osdi_gate, sdeck(0)), "n1:g")
    g2 = named(out, "n1:g")
    check("the other parameters' rows are unaffected",
          g0 is not None and g2 is not None and abs(g0 - g2) / abs(g2) < 1e-3,
          f"n1:g {g0} vs {g2}")

    # ------------------------------------------------------- [2] .dc temp sweep
    print("\n    [2] a `.dc temp` sweep that crosses the collapse condition")
    print("        tsw=350 K = 76.85 C. `.temp` is the oracle: it re-does setup.")

    TD = "v1 d 0 dc 1\nn1 d 0 mm"

    def tdeck(hot):
        return f".model mm cs_gate(g=1e-3 gsr=1e-3 tsw=350 hot={hot})"

    for hot, label in ((1, "into a collapse (collapse when hot)"),
                       (0, "out of a collapse (collapse when cold)")):
        out = run(f"sw{hot}", TD, "dc temp 40 120 40\nprint i(v1)", osdi_gate, tdeck(hot))
        check(f"{label}: the sweep warns instead of failing silently",
              "node collapse" in out, "warned" if "node collapse" in out else "SILENT")
        got = rows(out)
        # the oracle, one analysis per temperature
        truth = []
        for t in (40, 120):
            o = run(f"tc{hot}_{t}", TD, "op\nprint i(v1)", osdi_gate,
                    tdeck(hot) + f"\n.temp {t}")
            truth.append(num(o, "i(v1)"))
        moved = truth[0] is not None and truth[1] is not None and \
            abs(truth[0] - truth[1]) / abs(truth[1]) > 1e-3
        check(f"{label}: the two topologies really do differ",
              moved, f".temp 40 -> {truth[0]}, .temp 120 -> {truth[1]}")
        check(f"{label}: the sweep still produced its rows", len(got) == 3, f"{len(got)} rows")

    # negative control: temperature dependence that does NOT change the topology
    out = run("swplain", TD, "dc temp 40 120 40\nprint i(v1)", osdi_gate,
              ".model mm cs_gate(g=1e-3 gsr=1e-3 rd=1)")
    check("a sweep over a model whose collapse does NOT move stays quiet",
          "node collapse" not in out, "quiet" if "node collapse" not in out else "warned")
    got = rows(out)
    check("...and is unchanged across the range (no topology to move)",
          len(got) == 3 and all(abs(v - got[0][1]) < 1e-12 for _, v in got),
          f"{[v for _, v in got]}")

    # ------------------------------------------------- [3] savecurrents at 2
    print("\n    [3] `.options savecurrents` on a TWO-terminal device")

    TWO = "v1 a 0 pulse(0 1 1n 1n 1n 1u 2u)\nn1 a 0 mm"
    MOD2 = ".model mm cs_two(r=1000 c=1e-9)\n.options savecurrents"

    out = run("sc2", TWO, "tran 2n 200n\nprint length(@n1[i])\nprint length(@n1[i_p])\n"
                          "print length(@n1[i_n])", osdi_gate if False else osdi_two, MOD2)
    li, lp, ln = (num(out, f"length(@n1[{k}])") for k in ("i", "i_p", "i_n"))
    check("per-terminal currents are waveforms, not length-1 scalars",
          lp is not None and lp > 1 and ln is not None and ln > 1,
          f"len(i_p)={lp} len(i_n)={ln}")
    check("the bare `@dev[i]` Enhancement-394 defines is still there",
          li is not None and li > 1 and li == lp, f"len(i)={li}")

    out = run("sc2v", TWO, "tran 2n 200n\nlet d1=abs(@n1[i_p]-@n1[i])\n"
                           "let d2=abs(@n1[i_n]+@n1[i_p])\nlet a=abs(@n1[i_p])\n"
                           "meas tran m1 max d1\nmeas tran m2 max d2\nmeas tran am max a",
              osdi_two, MOD2)
    m1, m2, am = (num(out, k) for k in ("m1", "m2", "am"))
    check("`i_p` is exactly the bare `i` (they are the same parameter id)",
          m1 == 0.0, f"max|i_p - i|={m1}")
    check("`i_n` is exactly -`i_p` (KCL on a two-terminal device)",
          m2 == 0.0, f"max|i_n + i_p|={m2}")
    check("and the waveform is the capacitive one, not the settled value",
          am is not None and am > 0.5, f"max|i_p|={am} A")

    # negative controls: 3-terminal unchanged, and no duplicate vectors
    THREE = ("v1 a 0 pulse(0 1 1n 1n 1n 1u 2u)\nvg g 0 dc 2\nn1 a 0 mm3\n"
             ".model mm3 cs_gate(g=1e-3 gsr=1e-3 rd=1)\n.options savecurrents")
    out = run("sc3", "v1 a 0 pulse(0 1 1n 1n 1n 1u 2u)\nn1 a 0 mm3",
              "tran 2n 200n\ndisplay", osdi_gate,
              ".model mm3 cs_gate(g=1e-3 gsr=1e-3 rd=1)\n.options savecurrents")
    vecs = sorted(set(re.findall(r"^\s*(@\S+\[\S+\])\s*:", out, re.M)))
    check("a two-terminal-model deck still names its terminals d/s",
          vecs == ["@n1[i]", "@n1[i_d]", "@n1[i_s]"], f"{vecs}")

    for extra, label in ((".save @n1[i_p]\n" + MOD2, "explicit .save i_p + savecurrents"),
                         (".save @n1[i]\n" + MOD2, "explicit .save i + savecurrents")):
        out = run("dup" + re.sub(r"\W", "", label)[:8], TWO, "tran 2n 100n\ndisplay",
                  osdi_two, extra)
        seen = re.findall(r"^\s*(@\S+\[\S+\])\s*:", out, re.M)
        dup = [v for v in set(seen) if seen.count(v) > 1]
        check(f"{label}: no duplicate vectors", not dup, f"{dup or 'none'}")

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    _check_both_solvers(__file__)
    sys.exit(main())
