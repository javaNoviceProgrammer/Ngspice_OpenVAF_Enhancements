#!/usr/bin/env python3
"""Enhancements 820 to 822 (F4-F6 of the 2026-10-08 ngspice + OSDI hunt): what a
.dc sweep of a temperature or of an OSDI parameter does to a Verilog-A model's
state, its final step, the values it leaves behind and the place its messages
name.

Enhancement-820 (F4). A `.dc temp` or `.dc @n1[p]` point re-runs the device's
temperature pass, which re-fires @(initial_step) -- kept: BSIM4 does its whole
temperature and parameter preprocessing there, and LRM 5.2.1 re-executes
initialisation when a sweep changes a parameter it reads. But every variable
was initialised with it, so a counter read the same at every point where a
source sweep carried it (LRM 4.6.2 carries variables from one dc point to the
next); and @(final_step) ran after the sweep had restored the temperature or
parameter, so it saw the netlist's value, not the last point's (Table 5-1).
  [1] dc temp, dc @n1[p] (instance), dc @tm[q] (model): the initial step at
      every point, recomputing what depends on the swept value, the variable
      carried from its declared 10 to 13; @(final_step) at the last point
  [1] a source sweep (control), a nested source/temperature sweep, an op after
      the sweep (the variable starts again), $finish in a temperature sweep
      (the final step at the finishing point)

Enhancement-821 (F5). A sweep aborted by a Verilog-A $fatal returned with the
swept source or parameter at the failing value, so every later analysis ran on
it until `reset` and the next op raised the same $fatal.
  [2] a source and a model-parameter sweep aborted by $fatal: the netlist's
      value back, the next op runs; $stop still keeps its value (resumable)

Enhancement-822 (F6). A message raised in a setup or temperature pass took its
place from whatever analysis ran last: a parameter or temperature sweep named
the previous point, an op after a dc said "(at sweep value 0)", an altermod
after a tran "(at t = 2e-09)". And a $fatal raised in setup code printed twice.
  [3] the point being applied, "(during setup)" outside a sweep, once
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

WORK = tempfile.mkdtemp(prefix="sweepstate_")
checks = passed = 0

H = '`include "disciplines.vams"\n'
MODULES = {
    # counts its initial steps into a variable with a declared initial value,
    # and computes there a conductance from the temperature and both parameters
    "tev": H + """module tev(a, b);
inout a, b; electrical a, b;
(* type="instance" *) parameter real p = 1;
parameter real q = 1;
integer n = 10;
real g;
analog begin
  @(initial_step) begin
    n = n + 1;
    g = 1e-3*p*q*$temperature/300.15;
    $strobe("INIT n=%0d T=%.2f p=%g q=%g", n, $temperature, p, q);
  end
  I(a,b) <+ g*V(a,b);
  @(final_step) $strobe("FINAL n=%0d T=%.2f V=%.3f p=%g q=%g", n, $temperature, V(a,b), p, q);
end
endmodule
""",
    "tfin": H + """module tfin(a, b);
inout a, b; electrical a, b;
analog begin
  I(a,b) <+ V(a,b)/1k;
  if (V(a,b) > 0.5 && $temperature > 320) $finish;
  @(final_step) $strobe("FINAL T=%.2f", $temperature);
end
endmodule
""",
    # $fatal on the solution, and on a parameter (hoisted into setup)
    "fv": H + """module fv(a, b);
inout a, b; electrical a, b;
analog begin
  I(a,b) <+ V(a,b)/1k;
  if (V(a,b) > 1.5) $fatal(0, "too high %g", V(a,b));
end
endmodule
""",
    "fp": H + """module fp(a, b);
inout a, b; electrical a, b;
parameter real g = 1e-3;
analog begin
  I(a,b) <+ g*V(a,b);
  if (g > 2.5e-3) $fatal(0, "g too big %g", g);
end
endmodule
""",
    "fs": H + """module fs(a, b);
inout a, b; electrical a, b;
analog begin
  I(a,b) <+ V(a,b)/1k;
  if (V(a,b) > 1.5 && V(a,b) < 2.5) $stop;
