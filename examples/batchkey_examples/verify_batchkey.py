#!/usr/bin/env python3
"""Enhancement-453: the batch cache answered with the wrong build, and an
impossible target crashed the compiler.

BATCH MODE keys its cache on the source text, the defines, the lints and the
compiler version. The settings that decide what MACHINE CODE comes out were not
part of the key, so a request that differed only in those settings was answered
with whatever artifact was already in the cache:

  * `-O`.  `openvaf-r m.va -b -O 0` followed by `openvaf-r m.va -b -O 3`
    produced ONE cache entry. The second run printed nothing unusual, exited 0,
    and handed back the `-O 0` build -- 113424 bytes where a real `-O 3` build
    is 36936. Debug once and every later optimized build is silently the debug
    one.

  * `--target`.  A cross-target request was answered with the HOST artifact:
    `--target x86_64-unknown-linux` on an arm64 mac exited 0 with an arm64
    Mach-O in hand. A Linux build that is not a Linux build, reported as
    success.

CROSS-COMPILING itself then panicked. `initialize_llvm` registers only the
NATIVE LLVM target, so a foreign architecture failed inside `create_target`
("No available targets are compatible with triple ...") -- and that failure was
reached through `back.new_module(..).unwrap()` on a rayon worker: exit 101, a
crash banner, a crash-log file and a request to open a GitHub issue, for asking
a mac binary to build for Linux.

The two are one story: with the target in the cache key the wrong-artifact answer
becomes a real compile, and that compile must then fail HONESTLY rather than
abort. Both halves are checked here, because fixing only the key would have
turned a silently wrong answer into a crash.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

checks = passed = 0
SRC = ('`include "disciplines.vams"\n'
       'module batchkey(a,b); inout a,b; electrical a,b;\n'
       '  parameter real g = 1e-3;\n'
       '  analog I(a,b) <+ V(a,b)*g;\n'
       'endmodule\n')

# A target that no build of this compiler can emit on a machine whose LLVM is
# initialized with the native target only. Picked to differ from every host
# architecture the project ships for, so the check means the same thing on an
# arm64 mac and on an x86_64 Linux box.
FOREIGN = "riscv64-unknown-linux"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def src_path():
    p = os.path.join(HERE, "_bk.va")
    with open(p, "w") as f:
        f.write(SRC)
    return p


def run(args, cache=None):
    """openvaf-r with `args`; returns (rc, output)."""
    r = subprocess.run([OPENVAF] + args, capture_output=True, text=True,
                       timeout=300, cwd=HERE)
    return r.returncode, (r.stdout + r.stderr)


def cache_dir(name):
    """A fresh, EXISTING cache directory -- `--cache-dir` requires one."""
    d = os.path.join(HERE, name)
    if os.path.isdir(d):
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
    else:
        os.makedirs(d)
    return d


def entries(d):
    return sorted(os.listdir(d))


print("Enhancement-453: the batch cache key, and an impossible target\n")
va = src_path()

# ------------------------------------------------------- the optimization level
print("the cache key covers -O")
d = cache_dir("_bk_opt")
rc0, _ = run([va, "--batch", "--cache-dir", d, "-O", "0"])
after_o0 = entries(d)
rc3, _ = run([va, "--batch", "--cache-dir", d, "-O", "3"])
after_o3 = entries(d)
check("[E-453] -O 0 then -O 3 are two DIFFERENT cache entries",
      len(after_o3) == 2, f"{len(after_o3)} entry/entries, rc={rc0}/{rc3}")
sizes = sorted(os.path.getsize(os.path.join(d, f)) for f in after_o3)
check("[E-453] ...and they are genuinely different builds",
      len(set(sizes)) == 2, f"sizes {sizes}")

# The point of a cache is still to hit. Re-asking for -O 0 must reuse, not add.
run([va, "--batch", "--cache-dir", d, "-O", "0"])
check("[E-453] re-running -O 0 HITS the cache (no third entry)",
      len(entries(d)) == 2, f"{len(entries(d))} entries")

# ---------------------------------------------------------------- the target
print("\nthe cache key covers --target")
d = cache_dir("_bk_tgt")
rc_native, _ = run([va, "--batch", "--cache-dir", d])
native_entries = entries(d)
check("[E-453] a native batch build caches one artifact",
      rc_native == 0 and len(native_entries) == 1, f"rc={rc_native}")

rc_x, out_x = run([va, "--batch", "--cache-dir", d, "--target", FOREIGN])
check("[E-453] a foreign --target is NOT answered from the host cache",
      rc_x != 0, f"rc={rc_x}")
check("[E-453] ...and does NOT panic (exit 101 + crash report)",
      rc_x != 101, f"rc={rc_x}")
check("[E-453] ...and no foreign artifact was invented",
      entries(d) == native_entries, f"{entries(d)}")

# --------------------------------------------------- the target must be honest
print("\nan impossible target is refused, not aborted")
rc_f, out_f = run([va, "-o", "_bk_x.osdi", "--target", FOREIGN])
check("[E-453] a foreign --target is refused", rc_f != 0, f"rc={rc_f}")
check("[E-453] ...and does NOT panic", rc_f != 101, f"rc={rc_f}")
check("[E-453] ...and no crash report is produced",
      "has crashed" not in out_f and "open an issue" not in out_f,
      out_f.strip().splitlines()[0][:60] if out_f.strip() else "")
check("[E-453] ...and the message names the target",
      "cannot generate code for target" in out_f,
      out_f.strip().splitlines()[0][:60] if out_f.strip() else "")
check("[E-453] ...and says what this binary CAN build for",
      "has a code generator for" in out_f,
      out_f.strip().splitlines()[0][:60] if out_f.strip() else "")
check("[E-453] ...and did not leave a half-written output",
      not os.path.isfile(os.path.join(HERE, "_bk_x.osdi")))

# ------------------------------------------------------------------- controls
print("\nordinary compilation is untouched (controls)")
rc, out = run([va, "-o", "_bk_ok.osdi"])
check("[E-453] a plain build still compiles",
      rc == 0 and os.path.isfile(os.path.join(HERE, "_bk_ok.osdi")), f"rc={rc}")
check("[E-453] ...and the .osdi is a real module",
      os.path.isfile(os.path.join(HERE, "_bk_ok.osdi"))
      and os.path.getsize(os.path.join(HERE, "_bk_ok.osdi")) > 1000)

# The HOST target named explicitly must still work -- the check rejects targets
# LLVM cannot emit, not every use of --target.
rc_h, out_h = run([va, "--supported-targets"])
host_ok = None
for name in [ln.strip() for ln in out_h.splitlines() if ln.strip()]:
    if name.startswith(("aarch64", "x86_64", "riscv64")):
        rc_t, _ = run([va, "-o", "_bk_t.osdi", "--target", name])
        if rc_t == 0:
            host_ok = name
            break
check("[E-453] the host target still compiles when named explicitly",
      host_ok is not None,
      host_ok if host_ok else f"none of the supported targets built ({rc_h})")

d = cache_dir("_bk_same")
run([va, "--batch", "--cache-dir", d])
run([va, "--batch", "--cache-dir", d])
check("[E-453] two identical batch builds still share ONE entry",
      len(entries(d)) == 1, f"{len(entries(d))} entries")

for junk in os.listdir(HERE):
    if junk.startswith("_bk"):
        p = os.path.join(HERE, junk)
        if os.path.isdir(p):
            for f in os.listdir(p):
                os.remove(os.path.join(p, f))
            os.rmdir(p)
        else:
            os.remove(p)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
