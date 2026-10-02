#!/usr/bin/env python3
"""Enhancement-527: the kernel and random system functions, audited against
Accellera VAMS-2023 clause 9, then fixed.

What this suite pins, each against the quoted clause:

  * 9.17.2 -- "the next time step taken is no larger than the SMALLEST
    $bound_step() argument currently active": several calls in one
    evaluation used to leave the LAST one as the cap. Both orders of a
    (1e-6, 1e-4) pair now cap at 1e-6; single bounds are untouched.
  * 9.21 ($table_model, the whole surface): default LINEAR extrapolation
    on both ends (Tables 9-31/9-32 -- it used to clamp unless an 'L'
    appeared); per-DIMENSION comma-separated control sub-strings
    (any code used to apply to every axis); per-END extrapolation
    characters; closest-point lookup 'D' with the 9.21.4
    farther-from-zero tie rule; 'E' = runtime error on extrapolation;
    the ';N' dependent-column selector honoured; the LRM 9.21.1
    N+M-column isoline file format -- RAGGED isolines included (the
    LRM's own sample file) -- beside the project's self-describing grid;
    and the 1-D '{xs}, '{ys} array-pair form. E-562 (the book audit)
    then implemented '2' (quadratic spline) and 'I' (ignore a column);
    on the linear lin.dat the quadratic spline reproduces 2x exactly.
  * 9.13.2 -- "mean, degree_of_freedom, and k_stage shall be greater
    than zero. Otherwise an error shall be reported": a deck-supplied
    violation now aborts with the mandated runtime error naming the
    function and clause (exponential/poisson silently clamped;
    chi-square/t/erlang fed the RNG raw and returned deviates outside
    the distribution's own support).
  * 9.16 -- $simprobe with NO default "an error shall be generated":
    compile-time warning plus runtime fatal (was a silent 0.0). The
    default form still returns its default.
  * 9.20 -- the alias builtins are analog-initial-only (enforced) and
    9.13's type_string warns outside a paramset.
  * 9.15 Table 9-28 -- $simparam$str serves analysis_type and cwd
    (beside analysis_name/simulator); $vt uses the 2019 exact SI k/q,
    agreeing with `P_K*T/`P_Q exactly under PHYSICAL_CONSTANTS_NIST2018.
"""

import atexit
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
        if junk.startswith("_lk_"):
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


