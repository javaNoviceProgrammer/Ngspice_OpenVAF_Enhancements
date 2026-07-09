#!/usr/bin/env python3
"""Verify the LRM example suite against openvaf-r.

[1] every file in va/ compiles cleanly (exit 0)
[2] every file in limitations/ is rejected with the pinned diagnostic
    (and, critically, does NOT crash the compiler)
[3] manifest counts match the files on disk
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

VAF = str(VAF)

manifest = json.load(open(os.path.join(HERE, "manifest.json")))
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))


def compile_va(path, flags):
    r = subprocess.run([VAF, *flags, path], capture_output=True, text=True,
                       timeout=120, cwd=os.path.dirname(path))
    return r.returncode, (r.stderr or "") + (r.stdout or "")


# [1] in-scope examples compile
n_ok = 0
for e in manifest["va"]:
    path = os.path.join(HERE, "va", e["file"])
    code, out = compile_va(path, e.get("flags", []))
    if code != 0:
        check(f"va/{e['file']} compiles", False, out.strip().splitlines()[0] if out.strip() else f"exit {code}")
    else:
        n_ok += 1
check(f"all {len(manifest['va'])} va/ examples compile", n_ok == len(manifest["va"]),
      f"{n_ok}/{len(manifest['va'])}")

# [2] limitations rejected with the pinned diagnostic, without crashing
n_pin = 0
for e in manifest["limitations"]:
    path = os.path.join(HERE, "limitations", e["file"])
    code, out = compile_va(path, e.get("flags", []))
    crashed = "crashed" in out
    if code == 0 or crashed or e["expect"] not in out:
        why = "compiled unexpectedly" if code == 0 else (
              "CRASHED" if crashed else f"diagnostic changed: wanted {e['expect']!r}")
        check(f"limitations/{e['file']} pinned", False, why)
    else:
        n_pin += 1
check(f"all {len(manifest['limitations'])} limitations pinned (rejected, no crash)",
      n_pin == len(manifest["limitations"]), f"{n_pin}/{len(manifest['limitations'])}")

# [3] findings/ micro-repros: fixed defects must compile, open gaps must
# stay pinned to their diagnostic (and never crash)
n_find = 0
for e in manifest["findings"]:
    path = os.path.join(HERE, "findings", e["file"])
    code, out = compile_va(path, e.get("flags", []))
    crashed = "crashed" in out
    if "expect" in e:
        ok = code != 0 and not crashed and e["expect"] in out
        why = "compiled unexpectedly" if code == 0 else (
              "CRASHED" if crashed else f"diagnostic changed: wanted {e['expect']!r}")
    else:
        ok = code == 0
        why = out.strip().splitlines()[0] if out.strip() else f"exit {code}"
    if ok:
        n_find += 1
    else:
        check(f"findings/{e['file']}", False, why)
check(f"all {len(manifest['findings'])} findings pinned", n_find == len(manifest["findings"]),
      f"{n_find}/{len(manifest['findings'])}")

# [4] manifest matches the tree
for d, key in (("va", "va"), ("limitations", "limitations"), ("ams", "ams"),
               ("findings", "findings")):
    files = sorted(f for f in os.listdir(os.path.join(HERE, d)) if f.endswith(".va"))
    check(f"{d}/ matches manifest ({len(files)} files)",
          files == sorted(e["file"] for e in manifest[key]))

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
