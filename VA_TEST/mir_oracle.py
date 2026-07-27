#!/usr/bin/env python3
"""Output-preservation oracle for openvaf-r changes, over the whole .va corpus.

`--dump-mir` is the right thing to compare when asking "did my change alter what
the compiler produces?" -- `.osdi` bytes are not reproducible (parallel LLVM
codegen), MIR is.

TWO THINGS MAKE A NAIVE HASH LIE, and both cost real investigations before they
were understood. This tool exists so they are handled once, here, instead of
being re-derived in a throwaway script every time:

 1. THE COMPILER'S OWN TIMING LINE IS IN THE OUTPUT.
    `--dump-mir` ends with `Finished building <file> in 0.09s`, and that number
    jitters run to run. Hashing the raw dump therefore reports differences that
    have nothing to do with the change under test. This was misdiagnosed for a
    long time as "multi-module dump-order nondeterminism"; it is not, it is the
    clock. Every noise line is stripped below.

 2. A GENUINELY NONDETERMINISTIC MINORITY.
    Multi-module files that use IMPLICIT NETS get their internal node IDs from a
    hash container, so value numbering and a few bindings permute between runs.
    `examples/lrm_examples/va/lrm_p150_1.va` is the known example. This is a
    REPRODUCIBILITY defect, not a miscompile: 8 independent compilations produced
    two distinct MIRs but byte-identical ngspice output. `--stable` re-runs a
    file that differs to see whether ONE binary disagrees with itself, and
    reports those separately rather than as a change.

Usage
    mir_oracle.py capture <baseline.json> [--bin BIN]
    mir_oracle.py compare <baseline.json> [--bin BIN] [--stable]
    mir_oracle.py ab <old-bin> <new-bin> [--stable]

`ab` is usually what you want: build the old binary (or extract it from a
release tag with `git show <tag>:bin/macos/apple-silicon/openvaf-r`) and diff it
against the new one directly, with no baseline file to go stale.

Exit code is non-zero if any model's MIR changed.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_BIN = os.path.join(ROOT, "bin", "macos", "apple-silicon", "openvaf-r")

# Lines that carry no information about the generated code. The timing line is
# the one that matters; the others are progress chatter that may appear too.
NOISE = re.compile(r"^\s*(Finished building .* in .*s|Finished .*|Compiling .*)\s*$")


def clean(text):
    """Drop the noise lines so the hash reflects the MIR and nothing else."""
    return "\n".join(l for l in text.splitlines() if not NOISE.match(l))


def corpus():
    return sorted(set(
        glob.glob(os.path.join(ROOT, "examples", "**", "*.va"), recursive=True) +
        glob.glob(os.path.join(HERE, "**", "*.va"), recursive=True)))


def mir_hash(binary, path, tmpd, timeout=180):
    out = os.path.join(tmpd, "o.osdi")
    try:
        r = subprocess.run([binary, "--dump-mir", path, "-o", out],
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    if r.returncode not in (0, 65):
        return "RC%d" % r.returncode
    return hashlib.md5(clean(r.stdout + r.stderr).encode()).hexdigest()


def self_consistent(binary, path, tmpd, n=4):
    """True if this ONE binary agrees with itself across n runs."""
    return len({mir_hash(binary, path, tmpd) for _ in range(n)}) == 1


def sweep(old_bin, new_bin, baseline=None, stable=False):
    files = corpus()
    same = changed = nondet = 0
    changed_list, nondet_list = [], []
    with tempfile.TemporaryDirectory() as tmpd:
        for i, f in enumerate(files, 1):
            rel = os.path.relpath(f, ROOT)
            a = baseline.get(rel) if baseline is not None else mir_hash(old_bin, f, tmpd)
            b = mir_hash(new_bin, f, tmpd)
            if a is None:
                continue
            if a == b:
                same += 1
            elif stable and not (self_consistent(new_bin, f, tmpd)
                                 and (baseline is not None
                                      or self_consistent(old_bin, f, tmpd))):
                nondet += 1
                nondet_list.append(rel)
            else:
                changed += 1
                changed_list.append((rel, a, b))
            if i % 100 == 0:
                print("  [%d/%d] identical=%d changed=%d nondeterministic=%d"
                      % (i, len(files), same, changed, nondet), flush=True)
    print()
    print("TOTAL %d   IDENTICAL %d   CHANGED %d   NONDETERMINISTIC %d"
          % (len(files), same, changed, nondet))
    for rel in nondet_list:
        print("   nondeterministic (not a change): %s" % rel)
    for rel, a, b in changed_list:
        print("   CHANGED %s  %s -> %s" % (rel, str(a)[:8], str(b)[:8]))
    return 1 if changed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["capture", "compare", "ab"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--bin", default=os.environ.get("OPENVAF_BIN", DEFAULT_BIN))
    ap.add_argument("--stable", action="store_true",
                    help="re-run a differing file to separate genuine "
                         "nondeterminism from a real change")
    a = ap.parse_args()

    if a.mode == "capture":
        if len(a.args) != 1:
            ap.error("capture needs <baseline.json>")
        out = {}
        files = corpus()
        with tempfile.TemporaryDirectory() as tmpd:
            for i, f in enumerate(files, 1):
                out[os.path.relpath(f, ROOT)] = mir_hash(a.bin, f, tmpd)
                if i % 100 == 0:
                    print("  [%d/%d]" % (i, len(files)), flush=True)
        with open(a.args[0], "w") as fh:
            json.dump(out, fh, indent=1)
        print("captured %d models -> %s" % (len(out), a.args[0]))
        return 0

    if a.mode == "compare":
        if len(a.args) != 1:
            ap.error("compare needs <baseline.json>")
        with open(a.args[0]) as fh:
            baseline = json.load(fh)
        return sweep(None, a.bin, baseline=baseline, stable=a.stable)

    if len(a.args) != 2:
        ap.error("ab needs <old-bin> <new-bin>")
    return sweep(a.args[0], a.args[1], stable=a.stable)


sys.exit(main())
