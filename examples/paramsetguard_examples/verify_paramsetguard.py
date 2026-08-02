#!/usr/bin/env python3
"""Enhancement-398: four defects in `paramset`, all of them silent.

A `paramset` (Enhancement-21) wraps a module and binds some of its parameters —
it is how a PDK ships a validated, pre-configured view of a compact model. Every
*other* way of supplying a parameter value is checked. This one was not.

  [1] `paramset` WAS THE ONLY SUPPLY PATH THAT BYPASSED RANGE VALIDATION.

      With `parameter real k = 1.0 from (0:inf);` in the target,

          paramset dut basemod; .k = -1.0; endparamset

      put **-1.0 into the model** and neither the compiler nor ngspice said a
      word. Every other route rejects it and aborts with "Parameter k is out of
      bounds!" — a model card, an instance line, `alter`, `altermod`, a `.param`,
      and a subcircuit parameter. Six paths enforced the range; one did not.

      The mechanism: binding an override turns the target parameter into a
      localparam, and `param_body_with_sourcemap` returned `bounds: Vec::new()`
      for it, so the constraint was discarded before anything could check it.
      `insert_param_init` then had nothing to emit, and because a localparam is
      not settable, ngspice's runtime validation never saw it either.

      The check now runs where the override and the target's constraints are
      both still syntax. It folds **literal values only** — an override built
      from the paramset's own (netlist-settable) parameters is not knowable
      there, and pretending otherwise would reject legitimate paramsets.

      This does NOT conflict with [Enhancement-56](../../enhancements_doc/Enhancement-56.md),
      which deliberately refuses to range-check a parameter's DEFAULT so that
      CMC models can use an out-of-range default to mean "feature disabled". A
      paramset override is a *supplied value*, not a default, and a range exists
      precisely to bind those.

  [2] AN OVERRIDE NAMING A PARAMETER THE TARGET DOES NOT DECLARE WAS DROPPED IN
      SILENCE. The binder looks the name up among the target's parameters; a
      name that matches nothing simply never bound anything. The netlist path
      reports the same mistake ("unrecognized parameter (...) - ignored"), and
      [Enhancement-392](../../enhancements_doc/Enhancement-392.md) established
      exactly this check for `#(.param())` on module instantiation.

  [3] THE SAME PARAMETER ASSIGNED TWICE WAS ACCEPTED, and the **first**
      assignment won — the binder takes the first match. Nothing said the second
      had been discarded.
      [Enhancement-395](../../enhancements_doc/Enhancement-395.md) reports this
      for netlist lines.

  [4] `$param_given` REPORTED FALSE FOR A PARAMSET-SUPPLIED VALUE.

      | how `g` is supplied | model receives | `$param_given(g)` |
      | --- | --- | --- |
      | netlist `basemod(g=5e-3)` | 0.005 | given |
      | paramset `.g = 5e-3`      | 0.005 | **NOT given** |
      | nobody                    | 0.001 | NOT given |

      A bound parameter is a localparam, so it has no runtime given-flag and
      `ParamGiven` resolved to false. `$param_given` is the standard CMC idiom
      for "did the user specify this, or is this my default?" — typically to
      derive one parameter from another only when the user did not set it.
      Through a paramset every such derivation silently took the default branch
      while the model ran the paramset's value.

      It reports `given` now. An ordinary `localparam`, which nobody supplied,
      still reports not-given.

SCOPE, stated rather than hidden: paramset *binning* clauses (`.w from [0:10]`,
LRM 6.4 — selecting among several paramsets by device geometry) remain
unsupported and are a clean parse error. That is a missing feature, not a
silently wrong answer, and it is not what this release is about.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
HDR = '`include "disciplines.vams"\n'

TARGET = """module basemod(p,n);
 inout p,n; electrical p,n;
 parameter real g = 1e-3;
 parameter real k = 1.0 from (0:inf);
 parameter integer n2 = 1 from [1:3];
 parameter real ex = 2.0 exclude 5.0;
 parameter real cl = 1.0 from [0:10];
 (* desc="kk" *) real kk;
 (* desc="gg" *) real gg;
 (* desc="pg" *) real pg;
 analog begin
   kk = k; gg = g;
   pg = $param_given(g) ? 1.0 : 0.0;
   I(p,n) <+ V(p,n)*g*k;
 end