end
endmodule
""",
    # a temperature-dependent warning (setup code) and a solution-dependent one
    "tw": H + """module tw(a, b);
inout a, b; electrical a, b;
analog begin
  I(a,b) <+ V(a,b)/1k;
  if ($temperature > 310) $warning("hot %g", $temperature - 273.15);
  if (V(a,b) > 1.5) $warning("high %g", V(a,b));
end
endmodule
""",
}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


for name, src in MODULES.items():
    va = os.path.join(WORK, name + ".va")
    with open(va, "w") as f:
        f.write(src)
    r = subprocess.run([VAF, va, "-o", os.path.join(WORK, name + ".osdi")],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(module, body, ctl, tag):
    """combined stdout+stderr of a deck loading `module`"""
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* sweepstate {tag}\n.control\npre_osdi {module}.osdi\n.endc\n{body}\n"
                f".control\nset numdgt=8\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, errors="replace")
    return p.stdout + p.stderr


def inits(out):
    """(n, T, p, q) of every INIT line"""
    return [(int(a), float(b), float(c), float(d))
            for a, b, c, d in re.findall(r"INIT n=(\d+) T=(\S+) p=(\S+) q=(\S+)", out)]


def finals(out):
    return [(int(a), float(b), float(c), float(d), float(e)) for a, b, c, d, e in
            re.findall(r"FINAL n=(\d+) T=(\S+) V=(\S+) p=(\S+) q=(\S+)", out)]


def rows(out):
    """the last column of every `print` table row"""
    return [float(m) for m in re.findall(r"^\d+\t\S+\t(\S+)\s*$", out, re.M)]


def val(out, name):
    m = re.search(r"^" + re.escape(name) + r" = (\S+)", out, re.M)
    return float(m.group(1).rstrip(",")) if m else None


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1e-12, abs(b))


def lines(out, pat):
    return [l.strip() for l in out.splitlines() if re.search(pat, l)]


TEV = "v1 1 0 1\nn1 1 0 tm\n.model tm tev"
G = lambda t, p=1.0, q=1.0: 1e-3 * p * q * t / 300.15   # noqa: E731

print("Enhancements 820-822: a .dc sweep of a temperature or an OSDI parameter\n")

# ------------------------------------------------------------- [1] ---
print("[1] Enhancement-820: the initial step per point, the variables carried, the final step at the last point")
out = run("tev", TEV, "dc temp 0 100 50\nprint i(v1)", "temp")
ts = [273.15, 323.15, 373.15]
check("[1] `dc temp 0 100 50`: the initial step at each point, the variable carried 11, 12, 13 "
      "(was 11 at every point)",
      inits(out) == [(11, ts[0], 1, 1), (12, ts[1], 1, 1), (13, ts[2], 1, 1)], f"{inits(out)}")
check("[1] ...the conductance it computes follows the temperature: i(v1) = -1 mA * T/300.15 at each point",
      len(rows(out)) == 3 and all(near(a, -G(t)) for a, t in zip(rows(out), ts)), f"{rows(out)}")
check("[1] ...@(final_step) once, at the last point, T = 373.15 (was the restored 300.15)",
      finals(out) == [(13, 373.15, 1.0, 1, 1)], f"{finals(out)}")

out = run("tev", TEV, "dc @n1[p] 1 3 1\nprint i(v1)", "inst")
check("[1] `dc @n1[p] 1 3 1` (instance parameter): the variable carried 11, 12, 13; "
      "i(v1) = -p mA; the final step at p = 3 (was 11 at every point and p = 1)",
      [i[0] for i in inits(out)] == [11, 12, 13] and [i[2] for i in inits(out)] == [1, 2, 3]
      and len(rows(out)) == 3 and all(near(a, -G(300.15, p=k)) for a, k in zip(rows(out), (1, 2, 3)))
      and finals(out) == [(13, 300.15, 1.0, 3, 1)], f"{inits(out)} {rows(out)} {finals(out)}")

out = run("tev", TEV, "dc @tm[q] 1 3 1\nprint i(v1)", "model")
check("[1] `dc @tm[q] 1 3 1` (model parameter): the variable carried 11, 12, 13; "
      "i(v1) = -q mA; the final step at q = 3 (was 11 at every point and q = 1)",
      [i[0] for i in inits(out)] == [11, 12, 13] and [i[3] for i in inits(out)] == [1, 2, 3]
      and len(rows(out)) == 3 and all(near(a, -G(300.15, q=k)) for a, k in zip(rows(out), (1, 2, 3)))
      and finals(out) == [(13, 300.15, 1.0, 1, 3)], f"{inits(out)} {rows(out)} {finals(out)}")

out = run("tev", TEV, "dc v1 0 2 1", "src")
check("[1] `dc v1 0 2 1` (control): one initial step, the final step at V = 2",
      inits(out) == [(11, 300.15, 1, 1)] and finals(out) == [(11, 300.15, 2.0, 1, 1)],
      f"{inits(out)} {finals(out)}")

out = run("tev", TEV, "dc v1 0 1 1 temp 0 100 100", "nested")
check("[1] `dc v1 0 1 1 temp 0 100 100`: an initial step per temperature, the variable carried "
      "11, 12; the final step at 373.15 K and V = 1",
      inits(out) == [(11, 273.15, 1, 1), (12, 373.15, 1, 1)] and finals(out) == [(12, 373.15, 1.0, 1, 1)],
      f"{inits(out)} {finals(out)}")

out = run("tev", TEV, "dc temp 0 100 50\nop\nprint i(v1)", "then_op")
check("[1] an op after the sweep is a new analysis: the variable starts again at 11, at 300.15 K, "
      "i(v1) = -1 mA",
      [i[0] for i in inits(out)] == [11, 12, 13, 11] and inits(out)[-1][1] == 300.15
      and [f[:2] for f in finals(out)] == [(13, 373.15), (11, 300.15)]
      and near(val(out, "i(v1)"), -1e-3), f"{inits(out)} {finals(out)} {val(out, 'i(v1)')}")

out = run("tfin", "v1 1 0 1\nn1 1 0 fm\n.model fm tfin", "dc temp 0 100 50", "finish")
check("[1] $finish at the 50 C point of a temperature sweep: the final step at that point, "
      "T = 323.15 (was the restored 300.15)",
      "$finish requested" in out and re.findall(r"FINAL T=(\S+)", out) == ["323.15"],
      f"{re.findall(r'FINAL T=(\S+)', out)} {out[-300:]}")

# ------------------------------------------------------------- [2] ---
print("[2] Enhancement-821: an aborted sweep puts the swept value back")
out = run("fv", "v1 1 0 1\nn1 1 0 fm\n.model fm fv", "dc v1 0 3 1\nprint @v1[dc]\nop\nprint i(v1)", "abort_src")
check("[2] `dc v1 0 3 1` stopped by $fatal at 2 V: @v1[dc] back to the netlist's 1 (was 2), "
      "and the next op runs: i(v1) = -1 mA, the $fatal once",
      "raised $fatal at sweep value 2" in out and val(out, "@v1[dc]") == 1.0
      and near(val(out, "i(v1)"), -1e-3) and len(lines(out, r"^\s*OSDI\(fatal\)")) == 1,
      f"{val(out, '@v1[dc]')} {val(out, 'i(v1)')} {lines(out, 'OSDI.fatal')}")

out = run("fp", "v1 1 0 1\nn1 1 0 fpm\n.model fpm fp g=1m", "dc @fpm[g] 1m 4m 1m\nprint @fpm[g]\nop\nprint i(v1)",
          "abort_par")
check("[2] `dc @fpm[g] 1m 4m 1m` stopped by $fatal at 3m: @fpm[g] back to 1m (was 3m), "
      "and the next op runs: i(v1) = -1 mA",
      "raised $fatal at sweep value 0.003" in out and near(val(out, "@fpm[g]"), 1e-3)
      and near(val(out, "i(v1)"), -1e-3) and len(lines(out, r"^\s*OSDI\(fatal\)")) == 1,
      f"{val(out, '@fpm[g]')} {val(out, 'i(v1)')} {lines(out, 'OSDI.fatal')}")

out = run("fs", "v1 1 0 1\nn1 1 0 fm\n.model fm fs", "dc v1 0 3 1\nprint @v1[dc]", "stop")
check("[2] $stop at 2 V (control): a pause keeps the swept value for `resume`, @v1[dc] = 2",
      "$stop requested" in out and val(out, "@v1[dc]") == 2.0, f"{val(out, '@v1[dc]')} {out[-300:]}")

# ------------------------------------------------------------- [3] ---
print("[3] Enhancement-822: the place a setup-pass message names")
out = run("fp", "v1 1 0 1\nn1 1 0 fpm\n.model fpm fp g=1m", "dc @fpm[g] 1m 4m 1m", "tag_par")
check("[3] `dc @fpm[g] 1m 4m 1m`: the device's line names the point it was raised at, 0.003, "
      "as the error line does (was 0.002)",
      lines(out, r"^\s*OSDI\(fatal\)") == ["OSDI(fatal) n1: g too big 0.003 (at sweep value 0.003)"],
      f"{lines(out, 'OSDI.fatal')}")

out = run("tw", "v1 1 0 1\nn1 1 0 twm\n.model twm tw", "dc temp 0 100 50", "tag_temp")
check("[3] `dc temp 0 100 50` with a temperature-dependent $warning: 'hot 50 (at sweep value 50)', "
      "'hot 100 (at sweep value 100)' (were 0 and 50)",
      lines(out, r"^\s*OSDI\(warn\)") == ["OSDI(warn) n1: hot 50 (at sweep value 50)",
                                      "OSDI(warn) n1: hot 100 (at sweep value 100)"],
      f"{lines(out, 'OSDI.warn')}")

out = run("tw", "v1 1 0 1\nn1 1 0 twm\n.model twm tw", "dc v1 0 2 1\ntran 1n 2n", "tag_solve")
check("[3] a solution-dependent $warning (control): 'high 2 (at sweep value 2)' in the dc",
      lines(out, r"^\s*OSDI\(warn\)") == ["OSDI(warn) n1: high 2 (at sweep value 2)"],
      f"{lines(out, 'OSDI.warn')}")

out = run("fp", "v1 1 0 1\nn1 1 0 fpm\n.model fpm fp g=3m", "op", "tag_op")
check("[3] `op` with g = 3m on the card: the setup $fatal once, '(during setup)' "
      "(was twice, with no place)",
      lines(out, r"^\s*OSDI\(fatal\)") == ["OSDI(fatal) n1: g too big 0.003 (during setup)"]
      and "raised $fatal during the operating point" in out, f"{lines(out, 'OSDI.fatal')}")

out = run("fp", "v1 1 0 1\nn1 1 0 fpm\n.model fpm fp g=1m", "tran 1n 2n\naltermod fpm g=3m\nop", "tag_tran")
check("[3] `altermod fpm g=3m` after a tran, then `op`: '(during setup)' at each "
      "(were '(at t = 2e-09)' and twice '(at t = 0)')",
      lines(out, r"^\s*OSDI\(fatal\)") == ["OSDI(fatal) n1: g too big 0.003 (during setup)"] * 2,
      f"{lines(out, 'OSDI.fatal')}")

out = run("fp", "v1 1 0 1\nn1 1 0 fpm\n.model fpm fp g=1m", "dc v1 0 1 1\naltermod fpm g=3m\nop", "tag_dc")
check("[3] `altermod fpm g=3m` after a finished dc, then `op`: '(during setup)' at each "
      "(were '(at sweep value 1)' and twice '(at sweep value 0)')",
      lines(out, r"^\s*OSDI\(fatal\)") == ["OSDI(fatal) n1: g too big 0.003 (during setup)"] * 2,
      f"{lines(out, 'OSDI.fatal')}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
