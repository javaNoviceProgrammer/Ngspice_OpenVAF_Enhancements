#!/usr/bin/env python3
"""Enhancement-598: `$simparam$str(name, default)` -- the non-fatal string form.

The two-argument call was refused at compile time ("expected 1 arguments but
found 2") although the backend had carried the `simparam_str_opt` callback
since Enhancement-215, so a model had no way to ask for a string simparam a
simulator may not serve (`instance`, `module`, `path`) without a `$fatal` at
the operating point (F3 of the 2026-09-10 integration hunt). The LRM's own
syntax, 9.15.1, gives the string form the same optional default as `$simparam`.

Checks:
  [1] compile: the two-argument form is accepted; a non-string default and a
      third argument are refused; the one-argument form still warns L025 on an
      unserved name and the two-argument form does not
  [2] run: a served name with a default returns the served value; an unserved
      name returns the default -- a literal, a string parameter, a string
      variable; the run completes (the one-argument form is a $fatal there)
  [3] a parameter default `parameter string q = $simparam$str("module", "d")`
      resolves to the default, `("simulator", "?")` to "ngspice"
  [4] the L025 note names the string spelling of the help
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

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="simparamstrdef_")
N1 = "@" + "n1"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def compile_va(name, body, decl=""):
    va = os.path.join(WORK, name + ".va")
    with open(va, "w") as f:
        f.write(f'`include "disciplines.vams"\nmodule {name}(p, n);\ninout p, n; electrical p, n;\n{decl}\n'
                f'string s;\nanalog begin\n{body}\n  I(p,n) <+ V(p,n)/1k;\nend\nendmodule\n')
    r = subprocess.run([VAF, va, "-o", os.path.join(WORK, name + ".osdi")], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def run(name, ctl):
    path = os.path.join(WORK, name + ".cir")
    with open(path, "w") as f:
        f.write(f"* simparamstrdef {name}\n.control\npre_osdi {name}.osdi\n.endc\nv1 a 0 1\nn1 a 0 mm\n.model mm {name}\n.control\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120, cwd=WORK)
    return p.stdout + p.stderr


def vals(out):
    return {m.group(1).lower(): float(m.group(2)) for m in re.finditer(r"(?m)^(@\S+) = (\S+)", out)}


print("Enhancement-598: $simparam$str with a default\n")

# ------------------------------------------------------------- [1] ---
rc, log = compile_va("c1", '  s = $simparam$str("instance", "dflt");')
check("[1] the two-argument form compiles", rc == 0, log[-200:])
check("[1] ...and does not warn L025 for the unserved name (the default is the point)", "L025" not in log, log[-200:])
rc, log = compile_va("c2", '  s = $simparam$str("instance", 5);')
check("[1] a non-string default is a type error", rc != 0 and "expected string value" in log, log[-200:])
rc, log = compile_va("c3", '  s = $simparam$str("instance", "a", "b");')
check("[1] three arguments are refused", rc != 0 and "expected at most 2 arguments" in log, log[-200:])
rc, log = compile_va("c4", '  s = $simparam$str("instance");')
check("[1] the one-argument form still warns L025 on an unserved name", rc == 0 and "L025" in log, log[-200:])
check("[4] ...and the note spells the string form of the help",
      '$simparam$str("instance", "<default>")' in log, log[-300:])

# ------------------------------------------------------------- [2] ---
body = '''  ok1 = ($simparam$str("analysis_name", "none") == "none") ? 0 : 1;
  ok2 = ($simparam$str("instance", "dflt") == "dflt") ? 1 : 0;
  ok3 = ($simparam$str("module", dflt) == "fallback") ? 1 : 0;
  s = "var";
  ok4 = ($simparam$str("path", s) == "var") ? 1 : 0;
  ok5 = ($simparam$str("simulator", "?") == "ngspice") ? 1 : 0;'''
decl = ('parameter string dflt = "fallback";\n' + "\n".join(f'(* desc="ok{i}" *) real ok{i};' for i in range(1, 6)))
rc, log = compile_va("r1", body, decl)
check("[2] the run model compiles", rc == 0, log[-200:])
out = run("r1", "op\n" + "\n".join(f"print {N1}[ok{i}]" for i in range(1, 6)))
v = vals(out)
check("[2] a served name with a default returns the served value (analysis_name, simulator)",
      v.get(f"{N1}[ok1]") == 1.0 and v.get(f"{N1}[ok5]") == 1.0, f"{v}")
check("[2] an unserved name returns the default: a literal, a string parameter, a string variable",
      v.get(f"{N1}[ok2]") == 1.0 and v.get(f"{N1}[ok3]") == 1.0 and v.get(f"{N1}[ok4]") == 1.0, f"{v}")
check("[2] ...and the run completes, where the one-argument form is a $fatal",
      "fatal" not in out.lower() and "aborting" not in out, out[-200:])
rc, log = compile_va("r2", '  s = $simparam$str("instance");\n  a = (s == "x") ? 1 : 0;', '(* desc="a" *) real a;')
out = run("r2", "op\nprint v(a)")
check("[2] (control) the one-argument form on the same name is fatal at the operating point",
      'unknown $simparam$str "instance"' in out and "aborting" in out, out[-200:])

# ------------------------------------------------------------- [3] ---
rc, log = compile_va("p1", '  a = (q == "d") ? 1 : 0;\n  b = (q2 == "ngspice") ? 1 : 0;',
                     'parameter string q = $simparam$str("module", "d");\nparameter string q2 = $simparam$str("simulator", "?");\n'
                     '(* desc="a" *) real a;\n(* desc="b" *) real b;')
check("[3] the two-argument form is accepted as a parameter default", rc == 0, log[-200:])
out = run("p1", f"op\nprint {N1}[a]\nprint {N1}[b]\nshowmod mm")
v = vals(out)
check("[3] ...the unserved name resolves to the default and the served one to its value",
      v.get(f"{N1}[a]") == 1.0 and v.get(f"{N1}[b]") == 1.0 and re.search(r"\bq\s+d\b", out) and re.search(r"\bq2\s+ngspice\b", out), f"{v}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
