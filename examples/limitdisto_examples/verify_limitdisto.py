#!/usr/bin/env python3
"""Enhancement-353: `.disto` for Verilog-A models that use `$limit`.

Enhancement-352 gave OSDI devices distortion analysis, but only for models that
read their controlling voltages directly. A model that passes one through
`$limit` -- which is every production diode, BJT and MOS model, since limiting is
how they converge -- contributed nothing at all.

The reason is that the residual depends on the LIMITED value, not on the raw
voltage read, so differentiating it by the raw read yields zero and the model
looks perfectly linear. `build_jacobian` already folds the limited values back
in via `intern.lim_state`; the Taylor tensors now perform the same fold, summing
over each input's chain of (limited values, then the raw unknown) with the sign
each contributes.

METHOD. `$limit` is a convergence aid: at convergence the limited value equals
the actual one, so a model written with it and the same model written without it
are THE SAME DEVICE and every distortion product must agree. That gives an exact
expectation without appealing to another simulator. Both spellings are generated
from one body string, which is what guarantees they differ only by `$limit` and
cannot drift apart.

The shapes are chosen to cover the chain combinatorics, which is where this can
go wrong -- a model limiting a single branch never puts more than one entry on
either side of a pair:

  A  two independently limited inputs, each with its own diagonal nonlinearity
  B  a cross term with BOTH inputs limited      (2 x 2 pair combinations)
  C  a cross term with ONE input limited        (asymmetric chains, 2 x 1)
  D  a THIRD-order cross term, so the triple loop runs on a 3-entry chain
  E  a limit on the REVERSED branch V(ref,a) -- the only spelling that puts a
     NEGATED entry in a chain, so the only one that exercises the sign XOR

WHY THE CHECKS LOOK LIKE THIS. The failure being guarded against is not
"slightly wrong" but "identically zero", and zero is also what a degenerate deck
produces. So a BOTH-ZERO result is scored as a FAILURE, never a pass, and the
operating points are compared first -- if the two spellings do not converge to
the same point they are not the same device and the comparison would be
meaningless. Products are compared as COMPLEX values rather than magnitudes,
because a dropped sign on a negated chain entry flips the sign and leaves the
magnitude untouched, which would score shape E's own target bug as a pass.

Two shapes legitimately have no IM3: a bilinear term k*v1*v2 has no third
derivative at all, so zero there is the correct answer and is asserted as such
rather than being counted as a product.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------- the models
LIM = '$limit(V(%s,ref),"pnjlim",0.026,0.7)'


def bodies(limited):
    """The five shapes. `limited` selects the spelling; everything else is
    identical, which is the point -- the two builds must be the same device."""
    va = LIM % "a" if limited else "V(a,ref)"
    vb = LIM % "b" if limited else "V(b,ref)"
    rva = ('$limit(V(ref,a),"pnjlim",0.026,0.7)' if limited else "V(ref,a)")
    lin = "    I(a,ref) <+ 1e-3*V(a,ref);\n    I(b,ref) <+ 1e-3*V(b,ref);\n"
    return {
        "lmA": ("    I(a,ref) <+ 1e-15*(exp(%s/0.026) - 1.0) + 1e-12*V(a,ref);\n"
                "    I(b,ref) <+ 1e-15*(exp(%s/0.026) - 1.0) + 1e-12*V(b,ref);\n"
                "    I(out,ref) <+ 1e-3*V(out,ref);\n" % (va, vb)),
        "lmB": lin + "    I(out,ref) <+ k*%s*%s + 1e-3*V(out,ref);\n" % (va, vb),
        "lmC": lin + "    I(out,ref) <+ k*%s*V(b,ref) + 1e-3*V(out,ref);\n" % va,
        "lmD": lin + "    I(out,ref) <+ k*%s*%s*%s + 1e-3*V(out,ref);\n" % (va, va, vb),
        "lmE": lin + "    I(out,ref) <+ k*%s*%s + 1e-3*V(out,ref);\n" % (rva, vb),
    }


LABEL = {
    "lmA": "two independently limited diagonal nonlinearities",
    "lmB": "cross term with both inputs limited",
    "lmC": "cross term with one input limited (asymmetric chains)",
    "lmD": "third-order cross term, limited (exercises the triples)",
    "lmE": "reversed-branch limit, i.e. a negated chain entry",
}
# shape A's nonlinearity sits on the a/b branches, not on `out`
PROBE = {"lmA": "a", "lmB": "out", "lmC": "out", "lmD": "out", "lmE": "out"}
# a bilinear cross term has no third derivative, so its IM3 is correctly zero
HAS_IM3 = {"lmA": True, "lmB": False, "lmC": False, "lmD": True, "lmE": False}
SHAPES = ["lmA", "lmB", "lmC", "lmD", "lmE"]


def build():
    for limited, suffix in ((False, "_p"), (True, "_l")):
        for base, body in bodies(limited).items():
            name = "_" + base + suffix
            src = os.path.join(HERE, name + ".va")
            with open(src, "w") as f:
                f.write('`include "disciplines.vams"\n'
                        "module %s(a, b, out, ref);\n"
                        "  inout a, b, out, ref; electrical a, b, out, ref;\n"
                        "  parameter real k = 1e-3;\n"
                        "  analog begin\n%s  end\nendmodule\n" % (name, body))
            out = os.path.join(HERE, name + ".osdi")
            r = subprocess.run([OPENVAF, src, "-o", out],
                               capture_output=True, text=True, timeout=900)
            if r.returncode != 0 or not os.path.exists(out):
                print("FATAL: %s failed to compile\n%s" % (name, r.stdout + r.stderr))
                sys.exit(2)


# Both drives carry BOTH tones and reach the device through a series resistor.
# Without the series R the node is pinned by an ideal source and no injected
# distortion current can move it; without both tones on both inputs a
# nonlinearity in one variable sees a single tone and has no intermodulation to
# produce. Either mistake makes every product zero for reasons that have nothing
# to do with $limit.
DECK = """limit disto {name}
Va na 0 dc 0.65 ac 1 distof1 1 distof2 1
Vb nb 0 dc 0.60 ac 1 distof1 1 distof2 1
Rsa na a 1k
Rsb nb b 1k
N1 a b out 0 m1
.model m1 {name}(k=1e-3)
Rl out 0 1k
Ra a 0 1meg
Rb b 0 1meg
.control
pre_osdi {name}.osdi
option noacct
set numdgt=14
{ctl}
.endc
.end
"""


def run(name, ctl, tag, timeout=600):
    p = os.path.join(HERE, "_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(DECK.format(name=name, ctl=ctl))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG"
    return r.stdout + r.stderr


def products(node, out):
    return [complex(float(a), float(b)) for a, b in
            re.findall(r"^%s\[0\] = ([-\d.e+]+),\s*([-\d.e+]+)" % re.escape(node), out, re.M)]


NAMES = ["f1+f2", "f1-f2", "2f1-f2"]


def main():
    build()
    warned_any = False

    for base in SHAPES:
        node = PROBE[base]
        ctl = ("disto dec 2 1e4 1e5 0.9\nsetplot disto1\nprint %s[0]\n"
               "setplot disto2\nprint %s[0]\nsetplot disto3\nprint %s[0]"
               % (node, node, node))

        # the two spellings must be the same device before anything else means
        # anything
        ops, got, warn = {}, {}, {}
        for suf in ("_p", "_l"):
            name = "_" + base + suf
            o = run(name, "op\nprint v(%s)" % node, base + suf + "op")
            m = re.search(r"v\(%s\) = ([-\d.e+]+)" % re.escape(node), o)
            ops[suf] = float(m.group(1)) if m else None
            o = run(name, ctl, base + suf + "d")
            got[suf] = products(node, o)
            warn[suf] = "contributes no distortion" in o
        warned_any |= warn["_l"]

        if None in ops.values():
            check("%s: %s" % (base, LABEL[base]), False, "no operating point")
            continue
        if abs(ops["_p"] - ops["_l"]) > 1e-6 * max(1e-30, abs(ops["_p"])):
            check("%s: %s" % (base, LABEL[base]), False,
                  "operating points differ: %s vs %s" % (ops["_p"], ops["_l"]))
            continue

        detail, ok, live = [], True, 0
        for i, nm in enumerate(NAMES):
            if i >= len(got["_p"]) or i >= len(got["_l"]):
                detail.append("%s missing" % nm)
                ok = False
                continue
            cp, cl = got["_p"][i], got["_l"][i]
            scale = max(abs(cp), abs(cl))
            if scale < 1e-30:
                # zero is the OLD failure mode, so it only passes where the
                # mathematics requires it
                if nm == "2f1-f2" and not HAS_IM3[base]:
                    detail.append("%s zero (bilinear: no 3rd derivative)" % nm)
                else:
                    detail.append("%s BOTH ZERO" % nm)
                    ok = False
                continue
            live += 1
            rel = abs(cp - cl) / scale          # complex: catches a sign flip
            if rel >= 1e-6:
                ok = False
            detail.append("%s rel %.1e" % (nm, rel))
        if live == 0:
            ok = False
            detail.append("nothing non-zero to compare")
        check("%s: %s" % (base, LABEL[base]), ok, "; ".join(detail))

    # A limiting model must no longer be reported as contributing nothing --
    # that report was correct before Enhancement-353 and is the regression this
    # guards.
    check("a limiting model is no longer reported as contributing no distortion",
          not warned_any, "silent" if not warned_any else "STILL WARNS")

    # Shape E is only meaningful if reversing the branch actually changes the
    # answer; if E and B agreed the negated chain entry would be untested.
    e = products("out", run("_lmE_l", "disto dec 2 1e4 1e5 0.9\nsetplot disto1\n"
                            "print out[0]", "sgnE"))
    b = products("out", run("_lmB_l", "disto dec 2 1e4 1e5 0.9\nsetplot disto1\n"
                            "print out[0]", "sgnB"))
    ok = bool(e) and bool(b) and abs(e[0]) > 1e-30 and \
        abs(e[0] + b[0]) < 1e-9 * abs(e[0])     # exact negatives of each other
    check("the reversed-branch shape is the exact negative of the forward one",
          ok, "E %s vs B %s" % ("%.6e" % e[0].real if e else None,
                                "%.6e" % b[0].real if b else None))

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
