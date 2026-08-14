#!/usr/bin/env python3
"""Enhancement-452: an unusable `-o` destroyed the source, or crashed.

Three ways a `-o` destination went wrong, none of them reported by the driver --
each reached the backend and failed there.

  * `-o` NAMING THE INPUT FILE. The compiled module was written straight over
    the source and the run reported SUCCESS:

        openvaf-r m.va -o m.va   ->  rc=0, "Finished building m.va in 0.08s"
        m.va: 111 bytes of Verilog-A  ->  36888 bytes of Mach-O

    The source is gone. Reachable from a shell loop whose output variable is
    accidentally the input one, or from tab-completion.

  * an EMPTY `-o`. `dst.file_stem()` in osdi::compile is an `.expect()`, so it
    panicked -- exit 101, a crash banner, a crash-log file and a request to open
    a GitHub issue, for a typo.

  * an UNWRITABLE directory. `emit_object` returns an error and the caller wraps
    it in `assert_eq!(.., Ok(()))`, so a permission problem panicked the same way.

The destination is now checked in the driver, before any parsing, at the last
point that still knows both the input and the requested output. An ordinary user
error costs one line and a non-zero exit; it does not cost the source file, and
it does not ask the user to file a bug.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF  # noqa: E402

checks = passed = 0
GOOD = ('`include "disciplines.vams"\n'
        'module optpath(a,b); inout a,b; electrical a,b;\n'
        '  parameter real g = 1e-3;\n'
        '  analog I(a,b) <+ V(a,b)*g;\n'
        'endmodule\n')


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(args, tag):
    """write a fresh source, run openvaf-r, report (rc, output, source-intact)"""
    src = os.path.join(HERE, f"_op_{tag}.va")
    with open(src, "w") as f:
        f.write(GOOD)
    real = [src if a == "SRC" else a for a in args]
    r = subprocess.run([OPENVAF] + real, capture_output=True, text=True,
                       timeout=120, cwd=HERE)
    with open(src, "rb") as f:
        intact = f.read(2) == b"`i"
    return r.returncode, (r.stdout + r.stderr), intact


print("Enhancement-452: an unusable -o destroyed the source, or crashed\n")

# --------------------------------------------------------- the three faults ---
print("the destination is refused, and the source survives")
rc, out, intact = run(["SRC", "-o", "SRC"], "same")
check("[E-452] `-o` naming the input is refused", rc != 0, f"rc={rc}")
check("[E-452] ...and the SOURCE FILE IS STILL THERE", intact,
      "the compiled module was written over it" if not intact else "")
check("[E-452] ...and the message says why",
      "is the input file" in out, out.strip().splitlines()[0][:60] if out.strip() else "")

rc, out, _ = run(["SRC", "-o", ""], "empty")
check("[E-452] an empty `-o` is refused", rc != 0, f"rc={rc}")
check("[E-452] ...and does NOT panic (exit 101 + crash report)", rc != 101, f"rc={rc}")
check("[E-452] ...and the message names the problem",
      "does not name a file" in out, out.strip().splitlines()[0][:60] if out.strip() else "")

rc, out, _ = run(["SRC", "-o", "/_e452_cannot_write.osdi"], "unwrit")
check("[E-452] an unwritable output directory is refused", rc != 0, f"rc={rc}")
check("[E-452] ...and does NOT panic", rc != 101, f"rc={rc}")
check("[E-452] ...and the message names the directory",
      "cannot write to the output directory" in out,
      out.strip().splitlines()[0][:60] if out.strip() else "")

rc, out, _ = run(["SRC", "-o", "_op_nodir/x.osdi"], "nodir")
check("[E-452] a non-existent output directory is refused", rc != 0, f"rc={rc}")
check("[E-452] ...and does NOT panic", rc != 101, f"rc={rc}")

# ------------------------------------------------- nothing else may change ---
print("\nordinary compilation is untouched (controls)")
rc, out, _ = run(["SRC", "-o", "_op_ok1.osdi"], "ok1")
check("[E-452] a plain `-o` still compiles",
      rc == 0 and os.path.isfile(os.path.join(HERE, "_op_ok1.osdi")), f"rc={rc}")

rc, out, _ = run(["SRC"], "ok2")
check("[E-452] no `-o` at all still compiles beside the source",
      rc == 0 and os.path.isfile(os.path.join(HERE, "_op_ok2.osdi")), f"rc={rc}")

os.makedirs(os.path.join(HERE, "_op_sub"), exist_ok=True)
rc, out, _ = run(["SRC", "-o", "_op_sub/_op_ok3.osdi"], "ok3")
check("[E-452] `-o` into an existing subdirectory still compiles",
      rc == 0 and os.path.isfile(os.path.join(HERE, "_op_sub", "_op_ok3.osdi")), f"rc={rc}")

# `-o` onto a DIFFERENT existing file is legitimate -- overwriting a previous
# build output is the normal way to rebuild, and only the INPUT is protected.
rc, out, _ = run(["SRC", "-o", "_op_ok1.osdi"], "over")
check("[E-452] overwriting a previous OUTPUT is still allowed", rc == 0, f"rc={rc}")

# and the compiled module still works
rc, out, _ = run(["SRC", "-o", "_op_final.osdi"], "final")
check("[E-452] the .osdi it produces is non-empty",
      rc == 0 and os.path.getsize(os.path.join(HERE, "_op_final.osdi")) > 1000,
      f"{os.path.getsize(os.path.join(HERE, '_op_final.osdi')) if os.path.isfile(os.path.join(HERE,'_op_final.osdi')) else 0} bytes")

for junk in os.listdir(HERE):
    if junk.startswith("_op_"):
        p = os.path.join(HERE, junk)
        if os.path.isdir(p):
            for f in os.listdir(p):
                os.remove(os.path.join(p, f))
            os.rmdir(p)
        else:
            os.remove(p)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
