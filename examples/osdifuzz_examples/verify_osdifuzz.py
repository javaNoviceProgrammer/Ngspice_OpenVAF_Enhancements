#!/usr/bin/env python3
"""verify_osdifuzz.py -- Enhancement-228: OSDI `.osdi` loader count hardening.

A `.osdi` model is an external, compiled shared library that ngspice `dlopen`s
and then reads OSDI *descriptor metadata* out of (`load_object_file` in
`osdi/osdiregistry.c`, reached by `pre_osdi`). The loader strided / indexed the
descriptor arrays by the counts the file declares -- `OSDI_NUM_DESCRIPTORS`, and
each descriptor's `num_params` / `num_opvars` / `num_terminals` / ... -- with no
bounds. A corrupted, truncated, or ABI-mismatched object file that still loads
but declares an out-of-range count made the loader read past the array -> SIGSEGV
during `pre_osdi`.

E-228 sanity-bounds those counts: a count above a generous ceiling (the signature
of a truncated file or an ABI-drifted compiler) is rejected with a clean
diagnostic instead of crashing. NOTE (honest scope): a count that lies within the
plausible range is an internally inconsistent binary indistinguishable from a
valid one and is out of scope -- this guard targets the egregious/huge-count
corruption, not every possible malformed .osdi.

This test builds two malformed `.osdi` files from tiny C stubs (portable, no
binary-mutation / re-signing games): one declaring an implausible descriptor
count (entry guard), one with a valid count but an implausible per-descriptor
field count built from the real `OsdiDescriptor` struct (per-descriptor guard).
Each must load-reject cleanly (was SIGSEGV). A positive control confirms a real
openvaf-r-built `.osdi` still loads and simulates.

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

REPO = os.path.dirname(os.path.dirname(HERE))
OSDI_INC = os.path.join(REPO, "ngspice-46", "src", "osdi")   # holds osdi.h
CC = os.environ.get("CC", "cc")

checks = passed = 0
D = tempfile.mkdtemp(prefix="osdifuzz228_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))


def run(control, timeout=30):
    p = os.path.join(D, "f.cir")
    with open(p, "w") as f:
        f.write("* osdifuzz\n.control\n" + control + "\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", p], capture_output=True, text=True,
                           timeout=timeout, cwd=D, errors="replace")
    except subprocess.TimeoutExpired:
        return None, "HANG"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def is_clean(rc, out):
    return rc is not None and not (rc < 0 or (rc >= 128 and rc != 142)) \
        and "segmentation" not in out.lower()


def build_stub(name, body):
    """Compile a C stub exporting OSDI symbols into name.osdi; return path or None."""
    c = os.path.join(D, name + ".c")
    o = os.path.join(D, name + ".osdi")
    with open(c, "w") as f:
        f.write(body)
    r = subprocess.run([CC, "-shared", "-fPIC", "-I", OSDI_INC, "-o", o, c],
                       capture_output=True, text=True)
    return o if (r.returncode == 0 and os.path.exists(o)) else None


print("Enhancement-228: implausible OSDI descriptor counts -> clean reject (no crash)")

if shutil.which(CC) is None:
    check("a C compiler (%s) is available to build the malformed stubs" % CC, False)
    print(f"\n{passed}/{checks} checks passed")
    raise SystemExit(1)

# --- positive control: a real openvaf-r .osdi still loads and simulates ---
va = os.path.join(D, "vares.va")
with open(va, "w") as f:
    f.write("`include \"disciplines.vams\"\n"
            "module vares(p,n);\n  inout p,n; electrical p,n;\n"
            "  parameter real r = 1k;\n  analog V(p,n) <+ r*I(p,n);\nendmodule\n")
osdi = os.path.join(D, "vares.osdi")
rc = subprocess.run([OPENVAF, va, "-o", osdi], capture_output=True, text=True, cwd=D).returncode
deck = ("N1 a 0 rmod\nV1 a 0 1\n.model rmod vares r=2k\n"
        ".control\npre_osdi %s\nop\nprint v(a)\n.endc" % osdi)
with open(os.path.join(D, "g.cir"), "w") as f:
    f.write("* osdi smoke\n" + deck + "\n.end\n")
r = subprocess.run([NGSPICE, "-b", os.path.join(D, "g.cir")],
                   capture_output=True, text=True, cwd=D, errors="replace")
out = (r.stdout or "") + (r.stderr or "")
m = re.search(r"v\(a\)\s*=\s*([-\d.eE+]+)", out)
val = float(m.group(1)) if m else None
check("positive control: a real openvaf-r .osdi loads and simulates (v(a)=1)",
      rc == 0 and is_clean(r.returncode, out) and val is not None and abs(val - 1.0) < 1e-6,
      out.strip()[-120:] if val is None else f"v(a)={val}")

# --- malformed #1: implausible OSDI_NUM_DESCRIPTORS -> entry guard ---
bad1 = build_stub("bad1", (
    "#include <stdint.h>\n"
    "uint32_t OSDI_VERSION_MAJOR = 0;\n"
    "uint32_t OSDI_VERSION_MINOR = 7;\n"
    "uint32_t OSDI_DESCRIPTOR_SIZE = 368;\n"
    "uint32_t OSDI_NUM_DESCRIPTORS = 100000;   /* implausible */\n"
    "char OSDI_DESCRIPTORS[368];               /* dummy; guard fires first */\n"))
if not bad1:
    check("built malformed stub #1 (huge OSDI_NUM_DESCRIPTORS)", False)
else:
    rc, out = run("pre_osdi %s" % bad1)
    check("malformed .osdi: huge OSDI_NUM_DESCRIPTORS -> clean reject (was SIGSEGV)",
          is_clean(rc, out) and "descriptors" in out.lower() and "exceeds" in out.lower(),
          f"rc={rc}")

# --- malformed #2: valid count, implausible per-descriptor field -> loop guard ---
bad2 = build_stub("bad2", (
    "#include <stdint.h>\n"
    "#include \"osdi.h\"\n"
    "uint32_t OSDI_VERSION_MAJOR = 0;\n"
    "uint32_t OSDI_VERSION_MINOR = 7;\n"
    "uint32_t OSDI_DESCRIPTOR_SIZE = sizeof(OsdiDescriptor);\n"
    "uint32_t OSDI_NUM_DESCRIPTORS = 1;\n"
    "OsdiDescriptor OSDI_DESCRIPTORS[1] = { { .num_params = 0xFFFFFFFFu } };\n"))
if not bad2:
    check("built malformed stub #2 (huge descriptor num_params)", False,
          "osdi.h at %s" % OSDI_INC)
else:
    rc, out = run("pre_osdi %s" % bad2)
    check("malformed .osdi: huge descriptor field count -> clean reject (was SIGSEGV)",
          is_clean(rc, out) and "implausible field count" in out.lower(), f"rc={rc}")

shutil.rmtree(D, ignore_errors=True)
print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
