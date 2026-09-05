#!/usr/bin/env python3
"""Enhancement-555: a machine write leaves givenness alone, and a default is
judged against a range that moved.

F1 of the 2026-09-05 hunt. The descriptor's access() marks a parameter GIVEN
on every write. An `.option osdimc` draw, and the restore after a `.dc` or
`sweep` of the parameter, went through it, so a parameter the deck never gave
came out given -- and a model that picks a default with $param_given (BSIM4:
toxp = toxe - dtox when toxp is not given) ran its "given" branch at the
declared default from trial 2 on, and after any sweep: a 0.003% sigma on toxp
cost 32% of the drain current. Now the compiler exports which statistical
parameters the model tests with $param_given (OSDI_DIST_GATED) and a
per-descriptor given-flag entry point (OSDI_PARAM_GIVEN_FNS); the simulator
draws a gated parameter only when the deck gave it and says so once, and
every sweep restore puts the flag back as it found it.

F2 of the same hunt. The compiled setup judged a parameter's range only when
the parameter was given: `l = 1.2 from [lmin:inf)` with lmin altered, swept
or drawn to 1.5 ran with l below its bound. A default whose bounds read
another parameter is now judged at setup (the E-56 exemption for a constant
default outside a constant range -- the CMC "feature off" idiom -- stands).

Checks (both solvers):
  [1]  the objects export OSDI_PARAM_GIVEN_FNS
  [2]  a gated parameter the deck never gave is not drawn: $param_given stays 0, the derived default stays, the note prints once
  [3]  the same parameter given on the card is drawn, as before
  [4]  per instance: the instance without the parameter on its line is not drawn, the one with it is
  [5]  a dc sweep of a defaulted parameter leaves it not-given afterwards (sens never flipped it)
  [6]  the sweep command and a dc sweep of an instance-typed parameter do the same
  [7]  BSIM4, toxp derived from toxe: the drain current is the same on every trial and the note names toxp
  [8]  BSIM4 with toxp on the card: drawn
  [9]  BSIM4: a dc sweep of toxp leaves the drain current where it was
  [10] montecarlo -expr on the gated deck records the nominal, not a switched model
  [11] F2: altermod of the bound parameter refuses the defaulted l; given l is refused as before
  [12] F2: a dc sweep of the bound parameter stops at the first point that moves the bound past l
  [13] F2: osdimc draws of the bound parameter fail the trials that move it past l
  [14] F2: E-546 path -- a model parameter defaulted against an instance-read bound is judged per instance
  [15] F2: a constant default outside its own constant range still runs (E-56), with lint L027 at compile time
  [16] an object compiled without the entry point (a pre-E-555 compiler from git) still loads and draws
  [17] E-558: .save of a model card's parameter records it per point; an unknown one warns
  [18] E-558: the out-of-bounds message says the declared range and the value of the parameter that moved it
"""

import atexit
import os
import platform
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)

ROOT = os.path.dirname(os.path.dirname(HERE))
BSIM4 = os.path.join(ROOT, "VA_TEST", "VA-Models-main", "code", "bsim4", "vacode", "bsim4.va")
# A compiler from BEFORE this enhancement, for the old-object case: the prebuilt
# binary committed at the E-554 release, taken from the repository's history
# (the CI republishes bin/ after every push, so the working tree's copy is
# current and cannot play the old one). macOS on Apple silicon only.
OLD_REF = "Enhancement-554_osdidist"
OLD_BIN = "bin/macos/apple-silicon/openvaf-r"


def old_compiler():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return None
    dst = os.path.join(HERE, "_pg_oldvaf")
    r = subprocess.run(["git", "-C", ROOT, "show", f"{OLD_REF}:{OLD_BIN}"],
                       capture_output=True, timeout=120)
    if r.returncode != 0 or len(r.stdout) < 1000000:
        return None
    with open(dst, "wb") as f:
        f.write(r.stdout)
    os.chmod(dst, 0o755)
    return dst


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_pg_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


HEAD = '`include "disciplines.vams"\nmodule %s(a,b); inout a,b; electrical a,b;\n'