endmodule
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_op_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def run(d, deck, guard=40):
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", f"alarm {guard}; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def op(d, card, opvars=("gg", "kk", "pg")):
    pv = " ".join(f"@n1[{v}]" for v in opvars)
    rc, out = run(d, ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nN1 a 0 mm\n"
                      f".model mm {card}\n.control\noption noacct\nset numdgt=12\nop\n"
                      f"print i(v1) {pv}\n.endc\n.end\n"))
    res = {"rc": rc, "out": out}
    for v in opvars:
        m = re.search(rf"@n1\[{v}\]\s*=\s*([-+0-9.eE]+)", out)
        res[v] = float(m.group(1)) if m else None
    return res


def ps(body):
    return HDR + TARGET + f"paramset dut basemod; {body} endparamset\n"


def main():
    # =============================================== [1] range enforcement
    print("\n  -- [1] a paramset override is range-checked --")
    REJECT = [
        ("k = -1.0 against `from (0:inf)`", ".k = -1.0;"),
        ("k = 0.0 on an OPEN lower bound", ".k = 0.0;"),
        ("n2 = 9 against `from [1:3]`", ".n2 = 9;"),
        ("n2 = 0 below `from [1:3]`", ".n2 = 0;"),
        ("ex = 5.0 against `exclude 5.0`", ".ex = 5.0;"),
        ("cl = 10.1 above `from [0:10]`", ".cl = 10.1;"),
        ("cl = -0.1 below `from [0:10]`", ".cl = -0.1;"),
    ]
    for label, body in REJECT:
        d, rc, out = build(ps(body), "r")
        check(f"{label} is rejected", rc != 0,
              (out.strip().splitlines() or [""])[0][:58])
        check(f"{label}: the message names the value and the range",
              "paramset assigns" in out and ("range" in out or "exclude" in out), "")

    ACCEPT = [
        ("k = 2.0, inside the range", ".k = 2.0;", None),
        ("cl = 10, the CLOSED upper bound", ".cl = 10;", None),
        ("cl = 0, the CLOSED lower bound", ".cl = 0;", None),
        ("g = 5e-3, no range declared", ".g = 5e-3;", 5e-3),
        ("ex = 6.0, outside the excluded value", ".ex = 6.0;", None),
    ]
    for label, body, want_g in ACCEPT:
        d, rc, out = build(ps(body), "a")
        check(f"{label} still compiles", rc == 0,
              (out.strip().splitlines() or [""])[0][:58])
        if rc == 0 and want_g is not None:
            r = op(d, "dut()")
            check(f"{label}: the value reaches the model", r["gg"] == want_g, f"{r['gg']}")

    # an override built from the paramset's own parameters is not folded
    d, rc, out = build(ps("parameter real s = 2.0; .k = s;"), "expr")
    check("an override that is an EXPRESSION is not folded (stated boundary)",
          rc == 0, (out.strip().splitlines() or [""])[0][:58])

    # the same violations by every OTHER route must still be caught
    print("\n     every other supply path was already checked -- confirm it still is")
    d, rc, out = build(ps(".g = 1e-3;"), "other")
    if rc == 0:
        for label, card in [("model card k=-1", "dut(k=-1)"), ("model card n2=9", "dut(n2=9)"),
                            ("model card ex=5", "dut(ex=5)")]:
            r = op(d, card)
            check(f"  {label} is still rejected at run time",
                  "out of bounds" in r["out"] or r["kk"] is None,
                  (["", "value reached the model"][r["kk"] is not None]))

    # =============================================== [2] unknown parameter
    print("\n  -- [2] an override naming no target parameter --")
    d, rc, out = build(ps(".nosuch = 1.0;"), "unk")
    check("an unknown parameter name is rejected", rc != 0,
          (out.strip().splitlines() or [""])[0][:58])
    check("the message names both the parameter and the target module",
          "nosuch" in out and "basemod" in out, "")
    d, rc, out = build(ps(".g = 5e-3;"), "known")
    check("a valid name still compiles", rc == 0,
          (out.strip().splitlines() or [""])[0][:58])

    # =============================================== [3] duplicate override
    print("\n  -- [3] the same parameter assigned twice --")
    d, rc, out = build(ps(".g = 1e-3; .g = 9e-3;"), "dup")
    check("a duplicate assignment is rejected", rc != 0,
          (out.strip().splitlines() or [""])[0][:58])
    check("the message says which parameter", "more than once" in out and "'g'" in out, "")
    d, rc, out = build(ps(".g = 1e-3; .k = 2.0;"), "twodiff")
    check("two DIFFERENT parameters still compile", rc == 0,
          (out.strip().splitlines() or [""])[0][:58])

    # =============================================== [4] $param_given
    print("\n  -- [4] $param_given through a paramset --")
    d, rc, out = build(HDR + TARGET + "paramset dut basemod; .g = 5e-3; endparamset\n", "pg_ps")
    check("the paramset model compiles", rc == 0, (out.strip().splitlines() or [""])[0][:58])
    if rc == 0:
        r = op(d, "dut()")
        check("a paramset-supplied value reaches the model", r["gg"] == 5e-3, f"{r['gg']}")
        check("and $param_given reports GIVEN", r["pg"] == 1.0, f"{r['pg']}")

    d, rc, out = build(HDR + TARGET, "pg_plain")
    if rc == 0:
        r = op(d, "basemod(g=5e-3)")
        check("a netlist-supplied value still reports GIVEN", r["pg"] == 1.0, f"{r['pg']}")
        r = op(d, "basemod()")
        check("nobody supplying it still reports NOT given", r["pg"] == 0.0, f"{r['pg']}")
        check("and the default is what the model runs", r["gg"] == 1e-3, f"{r['gg']}")

    d, rc, out = build(HDR + TARGET + "paramset dut basemod; endparamset\n", "pg_none")
    if rc == 0:
        r = op(d, "dut(g=7e-3)")
        check("a paramset that binds nothing: the netlist value still reports GIVEN",
              r["pg"] == 1.0 and r["gg"] == 7e-3, f"g={r['gg']} pg={r['pg']}")
        r = op(d, "dut()")
        check("a paramset that binds nothing and no netlist value: NOT given",
              r["pg"] == 0.0, f"{r['pg']}")

    # =============================================== paramset still works
    print("\n  -- the feature itself is unchanged --")
    d, rc, out = build(HDR + TARGET + "paramset dut basemod; .g = 5e-3; .k = 2.0; endparamset\n",
                       "works")
    if rc == 0:
        r = op(d, "dut()")
        check("a two-parameter paramset gives g*k = 1.0e-02",
              r["gg"] == 5e-3 and r["kk"] == 2.0, f"g={r['gg']} k={r['kk']}")
    d, rc, out = build(HDR + TARGET
                       + "paramset mid basemod; .g = 1e-3; endparamset\n"
                       + "paramset dut mid; .k = 4.0; endparamset\n", "chain")
    check("a paramset of a paramset still compiles", rc == 0,
          (out.strip().splitlines() or [""])[0][:58])
    if rc == 0:
        r = op(d, "dut()")
        check("  and both bindings take effect", r["gg"] == 1e-3 and r["kk"] == 4.0,
              f"g={r['gg']} k={r['kk']}")

    for j in os.listdir(HERE):
        if j.startswith("_op_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    return 0 if passed == checks else 1


sys.exit(main())