def compile_file(name):
    osdi = os.path.join(HERE, f"_lk_{os.path.splitext(name)[0]}.osdi")
    r = subprocess.run([OPENVAF, os.path.join(HERE, name), "-o", osdi], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    return r.returncode, (r.stdout + r.stderr), osdi


def compile_src(src, tag):
    va = os.path.join(HERE, f"_lk_{tag}.va")
    with open(va, "w") as f:
        f.write(src)
    return compile_file(os.path.basename(va))


def run(body, ctl, tag, osdi, timeout=300):
    p = os.path.join(HERE, f"_lk_{tag}.cir")
    with open(p, "w") as f:
        f.write(f"lrmkernel\n{body}\n.control\npre_osdi {os.path.basename(osdi)}\n"
                f"option noacct\n{ctl}\nquit\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def num(out, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def close(a, b, tol):
    return a is not None and abs(a - b) <= tol


# ---- [1] $bound_step smallest-wins (9.17.2) --------------------------------
print("$bound_step smallest-active-bound (LRM 9.17.2):")
for name, want in (("bs1", 1e-6), ("bs2", 1e-6), ("bs3", 1e-6), ("bs4", 1e-4)):
    rc, out, osdi = compile_file(f"{name}.va")
    dat = os.path.join(HERE, f"_lk_{name}.txt")
    run(f"V1 in 0 1.0\nN1 in 0 mm\n.model mm {name}\n.tran 10u 1m 0 1m",
        f"run\nwrdata _lk_{name}.txt v(in)", name, osdi)
    try:
        ts = [float(l.split()[0]) for l in open(dat) if l.strip()]
        maxdt = max(b - a for a, b in zip(ts, ts[1:]))
    except (OSError, ValueError):
        maxdt = None
    why = {"bs1": "single 1e-6", "bs4": "single 1e-4",
           "bs2": "1e-6 then 1e-4 (last used to win)",
           "bs3": "1e-4 then 1e-6"}[name]
    check(f"{name} ({why}): max dt = {want:g}",
          maxdt is not None and abs(maxdt - want) < 0.2 * want, f"maxdt={maxdt}")

# ---- [2] $table_model per LRM 9.21 -----------------------------------------
print("\n$table_model (LRM 9.21):")
rc, out, osdi = compile_file("tbl3.va")
check("tbl3.va compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 tblm3",
              "op\nprint @N1[t1] @N1[t2] @N1[t10] @N1[t3] @N1[t4] @N1[t6] "
              "@N1[t11] @N1[t8] @N1[t12]", "t3", osdi)
    for opv, want, why in [
        ("t1", 3.0, "interpolation at 1.5"),
        ("t2", 8.0, "DEFAULT LINEAR extrapolation above (was 6.0 clamp)"),
        ("t10", 0.0, "default linear below (was 2.0 clamp)"),
        ("t3", 6.0, "explicit '1C' clamps"),
        ("t4", 8.0, "explicit '1L'"),
        ("t6", 2.0, "2-D self-describing grid file still works"),
        ("t11", 2.0, "per-dimension '1C,1L': y clamps, x extends (was 3.0)"),
        ("t8", 3.0, "inline interleaved pairs"),
        ("t12", 3.0, "';2' on a one-dependent-column file clamps to it"),
    ]:
        check(f"{why}: {opv} = {want}", close(num(sim, f"@n1[{opv}]"), want, 1e-9),
              f"{num(sim, f'@n1[{opv}]')}")

rc, out, osdi = compile_file("tbl2.va")
check("tbl2.va (isoline file + array pair) compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 tblm2",
              "op\nprint @N1[t6] @N1[t9]", "t2", osdi)
    check("the LRM 9.21.1 N+M-column file interpolates: f(0.25,3.5) = 2.0",
          close(num(sim, "@n1[t6]"), 2.0, 1e-9), f"{num(sim, '@n1[t6]')}")
    check("the '{xs}, '{ys} array-pair form works", close(num(sim, "@n1[t9]"), 3.0, 1e-9),
          f"{num(sim, '@n1[t9]')}")

rc, out, osdi = compile_file("tblx.va")
check("tblx.va (ragged/selector/closest) compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 tblx",
              "op\nprint @N1[r1] @N1[r2] @N1[r3] @N1[r4] @N1[r5] @N1[r6] @N1[r7]",
              "tx", osdi)
    for opv, want, why in [
        ("r1", 2.0, "RAGGED isolines (the LRM's own sample file): f(0.25,3.5)"),
        ("r2", 3.5, "linear extrapolation along a short isoline"),
        ("r3", 150.0, "';2' selects the second dependent column (h = 100x)"),
        ("r4", 15.0, "';1' selects the first (g = 10x)"),
        ("r5", 2.0, "'D' closest at 1.4 -> knot 1"),
        ("r6", 4.0, "'D' closest at 1.6 -> knot 2"),
        ("r7", 4.0, "'D' TIE at 1.5 -> the knot farther from zero (9.21.4)"),
    ]:
        check(f"{why}: {opv} = {want:g}", close(num(sim, f"@n1[{opv}]"), want, 1e-9),
              f"{num(sim, f'@n1[{opv}]')}")

rc, out, osdi = compile_file("tble.va")
check("tble.va ('E' error extrapolation) compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 tble", "op\nprint @N1[r1]",
              "te", osdi)
    check("'E' aborts out of range with the 9.21.2 runtime fatal",
          "9.21.2" in sim and "fatal" in sim.lower(),
          next((l.strip()[:60] for l in sim.splitlines() if "fatal" in l.lower()), ""))

rc, out, osdi = compile_src(
    '`include "disciplines.vams"\nmodule q(a,c); inout a,c; electrical a,c;\n'
    ' (* desc="quadratic" *) real r;\n analog begin r = $table_model(1.5, "lin.dat", "2");'
    ' I(a,c) <+ V(a,c); end\nendmodule\n', "q2")
check("'2' (quadratic spline, E-562) compiles", rc == 0,
      (out.strip().splitlines() or [""])[0][:60])
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 q\n.model q q", "op\nprint @N1[r]", "q2", osdi)
    check("'2' on linear data is exact: q(1.5) = 3", close(num(sim, "@n1[r]"), 3.0, 1e-9),
          f"{num(sim, '@n1[r]')}")

# ---- [3] 9.13.2 domain errors on the deck route ----------------------------
print("\ndistribution domains (LRM 9.13.2):")
rc, out, osdi = compile_file("negdist.va")
check("negdist.va compiles", rc == 0)
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 mn\n.model mn negm(m=-1.0 d=-2.0)",
              "op\nprint @N1[e1]", "nd", osdi)
    for fn in ("$rdist_exponential", "$rdist_chi_square", "$rdist_t",
               "$rdist_erlang"):
        check(f"{fn} with a deck-supplied violation reports the mandated error",
              fn in sim and "9.13.2" in sim, "")
    sim = run("V1 in 0 1.0\nN1 in 0 mn\n.model mn negm(m=1.0 d=2.0)",
              "op\nprint @N1[e1] @N1[c1]", "ndok", osdi)
    check("legal arguments still draw", num(sim, "@n1[e1]") is not None
          and "9.13.2" not in sim, f"e1={num(sim, '@n1[e1]')}")

# ---- [4] $simprobe / aliases / type_string ---------------------------------
print("\n$simprobe and context rules (LRM 9.16/9.20/9.13):")
rc, out, osdi = compile_file("simprobe_nd.va")
check("no-default $simprobe warns at compile", "FATAL at run time" in out)
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 mm\n.model mm prm", "op\nprint @N1[p2]",
              "pr", osdi)
    check("...and is FATAL at run time (LRM 9.16)",
          "9.16" in sim and "fatal" in sim.lower(), "")