def compile_va(name, params, body="analog I(a,b) <+ V(a,b)/r;", compiler=OPENVAF):
    va = os.path.join(HERE, f"_pg_{name}.va")
    osdi = os.path.join(HERE, f"_pg_{name}.osdi")
    with open(va, "w") as f:
        f.write(HEAD % name + params + "\n" + body + "\nendmodule\n")
    r = subprocess.run([compiler, va, "-o", osdi], cwd=HERE, capture_output=True,
                       text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr, osdi


def run(deck, tag, timeout=600):
    p = os.path.join(HERE, f"_pg_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


def seq(out, name):
    vals = []
    for m in re.finditer(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    return vals


GATED = ('(* std=25.0 *) parameter real r = 1000.0 from (0:inf);\n'
         '(* desc="param_given(r)" *) real pg;\n'
         '(* desc="effective r" *) real reff;')
GATED_BODY = ("analog begin\n  pg = $param_given(r) ? 1.0 : 0.0;\n"
              "  reff = $param_given(r) ? r : 2000.0;\n  I(a,b) <+ V(a,b)/reff;\nend")

print("Enhancement-555: givenness survives machine writes; a default is judged against a moved bound\n")

rc, log, VPG = compile_va("vpg", GATED, GATED_BODY)
rc2, _, VPGI = compile_va("vpgi", GATED.replace("(* std=25.0 *)", '(* type="instance", std=25.0 *)'),
                          GATED_BODY)
assert rc == 0 and rc2 == 0, log
nm = subprocess.run(["nm", VPG], capture_output=True, text=True).stdout
check("[1] the objects export OSDI_PARAM_GIVEN_FNS", "OSDI_PARAM_GIVEN_FNS" in nm)

DECK = """pg {tag}
V1 a 0 1
N1 a 0 mm {inst}
.model mm {model}
.control
pre_osdi _pg_{obj}.osdi
{body}
.endc
.end
"""


def gated_deck(tag, body, model="vpg", obj="vpg", inst=""):
    return DECK.format(tag=tag, body=body, model=model, obj=obj, inst=inst)


out = run(gated_deck("g1", "set osdimc\nset mcseed=5\nrepeat 4\n  op\n  print @n1[pg] @n1[reff] @mm[r]\nend"), "g1")
check("[2] a gated parameter the deck never gave is not drawn: pg stays 0, reff stays 2000, the note prints once",
      seq(out, "@n1[pg]") == [0.0] * 4 and seq(out, "@n1[reff]") == [2000.0] * 4
      and seq(out, "@mm[r]") == [1000.0] * 4 and out.count("not drawn") == 1
      and "tests $param_given(r)" in out, out.strip()[-200:])
out = run(gated_deck("g2", "set osdimc\nset mcseed=5\nrepeat 3\n  op\n  print @n1[pg] @n1[reff]\nend",
                     model="vpg r=1000"), "g2")
reff = seq(out, "@n1[reff]")
check("[3] the same parameter given on the card is drawn, as before",
      seq(out, "@n1[pg]") == [1.0] * 3 and len(reff) == 3 and reff[0] == 1000.0
      and reff[1] != 1000.0 and "not drawn" not in out, f"reff={reff}")
out = run("pg g3\nV1 a 0 1\nN1 a 0 mm\nN2 a 0 mm r=500\n.model mm vpgi\n.control\npre_osdi _pg_vpgi.osdi\n"
          "set osdimc\nset mcseed=5\nrepeat 3\n  op\n  print @n1[pg] @n1[reff] @n2[pg] @n2[reff]\nend\n.endc\n.end\n", "g3")
r2 = seq(out, "@n2[reff]")
check("[4] per instance: the instance without the parameter on its line is not drawn, the one with it is",
      seq(out, "@n1[pg]") == [0.0] * 3 and seq(out, "@n1[reff]") == [2000.0] * 3
      and seq(out, "@n2[pg]") == [1.0] * 3 and len(r2) == 3 and r2[1] != 500.0
      and out.count("not drawn") == 1, f"n2 reff={r2}")

out = run(gated_deck("g5", "op\nprint @n1[pg]\ndc @mm[r] 900 1100 100\nop\nprint @n1[pg] @n1[reff]\n"
                     "reset\nop\nsens i(v1)\nop\nprint @n1[pg]"), "g5")
check("[5] a dc sweep of a defaulted parameter leaves it not-given afterwards (sens never flipped it)",
      seq(out, "@n1[pg]") == [0.0, 0.0, 0.0] and seq(out, "@n1[reff]") == [2000.0], out.strip()[-160:])
out = run(gated_deck("g6", "op\nsweep @mm[r] 900 1100 100 -analysis op -output i(v1)\nop\nprint @n1[pg] @n1[reff]"), "g6")
out2 = run("pg g6b\nV1 a 0 1\nN1 a 0 mm\n.model mm vpgi\n.control\npre_osdi _pg_vpgi.osdi\nop\n"
           "dc @n1[r] 900 1100 100\nop\nprint @n1[pg] @n1[reff]\n.endc\n.end\n", "g6b")
check("[6] the sweep command and a dc sweep of an instance-typed parameter do the same",
      seq(out, "@n1[pg]") == [0.0] and seq(out, "@n1[reff]") == [2000.0]
      and seq(out2, "@n1[pg]") == [0.0] and seq(out2, "@n1[reff]") == [2000.0],
      (out + out2).strip()[-160:])

# ------------------------------------------------------------- BSIM4 ---
if os.path.isfile(BSIM4):
    src = open(BSIM4).read()
    # statistics on toxp, a parameter BSIM4 derives from toxe when not given
    src = re.sub(r"^(\s*)(`MPRcc\(\s*toxp\b)", r"\1(* std=1e-13 *) \2", src, count=1, flags=re.M)
    b4dir = os.path.dirname(BSIM4)
    va = os.path.join(b4dir, "_pg_bsim4.va")
    with open(va, "w") as f:
        f.write(src)
    osdi = os.path.join(HERE, "_pg_bsim4.osdi")
    r = subprocess.run([OPENVAF, va, "-o", osdi], cwd=b4dir, capture_output=True, text=True, timeout=600)
    os.remove(va)
    assert r.returncode == 0, r.stdout + r.stderr
    B4 = ("pg {tag}\nvdd vdd 0 dc 1.2\nrload vdd d 1k\nvg g 0 dc 0.6\nn1 d g 0 0 mos_va\n"
          ".model mos_va bsim4va({card})\n.control\npre_osdi _pg_bsim4.osdi\n{body}\n.endc\n.end\n")
    out = run(B4.format(tag="b1", card="toxe=2e-9",
                        body="set osdimc\nset mcseed=5\nrepeat 3\n  op\n  print i(vdd)\nend"), "b1")
    idd = seq(out, "i(vdd)")
    check("[7] BSIM4, toxp derived from toxe: the drain current is the same on every trial and the note names toxp",
          len(idd) == 3 and max(idd) - min(idd) < 1e-12 and abs(idd[0] + 1.12387e-4) < 1e-8
          and "mos_va:toxp is not given" in out and out.count("not drawn") == 1, f"i(vdd)={idd}")
    out = run(B4.format(tag="b2", card="toxe=2e-9 toxp=2e-9",
                        body="set osdimc\nset mcseed=5\nrepeat 3\n  op\n  print i(vdd)\nend"), "b2")
    idd = seq(out, "i(vdd)")
    check("[8] BSIM4 with toxp on the card: drawn",
          len(idd) == 3 and idd[1] != idd[0] and "not drawn" not in out, f"i(vdd)={idd}")
    out = run(B4.format(tag="b3", card="toxe=2e-9",
                        body="op\nprint i(vdd)\ndc @mos_va[toxp] 2.5e-9 3.5e-9 0.5e-9\nop\nprint i(vdd)"), "b3")
    idd = seq(out, "i(vdd)")
    check("[9] BSIM4: a dc sweep of toxp leaves the drain current where it was",
          len(idd) == 2 and abs(idd[0] - idd[1]) < 1e-12 and abs(idd[0] + 1.12387e-4) < 1e-8, f"i(vdd)={idd}")
    out = run(B4.format(tag="b4", card="toxe=2e-9",
                        body="set osdimc\nset mcseed=5\nop\nmontecarlo 3 -seed 1 -analysis op -expr id=i(vdd)\n"
                             "setplot $montecarlo_plot\nprint id"), "b4")
    ids = [float(m.group(1)) for m in re.finditer(r"^\d+\s+(\S+)", out, re.M)]
    check("[10] montecarlo -expr on the gated deck records the nominal, not a switched model",
          len(ids) == 3 and all(abs(v + 1.12387e-4) < 1e-8 for v in ids), f"id={ids}")
else:
    for k in (7, 8, 9, 10):
        check(f"[{k}] (BSIM4 source not found; skipped)", True)

# ---------------------------------------------------------------- F2 ---
rc, log, _ = compile_va("vdep", '(* std=0.6 *) parameter real lmin = 1.0 from (0:inf);\n'
                        'parameter real l = 1.2 from [lmin:inf);', "analog I(a,b) <+ V(a,b)*l/1000.0;")
assert rc == 0, log
F2 = "pg {tag}\nV1 a 0 1\nN1 a 0 mm\n.model mm {model}\n.control\npre_osdi _pg_vdep.osdi\n{body}\n.endc\n.end\n"
out = run(F2.format(tag="f1", model="vdep", body="op\naltermod mm lmin=1.5\nop\necho after"), "f1")
out2 = run(F2.format(tag="f1b", model="vdep l=1.2", body="op\naltermod mm lmin=1.5\nop\necho after"), "f1b")
check("[11] F2: altermod of the bound parameter refuses the defaulted l; given l is refused as before",
      out.count("Parameter l of 'mm' is out of bounds (value 1.2;") == 1 and "after" in out
      and out2.count("Parameter l of 'mm' is out of bounds (value 1.2;") == 1, (out + out2).strip()[-200:])
out = run(F2.format(tag="f2", model="vdep", body="dc @mm[lmin] 0.5 2.0 0.5\nprint @mm[lmin] i(v1)\necho after"), "f2")
rows = re.findall(r"^\d+\s+(\S+)\s+", out, re.M)
check("[12] F2: a dc sweep of the bound parameter stops at the first point that moves the bound past l",
      "out of bounds (value 1.2;" in out and "after" in out and len(rows) <= 2, out.strip()[-200:])
out = run(F2.format(tag="f3", model="vdep", body="set osdimc\nset mcseed=11\nrepeat 8\n  op\nend\necho after"), "f3")
nfail = out.count("out of bounds (value 1.2;")
check("[13] F2: osdimc draws of the bound parameter fail the trials that move it past l",
      nfail >= 2 and "FAILED during setup" in out and "after" in out, f"{nfail} trials refused")
rc, log, _ = compile_va("vinst", '(* type="instance" *) parameter real w = 1.0 from (0:inf);\n'
                        'parameter real l = 2.0 from (0:w];', "analog I(a,b) <+ V(a,b)*w/l/1000.0;")
assert rc == 0, log
out = run("pg f4\nV1 a 0 1\nN1 a 0 mm w=1\n.model mm vinst\n.control\npre_osdi _pg_vinst.osdi\nop\necho after\n.endc\n.end\n", "f4")
out2 = run("pg f4b\nV1 a 0 1\nN1 a 0 mm w=3\n.model mm vinst\n.control\npre_osdi _pg_vinst.osdi\nop\nprint i(v1)\n.endc\n.end\n", "f4b")
check("[14] F2: E-546 path -- a model parameter defaulted against an instance-read bound is judged per instance",
      "Parameter l of 'n1' is out of bounds (value 2;" in out and "after" in out
      and abs(seq(out2, "i(v1)")[0] + 1.5e-3) < 1e-9, (out + out2).strip()[-160:])
rc, log, _ = compile_va("vbad", 'parameter real x = 0.0 from (0:inf);\nparameter real r = 1000.0;',
                        "analog I(a,b) <+ V(a,b)/r + V(a,b)*x;")
out = run("pg f5\nV1 a 0 1\nN1 a 0 mm\n.model mm vbad\n.control\npre_osdi _pg_vbad.osdi\nop\nprint i(v1)\n.endc\n.end\n", "f5")
check("[15] F2: a constant default outside its own constant range still runs (E-56), with lint L027 at compile time",
      rc == 0 and "L027" in log and "out of bounds" not in out and abs(seq(out, "i(v1)")[0] + 1e-3) < 1e-9,
      out.strip()[-120:])

# ------------------------------------------------------- old object ---
PREBUILT = old_compiler()
if PREBUILT:
    rc, log, OLD = compile_va("vold", '(* std=25.0 *) parameter real r = 1000.0;', compiler=PREBUILT)
    out = run(gated_deck("o1", "set osdimc\nset mcseed=5\nrepeat 3\n  op\n  print @mm[r]\nend",
                         model="vold", obj="vold"), "o1")
    vals = seq(out, "@mm[r]")
    check("[16] an object compiled without the entry point (a pre-E-555 compiler from git) still loads and draws",
          rc == 0 and "OSDI_PARAM_GIVEN_FNS" not in subprocess.run(["nm", OLD], capture_output=True, text=True).stdout
          and len(vals) == 3 and vals[0] == 1000.0 and vals[1] != 1000.0 and "not drawn" not in out, f"r={vals}")
else:
    check("[16] (no pre-E-555 compiler for this platform; skipped)", True)

# ------------------------------------------------------ E-558: F11, F9 ---
out = run("pg s1\nV1 a 0 1\nN1 a 0 mm\n.model mm vpg r=1000\n.save @mm[r] @n1[reff] v(a) @mm[nosuch]\n.control\n"
          "pre_osdi _pg_vpg.osdi\ntran 1u 3u\nprint @mm[r][0] @mm[r][2] @n1[reff][1]\n.endc\n.end\n", "s1")
check("[17] E-558: .save of a model card's parameter records it per point; an unknown one warns",
      seq(out, "@mm[r][0]") == [1000.0] and seq(out, "@mm[r][2]") == [1000.0] and seq(out, "@n1[reff][1]") == [1000.0]
      and "no such device" not in out and "save '@mm[nosuch]'" in out and "has no parameter 'nosuch'" in out,
      out.strip()[-240:])
out = run(F2.format(tag="s2", model="vdep", body="op\naltermod mm lmin=1.5\nop\necho after"), "s2")
check("[18] E-558: the out-of-bounds message says the declared range and the value of the parameter that moved it",
      "Parameter l of 'mm' is out of bounds (value 1.2; range from [lmin:inf), lmin = 1.5)!" in out, out.strip()[-200:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
