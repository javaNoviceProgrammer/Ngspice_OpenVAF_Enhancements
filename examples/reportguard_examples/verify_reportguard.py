#!/usr/bin/env python3
"""Enhancement-476: the simulator reports only what it actually has.

Four defects from bug-hunt round 45. Each is the simulator's account of itself
disagreeing with what it does, and none of them raised an error:

  1  An OSDI operating-point variable answered with a NUMBER when nothing had
     computed one. The opvar storage is calloc'd, so `print @n1[op_r]` after
     "op simulation(s) aborted", or with no analysis run at all, returned a
     clean 0.0 -- indistinguishable from a real result -- while `i(v1)` in the
     same `print` honestly said "vector ... is not available".
  2  Every OSDI device's INTEGRATED noise total was advertised and unreachable.
     `onoise_total_<dev>` was built with a " " suffix instead of "", so the
     stored name carried a trailing blank: `display` padded it away and every
     read missed. The N_DENS sibling eleven lines above already passed "".
  3  A model declaring `dtemp`/`temperature` at MODEL scope had those names
     routed into the INSTANCE parameter table (Enhancement-397, deliberate), so
     `alter @n1[dtemp]=20` was ACCEPTED, stored the value where nothing reads
     it, and said nothing. Every other model-scope parameter reaching the same
     setter is refused honestly.
  4  openvaf's `SIMPARAM_NAMES` omitted `temp`, which ngspice has served since
     Enhancement-434. The compiler warned on the exact call that enhancement
     exists to support, and told the author the name is fatal at run time when
     it in fact returns the ambient temperature.

THE INVARIANT BEHIND [1] AND [2] IS "ADVERTISED == DELIVERABLE": every name the
simulator lists must be one it can hand over, and every number it hands over
must be one it actually has. Check [12] enforces that over the whole noise plot
rather than over the two vectors that were known to be broken, and checks
[24]-[26] enforce it for the simparam channel by reading BOTH lists out of the
source and requiring them to agree -- so the two-places drift that caused [4]
cannot recur silently.

WHAT IS DELIBERATELY NOT CHANGED:
  * `@n1[dtemp]` still READS the model's own parameter when the model declares
    it -- that routing is Enhancement-397's design, and the industry corpus
    depends on it. Only the instance-scope WRITE is refused. Check [17] pins
    the read; check [16] pins that an instance-scope `dtemp` still works.
  * `$simparam` name matching is case-SENSITIVE: `$simparam("TNOM")` is fatal.
    Check [27] pins it. Round 45 briefly reported this as an inconsistency; it
    was a macOS case-insensitive-FILESYSTEM collision between two probe files
    whose names differed only in case, so they were literally the same file.
  * Operating-point variables stay readable after a LATER analysis fails, once
    one has succeeded -- the values are a real evaluation, and that matches how
    a built-in keeps its last state. Check [9] pins it.
"""
import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers  # noqa: E402

_check_both_solvers(__file__)

ROOT = os.path.dirname(os.path.dirname(HERE))
Q = 1.6021918e-19


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_rg_") or junk.endswith(".osdi"):
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


