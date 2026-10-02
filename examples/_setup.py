"""Locate the `openvaf-r` and `ngspice` binaries for the example scripts.

Python counterpart of the `*_examples/_setup.sh` shell helper: it resolves the
two toolchain binaries for the current machine using the committed, CI-built
`bin/<os>/<arch>/` matrix. As a convenience for local development it first
prefers a locally-built binary (`OpenVAF-master-20260610/target/opt/…`,
`ngspice-46/build/src/…`) if one exists, and otherwise falls back to `bin/`.

The compiler is taken from the **`opt`** profile, which is what ships (CI builds
`bin/` with it) -- deliberately NOT `target/release/`. The two profiles differ by
roughly 40-55% in model compile time, so verifying against a `release` build and
comparing with the shipped binary reports a large regression that is nothing but
the profile. Build it with
`cargo build --profile opt --features llvm18 --bin openvaf-r`.

Usage from an example script (which lives in `examples/<name>_examples/`):

    import os, sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds this file)
    from _setup import VAF as OPENVAF, NG as NGSPICE
    from _setup import check_both_solvers as _check_both_solvers
    _check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

Exposes module-level `VAF` (openvaf-r) and `NG` (ngspice) absolute paths, plus
`check_both_solvers()` — see the dual-solver harness section below.
"""
import os
import platform

# ---------------------------------------------------------------------------
# stdin hygiene
# ---------------------------------------------------------------------------
# Point fd 0 at /dev/null for this process and therefore for every child it
# spawns. Nothing in the example suite reads stdin, and leaving it connected is
# actively harmful: on a machine with DISPLAY set, an ngspice that reaches the
# interactive prompt busy-polls the X11 event queue through readline with NO
# sleep -- about 53% CPU each, indefinitely. `-b` does not prevent that. With
# stdin inherited the process never receives EOF, so it waits at the prompt,
# the parent moves on, and the child is orphaned to PPID 1 still spinning.
# Twelve such orphans were seen on 2026-08-08 at ~640% CPU, load average 10.5 --
# which also silently corrupts any wall-clock timing measured while they run.
#
# Done here, once, rather than as `stdin=DEVNULL` on each of the ~717
# subprocess call sites across ~389 files: fd 0 is inherited, so this covers
# them all including any added later, and it cannot drift out of sync. The
# handful of scripts that legitimately drive ngspice with `input=` are
# unaffected -- subprocess replaces fd 0 with its own pipe in that case.
try:
    _devnull_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(_devnull_fd, 0)
    os.close(_devnull_fd)
except OSError:
    pass    # a platform without a usable /dev/null is not worth failing over

# This file lives in `examples/`; the repo root (which holds
# `OpenVAF-master-20260610/`, `ngspice-46/`, and `bin/`) is one level up.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXE = ".exe" if platform.system() == "Windows" else ""


def _bin_subdir():
    """`<os>/<arch>` under bin/ for the current machine (matches _setup.sh)."""
    system = platform.system()
    machine = platform.machine().lower()
    is_arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return os.path.join("macos", "apple-silicon" if is_arm else "intel")
    if system == "Linux":
        return os.path.join("linux", "arm" if is_arm else "intel")
    if system == "Windows":
        return os.path.join("windows", "intel")
    raise RuntimeError(f"Unsupported platform: {system} / {machine}")


def _resolve(local_parts, name, env):
    """The `env` override, else a local build if present, else bin/<os>/<arch>/.

    The override exists to point the whole suite at an ALTERNATIVE build without
    touching the tree -- an ASan/UBSan ngspice, a bisect build, a wrapper script:

        NGSPICE_BIN=/path/to/asan/ngspice python3 run_regression.py

    The obvious alternative -- copying the other binary over
    `ngspice-46/build/src/ngspice` and copying it back afterwards -- is a trap on
    macOS: `cp` over a signed executable invalidates its code signature and the
    kernel then SIGKILLs it (the run dies with exit 137 and no output, and stays
    broken until you `codesign -f -s -` it). It also leaves the tree in the wrong
    state if the run is interrupted. Use the env var.
    """
    override = os.environ.get(env)
    if override:
        return override
    local = os.path.join(_ROOT, *local_parts) + _EXE
    if os.path.isfile(local):
        return local
    return os.path.join(_ROOT, "bin", _bin_subdir(), name + _EXE)


