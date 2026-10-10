#!/usr/bin/env python3
"""verify_paramcycle.py -- Enhancement-844: a parameter without a type that reads
itself, or a later parameter, is an error and not a compiler panic.

F7 of the 2026-10-10 robustness and correctness campaign. A parameter declared
without a type takes the type of its default, so typing a read of one means
inferring that parameter's own body. A read inside a parameter's body that is not
strictly earlier in the file -- the parameter itself, in its default or its range,
or one declared afterwards that reads back -- asked for an inference already in
progress, and the compiler died on salsa's cycle panic (exit 101, the crash
banner). The fuzz found it as `parameter ione ione = ...`, where error recovery
leaves the default reading the parameter; `parameter p = p;` does the same with no
parse error at all. With a type (`parameter real p = p;`) the same reads were
already reported, since Enhancement-414 and before.

  [1] each untyped spelling is reported with the existing message, exit 65,
      and no crash: itself in the default, in an expression, in its range;
      a localparam; two parameters reading each other; through an aliasparam;
      the fuzz's `parameter p p = 1;`
  [2] the typed spellings are reported as before (control)
  [3] untyped parameters reading earlier ones still compile, and still take
      their defaults' types: an integer chain divides as integers

The solver plays no part in [1] and [2]; [3] runs the model once.
Exit code 0 = pass.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

WORK = tempfile.mkdtemp(prefix="paramcycle_")
HDR = '`include "disciplines.vams"\n'
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def compile_text(name, decls, use="p"):
    src = os.path.join(WORK, f"{name}.va")
    with open(src, "w") as f:
        f.write(HDR + "module m(a, c); inout a, c; electrical a, c;\n" + decls + "\n"
                f"analog I(a, c) <+ {use}*1e-3*V(a, c);\nendmodule\n")
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(WORK, f"{name}.osdi")],
                       capture_output=True, text=True, timeout=300, cwd=WORK,
                       env=dict(os.environ, RAYON_NUM_THREADS="1"))
    return r.returncode, r.stdout + r.stderr


def crashed(rc, log):
    return rc == 101 or rc < 0 or "has crashed" in log


def errors(log):
    return [l for l in log.splitlines() if l.startswith("error:") and "could not compile" not in l]


def reported(rc, log, msg):
    return rc == 65 and not crashed(rc, log) and any(msg in e for e in errors(log))


SELF = "references itself"
LATER = "defined afterwards"

print("  [1] untyped declarations that read themselves or a later parameter")
for name, decls, use, msg in (
        ("default", "parameter p = p;", "p", SELF),
        ("expr", "parameter p = 2*p + 1;", "p", SELF),
        ("range", "parameter p = 1 from [0:p];", "p", SELF),
        ("local", "localparam l = l + 1;", "l", SELF),
        ("mutual", "parameter p = q;\nparameter q = p;", "p", LATER),
        ("alias", "parameter p = al;\naliasparam al = p;", "p", SELF)):
    rc, log = compile_text("u_" + name, decls, use)
    check(f"[1] {decls.replace(chr(10), ' ')}: reported ({msg}), exit 65, no crash",
          reported(rc, log, msg), f"rc={rc} " + "; ".join(errors(log))[:90])
rc, log = compile_text("u_fuzz", "parameter p p = 1;", "1.0")
check("[1] parameter p p = 1; (the fuzz's spelling): the parse error, exit 65, no crash",
      rc == 65 and not crashed(rc, log) and any("expected '='" in e for e in errors(log)),
      f"rc={rc} " + "; ".join(errors(log))[:90])

print("\n  [2] the typed spellings (control)")
for name, decls, msg in (("default", "parameter real p = p;", SELF),
                         ("range", "parameter integer p = 4 from [p:8];", SELF),
                         ("mutual", "parameter real p = q;\nparameter real q = p;", LATER)):
    rc, log = compile_text("t_" + name, decls)
    check(f"[2] {decls.replace(chr(10), ' ')}: reported ({msg}), exit 65",
          reported(rc, log, msg), f"rc={rc} " + "; ".join(errors(log))[:90])

print("\n  [3] untyped parameters reading earlier ones")
rc, log = compile_text("chain", "parameter n = 3;\nparameter k = n*2;\nparameter x = 1.5;\n"
                       "parameter y = x*k;", "(k/4 + y)")
check("[3] n = 3, k = n*2, x = 1.5, y = x*k compile", rc == 0, f"rc={rc} " + "; ".join(errors(log))[:90])
if rc == 0:
    cir = os.path.join(WORK, "chain.cir")
    with open(cir, "w") as f:
        f.write("* chain\n.control\npre_osdi " + os.path.join(WORK, "chain.osdi") + "\n.endc\n"
                "v1 a 0 dc 1\nn1 a 0 mm\n.model mm m\n.control\nop\nprint i(v1)\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", cir], capture_output=True, text=True, timeout=120,
                       cwd=WORK, errors="replace")
    m = re.search(r"^i\(v1\)\s*=\s*(\S+)", p.stdout, re.M)
    i = float(m.group(1)) if m else None
    # k is an integer (6), so k/4 = 1; y = 1.5*6 = 9 is real; I = (1 + 9)*1e-3 at 1 V
    check("[3] ...and k is an integer (k/4 = 1) and y real (9): i(v1) = -10 mA",
          i is not None and abs(i + 10e-3) < 1e-12, f"i(v1)={i}")

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
