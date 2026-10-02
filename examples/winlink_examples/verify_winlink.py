#!/usr/bin/env python3
"""
verify_winlink.py -- Enhancement-769: a compiled model links on Windows.

A module is linked from five objects -- the descriptor module and the access,
setup_model, setup_instance and eval units -- and each carries the whole OSDI
stdlib. E-516 made the stdlib's mutable state (nineteen variables) weak and the
two I/O hooks the simulator looks up (osdi_io_iter_begin, osdi_io_flush)
weak_odr, so the five copies merge into one. On COFF, LLVM emitted each of
those weak definitions as a weak external whose default was named after the
first symbol of its object -- five different defaults for one symbol -- and
MSVC's link.exe refused every model with LNK1227 ("conflicting weak extern
definition for 'osdi_io_iter_begin'"); lld-link reports a duplicate symbol.
Each weak definition is now in a COMDAT of its own name with "any" selection,
and the linker keeps one copy.

On a non-Windows host the suite cross-compiles a one-resistor module for
<host arch>-pc-windows through a stand-in `link.exe` (a shell script on PATH
that keeps the objects), and reads the objects' COFF symbol tables itself, so
no LLVM tool is needed. On Windows the real link.exe does the link and the
native compile below is the test.

  [1] the cross-compile hands the stand-in linker five COFF objects (.o and
      .o1-.o4) for the right machine;
  [2] no object defines a weak external (each had 21);
  [3] every symbol defined in more than one object is, in each of them, an
      external in a COMDAT section with "any" selection -- the two I/O hooks
      among them;
  [4] where lld-link is available (Homebrew's llvm@18 ships it), the five
      objects link into a DLL whose only unresolved symbols are the C runtime's
      (msvcrt.lib supplies those on Windows), exporting both hooks and
      OSDI_DESCRIPTORS -- the same objects from the E-768 compiler stop at a
      duplicate symbol;
  [5] the module compiled for the host loads in ngspice and gives the right
      current (on Windows: linked by link.exe, the LNK1227 case).

It is a compiler property, checked once (no linear solver is involved).
"""
import os
import platform
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import NG as NGSPICE, VAF as OPENVAF

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


WINDOWS_HOST = platform.system() == "Windows"
ARM = platform.machine().lower() in ("arm64", "aarch64")
TARGET = "aarch64-pc-windows" if ARM else "x86_64-pc-windows"
MACHINE = 0xAA64 if ARM else 0x8664            # IMAGE_FILE_MACHINE_ARM64 / AMD64
HOOKS = ("osdi_io_iter_begin", "osdi_io_flush")
WORK = os.path.join(HERE, "_wl_work")


def coff_symbols(path):
    """{name: (storage class, section number, section is COMDAT, selection)} of
    the COFF object at `path`, read from its header, section table and symbol
    table (PE/COFF specification, sections 3, 4 and 5)."""
    data = open(path, "rb").read()
    machine, nsec, _, symptr, nsym, optsz, _ = struct.unpack_from("<HHIIIHH", data, 0)
    comdat = []
    for i in range(nsec):
        chars = struct.unpack_from("<I", data, 20 + optsz + 40 * i + 36)[0]
        comdat.append(bool(chars & 0x1000))                 # IMAGE_SCN_LNK_COMDAT
    strtab = symptr + 18 * nsym
    selection = {}
    syms = {}
    i = 0
    while i < nsym:
        off = symptr + 18 * i
        raw = data[off:off + 8]
        value, secnum, _, cls, naux = struct.unpack_from("<IhHBB", data, off + 8)
        if raw[:4] == b"\0\0\0\0":
            o = struct.unpack_from("<I", raw, 4)[0]
            name = data[strtab + o:data.index(b"\0", strtab + o)].decode()
        else:
            name = raw.rstrip(b"\0").decode()
        # a section symbol's first auxiliary record holds the COMDAT selection
        if cls == 3 and naux >= 1 and secnum > 0 and comdat[secnum - 1] and secnum not in selection:
            selection[secnum] = data[off + 18 + 14]
        if cls in (2, 105) and name:                          # EXTERNAL, WEAK_EXTERNAL
            in_comdat = secnum > 0 and comdat[secnum - 1]
            syms[name] = (cls, secnum, in_comdat, selection.get(secnum) if in_comdat else None)
        i += 1 + naux
    return machine, syms