VAF = _resolve(("OpenVAF-master-20260610", "target", "opt", "openvaf-r"),
               "openvaf-r", "OPENVAF_BIN")
NG = _resolve(("ngspice-46", "build", "src", "ngspice"), "ngspice", "NGSPICE_BIN")

# Enhancement-574: ngspice's own compiles -- `pre_osdi -va`, `pre_snp` -- find
# the compiler through osdi_find_openvaf(): the `openvaf` variable, $OPENVAF,
# $SPICE_LIB_DIR/openvaf-r, then a bare `openvaf-r` on PATH. A `set openvaf=`
# in a deck's control block runs AFTER the pre_ commands it would have to
# precede, so a suite that pinned the compiler that way was in fact using
# whatever PATH held -- and on a machine with no openvaf-r on PATH it failed
# outright. Hand every child the compiler this harness resolved, so ngspice
# compiles with the same binary the scripts do. A suite that tests the lookup
# itself (reusecache_examples) removes it per call.
os.environ["OPENVAF"] = VAF


# Enhancement-777: NG_TRACE_DIR=<dir> records every ngspice and openvaf-r run a
# suite makes through subprocess.run -- the command, its directory, the deck it
# was given, the exit status and the tail of its output -- in <dir>/<suite>.log.
# A suite's own report says which check failed; this says what the simulator
# printed, which on a CI machine nobody can otherwise see. With NG_TRACE_LLDB=1
# on macOS a run killed by a signal is run again under lldb for a backtrace.
# run_regression.py sets it when it re-runs the failed suites (NG_TRACE_FAILED).
def _install_trace(trace_dir):
    import subprocess as _sp
    import sys as _sys
    import time as _time
    real_run = _sp.run
    tools = {"ngspice", "openvaf-r", os.path.basename(NG).split(".")[0],
             os.path.basename(VAF).split(".")[0]}
    suite = os.path.basename(os.path.dirname(os.path.abspath(_sys.argv[0] or "x")))
    log_path = os.path.join(trace_dir, suite + ".log")
    count = [0]

    def text(v):
        if v is None:
            return ""
        return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)

    def record(args, kw, res, exc, dt):
        argv = [str(a) for a in args] if isinstance(args, (list, tuple)) else [str(args)]
        if not argv or os.path.basename(argv[0]).split(".")[0] not in tools:
            return
        count[0] += 1
        cwd = kw.get("cwd") or os.getcwd()
        lines = [f"=== run {count[0]}  {dt:.1f}s  rc={getattr(res, 'returncode', exc)}  cwd={cwd}",
                 "args: " + " ".join(argv)]
        for a in argv[1:]:
            p = a if os.path.isabs(a) else os.path.join(cwd, a)
            if a.endswith((".cir", ".sp", ".net")) and os.path.isfile(p):
                try:
                    lines.append(f"--- deck {a}:\n" + open(p, errors="replace").read()[:3000])
                except OSError:
                    pass
        if kw.get("input") is not None:
            lines.append("--- stdin:\n" + text(kw.get("input"))[:3000])
        if res is not None:
            lines.append("--- stdout (tail):\n" + text(res.stdout)[-3000:])
            lines.append("--- stderr (tail):\n" + text(res.stderr)[-2000:])
            rc = res.returncode
            # a Windows crash is an NTSTATUS exit code (0xC0000005 an access
            # violation): run it again under cdb, which GitHub's Windows
            # images ship with the Windows SDK, for the faulting stack
            cdb = None
            if os.name == "nt" and rc is not None and rc >= 0xC0000000:
                import shutil as _sh
                for c in (_sh.which("cdb"),
                          r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe"):
                    if c and os.path.isfile(c):
                        cdb = c
                        break
            if cdb:
                try:
                    dbg = real_run([cdb, "-g", "-G", "-lines", "-c", ".ecxr; kv 30; lm; q"] + argv,
                                   cwd=cwd, input=kw.get("input"), capture_output=True,
                                   text=isinstance(kw.get("input"), str) or kw.get("input") is None,
                                   timeout=300)
                    lines.append("--- cdb:\n" + text(dbg.stdout)[-6000:])
                except Exception as e:      # noqa: BLE001
                    lines.append(f"--- cdb failed: {e}")
            elif os.name == "nt" and rc is not None and rc >= 0xC0000000:
                lines.append(f"--- crash 0x{rc:08X}; no cdb found for a stack")
            if (rc is not None and rc < 0 and _sys.platform == "darwin"
                    and os.environ.get("NG_TRACE_LLDB")):
                try:
                    bt = real_run(["lldb", "--batch", "-o", "run", "-o", "bt 30", "-o", "quit", "--"] + argv,
                                  cwd=cwd, input=kw.get("input"), capture_output=True,
                                  text=isinstance(kw.get("input"), str) or kw.get("input") is None,
                                  timeout=300)
                    lines.append("--- lldb:\n" + text(bt.stdout)[-4000:])
                except Exception as e:      # noqa: BLE001 -- a trace must not fail a suite
                    lines.append(f"--- lldb failed: {e}")
        os.makedirs(trace_dir, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", errors="replace") as fh:
            fh.write("\n".join(lines) + "\n\n")

    def traced(args, *a, **kw):
        t0 = _time.time()
        res = exc = None
        try:
            res = real_run(args, *a, **kw)
            return res
        except BaseException as e:
            exc = type(e).__name__
            raise
        finally:
            try:
                record(args, kw, res, exc, _time.time() - t0)
            except Exception:              # noqa: BLE001
                pass

    _sp.run = traced


if os.environ.get("NG_TRACE_DIR"):
    _install_trace(os.environ["NG_TRACE_DIR"])


# ---------------------------------------------------------------------------
# XSPICE code models (SPICE_LIB_DIR)
# ---------------------------------------------------------------------------
# The prebuilt bin/<os>/<arch>/ bundle ships ngspice's XSPICE code models
# (analog.cm, digital.cm, ...) under codemodels/, plus a portable spinit under
# scripts/ that loads them relative to $SPICE_LIB_DIR. Pointing SPICE_LIB_DIR at
# that bundle makes `codemodel`-based A-devices work out of the box. Guarded on
# the spinit's presence, so it is a no-op until the CI-built bundle is committed;
# a user's own SPICE_LIB_DIR always wins (setdefault). The spinit gates its
# loads on `if $?xspice_enabled`, and a successful load is silent, so this does
# not affect non-XSPICE decks. See docs/handbook/03-ngspice-workflows.md.
SPICE_LIB = os.path.join(_ROOT, "bin", _bin_subdir())

# Enhancement-440: when ngspice itself comes from the LOCAL build, its code
# models must come from that build too.
#
# `_resolve` above prefers `ngspice-46/build/src/ngspice` when it exists, but
# this block used to point SPICE_LIB_DIR unconditionally at the committed
# `bin/<os>/<arch>` bundle -- so a locally built simulator was verified against
# whatever code models CI had built weeks earlier. An edit under
# `src/xspice/icm/` was therefore NOT exercised by the suite that is supposed to
# be authoritative for it, and the binary and its models could disagree.
#
# The failure mode is not hypothetical and is worse than a stale test: with no
# SPICE_LIB_DIR set at all, ngspice falls back to its compiled-in prefix and
# silently loads a THIRD party's models -- on this machine an unrelated ngspice
# installed under /usr/local in Feb 2025. Four "crashes" found by hand against
# that install did not exist in this tree at all; they were fixed here long ago.
# Whatever runs, its code models must come from the same build as its binary.
_LOCAL_ICM = os.path.join(_ROOT, "ngspice-46", "build", "src", "xspice", "icm")
_LOCAL_CMS = ("analog", "digital", "spice2poly", "table", "tlines",
              "xtradev", "xtraevt")


def _local_codemodel_lib():
    """A SPICE_LIB_DIR whose spinit loads the LOCAL build's .cm files.

    Returns None unless ngspice was resolved to the local build and every code
    model is present there, so a partial or absent build falls back to `bin/`.
    """
    if os.path.abspath(NG) != os.path.abspath(
            os.path.join(_ROOT, "ngspice-46", "build", "src", "ngspice") + _EXE):
        return None
    paths = [os.path.join(_LOCAL_ICM, cm, cm + ".cm") for cm in _LOCAL_CMS]
    if not all(os.path.isfile(p) for p in paths):
        return None

    libdir = os.path.join(_ROOT, "ngspice-46", "build", "_spicelib")
    scripts = os.path.join(libdir, "scripts")
    spinit = os.path.join(scripts, "spinit")
    body = ("* Generated by examples/_setup.py (Enhancement-440).\n"
            "* Loads the code models built alongside ngspice-46/build/src/ngspice.\n"
            "if $?xspice_enabled\n"
            + "".join("codemodel %s\n" % p for p in paths)
            + "end\n")
    try:
        os.makedirs(scripts, exist_ok=True)
        # rewrite only when it would change, so a read-only or shared tree is
        # not churned on every import
        if not os.path.isfile(spinit) or open(spinit).read() != body:
            with open(spinit, "w") as f:
                f.write(body)
    except OSError:
        return None
    return libdir


# Enhancement-574: every verify script reads the compiler's diagnostics as
# TEXT, so no child of the harness may colour them. openvaf-r chose its colours
# with termcolor's ColorChoice::Auto, which consults TERM and NO_COLOR and never
# asks whether the stream is a terminal: from a colour terminal every
# diagnostic written into a pipe carried escape codes, and five suites that
# parse them (lrmdisc, lrmfuncs, natureref, vafdeterminism, vafice) failed in
# a sweep run from an ordinary shell while a harness with TERM unset passed.
# The compiler now checks the stream; a prebuilt or older binary may not, so
# the harness settles it here for every subprocess a verify script spawns, on
# every platform: a dumb terminal and NO_COLOR, the two switches termcolor
# honours on any version. A suite that wants colour for its own test
# (vafcolor_examples) sets both per call.
os.environ["TERM"] = "dumb"
os.environ["NO_COLOR"] = "1"

_LOCAL_LIB = _local_codemodel_lib()
if _LOCAL_LIB:
    os.environ.setdefault("SPICE_LIB_DIR", _LOCAL_LIB)
elif os.path.isfile(os.path.join(SPICE_LIB, "scripts", "spinit")):
    os.environ.setdefault("SPICE_LIB_DIR", SPICE_LIB)


# ---------------------------------------------------------------------------
# Dual-solver test harness (KLU + Sparse 1.3)
# ---------------------------------------------------------------------------
# Every example is verified under BOTH ngspice linear solvers so a regression in
# either is caught. This build's default solver is Sparse 1.3; KLU is opt-in via
# `.option klu`. See docs/internals/ngspice_internals/ngspice_solver_notes.md.
#
# How it works: a verify script calls `check_both_solvers(__file__)` right after
# importing this module. On a normal (top-level) run that call re-executes the
# same script once per solver, injecting `.option <solver>` into every ngspice
# deck, and reports a combined verdict. Every analysis now runs under KLU
# (noise/pz E-113, sens E-114, disto E-115, complex-root pz E-171, balanced pz
# E-172); if ngspice ever reports an analysis as KLU-unsupported it is detected
# from its own error text and reported as SKIP rather than a failure. The
# handful of examples with a genuine known KLU limitation are listed in
# `KLU_XFAIL`.
#
# Escape hatches (env):
#   NGSPICE_SOLVER=klu|sparse   run ONCE under that solver (no dual re-exec)
#   NG_BOTH=0                   disable the dual harness (single default run)

import subprocess as _subprocess

SOLVERS = ("sparse", "klu")                 # order: default first
_SOLVER_CARD = {"sparse": ".option sparse", "klu": ".option klu"}
# ngspice's own diagnostic when an analysis is unavailable under KLU:
_KLU_UNSUPPORTED = "not (yet) supported with 'option KLU'"
# examples with a genuine, documented KLU limitation (not a mere skip) — each is
# a real KLU discrepancy that Sparse 1.3 (the default) handles correctly. See
# docs/internals/ngspice_internals/ngspice_solver_notes.md.
#
# There are currently none — the set is empty.
#
# (groundcontrib and hierbranch were XFAIL until Enhancement-116 fixed the root
#  cause: an OSDI internal node that appears in no Jacobian entry -- e.g. an
#  explicit `ground gnd` reference -- was given its own all-zero solver row,
#  which made the KLU matrix structurally singular. Such nodes are now tied to
#  ground at setup, so both pass under KLU. See osdisetup.c.
#  opamp741 was XFAIL because its transient used the default TRAPEZOIDAL method,
#  which rings on the stiff transistor-level feedback slew and collapses the
#  timestep under KLU -- an integration-method issue, not a KLU linear-solve
#  issue. Its transient decks (run_opamp741.py) now use Gear (`.option
#  method=gear`), which is dissipative, stable under KLU, and matches Sparse to
#  ~8 sig figs, so it passes under BOTH solvers.)
KLU_XFAIL = frozenset()

# Examples whose KLU pass is prohibitively SLOW (not wrong — just slow) and so is
# skipped by default; set NG_SLOW_KLU=1 to force the KLU pass on.
# (rfanalyses and rfpss were here until Enhancement-176: the driven-mode PSS
# made their shooting runs ~1000x faster, so both now run under BOTH solvers in
# the regular sweep. The remaining entries are heavy Monte-Carlo batteries, not
# PSS decks.)
SPARSE_ONLY = frozenset({"highsigma", "yield", "cmcsweep"})

# Examples excluded from the routine full-regression sweep (run_regression.py).
# They still work and can be run directly (or with `run_regression.py --all` /
# NG_RUN_ALL=1).
# (rfanalyses and rfpss were excluded here until Enhancement-176: the driven-mode
# PSS cut their runtimes from minutes to fractions of a second, so the whole RF
# periodic small-signal suite E-117..126 is now guarded on every sweep.)
#
#   cmcsweep     -- too slow to be worth running every time.
#   filterforms  -- Enhancement-405. NOT excluded for speed: it runs in about two
#                   seconds. It is held out of the routine sweep deliberately, so
#                   the reason is recorded here rather than left to be inferred
#                   from this set's original "too slow" rationale.
REGRESSION_EXCLUDE = frozenset({"cmcsweep", "filterforms"})

# Enhancement-774: examples held out of the routine sweep on ONE platform, each
# for a recorded reason -- a known, open problem there, not a pass. The CI sweep
# runs on five platforms; an entry here keeps a platform's known gap from hiding
# a new failure in the same red job, and the sweep names every one it skips.
# They still run directly, or with `run_regression.py --all` / NG_RUN_ALL=1.
# Keys are (system, machine) as platform.system() reports them, the machine
# normalised to aarch64 / x86_64; "*" matches any system.
PLATFORM_EXCLUDE = {
    ("Windows", "*"): {
        "helpcmd": "drives an interactive ngspice through a POSIX pseudo-terminal "
                   "(pty, termios), which Windows has no counterpart of",
        "syntaxhl": "tests terminal syntax colouring through a POSIX pseudo-terminal",
        "vafcolor": "tests the compiler's terminal colours through a POSIX pseudo-terminal",
    },
    ("*", "x86_64"): {
        "arrayscale": "x86-64 code generation of huge modules: a 10 000-entry "
                      "instance array takes ~550 s (E-771, open)",
        "cubic_table": "x86-64 code generation of huge modules: the 10 000-row "
                       "table compile passes 120 s on the Linux runner (open)",
        "table_model": "x86-64 code generation of huge modules: past the sweep's "
                       "20-minute limit on the Linux runner (open)",
        "collapsestate": "Sparse sens of a parameter that selects a node collapse "
                         "is 2.5x off on x86-64, Linux and macOS alike (open)",
    },
}


def _pe_exports(path):
    """The names in a PE (Windows DLL) export table, read from the file."""
    import struct
    with open(path, "rb") as fh:
        data = fh.read()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        return []
    coff = pe + 4
    nsec, = struct.unpack_from("<H", data, coff + 2)
    optsz, = struct.unpack_from("<H", data, coff + 16)
    opt = coff + 20
    magic, = struct.unpack_from("<H", data, opt)
    exp_rva, _ = struct.unpack_from("<II", data, opt + (96 if magic == 0x10B else 112))
    secs = opt + optsz

    def off(rva):
        for i in range(nsec):
            vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, secs + 40 * i + 8)
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + rva - vaddr
        return None

    e = off(exp_rva) if exp_rva else None
    if e is None:
        return []
    nnames, = struct.unpack_from("<I", data, e + 24)
    names = off(struct.unpack_from("<I", data, e + 32)[0])
    out = []
    for k in range(nnames):
        o = off(struct.unpack_from("<I", data, names + 4 * k)[0])
        out.append(data[o:data.index(b"\0", o)].decode(errors="replace"))
    return out


def exported_symbols(path):
    """Enhancement-775: the symbols a compiled model exports, as text a check can
    search -- `nm` on POSIX, the DLL's export table on Windows, which has no nm
    (the osdidist, osdimc and paramgiven checks read "no such file" there)."""
    import subprocess as _sp
    if os.name == "nt":
        try:
            return "\n".join(_pe_exports(path))
        except Exception:          # not a readable PE file: no exports
            return ""
    return _sp.run(["nm", path], capture_output=True, text=True).stdout


def platform_key():
    """(system, machine) of this host, the machine normalised (arm64 -> aarch64,
    AMD64 -> x86_64) so that one entry covers Linux, macOS and Windows names."""
    import platform as _platform
    machine = _platform.machine().lower()
    machine = {"arm64": "aarch64", "amd64": "x86_64", "x64": "x86_64"}.get(machine, machine)
    return _platform.system(), machine


def platform_excluded():
    """{example stem: reason} held out of the sweep on this host."""
    system, machine = platform_key()
    out = {}
    for (sys_key, mach_key), stems in PLATFORM_EXCLUDE.items():
        if sys_key in ("*", system) and mach_key in ("*", machine):
            out.update(stems)
    return out


def klu_enabled(script=None):
    """Whether an example's KLU pass should run. SPARSE_ONLY examples (heavy PSS)
    skip KLU by default for speed; NG_SLOW_KLU=1 forces it on. Used both by
    check_both_solvers and by scripts that drive the two solvers themselves."""
    import sys as _sys
    if os.environ.get("NG_SLOW_KLU") == "1":
        return True
    return _example_stem(script or _sys.argv[0]) not in SPARSE_ONLY


def _example_stem(script):
    """`opamp741` from `.../opamp741_examples/verify_opamp741.py`."""
    d = os.path.basename(os.path.dirname(os.path.abspath(script)))
    return d[:-len("_examples")] if d.endswith("_examples") else d


def _looks_like_ngspice(args):
    if not isinstance(args, (list, tuple)) or not args:
        return False
    a0 = str(args[0])
    return os.path.basename(a0).startswith("ngspice") or a0.endswith("ngspice")


def _deck_from_args(args):
    """The deck path in an ngspice arg list (arg after -b, else a .cir/.sp)."""
    argl = [str(x) for x in args]
    for i, a in enumerate(argl):
        if a == "-b" and i + 1 < len(argl):
            return argl[i + 1]
    for a in reversed(argl):
        if a.lower().endswith((".cir", ".sp", ".net", ".spice", ".ckt")):
            return a
    return None


# Decks we edited in place, mapped to their original contents. We restore them
# when this (single-solver) process exits -- ngspice has long since read the deck
# by then -- so a both-solver run never leaves `.option` cards committed in the
# real example decks. Without this, each sweep permanently pollutes the decks.
_INJECTED_ORIGINALS = {}
_RESTORE_REGISTERED = False


def _restore_injected_decks():
    for deck, txt in _INJECTED_ORIGINALS.items():
        try:
            with open(deck, "w") as f:
                f.write(txt)
        except OSError:
            pass


def _inject_card(deck, cwd, card):
    """Insert `card` as the second line (after the SPICE title) of `deck`,
    remembering the original so it is restored when this process exits."""
    global _RESTORE_REGISTERED
    if not deck:
        return
    if not os.path.isabs(deck):
        deck = os.path.join(cwd or os.getcwd(), deck)
    if not os.path.isfile(deck):
        return
    try:
        with open(deck) as f:
            txt = f.read()
    except OSError:
        return
    if card.lower() in txt.lower():
        return  # already pinned (idempotent)
    if deck not in _INJECTED_ORIGINALS:
        _INJECTED_ORIGINALS[deck] = txt
        if not _RESTORE_REGISTERED:
            import atexit
            atexit.register(_restore_injected_decks)
            _RESTORE_REGISTERED = True
    lines = txt.split("\n")
    lines.insert(1 if lines else 0, card)
    try:
        with open(deck, "w") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


# KLU now runs noise + single-ended pole-zero (E-113), DC/AC sensitivity (E-114),
# distortion (E-115), complex-root pole-zero (E-171), and balanced/differential-
# output pole-zero (E-172: SMPcAddCol gained a KLU branch with the union pattern
# reserved at setup). No analysis card remains Sparse-only under KLU.
def _deck_requests_klu_unsupported(deck, cwd):
    _ = (deck, cwd)
    return False


def _install_solver_injector(solver):
    """Patch subprocess so every ngspice call pins `solver` via `.option`.
    Hooks `Popen.__init__`, through which run/check_output/call/Popen all pass.

    (_deck_requests_klu_unsupported is a stub kept for the emit hook below: as
    of E-172 every analysis card runs under KLU, so it always returns False.  If
    a future KLU gap appears, detect it there and the harness will report SKIP
    even when the verify script captures ngspice's error output.)"""
    card = _SOLVER_CARD.get(solver)
    if not card:
        return
    _orig_popen_init = _subprocess.Popen.__init__

    def _patched_init(self, args, *a, **k):
        if _looks_like_ngspice(args):
            deck = _deck_from_args(args)
            _inject_card(deck, k.get("cwd"), card)
            if solver == "klu" and _deck_requests_klu_unsupported(deck, k.get("cwd")):
                import sys as _sys
                _sys.stderr.write(_KLU_UNSUPPORTED + "\n")
                _sys.stderr.flush()
        return _orig_popen_init(self, args, *a, **k)

    _subprocess.Popen.__init__ = _patched_init


# If we are already running under a chosen solver (a re-exec child, or a user
# NGSPICE_SOLVER override), install the deck injector now, at import time.
_ACTIVE_SOLVER = os.environ.get("_NG_SOLVER") or os.environ.get("NGSPICE_SOLVER")
if _ACTIVE_SOLVER in SOLVERS:
    _install_solver_injector(_ACTIVE_SOLVER)


def _indent(text, pad="    "):
    return "\n".join(pad + ln for ln in text.split("\n"))


def check_both_solvers(script=None):
    """Run the calling verify script under every solver in `SOLVERS`.

    On a top-level run this re-executes the script once per solver and exits
    with a combined verdict; in a re-exec child (or under NGSPICE_SOLVER) it
    returns immediately so the script proceeds normally under that one solver.
    """
    import sys
    # child of the harness, explicit single-solver run, or harness disabled:
    if (os.environ.get("_NG_SOLVER")
            or os.environ.get("NGSPICE_SOLVER")
            or os.environ.get("NG_BOTH") == "0"):
        return

    script = os.path.abspath(script or sys.argv[0])
    stem = _example_stem(script)
    # heavy-PSS examples skip the (slow) KLU pass unless NG_SLOW_KLU=1
    solvers = [s for s in SOLVERS if s != "klu" or klu_enabled(script)]
    if len(solvers) == 1:
        print(f"=== [{stem}] verifying under {solvers[0]} only "
              f"(KLU skipped: heavy PSS is slow to re-factor; NG_SLOW_KLU=1 to force) ===",
              flush=True)
    else:
        print(f"=== [{stem}] verifying under BOTH solvers ({', '.join(solvers)}) ===",
              flush=True)

    results = {}
    for solver in solvers:
        env = dict(os.environ)
        env["_NG_SOLVER"] = solver
        try:
            r = _subprocess.run([sys.executable, script] + sys.argv[1:],
                                env=env, capture_output=True, text=True,
                                stdin=_subprocess.DEVNULL, timeout=1800)
            out, rc = r.stdout + r.stderr, r.returncode
        except _subprocess.TimeoutExpired as e:
            out, rc = (e.stdout or "") + "\n[TIMEOUT]", 124

        if solver == "klu" and _KLU_UNSUPPORTED in out:
            status = "SKIP"      # noise / pole-zero: unsupported under KLU
        elif solver == "klu" and rc != 0 and stem in KLU_XFAIL:
            status = "XFAIL"     # known, documented KLU limitation
        else:
            status = "PASS" if rc == 0 else "FAIL"
        results[solver] = status

        print(f"\n----- [solver={solver}] {status} -----", flush=True)
        if status == "SKIP":
            print("    ngspice reported \"" + _KLU_UNSUPPORTED + "\";")
            print("    this example is Sparse-only for that analysis; KLU skipped.")
        elif status == "XFAIL":
            print("    Known KLU limitation (stiff transient diverges under KLU); "
                  "expected. See docs/internals/ngspice_internals/"
                  "ngspice_solver_notes.md")
            print(_indent(out.strip()[-1000:]))
        else:
            print(_indent(out.strip()))

    if "klu" not in results:
        results["klu"] = "SKIP"   # heavy-PSS example: KLU pass intentionally skipped
    ok = (results.get("sparse") == "PASS"
          and results.get("klu") in ("PASS", "SKIP", "XFAIL"))
    summary = "  ".join(f"{s}={results[s]}" for s in SOLVERS)
    print(f"\n=== BOTH-SOLVER RESULT [{stem}]: {summary} "
          f"=> {'OK' if ok else 'FAILURE'} ===", flush=True)
    sys.exit(0 if ok else 1)
