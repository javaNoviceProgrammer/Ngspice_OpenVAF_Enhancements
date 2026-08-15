#!/usr/bin/env python3
"""Enhancement-461: string-parameter set selection, and the value that reaches it.

Reported from the field: `parameter string ty = "NMOS" from '{"NMOS","PMOS"};`
does not work -- a legal member is rejected at setup with "Parameter ty is out
of bounds!". Two independent defects were behind it, one in each code base.

  [1] ONLY THE FIRST MEMBER OF THE SET WAS EVER ENFORCED (openvaf-r).

      LRM 3.4.2 gives string parameters their own range form: "The from keyword
      may be used with a list of valid string values, or the exclude keyword may
      be used with a list of invalid string values ... constructed using an
      assignment pattern".

      The parser reads the whole list -- `expr(p)` then `while p.eat(T![,])` --
      so every member lands in the syntax tree. The AST accessor then threw the
      rest away:

          Some(ConstraintValue::Val(self.expr()?))   // support::child -> FIRST

      so `from '{"aaa","bbb","ccc"}` accepted only "aaa" and rejected "bbb" and
      "ccc", its own members. Reordering the list changed which single value was
      legal. `exclude` failed the DANGEROUS way round: with
      `exclude '{"aaa","bbb"}` the value "bbb" -- explicitly forbidden by the
      model -- was silently ACCEPTED. Nothing warned, because from the
      compiler's point of view the set simply had one member.

      This is Enhancement-429's shape: elements parsed, attached, and dropped by
      the accessor, with the errors hiding in what was dropped.

      A set now becomes ONE ParamConstraint PER MEMBER, which is exactly what
      `check_param` already wanted: `From` jumps to the ok-exit on any match and
      only calls `invalid` on fallthrough, `Exclude` calls `invalid` on any
      match. Numeric sets (`from '{1,2,3}`) had the identical bug and are fixed
      by the same change.

  [2] THE VALUE ITSELF WAS CORRUPTED BEFORE THE MODEL SAW IT (ngspice).

      `.model mm dut(ty="PMOS")` reached the model as `pmos`, and
      `ty="with space"` as `with` -- the remainder then reported as
      "unrecognized parameter (space)". So even a correct set check could not
      have matched a mixed-case member.

      Two causes. The netlist reader lower-cases whole lines, with case
      retention wired only to Cider `.model` cards, `ic.file`, and a fixed list
      of XSPICE code models -- an OSDI model card matched none of them. And
      `inp_casefix` turns quotes into SPACES unless the line is `.param`,
      `.subckt` or an X line, which cut the value at its first space.

      A quoted value on a model card or device instance line is DATA -- a
      selector compared with `==`, a file name, a `from` set member -- not an
      identifier SPICE may fold. Both paths now keep it verbatim.

The suite checks the SET semantics through a real simulation (a member must be
accepted, a non-member refused) and the VALUE the model receives, because either
defect alone reproduces the report.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

HDR = '`include "disciplines.vams"\n'
N = [0]
OK = [0]
Q = '"'


def check(label, ok, detail=""):
    N[0] += 1
    if ok:
        OK[0] += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {label:54s} {detail[:30]}")


def build(decl, tag, body=None):
    d = os.path.join(HERE, "_w_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    src = (HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n" + decl
           + ' analog begin @(initial_step) $strobe("SEES [%s]", ty);\n'
           "  I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n")
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900,
                       stdin=subprocess.DEVNULL)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def run(d, card="dut()", net="N1 a 0 mm"):
    deck = ("p\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\n" + net + "\n.model mm " + card
            + "\n.control\noption noacct\nop\n.endc\n.end\n")
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL)
    out = (r.stdout or "") + (r.stderr or "")
    seen = re.findall(r"SEES \[([^\]]*)\]", out)
    refused = any("out of bounds" in l for l in out.splitlines())
    return (seen[0] if seen else None), refused, out


LIST3 = ",".join(Q + x + Q for x in ("aaa", "bbb", "ccc"))
REV3 = ",".join(Q + x + Q for x in ("ccc", "bbb", "aaa"))

print("\n[1] a `from` set accepts EVERY member, not just the first")
d, rc, out = build(f' parameter string ty = "aaa" from \'{{{LIST3}}};\n', "from3")
check("the model compiles", rc == 0, (out.strip().splitlines() or [""])[0][:28])
for v in ("aaa", "bbb", "ccc"):
    seen, refused, _ = run(d, f'dut() ty="{v}"')
    check(f'ty="{v}" is accepted and arrives intact', (not refused) and seen == v, f"seen={seen!r}")
seen, refused, _ = run(d, 'dut() ty="zzz"')
check('ty="zzz" (not a member) is refused', refused, f"seen={seen!r}")

print("\n[2] the order the set is written in does not decide anything")
d, rc, _o = build(f' parameter string ty = "aaa" from \'{{{REV3}}};\n', "rev3")
for v in ("aaa", "bbb", "ccc"):
    seen, refused, _ = run(d, f'dut() ty="{v}"')
    check(f'reversed list, ty="{v}" is accepted', (not refused) and seen == v, f"seen={seen!r}")

print("\n[3] an `exclude` set refuses EVERY member -- the silent-acceptance half")
d, rc, _o = build(f' parameter string ty = "zzz" exclude \'{{{Q}aaa{Q},{Q}bbb{Q}}};\n', "ex2")
for v in ("aaa", "bbb"):
    seen, refused, _ = run(d, f'dut() ty="{v}"')
    check(f'ty="{v}" (excluded) is refused', refused, f"seen={seen!r}")
seen, refused, _ = run(d, 'dut() ty="ccc"')
check('ty="ccc" (not excluded) is accepted', (not refused) and seen == "ccc", f"seen={seen!r}")

print("\n[4] numeric sets had the identical defect")
for tag, decl, vals in [
        ("intset", ' parameter integer ty = 1 from \'{1,2,3};\n string s;\n', ("1", "2", "3")),
        ("realset", ' parameter real ty = 1.0 from \'{1.0,2.0,3.0};\n string s;\n', ("1.0", "2.0", "3.0"))]:
    d = os.path.join(HERE, "_w_" + tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(
        HDR + "module dut(p,n);\n inout p,n; electrical p,n;\n" + decl
        + " analog I(p,n) <+ V(p,n)*1e-3;\nendmodule\n")
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                   capture_output=True, text=True, env=env, cwd=d, stdin=subprocess.DEVNULL)
    for v in vals:
        _s, refused, _o = run(d, f"dut() ty={v}")
        check(f"{tag}: ty={v} (a member) is accepted", not refused, "")
    _s, refused, _o = run(d, "dut() ty=9")
    check(f"{tag}: ty=9 (not a member) is refused", refused, "")

print("\n[5] the value reaches the model verbatim -- case, spaces and all")
d, rc, _o = build(' parameter string ty = "Default";\n', "val")
for card, want in [('dut()', 'Default'),
                   ('dut() ty="PMOS"', 'PMOS'),
                   ('dut() ty="MixedCase"', 'MixedCase'),
                   ('dut() ty="File_Name.TBL"', 'File_Name.TBL'),
                   ('dut() ty="with space"', 'with space'),
                   ('dut() ty="UPPER lower 123"', 'UPPER lower 123')]:
    seen, _r, _o = run(d, card)
    check(f"model card {card[5:]:28s}", seen == want, f"{seen!r}")
# a `.model` split across a continuation line
open(os.path.join(d, "q.cir"), "w").write(
    "p\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nN1 a 0 mm\n"
    '.model mm dut(\n+ ty="Mixed Case" )\n.control\noption noacct\nop\n.endc\n.end\n')
r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", NGSPICE, "-b", "q.cir"],
                   cwd=d, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL)
seen = re.findall(r"SEES \[([^\]]*)\]", (r.stdout or "") + (r.stderr or ""))
check("a .model split over a continuation line", seen and seen[0] == "Mixed Case",
      f"{seen[0] if seen else None!r}")

print("\n[6] the same on a device INSTANCE line")
d, rc, _o = build(' (*type="instance"*) parameter string ty = "Default";\n', "inst")
for net, want in [('N1 a 0 mm', 'Default'),
                  ('N1 a 0 mm ty="PMOS"', 'PMOS'),
                  ('N1 a 0 mm ty="Mixed Case"', 'Mixed Case')]:
    seen, _r, _o = run(d, "dut()", net)
    check(f"instance {net[9:]:30s}", seen == want, f"{seen!r}")

print("\n[7] the reported model, end to end")
d, rc, _o = build(' parameter string ty = "NMOS" from \'{"NMOS","PMOS","BJT"};\n', "report")
for v in ("NMOS", "PMOS", "BJT"):
    seen, refused, _o = run(d, f'dut() ty="{v}"')
    check(f'ty="{v}" selects and arrives as written', (not refused) and seen == v, f"{seen!r}")
seen, refused, _o = run(d, 'dut() ty="JFET"')
check('ty="JFET" (not in the set) is refused', refused, "")

for j in os.listdir(HERE):
    if j.startswith("_w_"):
        shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
ok = OK[0] == N[0]
print(f"\n{'ALL PASS' if ok else 'FAILURES'}: {OK[0]}/{N[0]} passed")
sys.exit(0 if ok else 1)