rc, out, _ = compile_src(
    '`include "disciplines.vams"\nmodule pd(a,c); inout a,c; electrical a,c;\n'
    ' (* desc="d" *) real p;\n analog begin p = $simprobe("i","q",3.25);'
    ' I(a,c) <+ V(a,c)/1e3; end\nendmodule\n', "pd")
check("the default form compiles silently", rc == 0 and "FATAL" not in out)
rc, out, _ = compile_src(
    '`include "disciplines.vams"\nmodule al(a,c); inout a,c; electrical a,c;\n'
    ' integer r;\n analog begin r = $analog_node_alias(a,"x");'
    ' I(a,c) <+ V(a,c); end\nendmodule\n', "al")
check("$analog_node_alias outside analog initial is the 9.20 error",
      rc != 0 and "analog initial" in out)
rc, out, _ = compile_src(
    '`include "disciplines.vams"\nmodule ts(a,c); inout a,c; electrical a,c;\n'
    ' integer s; real y;\n analog begin s=1; y = $rdist_normal(s,0.0,1.0,"global");'
    ' I(a,c) <+ V(a,c); end\nendmodule\n', "ts")
check("type_string outside a paramset warns", rc == 0 and "type_string" in out)

# ---- [5] $simparam$str names and $vt constants -----------------------------
print("\n$simparam$str (Table 9-28) and $vt:")
rc, out, osdi = compile_file("simparams.va")
check("analysis_type/cwd compile with no unknown-name warning",
      rc == 0 and "L025" not in out)
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 sps",
              "op\nprint @N1[same] @N1[cwok]", "sp", osdi)
    check("analysis_type answers (same string as analysis_name here)",
          close(num(sim, "@n1[same]"), 1.0, 1e-12), "")
    check("cwd answers non-empty", close(num(sim, "@n1[cwok]"), 1.0, 1e-12), "")
