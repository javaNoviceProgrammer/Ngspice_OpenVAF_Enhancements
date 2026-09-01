#!/usr/bin/env python3
"""Automatic Monte-Carlo from Verilog-A parameter statistics.

A parameter declared with `(* std=<sigma> *)` (absolute) or
`(* std_rel=<fraction> *)` (relative to the nominal), optionally with
`(* dist="gauss"|"uniform" *)` (gauss is the default; for uniform the value
is the HALF-WIDTH), carries its own statistics. The compiler exports them
through the OSDI_STAT_PARAM_{COUNTS,INFOS} side-table (the absdelay
mechanism -- no descriptor-ABI change, old objects simply have none), and
`.option osdimc` (alias `automc`) makes every run-class command a fresh
trial: nominal+draw is written through the ordinary parameter setter, so
the netlist is never re-expanded and no `reset` is involved.

What this suite pins:

  * the FIRST run after sourcing is the NOMINAL baseline (defaults of
    unset parameters are only knowable after one setup pass); draws begin
    with the second run;
  * a MODEL parameter is one draw per model card per trial (process --
    instances sharing the card move in lockstep, distinct cards differ),
    an instance parameter (`(* type="instance" *)`) is an independent draw
    per instance (mismatch);
  * draws are PURE functions of (mcseed, trial, owner name, param id):
    a re-run of the same deck reproduces every value bit-for-bit, and a
    different seed changes them -- the compiler's (seed, salt) $random
    philosophy, no hidden RNG state;
  * measured over 300 trials: gauss mean/sigma match the declared values,
    uniform draws fill exactly [nominal-std, nominal+std], std_rel scales
    with the nominal, and an unset parameter recenters on its DEFAULT;
  * `alter` RECENTERS a statistical parameter's nominal;
  * switching the option off restores every drawn parameter to nominal;
  * a model without statistics attributes is untouched by the option;
  * diagnostics: unknown dist / non-real param / localparam / dist-without-
    sigma each warn (and compile); a negative sigma and std beside std_rel
    are located errors; the clean model compiles with zero warnings, and a
    model without attributes exports no statistics symbols at all.
"""

import atexit
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_mc_"):
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