def find_lld_link():
    for name in ("lld-link", "lld-link-18"):
        p = shutil.which(name)
        if p:
            return p
    for d in ("/opt/homebrew/opt/llvm@18/bin", "/usr/local/opt/llvm@18/bin", "/usr/lib/llvm-18/bin"):
        p = os.path.join(d, "lld-link")
        if os.path.isfile(p):
            return p
    return None


print("Enhancement-769: a compiled model links on Windows")
shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)

objs = []
if WINDOWS_HOST:
    for _ in range(4):
        check("[1-4] (Windows host: the real link.exe links the module -- see [5])", True)
else:
    # ---- [1] cross-compile through a stand-in link.exe -------------------------
    bindir = os.path.join(WORK, "bin")
    keep = os.path.join(WORK, "keep")
    os.makedirs(bindir)
    os.makedirs(keep)
    stand_in = os.path.join(bindir, "link.exe")
    with open(stand_in, "w") as f:
        f.write('#!/bin/sh\n'
                '# stand-in for MSVC link.exe: keep the objects, create the output, succeed\n'
                'for a in "$@"; do\n'
                '  case "$a" in\n'
                '    /OUT:*) out="${a#/OUT:}";;\n'
                '    *.o|*.o[0-9a-z]) [ -f "$a" ] && cp "$a" "$WL_KEEP/";;\n'
                '  esac\n'
                'done\n'
                '[ -n "$out" ] && : > "$out"\n'
                'exit 0\n')
    os.chmod(stand_in, 0o755)
    shutil.copy(os.path.join(HERE, "winres.va"), WORK)
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""), WL_KEEP=keep)
    r = subprocess.run([OPENVAF, "winres.va", "--target", TARGET, "-o", "winres_win.osdi"],
                       cwd=WORK, env=env, capture_output=True, text=True, timeout=300)
    objs = [os.path.join(keep, n) for n in ("winres_win.o", "winres_win.o1", "winres_win.o2",
                                           "winres_win.o3", "winres_win.o4")]
    have = [p for p in objs if os.path.isfile(p)]
    tables = {}
    for p in have:
        try:
            tables[p] = coff_symbols(p)
        except (struct.error, ValueError, IndexError, UnicodeDecodeError):
            pass
    check(f"[1] openvaf-r --target {TARGET} hands the linker five COFF objects for machine 0x{MACHINE:04x}",
          r.returncode == 0 and len(tables) == 5 and all(t[0] == MACHINE for t in tables.values()),
          f"rc={r.returncode}, {len(have)} objects kept, {len(tables)} readable; {(r.stderr or r.stdout).strip()[-200:]}")

    # ---- [2] no weak externals ---------------------------------------------------
    weak = {os.path.basename(p): sorted(n for n, s in t[1].items() if s[0] == 105) for p, t in tables.items()}
    nweak = sum(len(v) for v in weak.values())
    check("[2] no object defines a weak external (each defined 21 of them, with a different default per object)",
          len(tables) == 5 and nweak == 0,
          "; ".join(f"{k}: {len(v)} ({', '.join(v[:3])}...)" for k, v in weak.items() if v))

    # ---- [3] every symbol defined in several objects is an any-COMDAT -----------
    defined = {}
    for p, t in tables.items():
        for n, (cls, sec, in_comdat, sel) in t[1].items():
            if cls == 2 and sec > 0:
                defined.setdefault(n, []).append((os.path.basename(p), in_comdat, sel))
    shared = {n: v for n, v in defined.items() if len(v) > 1}
    bad = sorted(n for n, v in shared.items() if not all(c and s == 2 for _, c, s in v))
    check("[3] every symbol defined in more than one object is, in each, an external in a COMDAT section with "
          "'any' selection -- the two I/O hooks among them",
          len(tables) == 5 and shared and not bad and all(h in shared and len(shared[h]) == 5 for h in HOOKS),
          f"{len(shared)} shared symbols; not any-COMDAT: {bad[:5]}; hooks: "
          + ", ".join(f"{h}: {len(shared.get(h, []))} objects" for h in HOOKS))

    # ---- [4] lld-link links them -------------------------------------------------
    lld = find_lld_link()
    if lld is None:
        check("[4] (lld-link not found: the link of the five objects is not attempted here)", True)
    else:
        dll = os.path.join(WORK, "winres_win.dll")
        lr = subprocess.run([lld, "/NOLOGO", "/DLL", "/NOENTRY", "/force:unresolved", f"/OUT:{dll}"]
                            + [p for p in objs[1:] + objs[:1] if os.path.isfile(p)],
                            capture_output=True, text=True, timeout=120)
        msgs = lr.stdout + lr.stderr
        dups = [ln for ln in msgs.splitlines() if "duplicate symbol" in ln]
        undef = sorted({ln.split("undefined symbol:")[1].strip() for ln in msgs.splitlines()
                        if "undefined symbol:" in ln})
        # _fltused: the x64 CRT's marker that floating point is used (an
        # x86_64-pc-windows object references it; an arm64 one does not)
        crt = {"_fltused", "__acrt_iob_func", "fclose", "fputs", "free", "fseek", "ftell", "fopen", "fgets", "fprintf",
               "malloc", "realloc", "calloc", "memcpy", "memset", "strlen", "strcmp", "strcpy", "printf",
               "snprintf", "vsnprintf", "fflush", "fwrite", "fread", "getenv", "exit", "abort", "puts",
               "fgetc", "ungetc", "strtod", "strtol", "strncmp", "strncpy", "memmove", "memcmp", "putchar",
               "sprintf", "sscanf", "fscanf", "freopen", "rewind", "feof", "ferror", "clearerr", "_getcwd",
               "getcwd", "time", "clock", "rand", "srand", "qsort", "atoi", "atof", "tolower", "toupper",
               "isspace", "isdigit", "isalpha", "strchr", "strrchr", "strstr", "strdup", "_strdup", "_fileno",
               "_stat64i32", "_stat64", "__stdio_common_vsprintf", "__stdio_common_vfprintf",
               "__stdio_common_vsscanf", "__stdio_common_vfscanf", "fsetpos", "fgetpos", "_fseeki64",
               "_ftelli64", "_errno"}
        exports = set()
        if os.path.isfile(dll) and os.path.getsize(dll) > 0:
            with open(dll, "rb") as f:
                body = f.read()
            for name in HOOKS + ("OSDI_DESCRIPTORS",):
                if name.encode() + b"\0" in body:
                    exports.add(name)
        check("[4] lld-link links the five objects into a DLL: no duplicate symbol, only C runtime functions "
              "unresolved (msvcrt.lib supplies them on Windows), both hooks and OSDI_DESCRIPTORS named in it",
              lr.returncode == 0 and not dups and set(undef) <= crt and len(exports) == 3,
              f"rc={lr.returncode}; {dups[:2]}; non-CRT unresolved: {sorted(set(undef) - crt)[:5]}; named: {sorted(exports)}")