rc, out, osdi = compile_file("vtsi.va")
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 sps2", "op\nprint @N1[dvt]",
              "vt", osdi)
    check("$vt(300) == `P_K*300/`P_Q exactly under PHYSICAL_CONSTANTS_NIST2018",
          close(num(sim, "@n1[dvt]"), 0.0, 1e-18), f"dvt={num(sim, '@n1[dvt]')}")

# ---- [6] Enhancement-758: cwd is cached, re-read after `cd`, and cheap ------
# The `cwd` entry used to be re-read with getcwd() on EVERY load call, which on
# macOS opens and stats the directory chain: ~12 us per Newton iteration for any
# deck with a compiled model, whatever its size (a one-instance transient of
# 1.2 M iterations spent 12.8 of 14.4 s there). It is cached now and the `cd`
# command invalidates it -- the one thing that changes the process directory.
print("\n$simparam$str(\"cwd\") cached across iterations (Enhancement-758):")
import tempfile
rc, out, osdi = compile_file("cwdprobe.va")
check("cwdprobe.va compiles", rc == 0, out.strip()[-120:])
if rc == 0:
    newdir = os.path.realpath(tempfile.mkdtemp(prefix="lk_cd_"))
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 cwdprobe",
              f"op\ncd {newdir}\nop", "cwd", osdi)
    seen = [os.path.realpath(l.split("cwd=", 1)[1].strip()) for l in sim.splitlines() if "cwd=" in l]
    check("the first op reports the suite's own directory",
          len(seen) >= 1 and seen[0] == os.path.realpath(HERE), f"{seen[:1]}")
    check("after `cd` the next op reports the new directory (the cache is invalidated)",
          len(seen) >= 2 and seen[1] == newdir, f"{seen[1:2]} want {newdir}")
    try:
        os.rmdir(newdir)
    except OSError:
        pass
    # the cost: one compiled instance, ~4000 Newton iterations; the load time per
    # iteration was ~12 us (a getcwd per iteration), it is ~1-2.5 us now; 6 us
    # leaves room for a loaded machine and still fails the old behaviour
    sim = run("V1 in 0 pulse(0 1 1n 0.1n 0.1n 50n 100n)\nN1 in out m1\nC1 out 0 1p\n.model m1 cwdprobe",
              "tran 0.1n 200n\nrusage all", "cwdt", osdi)
    m_l = re.search(r"Transient load time = ([\d.eE+-]+)", sim)
    m_i = re.search(r"Transient iterations = (\d+)", sim)
    per_iter = float(m_l.group(1)) / int(m_i.group(1)) if (m_l and m_i and int(m_i.group(1)) > 0) else None
    check("[speed] the compiled load costs under 6 us per Newton iteration for one instance (was ~12 us, a getcwd each)",
          per_iter is not None and per_iter < 6e-6,
          f"{per_iter * 1e6:.2f} us/iter over {m_i.group(1) if m_i else '?'} iterations")