def compile_va(src, out):
    r = subprocess.run([OPENVAF, src, "-o", out], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return r.returncode, r.stdout + r.stderr


def run(body, ctl, tag, osdi=()):
    if not body.endswith("\n"):
        body += "\n"          # else ".control" joins the last element line
    pre = "".join(f"pre_osdi {o}\n" for o in osdi)
    deck = (f"reportguard\n{body}.control\noption noacct\nset numdgt=12\n"
            f"{pre}{ctl}\n.endc\n.end\n")
    p = os.path.join(HERE, f"_rg_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return r.stdout + r.stderr


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def unavailable(out, name):
    return re.search(r"vector\s+" + re.escape(name.lower()) + r"\s+is not available",
                     out, re.I) is not None


print("=== Enhancement-476: the simulator reports only what it actually has ===")

for src in ("rg_probe", "rg_noise", "rg_shadow_model", "rg_shadow_inst", "rg_temp"):
    rc, log = compile_va(f"{src}.va", f"{src}.osdi")
    if rc != 0:
        print(f"  FATAL: {src}.va did not compile\n{log}")
        sys.exit(1)

PROBE = ("V1 a 0 dc 1\n"
         "N1 a 0 pm\n"
         ".model pm rg_probe r=1k rbad=1 rcol=0\n")
PROBE_BAD = PROBE.replace("rbad=1", "rbad=0")     # refused by its own range

# ---------------------------------------------------------------------------
print("\n[1-10] an operating-point variable with no operating point behind it")
# ---------------------------------------------------------------------------
o = run(PROBE, "print @n1[op_r]", "noan", osdi=("rg_probe.osdi",))
check("[1] no analysis run: the opvar is not available",
      unavailable(o, "@n1[op_r]") and val(o, "@n1[op_r]") is None)
check("[2] ...and the reason names the variable and the instance",
      "operating-point variable" in o and "n1" in o)

o = run(PROBE_BAD, "op\nprint @n1[op_r]", "abort", osdi=("rg_probe.osdi",))
check("[3] analysis ABORTED: the opvar is not available",
      "aborted" in o.lower() and unavailable(o, "@n1[op_r]"))
check("[4] ...and no number is produced", val(o, "@n1[op_r]") is None)

o = run(PROBE, "op\nprint @n1[op_r] @n1[op_vmid] i(v1)", "good", osdi=("rg_probe.osdi",))
check("[5] after a good op the opvar reads back", val(o, "@n1[op_r]") is not None)
check("[6] ...and is the value the circuit actually has",
      val(o, "@n1[op_r]") == 1000.0 and abs(val(o, "i(v1)") + 1e-3) < 1e-12,
      f"op_r={val(o, '@n1[op_r]')} i={val(o, 'i(v1)')}")

# A PARAMETER is an input and must never be refused by the opvar gate. Note
# what it READS with nothing run: 0.0, not its declared default of 1.0, because
# ngspice applies OSDI parameter defaults during setup and the instance block is
# calloc'd until then. That predates this enhancement -- the shipped binary does
# the same -- and is deliberately left alone; see the README. What matters here
# is that the read is ANSWERED rather than refused.
o = run(PROBE, "print @n1[mul]", "param", osdi=("rg_probe.osdi",))
check("[7] a parameter is NOT gated: still answered with no analysis",
      val(o, "@n1[mul]") is not None and not unavailable(o, "@n1[mul]")
      and "operating-point variable" not in o, f"mul={val(o, '@n1[mul]')}")
o = run(PROBE, "op\nprint @n1[mul]", "param2", osdi=("rg_probe.osdi",))
check("[7b] ...and carries its declared default once setup has run",
      val(o, "@n1[mul]") == 1.0, f"mul={val(o, '@n1[mul]')}")

# reads DURING a run must not be refused -- the eval has happened by then
o = run("V1 a 0 pulse(0 1 0 1u 1u 10u 20u)\nR1 a b 1k\nN1 b 0 pm\n"
        ".model pm rg_probe r=1k rbad=1 rcol=0\n",
        "save v(b) @n1[op_vmid]\ntran 100n 20u\nprint length(@n1[op_vmid])",
        "wave", osdi=("rg_probe.osdi",))
n = val(o, "length(@n1[op_vmid])")
check("[8] an opvar saved through a transient is still a full waveform",
      n is not None and n > 50, f"{n} points")

# once a real evaluation has happened the value stays readable: it IS a result
o = run(PROBE, "op\naltermod @pm[rbad]=0\nop\nprint @n1[op_r]", "stale",
        osdi=("rg_probe.osdi",))
check("[9] DECISION: a good op then a failed one leaves the real value readable",
      val(o, "@n1[op_r]") == 1000.0, f"op_r={val(o, '@n1[op_r]')}")

# $fatal mid-evaluation: the values assigned before it are not an answer
with open(os.path.join(HERE, "_rg_fatal.va"), "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module _rg_fatal(p, n);\n inout p, n; electrical p, n;\n"
            ' (* desc="v" *) real op_v;\n'
            " analog begin\n"
            '  op_v = 1.0;\n'
            '  op_v = $simparam("no_such_name_at_all");\n'
            "  I(p,n) <+ V(p,n) / 1k;\n end\nendmodule\n")
compile_va("_rg_fatal.va", "_rg_fatal.osdi")
o = run("V1 a 0 dc 1\nN1 a 0 fm\n.model fm _rg_fatal\n",
        "op\nprint @n1[op_v]", "fatal", osdi=("_rg_fatal.osdi",))
check("[10] $fatal during evaluation: the opvar is not an answer either",
      unavailable(o, "@n1[op_v]") and val(o, "@n1[op_v]") is None)

# ---------------------------------------------------------------------------
print("\n[11-15] the integrated noise totals are reachable and correct")
# ---------------------------------------------------------------------------
NOISE = ("I1 0 a dc 1m ac 1\n"
         "N1 a 0 dm\n"
         "R9 a 0 1meg\n"
         ".model dm rg_noise is=1e-14 kf=1e-12\n")
NCMD = "noise v(a) i1 dec 2 1 100 1\nsetplot noise2\n"

o = run(NOISE, NCMD + "print onoise_total_n1 inoise_total_n1", "ntot",
        osdi=("rg_noise.osdi",))
on1, in1 = val(o, "onoise_total_n1"), val(o, "inoise_total_n1")
check("[11] the device's integrated OUTPUT total reads back", on1 is not None, f"{on1}")
check("[12] the device's integrated INPUT total reads back", in1 is not None, f"{in1}")

o = run(NOISE, NCMD + "print onoise_total_n1 onoise_total_n1_shot "
                      "onoise_total_n1_flicker onoise_total_r9 onoise_total", "nsum",
        osdi=("rg_noise.osdi",))
tot, dev = val(o, "onoise_total"), val(o, "onoise_total_n1")
sh, fl = val(o, "onoise_total_n1_shot"), val(o, "onoise_total_n1_flicker")
r9 = val(o, "onoise_total_r9")
ok = None not in (tot, dev, sh, fl, r9)
check("[13] the device total is the quadrature sum of its OWN sources",
      ok and abs(dev - (sh * sh + fl * fl) ** 0.5) <= 1e-9 * dev,
      f"{dev:.6e} vs {(sh*sh+fl*fl)**0.5:.6e}" if ok else "missing")
check("[14] the grand total is the quadrature sum of the device totals",
      ok and abs(tot - (dev * dev + r9 * r9) ** 0.5) <= 1e-9 * tot,
      f"{tot:.6e} vs {(dev*dev+r9*r9)**0.5:.6e}" if ok else "missing")

# the general invariant: nothing `display` lists may be unreadable
o = run(NOISE, NCMD + "display", "ndisp", osdi=("rg_noise.osdi",))
names = []
for line in o[o.find("Here are"):].splitlines():
    m = re.match(r"\s{2,}(\S+?)\s*:\s+\w", line)
    if m and m.group(1) not in ("Title", "Name", "Date"):
        names.append(m.group(1))
o2 = run(NOISE, NCMD + "\n".join(f"print {n}" for n in names), "nread",
         osdi=("rg_noise.osdi",))
bad = [n for n in names if unavailable(o2, n)]
check("[15] every vector the noise plot ADVERTISES can be read",
      len(names) > 8 and not bad, f"{len(names)} advertised, unreadable={bad}")

# ---------------------------------------------------------------------------
print("\n[16-19] a routed model-scope temperature parameter refuses an instance write")
# ---------------------------------------------------------------------------
SHM = "V1 a 0 dc 1\nN1 a 0 sm\n.model sm rg_shadow_model base=1k\n"
o = run(SHM, "op\nprint i(v1)\nalter @n1[dtemp]=20\nop\nprint i(v1)", "shm",
        osdi=("rg_shadow_model.osdi",))
vals = re.findall(r"i\(v1\)\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", o, re.I)
check("[16] model-scope `dtemp`: the instance write is REFUSED, naming the remedy",
      "MODEL parameter" in o and "altermod" in o)
check("[17] ...and the answer does not move (it never did -- now it says so)",
      len(vals) == 2 and vals[0] == vals[1], f"{vals}")

o = run(SHM, "op\nprint i(v1)\nalter @n1[temp]=20\nop\nprint i(v1)", "shmt",
        osdi=("rg_shadow_model.osdi",))
check("[18] model-scope `temperature` is refused the same way",
      "MODEL parameter" in o and "altermod" in o)

o = run(SHM, "op\nprint @n1[dtemp]", "shmr", osdi=("rg_shadow_model.osdi",))
check("[19] DECISION: the READ still routes to the model's own parameter",
      val(o, "@n1[dtemp]") == 2.0, f"@n1[dtemp]={val(o, '@n1[dtemp]')}")

# ---------------------------------------------------------------------------
print("\n[20-23] the two cases that must keep working")
# ---------------------------------------------------------------------------
SHI = "V1 a 0 dc 1\nN1 a 0 sm\n.model sm rg_shadow_inst base=1k\n"
o = run(SHI, "op\nprint i(v1)\nalter @n1[dtemp]=20\nop\nprint i(v1)", "shi",
        osdi=("rg_shadow_inst.osdi",))
vals = re.findall(r"i\(v1\)\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", o, re.I)
check("[20] INSTANCE-scope `dtemp` (the corpus spelling) still writes through",
      len(vals) == 2 and float(vals[0]) != float(vals[1])
      and abs(float(vals[1]) + 1.0 / 20000.0) < 1e-12, f"{vals}")
check("[21] ...and no refusal is printed for it", "MODEL parameter" not in o)

o = run(SHM, "altermod @sm[dtemp]=20\nop\nprint i(v1)", "shmam",
        osdi=("rg_shadow_model.osdi",))
check("[22] `altermod` on the model still reaches the physics",
      abs(val(o, "i(v1)") + 1.0 / 60000.0) < 1e-12, f"i={val(o, 'i(v1)')}")

# a model with no colliding declaration keeps ngspice's OWN dtemp knob
TMP = "V1 a 0 dc 1\nN1 a 0 tm\n.model tm rg_temp r=1k tc=0.01\n"
o = run(TMP, "op\nprint i(v1)\nalter @n1[dtemp]=10\nop\nprint i(v1)", "tmp",
        osdi=("rg_temp.osdi",))
vals = re.findall(r"i\(v1\)\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", o, re.I)
check("[23] no collision: the loader's own dtemp knob still changes the answer",
      len(vals) == 2 and abs(float(vals[0]) + 1e-3) < 1e-12
      and abs(float(vals[1]) + 1.0 / 1100.0) < 1e-9, f"{vals}")

# ---------------------------------------------------------------------------
print("\n[24-28] the compiler's simparam list is the simulator's")
# ---------------------------------------------------------------------------
rs = os.path.join(ROOT, "OpenVAF-master-20260610", "openvaf", "hir_ty", "src",
                  "validation", "body.rs")
c = os.path.join(ROOT, "ngspice-46", "src", "osdi", "osdiload.c")
rust_names = c_names = []
try:
    txt = open(rs, encoding="utf-8", errors="replace").read()
    m = re.search(r"SIMPARAM_NAMES:\s*\[&'static str;\s*\d+\]\s*=\s*\[(.*?)\];", txt, re.S)
    rust_names = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    txt = open(c, encoding="utf-8", errors="replace").read()
    m = re.search(r"char\s*\*sim_params\[NUM_SIM_PARAMS\s*\+\s*1\]\s*=\s*\{(.*?)NULL\};", txt, re.S)
    c_names = re.findall(r'"([^"]+)"', m.group(1)) if m else []
except OSError:
    pass

check("[24] both name lists were found in the sources",
      len(rust_names) > 10 and len(c_names) > 10,
      f"compiler={len(rust_names)} simulator={len(c_names)}")
check("[25] the compiler's list IS the simulator's list -- no drift",
      sorted(rust_names) == sorted(c_names),
      f"compiler-only={sorted(set(rust_names)-set(c_names))} "
      f"simulator-only={sorted(set(c_names)-set(rust_names))}")

# every listed name must actually resolve at run time, with no default
body = "\n".join(f'  op_v{i} = $simparam("{n}");' for i, n in enumerate(c_names))
decl = "\n".join(f'  (* desc="{n}" *) real op_v{i};' for i, n in enumerate(c_names))
with open(os.path.join(HERE, "_rg_all.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule _rg_all(p, n);\n'
            " inout p, n; electrical p, n;\n" + decl +
            "\n analog begin\n" + body + "\n  I(p,n) <+ V(p,n) / 1k;\n end\nendmodule\n")
rc, log = compile_va("_rg_all.va", "_rg_all.osdi")
check("[26] a model reading EVERY served name compiles without a warning",
      rc == 0 and "L025" not in log, log.strip().splitlines()[:1])
o = run("V1 a 0 dc 1\nN1 a 0 am\n.model am _rg_all\n", "op\nprint i(v1)", "all",
        osdi=("_rg_all.osdi",))
check("[27] ...and runs: no name in the list is fatal at run time",
      "OSDI(fatal)" not in o and abs((val(o, "i(v1)") or 0) + 1e-3) < 1e-12,
      f"i={val(o, 'i(v1)')}")

# `temp` specifically -- the name Enhancement-434 added and the compiler missed
with open(os.path.join(HERE, "_rg_temp.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule _rg_temp(p, n);\n'
            ' inout p, n; electrical p, n;\n (* desc="t" *) real op_t;\n'
            ' analog begin\n  op_t = $simparam("temp");\n'
            "  I(p,n) <+ V(p,n) / 1k;\n end\nendmodule\n")
rc, log = compile_va("_rg_temp.va", "_rg_temp.osdi")
o = run(".option temp=40\nV1 a 0 dc 1\nN1 a 0 tm\n.model tm _rg_temp\n",
        "op\nprint @n1[op_t]", "sptemp", osdi=("_rg_temp.osdi",))
check('[28] $simparam("temp") is silent at build and returns the ambient',
      "L025" not in log and val(o, "@n1[op_t]") == 40.0,
      f"op_t={val(o, '@n1[op_t]')}")

# ---------------------------------------------------------------------------
print("\n[29-30] pinned decisions")
# ---------------------------------------------------------------------------
with open(os.path.join(HERE, "_rg_case.va"), "w") as f:
    f.write('`include "disciplines.vams"\nmodule _rg_case(p, n);\n'
            ' inout p, n; electrical p, n;\n (* desc="t" *) real op_t;\n'
            ' analog begin\n  op_t = $simparam("TNOM");\n'
            "  I(p,n) <+ V(p,n) / 1k;\n end\nendmodule\n")
rc, log = compile_va("_rg_case.va", "_rg_case.osdi")
o = run("V1 a 0 dc 1\nN1 a 0 cm\n.model cm _rg_case\n", "op\nprint i(v1)", "case",
        osdi=("_rg_case.osdi",))
check("[29] DECISION: $simparam matching is case-SENSITIVE; \"TNOM\" is fatal",
      "L025" in log and "OSDI(fatal)" in o)

o = run(NOISE, NCMD + "print onoise_total_r9\nsetplot noise1\nprint onoise_n1",
        "sib", osdi=("rg_noise.osdi",))
# `onoise_n1` is a 5-point density curve, so `print` emits a TABLE rather than
# `name = value` -- ask whether it is available, not what val() can scrape.
check("[30] the two siblings that were always right still are",
      val(o, "onoise_total_r9") is not None and not unavailable(o, "onoise_n1"),
      f"r9={val(o, 'onoise_total_r9')} dens_readable={not unavailable(o, 'onoise_n1')}")

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