# ---- [5] the host-native module loads in ngspice ----------------------------------
r = subprocess.run([OPENVAF, os.path.join(HERE, "winres.va"), "-o", os.path.join(WORK, "winres.osdi")],
                   cwd=WORK, capture_output=True, text=True, timeout=300)
deck = os.path.join(WORK, "winres.cir")
with open(deck, "w") as f:
    f.write("winlink load\nV1 a 0 dc 1\nN1 a 0 wr\n.model wr winres r=1k\n"
            ".control\npre_osdi winres.osdi\nop\nprint i(v1)\n.endc\n.end\n")
n = subprocess.run([NGSPICE, "-b", "winres.cir"], cwd=WORK, capture_output=True, text=True, timeout=120)
cur = None
for ln in (n.stdout + n.stderr).splitlines():
    if ln.strip().lower().startswith("i(v1)") and "=" in ln:
        try:
            cur = float(ln.split("=")[1].split()[0])
        except (ValueError, IndexError):
            pass
check("[5] the module compiled for the host loads in ngspice: i(v1) = -1 mA across 1 kOhm"
      + (" (linked by MSVC's link.exe: the LNK1227 case)" if WINDOWS_HOST else ""),
      r.returncode == 0 and cur is not None and abs(cur + 1e-3) < 1e-9,
      f"compile rc={r.returncode} {(r.stderr or '').strip()[-200:]}; i(v1)={cur}")

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