# ---- [7] Enhancement-760: the load path's bookkeeping is hoisted -------------
# After E-758 one compiled instance still cost ~0.6 us of load per Newton
# iteration against 0.08 us built in, none of it model evaluation: the
# repeated-message summary walked its 64-slot ring and freed 128 NULL pointers
# on every iteration, `noosdilim`, `osdilim_verbose` and `scale` were looked
# up by name on every load call (three list walks and a cp_usrvar probe each),
# the simulator version was re-parsed from its string, and the compiled
# runtime's file hook walked its 64 file slots. The options are re-read only
# when the variable lists' state stamp changes, so a `set` between runs must
# still reach the next run; the summary and the file hook return at once when
# nothing is held.
print("\nload-path bookkeeping hoisted (Enhancement-760):")
rc, out, osdi = compile_file("optprobe.va")
check("optprobe.va compiles", rc == 0, out.strip()[-120:])
if rc == 0:
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 optprobe",
              "op\nset scale=2.5\nop\nunset scale\nop", "opt", osdi)
    seen = [l.split("scale=", 1)[1].strip() for l in sim.splitlines() if "scale=" in l]
    check("$simparam(\"scale\") reads 1 before, 2.5 after `set scale=2.5`, 1 again after `unset scale` -- a set between runs reaches the next run",
          len(seen) >= 3 and [float(x) for x in seen[:3]] == [1.0, 2.5, 1.0], str(seen[:3]))
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 optprobe\n.option scale=4",
              "op", "optcard", osdi)
    seen = [l.split("scale=", 1)[1].strip() for l in sim.splitlines() if "scale=" in l]
    check("a deck's `.option scale=4` (the circuit's own variable list) is what the first run reads",
          len(seen) >= 1 and float(seen[0]) == 4.0, str(seen[:1]))
    # `set osdilim_verbose` between two runs: the limiter decision is reported
    # only after the set (the verbose flag was read per load call; it is read
    # per variable-state change now, and the set is one)
    sim = run("V1 in 0 1.0\nN1 in 0 m1\n.model m1 optprobe",
              "op\necho MARK\nset osdilim_verbose\nop", "optv", osdi)
    before, after = sim.split("MARK", 1) if "MARK" in sim else (sim, "")
    check("`set osdilim_verbose` between two runs: the limiter decision is reported after the set, not before",
          "no simulator-side limiting" not in before and "no simulator-side limiting" in after,
          f"before={'yes' if 'no simulator-side limiting' in before else 'no'} after={'yes' if 'no simulator-side limiting' in after else 'no'}")
    # the cost, against the built-in resistor in the same circuit shape: one
    # compiled instance over ~20 000 Newton iterations cost 8x the built-in
    # load per iteration before this enhancement (0.6 us against 0.08) and
    # ~1.5-2.5x after; the ratio holds on a loaded machine, where both grow
    def load_per_iter(dev, tag, runs=3):
        """The load time per Newton iteration, the BEST of `runs` runs: the
        run least disturbed by whatever else the machine is doing. One run
        each was noise on a shared CI runner -- in one linux-arm run the
        compiled load read 0.53 us on one solver pass and 1.33 us on the
        next while the built-in read 0.215 and 0.216."""
        best, n = None, 0
        for _ in range(runs):
            sim = run(f"V1 in 0 pulse(0 1 1n 0.1n 0.1n 50n 100n)\n{dev}\nC1 out 0 1p",
                      "tran 0.1n 1u\nrusage all", tag, osdi)
            m_l = re.search(r"Transient load time = ([\d.eE+-]+)", sim)
            m_i = re.search(r"Transient iterations = (\d+)", sim)
            if m_l and m_i and int(m_i.group(1)) > 0:
                t, n = float(m_l.group(1)) / int(m_i.group(1)), int(m_i.group(1))
                best = t if best is None else min(best, t)
        return best, n
    c_it, c_n = load_per_iter("N1 in out m1\n.model m1 optprobe", "optt")
    b_it, b_n = load_per_iter("R1 in out 1k", "optb")
    # The ratio only: an absolute cap held on one machine (1.5 us/iter on the
    # Linux CI runner, against a built-in resistor's 0.57 there); the E-759
    # binary measured 5x here.
    check("[speed] one compiled instance's load per Newton iteration is under 4x a built-in resistor's, best of three runs each (was 8x: ~0.6 us of bookkeeping against 0.08 us)",
          c_it is not None and b_it is not None and b_it > 0 and c_it < 4.0 * b_it,
          f"compiled {c_it * 1e6:.3f} us/iter over {c_n}, built-in {b_it * 1e6:.3f} us/iter over {b_n}" if (c_it and b_it) else "no timing")

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
