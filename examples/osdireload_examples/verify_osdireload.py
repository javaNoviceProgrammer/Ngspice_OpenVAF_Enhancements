#!/usr/bin/env python3
"""verify_osdireload.py -- Enhancement-229: `pre_osdi -f` force-reload.

In interactive mode ngspice loads each OSDI object file once: a plain re-load of
an already-loaded `.osdi` (e.g. when you re-`source` a deck) is skipped, because
the device type is already in the global registry and re-registering it would
silently shadow the new copy. That means recompiling a Verilog-A model does NOT
take effect without restarting ngspice.

Enhancement-229 adds a `-f` (`-force`) flag to `pre_osdi` / the `osdi` command:
it stages a fresh copy of the (recompiled) file under a unique path -- so dlopen
re-reads it instead of returning its cached handle -- and swaps the registered
device to the new descriptor in place. The edit -> recompile -> re-source loop
now picks up the new model with no restart.

This test drives ngspice in pipe mode: it loads a model whose resistance is 1k,
runs, recompiles the SAME file to a 2k model mid-session, and checks that a plain
re-load is skipped (still 1k) while `-f` reloads it (now 2k). The mid-session
recompile is simulated with an OS copy via ngspice's `shell` command (overwriting
a mapped file in place is a POSIX capability; on Windows the file would be locked,
which is the same reason the feature is chiefly for Linux/macOS developers).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE

checks = passed = 0
D = tempfile.mkdtemp(prefix="osdireload229_")
CP = "copy /Y" if os.name == "nt" else "cp -f"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def compile_va(body, out):
    src = os.path.join(D, out.replace(".osdi", ".va"))
    with open(src, "w") as f:
        f.write(body)
    r = subprocess.run([OPENVAF, src, "-o", os.path.join(D, out)],
                       capture_output=True, text=True, cwd=D)
    return r.returncode == 0 and os.path.exists(os.path.join(D, out))


MOD = ("`include \"disciplines.vams\"\n"
       "module vares(p,n);\n  inout p,n; electrical p,n;\n"
       "  analog V(p,n) <+ %d*I(p,n);\nendmodule\n")

print("Enhancement-229: pre_osdi -f reloads a recompiled .osdi (no restart)")

ok1 = compile_va(MOD % 1000, "mv1.osdi")   # R = 1k
ok2 = compile_va(MOD % 2000, "mv2.osdi")   # R = 2k
check("compiled two model versions (R=1k, R=2k) with openvaf-r", ok1 and ok2)

if not (ok1 and ok2):
    print(f"\n{passed}/{checks} checks passed")
    raise SystemExit(1)

shutil.copy(os.path.join(D, "mv1.osdi"), os.path.join(D, "m.osdi"))
with open(os.path.join(D, "run.cir"), "w") as f:
    f.write("* osdi reload circuit\nN1 a 0 rmod\nV1 a 0 1\n.model rmod vares\n.end\n")

# One interactive session: load v1, run; recompile to v2; plain reload (skipped);
# forced reload; run again. i(v1) = -1/R, so -1mA (1k) then -0.5mA (2k).
script = "\n".join([
    "osdi m.osdi",
    "source run.cir", "op", "print i(v1)",
    "shell %s mv2.osdi m.osdi" % CP,
    "osdi m.osdi",            # plain: already loaded -> skipped
    "osdi -f m.osdi",         # forced: reloaded
    "op",                     # hunt F16: the circuit built against v1 is refused
    "reset", "op", "print i(v1)",   # rebuilt against v2
    "source run.cir", "op", "print i(v1)",
    "quit", ""])
r = subprocess.run([NGSPICE, "-p"], input=script, capture_output=True, text=True,
                   cwd=D, errors="replace", timeout=60)
out = (r.stdout or "") + (r.stderr or "")
vals = [float(x) for x in re.findall(r"i\(v1\)\s*=\s*([-\d.eE+]+)", out)]

check("valid .osdi loads and simulates (R=1k -> i(v1) = -1mA)",
      len(vals) >= 1 and abs(vals[0] - (-1e-3)) < 1e-6,
      f"vals={vals}" if len(vals) < 1 else f"i={vals[0]:.3e}")
check("plain re-load of an already-loaded file is skipped (with a hint)",
      "already loaded" in out.lower() and "-f" in out)
check("`-f` reports a reload of the recompiled file",
      re.search(r"reloaded .*m\.osdi", out) is not None)
check("after `-f`, the recompiled model takes effect (R=2k -> i(v1) = -0.5mA)",
      len(vals) >= 3 and abs(vals[2] - (-0.5e-3)) < 1e-6,
      f"vals={vals}" if len(vals) < 3 else f"i={vals[2]:.3e}")
# hunt F16 (2026-09-05): the circuit built against v1 resolves its device type
# through the table `-f` just swapped, so a run would execute v2's code on v1's
# data layout. The reload says so, the run is refused, and a `reset` rebuilds
# the circuit against v2 (the same -0.5 mA the re-source gives).
check("hunt F16: the reload names the circuit built against the previous object, its next run is refused, and `reset` rebuilds it against the new one",
      "was built against the previous" in out and "cannot run on the new object's code" in out
      and len(vals) >= 3 and abs(vals[1] - (-0.5e-3)) < 1e-6,
      f"vals={vals} note={'was built against the previous' in out} refused={'cannot run on the new' in out}")

shutil.rmtree(D, ignore_errors=True)
print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
