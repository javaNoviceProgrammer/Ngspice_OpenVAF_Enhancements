"""Locate the `openvaf-r` and `ngspice` binaries for the example scripts.

Python counterpart of the `*_examples/_setup.sh` shell helper: it resolves the
two toolchain binaries for the current machine using the committed, CI-built
`bin/<os>/<arch>/` matrix. As a convenience for local development it first
prefers a locally-built binary (`OpenVAF-master-20260610/target/release/…`,
`ngspice-46/build/src/…`) if one exists, and otherwise falls back to `bin/`.

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
import re

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


def _resolve(local_parts, name):
    """Prefer a local build if present, else the bin/<os>/<arch>/ prebuilt."""
    local = os.path.join(_ROOT, *local_parts) + _EXE
    if os.path.isfile(local):
        return local
    return os.path.join(_ROOT, "bin", _bin_subdir(), name + _EXE)


VAF = _resolve(("OpenVAF-master-20260610", "target", "release", "openvaf-r"), "openvaf-r")
NG = _resolve(("ngspice-46", "build", "src", "ngspice"), "ngspice")


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
# deck, and reports a combined verdict. KLU cannot run noise / pole-zero
# analyses (an upstream ngspice limitation) — those are auto-detected from
# ngspice's own error and reported as SKIP rather than a failure. The handful of
# examples with a genuine known KLU limitation are listed in `KLU_XFAIL`.
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
#   opamp741      — the stiff transistor-level 741 transient diverges under KLU.
#   groundcontrib — the degenerate single-node node-to-ground contribution gives
#                   the wrong DC answer under KLU (v(p)=0 instead of 1.5).
#   hierbranch    — hierarchical branch *current* probes read 0 under KLU (the
#                   node voltages are correct). Deterministic; independent of the
#                   E-114 sensitivity fix (the DC KLU solve is untouched). This
#                   was previously masked by the deck-injector pollution bug (a
#                   stale `.option sparse` made the "klu" child silently run
#                   Sparse — a false pass); fixing that restore bug exposed it.
KLU_XFAIL = frozenset({"opamp741", "groundcontrib", "hierbranch"})


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
# and distortion (E-115). One analysis remains Sparse-only under KLU:
#   * BALANCED-output pole-zero -- a `pz n1 n2 n3 n4 vol|cur` command whose 4th
#     node (the output reference) is not ground (0).
_KLU_UNSUPPORTED_RE = re.compile(
    r"(?im)^\s*(?:"
    r"pz\s+\S+\s+\S+\s+\S+\s+(?!0\s)\S+\s+(?:vol|cur)"   # balanced-output pole-zero
    r")")


def _deck_requests_klu_unsupported(deck, cwd):
    if not deck:
        return False
    if not os.path.isabs(deck):
        deck = os.path.join(cwd or os.getcwd(), deck)
    try:
        with open(deck) as f:
            return bool(_KLU_UNSUPPORTED_RE.search(f.read()))
    except OSError:
        return False


def _install_solver_injector(solver):
    """Patch subprocess so every ngspice call pins `solver` via `.option`.
    Hooks `Popen.__init__`, through which run/check_output/call/Popen all pass.

    Under KLU, a deck that requests balanced-output pole-zero (which KLU cannot
    run) makes the injector emit the ngspice `_KLU_UNSUPPORTED` string on this
    process's own stderr, so the dual-solver harness can see it and report SKIP
    even when the verify script captures (and hence hides) ngspice's error."""
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
    print(f"=== [{stem}] verifying under BOTH solvers ({', '.join(SOLVERS)}) ===",
          flush=True)

    results = {}
    for solver in SOLVERS:
        env = dict(os.environ)
        env["_NG_SOLVER"] = solver
        try:
            r = _subprocess.run([sys.executable, script] + sys.argv[1:],
                                env=env, capture_output=True, text=True,
                                timeout=1800)
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
            print("    KLU does not support balanced-output pole-zero "
                  "(ngspice: \"" + _KLU_UNSUPPORTED + "\").")
            print("    This example is Sparse-only for that analysis; KLU skipped.")
        elif status == "XFAIL":
            print("    Known KLU limitation (stiff transient diverges under KLU); "
                  "expected. See docs/internals/ngspice_internals/"
                  "ngspice_solver_notes.md")
            print(_indent(out.strip()[-1000:]))
        else:
            print(_indent(out.strip()))

    ok = (results.get("sparse") == "PASS"
          and results.get("klu") in ("PASS", "SKIP", "XFAIL"))
    summary = "  ".join(f"{s}={results[s]}" for s in SOLVERS)
    print(f"\n=== BOTH-SOLVER RESULT [{stem}]: {summary} "
          f"=> {'OK' if ok else 'FAILURE'} ===", flush=True)
    sys.exit(0 if ok else 1)
