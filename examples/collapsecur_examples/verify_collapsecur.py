#!/usr/bin/env python3
"""verify_collapsecur.py -- Enhancement-416: the terminal current a node
collapse hid.

`if (rd == 0) V(d,di) <+ 0; else I(d,di) <+ V(d,di)/rd;` is the standard
compact-model idiom for an optional series resistance, and rd = 0 is the shipped
default of most real models (BSIM `rdsmod=0`, HICUM `re=0`). On that default path
the terminal is COLLAPSED onto the internal node, the model writes its current
into the internal node's residual, and terminal `d`'s own residual stays zero --
so `@n1[i_d]`, `show`, and `.options savecurrents` all reported exactly 0.0 for a
terminal carrying the device's full current.

With rd = 0 AND rs = 0 -- the shipped default of a typical model -- EVERY
terminal read 0.0 and the reported currents summed to zero, so a Kirchhoff check
did not flag it either. The solution itself was always right: osdiload.c stamps
the whole collapse group into one matrix row, which is exactly why only the
readback was wrong.

The fix sums the terminal's whole collapse group. The grouping has to be
recorded during setup, because write_node_mapping() replaces the local mapping
with global node numbers moments later and those cannot express a group: two
terminals wired to one net share a global number without being collapsed, and
ground additionally collects grounded terminals, nodes collapsed to ground,
Enhancement-116's decoupled internal nodes and Enhancement-401's dropped
term-short flow nodes. `coll_chain.va`'s `tognd` knob is the negative control
for precisely that -- an internal node on global node 0 beside a grounded
terminal, whose current must NOT be folded in.

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
    path = os.path.join(TMP, f"_cc_{tag}.cir")
    with open(path, "w") as fh:
        fh.write(f"* {tag}\n{deck}\n{extra}\n.control\npre_osdi {osdi}\n"
                 f"set numdgt=12\n{ctrl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def num(out, expr):
    m = re.search(re.escape(expr) + r"\s*=\s*(-?[\d.eE+-]+)", out)
    return float(m.group(1)) if m else None


def wrdata(tag, deck, ctrl, osdi, vecs, extra=""):
    """Run `ctrl` then wrdata `vecs`; return a list of (t, v1, v2, ...) tuples."""
    dat = os.path.join(TMP, f"_cc_{tag}.dat")
    if os.path.exists(dat):
        os.remove(dat)
    run(tag, deck, f"{ctrl}\nwrdata {dat} {vecs}", osdi, extra)
    if not os.path.exists(dat):
        return []
    rows = []
    for line in open(dat):
        f = line.split()
        if not f:
            continue
        # wrdata emits an (x, y) pair per vector; the x column repeats
        rows.append(tuple([float(f[0])] + [float(f[i]) for i in range(1, len(f), 2)]))
    return rows


CMC = "vd d 0 dc 1\nvg g 0 dc 2\nn1 d g 0 mm\n"


def model(**kw):
    kw = {"gm": 1e-3, "gds": 1e-6, "rd": 0, "rs": 0, "cgs": 0, "cds": 0, **kw}
    return ".model mm coll_cmc(" + " ".join(f"{k}={v}" for k, v in kw.items()) + ")"


def main():
    _check_both_solvers(__file__)
    print("Enhancement-416 -- terminal current across a node collapse\n")

    osdi_cmc = compile_va("coll_cmc")
    osdi_chn = compile_va("coll_chain")

    # ------------------------------------------------------------------ DC
    print("[1] DC: the four collapse combinations of the CMC idiom")
    print("    rd=0 collapses terminal d onto di; rs=0 collapses s onto si.")
    for rd, rs in ((0, 0), (0, 1), (1, 0), (1, 1)):
        out = run(f"dc{rd}{rs}", CMC, "op\nprint i(vd)\nprint @n1[i_d]\n"
                  "print @n1[i_g]\nprint @n1[i_s]", osdi_cmc, model(rd=rd, rs=rs))
        truth = num(out, "i(vd)")
        i_d, i_g, i_s = (num(out, f"@n1[{k}]") for k in ("i_d", "i_g", "i_s"))
        if None in (truth, i_d, i_g, i_s):
            check(f"rd={rd} rs={rs}: currents readable", False, out[-200:])
            continue
        collapsed = "collapsed" if (rd == 0 or rs == 0) else "not collapsed"
        check(f"rd={rd} rs={rs} ({collapsed}): i_d == -i(vd)",
              abs(i_d + truth) <= 1e-12 * max(1.0, abs(truth)),
              f"{i_d:.10e} vs {-truth:.10e}")
        check(f"rd={rd} rs={rs}: terminal currents obey KCL",
              abs(i_d + i_g + i_s) <= 1e-14, f"sum={i_d + i_g + i_s:.3e}")
        # the defect's signature: a terminal reading exactly zero while conducting
        if rd == 0:
            check(f"rd={rd} rs={rs}: i_d is not the old zero", i_d != 0.0, f"{i_d:.6e}")
        if rs == 0:
            check(f"rd={rd} rs={rs}: i_s is not the old zero", i_s != 0.0, f"{i_s:.6e}")

    # ------------------------------------------------------- collapse chain
    print("\n[2] a collapse CHAIN puts three descriptor nodes in one group")
    for chain in (1, 0):
        out = run(f"ch{chain}", "v1 a 0 dc 1\nn1 a 0 mm\n",
                  "op\nprint i(v1)\nprint @n1[i_a]\nprint @n1[i_c]", osdi_chn,
                  f".model mm coll_chain(g=1e-3 chain={chain} tognd=0)")
        truth, i_a, i_c = num(out, "i(v1)"), num(out, "@n1[i_a]"), num(out, "@n1[i_c]")
        if None in (truth, i_a, i_c):
            check(f"chain={chain}: readable", False)
            continue
        check(f"chain={chain} ({'a-n1-n2 merged' if chain else 'separate'}): "
              "i_a == -i(v1)", abs(i_a + truth) <= 1e-9 * max(1.0, abs(truth)),
              f"{i_a:.10e} vs {-truth:.10e}")
        check(f"chain={chain}: i_a + i_c == 0",
              abs(i_a + i_c) <= 1e-7 * max(abs(i_a), abs(i_c)),
              f"sum={i_a + i_c:.3e}")

    # ------------------------------------ negative control: collapse to ground
    print("\n[3] NEGATIVE CONTROL -- an internal node collapsed to GROUND")
    print("    Terminal c is tied to node 0 and so is the grounded internal node;")
    print("    they share a global node index WITHOUT sharing a collapse group.")
    # Grounding x removes the x->c branch, so i_c is NOT comparable across the
    # tognd knob -- it is comparable to the analytic value. With v(a)=1 and c at
    # ground, terminal c carries only the n2->c branch, g*V(n2,c) = 1.0 mA. The
    # separate I(a,x) branch delivers 1e-4*V(a,x) = 0.1 mA into the grounded x;
    # folding that in would make |i_c| read 1.1 mA instead of 1.0 mA.
    # tognd=0 is the companion: x is a real internal node between a and c, so
    # terminal c legitimately carries BOTH branches -- 1.0 mA from n2 plus the
    # divider current 1e-4*1e-3/(1e-4+1e-3) = 90.909 uA through x.
    for tognd, want in ((1, 1.0e-3), (0, 1.0e-3 + 1e-7 / 1.1e-3)):
        out = run(f"gnd{tognd}", "v1 a 0 dc 1\nn1 a 0 mm\n",
                  "op\nprint i(v1)\nprint @n1[i_a]\nprint @n1[i_c]", osdi_chn,
                  f".model mm coll_chain(g=1e-3 chain=1 tognd={tognd})")
        i_a, i_c, truth = num(out, "@n1[i_a]"), num(out, "@n1[i_c]"), num(out, "i(v1)")
        if None in (i_a, i_c, truth):
            check(f"tognd={tognd}: readable", False)
            continue
        check(f"tognd={tognd}: terminal c carries only its own branch "
              f"({want * 1e3:.1f} mA, not 1.1 mA)",
              abs(abs(i_c) - want) <= 1e-9, f"i_c={i_c:.10e}")
        check(f"tognd={tognd}: i_a still equals -i(v1)",
              abs(i_a + truth) <= 1e-9 * max(1.0, abs(truth)),
              f"{i_a:.10e} vs {-truth:.10e}")
    # ...and the grounded internal node is exactly why the terminal currents may
    # legitimately NOT sum to zero: that 0.1 mA leaves through node 0.
    out = run("gndkcl", "v1 a 0 dc 1\nn1 a 0 mm\n",
              "op\nprint @n1[i_a]\nprint @n1[i_c]", osdi_chn,
              ".model mm coll_chain(g=1e-3 chain=1 tognd=1)")
    i_a, i_c = num(out, "@n1[i_a]"), num(out, "@n1[i_c]")
    check("a ground-collapsed internal node sinks current outside the terminals",
          i_a is not None and abs((i_a + i_c) - 1.0e-4) <= 1e-9,
          f"i_a+i_c={i_a + i_c:.6e} (the 0.1 mA into the grounded node)")

    # ------------------------------------------------------------- transient
    print("\n[4] TRANSIENT: charge on the collapsed path")
    print("    1 nF driven at 1 V/us is ~1 mA of purely CAPACITIVE terminal")
    print("    current, so a resistive-only sum would be wrong by ~1000x here.")
    TR = "vd d 0 pwl(0 0 10u 10)\nvg g 0 dc 0\nn1 d g 0 mm\n"
    got = {}
    for tag, rd in (("coll", 0), ("open", 1e-6)):
        got[tag] = wrdata(f"tr_{tag}", TR, "tran 0.1u 4u", osdi_cmc,
                          "@n1[i_d] @n1[i_s]",
                          model(rd=rd, rs=1e-6, cds=1e-9))
    a, b = got["coll"], got["open"]
    if not a or not b:
        check("transient waveforms captured", False, f"{len(a)} / {len(b)} rows")
    else:
        n = min(len(a), len(b))
        worst = max(abs(a[i][1] - b[i][1]) / max(abs(b[i][1]), 1e-12)
                    for i in range(1, n))
        peak = max(abs(r[1]) for r in a)
        check("collapsed i_d tracks the uncollapsed reference over the whole run",
              worst < 1e-5, f"worst rel {worst:.2e} over {n} points")
        check("collapsed i_d is the ~1 mA capacitive current, not zero",
              abs(peak - 1e-3) < 5e-5, f"peak {peak:.6e}")
        check("collapsed run obeys KCL at every timepoint",
              max(abs(r[1] + r[2]) for r in a[1:]) <= 1e-12,
              f"max |i_d+i_s| {max(abs(r[1] + r[2]) for r in a[1:]):.3e}")

    # -------------------------------------------------- unchanged behaviours
    print("\n[5] behaviours that must NOT have moved")

    # Enhancement-397: the loader's own instance knobs keep their ids
    out = run("e397", CMC, "op\nprint @n1[temp]\nprint @n1[dtemp]\nprint @n1[dt]",
              osdi_cmc, model())
    check("E-397: @n1[temp] is still the ambient in Celsius",
          num(out, "@n1[temp]") == 27.0, str(num(out, "@n1[temp]")))
    check("E-397: @n1[dtemp] and @n1[dt] still read 0",
          num(out, "@n1[dtemp]") == 0.0 and num(out, "@n1[dt]") == 0.0)

    # Enhancement-413: savecurrents still expands per terminal, now non-zero
    out = run("e413", CMC, "op\nprint @n1[i_d]\nprint length(@n1[i_d])", osdi_cmc,
              model() + "\n.options savecurrents")
    check("E-413: savecurrents still yields a readable per-terminal current",
          num(out, "length(@n1[i_d])") == 1.0 and num(out, "@n1[i_d]") not in (None, 0.0),
          f"i_d={num(out, '@n1[i_d]')}")

    # an id past the terminal block is still rejected
    out = run("bad", CMC, "op\nprint @n1[i_nosuchterm]", osdi_cmc, model())
    check("a non-existent terminal current is still rejected",
          "no such parameter" in out.lower(), "")

    # Enhancement-402: a short instance line leaves a terminal unconnected
    out = run("e402", "vd d 0 dc 1\nvg g 0 dc 2\nn1 d g mm\n",
              "op\nprint @n1[i_d]\nprint @n1[i_s]", osdi_cmc, model(rs=1))
    check("E-402: a short instance line still warns",
          "not connected" in out.lower(), "")
    check("E-402: the unconnected terminal reports no current",
          num(out, "@n1[i_s]") == 0.0, str(num(out, "@n1[i_s]")))

    # `show` is a second reader of the same values
    out = run("show", CMC, "op\nshow n1", osdi_cmc, model())
    row = re.search(r"^\s*i_d\s+(-?[\d.eE+-]+)\s*$", out, re.M)
    check("`show` reports the same non-zero collapsed terminal current",
          row is not None and float(row.group(1)) != 0.0,
          row.group(1) if row else "no i_d row")

    print(f"\n{passed}/{checks} checks passed")
    return 0 if passed == checks else 1


if __name__ == "__main__":
    sys.exit(main())