def compile_va(name):
    osdi = os.path.join(HERE, f"_mc_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr, osdi


def run_deck(deck, tag, timeout=300):
    p = os.path.join(HERE, f"_mc_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def seq(out, name):
    """All printed values of @owner[param] / vector `name`, in order."""
    vals = []
    for m in re.finditer(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    return vals


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def sd(xs):
    if len(xs) < 2:
        return float("nan")
    mu = mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


# ---- [1] compilation & diagnostics -----------------------------------------
print("compilation and diagnostics:")
rc, out, OSDI = compile_va("smcres.va")
check("[1] the statistics-carrying model compiles with ZERO warnings",
      rc == 0 and "warning" not in out.lower(),
      out.strip().splitlines()[-1] if out.strip() else "")

rc, out, PLAIN = compile_va("smcplain.va")
check("[2] the attribute-free control model compiles", rc == 0)
nm = subprocess.run(["nm", PLAIN], capture_output=True, text=True)
check("[3] ...and exports NO statistics symbols (old-object shape)",
      "OSDI_STAT_PARAM" not in nm.stdout)
nm = subprocess.run(["nm", OSDI], capture_output=True, text=True)
check("[4] the statistics model exports OSDI_STAT_PARAM_{COUNTS,INFOS}",
      "OSDI_STAT_PARAM_COUNTS" in nm.stdout and "OSDI_STAT_PARAM_INFOS" in nm.stdout)

rc, out, _ = compile_va("smcwarn.va")
check("[5] unknown dist / integer param / localparam / dist-without-sigma "
      "each WARN and the model still compiles",
      rc == 0
      and 'unknown distribution "banana"' in out
      and "only a scalar real parameter" in out
      and "localparam cannot be varied" in out
      and "no effect without a 'std'" in out,
      f"rc={rc}")

rc, out, _ = compile_va("smcbad.va")
check("[6] a negative sigma, std beside std_rel, and quoted GARBAGE "
      "(\"25 ohm\", \"inf\") are located ERRORS",
      rc != 0
      and out.count("expected a non-negative real literal") >= 3
      and "mutually exclusive" in out,
      f"rc={rc}")

# ---- [2] baseline, draws, process vs mismatch ------------------------------
print("\nbaseline run, then draws; process vs mismatch:")
DECK = """osdimc basics
V1 a 0 1
N1 a 0 mm
N2 a 0 mm
N3 a 0 mm2
.model mm smcres
.model mm2 smcres
.option osdimc mcseed=42
.control
pre_osdi {osdi}
repeat 4
  op
  print @mm[r] @mm2[r] @n1[dr] @n2[dr] @mm[u] i(v1)
end
.endc
.end
"""
out = run_deck(DECK.format(osdi=os.path.basename(OSDI)), "basics")
r_mm, r_mm2 = seq(out, "@mm[r]"), seq(out, "@mm2[r]")
dr1, dr2 = seq(out, "@n1[dr]"), seq(out, "@n2[dr]")
u_mm = seq(out, "@mm[u]")
iv = seq(out, "i(v1)")

check("[7] run 1 is the NOMINAL baseline: r=1000, dr=0, u=default 50, "
      "i(v1) = -3 mA exact",
      len(r_mm) == 4 and r_mm[0] == 1000.0 and dr1[0] == 0.0 and dr2[0] == 0.0
      and u_mm[0] == 50.0 and abs(iv[0] - (-3e-3)) < 1e-12,
      f"r={r_mm[:1]} dr={dr1[:1]} u={u_mm[:1]} i={iv[:1]}")
check("[8] draws begin with run 2 (r leaves its nominal, current follows)",
      all(v != 1000.0 for v in r_mm[1:]) and all(v != iv[0] for v in iv[1:]),
      f"r={r_mm[1:]}")
check("[9] MISMATCH: the per-instance dr draws differ between n1 and n2",
      all(a != b for a, b in zip(dr1[1:], dr2[1:])),
      f"n1={dr1[1:2]} n2={dr2[1:2]}")
check("[10] PROCESS: distinct model cards of one module draw independently",
      all(a != b for a, b in zip(r_mm[1:], r_mm2[1:])),
      f"mm={r_mm[1:2]} mm2={r_mm2[1:2]}")
check("[11] an unset parameter recenters on its resolved DEFAULT",
      all(v != 50.0 for v in u_mm[1:]) and all(abs(v - 50.0) < 30.0 for v in u_mm[1:]),
      f"u={u_mm[1:3]}")

# ---- [3] determinism -------------------------------------------------------
print("\ndeterminism -- pure (seed, trial, owner, param) draws:")
out2 = run_deck(DECK.format(osdi=os.path.basename(OSDI)), "basics2")
check("[12] a fresh ngspice process with the same mcseed reproduces every "
      "draw bit-for-bit",
      seq(out2, "@mm[r]") == r_mm and seq(out2, "@n1[dr]") == dr1,
      f"trial2 r={r_mm[1:2]}")
out3 = run_deck(DECK.format(osdi=os.path.basename(OSDI)).replace("mcseed=42", "mcseed=43"),
                "seed43")
check("[13] a different mcseed changes the draws",
      seq(out3, "@mm[r]")[1:] != r_mm[1:],
      f"seed43 r={seq(out3, '@mm[r]')[1:2]}")

# ---- [4] the distributions, measured ---------------------------------------
print("\ndistributions measured over 300 trials:")
NSTAT = 301  # trial 1 is the nominal baseline
STAT_DECK = f"""osdimc stats
V1 a 0 1
N1 a 0 mm
.model mm smcres
.option osdimc mcseed=7
.control
pre_osdi {os.path.basename(OSDI)}
repeat {NSTAT}
  op
  print @mm[r] @mm[g] @mm[k] @n1[dr]
end
.endc
.end
"""
out = run_deck(STAT_DECK, "stats", timeout=600)
r_s = seq(out, "@mm[r]")[1:]
g_s = seq(out, "@mm[g]")[1:]
k_s = seq(out, "@mm[k]")[1:]
d_s = seq(out, "@n1[dr]")[1:]
check("[14] gauss r: sample mean matches the nominal 1000 "
      "(300 draws, tol 4*25/sqrt(300))",
      len(r_s) == NSTAT - 1 and abs(mean(r_s) - 1000.0) < 4 * 25 / math.sqrt(300),
      f"mean={mean(r_s):.3f} n={len(r_s)}")
check("[15] gauss r: sample sigma matches the declared std=25 (tol 20%)",
      abs(sd(r_s) - 25.0) < 5.0, f"sd={sd(r_s):.3f}")
check("[16] uniform g: every draw inside [nominal-std, nominal+std] and the "
      "range is actually used",
      all(8e-4 - 1e-15 <= v <= 12e-4 + 1e-15 for v in g_s)
      and min(g_s) < 9e-4 and max(g_s) > 11e-4,
      f"min={min(g_s):.6g} max={max(g_s):.6g}")
check("[17] std_rel k: sigma scales with the nominal (0.05*2 = 0.1, tol 25%)",
      abs(sd(k_s) - 0.1) < 0.025, f"sd={sd(k_s):.4f}")
check("[18] mismatch dr: mean 0, sigma 10 (tol 20%)",
      abs(mean(d_s)) < 4 * 10 / math.sqrt(300) and abs(sd(d_s) - 10.0) < 2.0,
      f"mean={mean(d_s):.3f} sd={sd(d_s):.3f}")

# ---- [5] alter recenters; off restores; plain models untouched -------------
print("\nalter recenters, disabling restores, plain models untouched:")
ALTER_DECK = f"""osdimc alter
V1 a 0 1
N1 a 0 mm
.model mm smcres
.option osdimc mcseed=42
.control
pre_osdi {os.path.basename(OSDI)}
op
op
alter @n1[dr] = 100
op
op
print @n1[dr]
.endc
.end
"""
out = run_deck(ALTER_DECK, "alter")
d_last = seq(out, "@n1[dr]")
check("[19] `alter` RECENTERS the nominal: later draws sit on 100, not 0",
      len(d_last) == 1 and d_last[0] != 100.0 and abs(d_last[0] - 100.0) < 60.0,
      f"dr={d_last}")

OFF_DECK = f"""osdimc off restores
V1 a 0 1
N1 a 0 mm
.model mm smcres
.control
pre_osdi {os.path.basename(OSDI)}
set osdimc
set mcseed=42
op
op
print @mm[r]
unset osdimc
op
print @mm[r] i(v1)
.endc
.end
"""
out = run_deck(OFF_DECK, "off")
r_off = seq(out, "@mm[r]")
iv_off = seq(out, "i(v1)")
check("[20] `set osdimc` in .control draws; `unset osdimc` RESTORES the "
      "nominal exactly",
      len(r_off) == 2 and r_off[0] != 1000.0 and r_off[1] == 1000.0
      and abs(iv_off[0] - (-1e-3)) < 1e-12,
      f"drawn={r_off[:1]} restored={r_off[1:]}")

NOOPT_DECK = f"""osdimc absent
V1 a 0 1
N1 a 0 mm
.model mm smcres
.control
pre_osdi {os.path.basename(OSDI)}
repeat 3
  op
  print @mm[r]
end
.endc
.end
"""
out = run_deck(NOOPT_DECK, "noopt")
check("[21] without the option nothing EVER varies",
      seq(out, "@mm[r]") == [1000.0, 1000.0, 1000.0])

PLAIN_DECK = f"""osdimc plain control
V1 a 0 1
N1 a 0 pp
.model pp smcplain
.option automc mcseed=42
.control
pre_osdi {os.path.basename(PLAIN)}
repeat 3
  op
  print @pp[r] i(v1)
end
.endc
.end
"""
out = run_deck(PLAIN_DECK, "plain")
check("[22] `.option automc` (the alias) leaves a model WITHOUT statistics "
      "attributes untouched",
      seq(out, "@pp[r]") == [1000.0] * 3
      and all(abs(v - (-1e-3)) < 1e-15 for v in seq(out, "i(v1)")),
      f"r={seq(out, '@pp[r]')}")

VERB_DECK = f"""osdimc verbose
V1 a 0 1
N1 a 0 mm
.model mm smcres
.option osdimc mcseed=42 osdimc_verbose
.control
pre_osdi {os.path.basename(OSDI)}
op
op
.endc
.end
"""
out = run_deck(VERB_DECK, "verb")
check("[23] osdimc_verbose reports each draw with trial, owner, value and "
      "nominal",
      re.search(r"osdimc: trial 2: mm:r = \S+ \(nominal 1000\)", out) is not None
      and "osdimc: trial 1:" not in out,
      "trial-2 lines present, none for the baseline")
check("[24] ...and none of the option names draws an 'unknown option' warning",
      "unknown option" not in out)

# ---- [6] bug-hunt hardening: machine writes, failed trials, finite draws ---
print("\nbug-hunt hardening (F1/F2/F5/F6/F13):")
SWEEP_DECK = f"""osdimc sweep no recenter
V1 a 0 1
N1 a 0 mm
.model mm smcres
.option osdimc mcseed=42
.control
pre_osdi {os.path.basename(OSDI)}
op
op
print @n1[dr]
dc @n1[dr] 50 100 25
op
print @n1[dr]
.endc
.end
"""
out = run_deck(SWEEP_DECK, "sweepnr")
drs = seq(out, "@n1[dr]")
check("[25] a .dc sweep of a statistical parameter does NOT recenter its "
      "nominal (draws stay centered on 0; F1)",
      len(drs) == 2 and abs(drs[1]) < 60.0 and drs[1] != drs[0]
      and abs(drs[1] - (-10.5375)) < 1e-3,
      f"post-sweep draw {drs[1] if len(drs) > 1 else '?'} = trial-4 delta")

RESET_DECK = f"""osdimc reset restarts
V1 a 0 1
N1 a 0 mm
.model mm smcres
.option osdimc mcseed=42
.control
pre_osdi {os.path.basename(OSDI)}
op
op
print @mm[r]
reset
op
print @mm[r]
op
print @mm[r]
.endc
.end
"""
out = run_deck(RESET_DECK, "reset")
rs = seq(out, "@mm[r]")
check("[26] `reset` restarts MC deterministically: baseline, then the SAME "
      "trial-2 draw as the first cycle (F2)",
      rs == [rs[0], 1000.0, rs[0]] and rs[0] != 1000.0,
      f"{rs}")

FAIL_DECK = f"""osdimc failed trial says so
V1 a 0 1
N1 a 0 mm
.model mm vcoll
.control
pre_osdi _mc_vcoll.osdi
set osdimc
set mcseed=5
repeat 8
  op
end
.endc
.end
"""
wv_vcoll = os.path.join(HERE, "_mc_vcoll.va")
with open(wv_vcoll, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module vcoll(a,b); inout a,b; electrical a,b,i;\n"
            "(* std=2.0 *) parameter real rd = 0.0 from [0:inf);\n"
            "analog begin\n"
            "  if (rd == 0.0) V(a,i) <+ 0.0;\n"
            "  else           I(a,i) <+ V(a,i)/rd;\n"
            "  I(i,b) <+ V(i,b)/1000.0;\n"
            "end endmodule\n")
rc, cout = subprocess.run([OPENVAF, wv_vcoll, "-o",
                           os.path.join(HERE, "_mc_vcoll.osdi")], cwd=HERE,
                          capture_output=True, text=True, timeout=300).returncode, ""
out = run_deck(FAIL_DECK, "failmsg")
check("[27] a range-violating draw fails LOUDLY: the error names the model "
      "and the value, and the trial is flagged in-band (F5/F6)",
      "of 'mm' is out of bounds (value" in out
      and "FAILED during setup; result vectors from the previous successful "
          "run remain current" in out,
      "attributed error + trial notice present")

HUGE_DECK = f"""osdimc non-finite draw refused
V1 a 0 1
N1 a 0 mm
.model mm vhuge
.control
pre_osdi _mc_vhuge.osdi
set osdimc
set mcseed=3
op
op
print @mm[r] i(v1)
.endc
.end
"""
wv_huge = os.path.join(HERE, "_mc_vhuge.va")
with open(wv_huge, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module vhuge(a,b); inout a,b; electrical a,b;\n"
            "(* std=1e308 *) parameter real r = 1000.0 from (0:inf);\n"
            "analog I(a,b) <+ V(a,b)/r; endmodule\n")
subprocess.run([OPENVAF, wv_huge, "-o", os.path.join(HERE, "_mc_vhuge.osdi")],
               cwd=HERE, capture_output=True, text=True, timeout=300)
out = run_deck(HUGE_DECK, "huge")
check("[28] an overflowing draw (sigma 1e308 -> +-inf) is refused with a "
      "named warning and the parameter stays at nominal (F13)",
      "is not finite" in out and seq(out, "@mm[r]") == [1000.0],
      f"r={seq(out, '@mm[r]')}")

ALTINF_DECK = f"""alter refuses non-finite
V1 a 0 1
N1 a 0 mm
.model mm smcres
.control
pre_osdi {os.path.basename(OSDI)}
alter @n1[dr] = 1e400
op
print @n1[dr] i(v1)
.endc
.end
"""
out = run_deck(ALTINF_DECK, "altinf")
check("[29] `alter` refuses a non-representable value (1e400) instead of "
      "silently storing +inf (F11)",
      "is not a finite number; not applied" in out
      and seq(out, "@n1[dr]") == [0.0],
      f"dr={seq(out, '@n1[dr]')}")

# ----------------------------------------------------------------------------
print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks}")
sys.exit(0 if passed == checks else 1)
