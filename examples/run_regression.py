#!/usr/bin/env python3
"""run_regression.py -- run the full example verification sweep.

Discovers every `examples/*_examples/verify_*.py`, runs each from its own
directory (so relative includes / `pre_osdi` resolve), and reports a combined
verdict. Each verify script drives BOTH linear solvers itself via
`check_both_solvers` (or its own loop), so this runner does not pick a solver;
it just collects the per-script results.

Two registries in `_setup.py` shape the sweep:
  * SPARSE_ONLY       — heavy periodic-steady-state examples whose KLU pass is
                        merely slow (KLU re-factors every PSS step); they run
                        Sparse-only here and report `klu=SKIP`. `NG_SLOW_KLU=1`
                        forces the KLU pass back on.
  * REGRESSION_EXCLUDE — examples held out of the routine sweep. Usually because
                        they are too slow to be worth it every time, but not
                        always: see the per-entry reasons in `_setup.py`. They
                        are skipped here but remain runnable
                        directly. `--all` (or NG_RUN_ALL=1) includes them.

Usage:
    python3 run_regression.py            # the sweep (honours REGRESSION_EXCLUDE)
    python3 run_regression.py --all      # include the excluded slow examples
    python3 run_regression.py foo bar    # only the named example stems
Exit code is non-zero if any run is not OK.
"""
import glob
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _setup import REGRESSION_EXCLUDE

RESULT_RE = re.compile(
    r"BOTH-SOLVER RESULT \[([^\]]+)\]:\s*sparse=(\S+)\s+klu=(\S+)\s*=>\s*(\S+)")


def stem_of(path):
    d = os.path.basename(os.path.dirname(path))
    return d[:-len("_examples")] if d.endswith("_examples") else d


def preflight():
    """Fail fast if this interpreter cannot run the suites.

    Several suites need numpy/matplotlib. Run under an interpreter without them
    -- most easily by putting /usr/bin ahead of the real python3 on PATH -- and
    they do not report that: they exit rc=1 in 0.0s, and the sweep ends with a
    couple of dozen unrelated-looking FAILUREs (every pyplot suite, plus a few
    that import numpy directly). That has cost a full 13-minute run more than
    once. One clear line beats twenty misleading ones.
    """
    missing = []
    for mod in ("numpy", "matplotlib"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print(f"run_regression: this python3 ({sys.executable}) cannot import "
              f"{', '.join(missing)}.\n"
              f"                Several suites need them and would fail with "
              f"rc=1 in 0.0s, which looks like a regression and is not.\n"
              f"                Check PATH -- putting /usr/bin first selects a "
              f"python3 without them.", file=sys.stderr)
        return False
    return True


def main(argv):
    if not preflight():
        return 2
    include_all = "--all" in argv or os.environ.get("NG_RUN_ALL") == "1"
    only = {a for a in argv if not a.startswith("-")}

    scripts = sorted(glob.glob(os.path.join(HERE, "*_examples", "verify_*.py")))
    excluded = []
    todo = []
    for s in scripts:
        stem = stem_of(s)
        if only and stem not in only:
            continue
        if not only and not include_all and stem in REGRESSION_EXCLUDE:
            excluded.append(stem)
            continue
        todo.append(s)

    if excluded:
        print(f"Excluding (not in the routine sweep; use --all to include): "
              f"{', '.join(sorted(set(excluded)))}\n")

    results = []
    t0 = time.time()
    for i, s in enumerate(todo, 1):
        stem = stem_of(s)
        d = os.path.dirname(s)
        ts = time.time()
        try:
            # stdin=DEVNULL so no test can inherit a live stdin and leave an
            # ngspice spinning at the interactive prompt (see _setup.py).
            r = subprocess.run([sys.executable, os.path.basename(s)], cwd=d,
                               capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=1200)
            out, rc = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or "") if isinstance(e.stdout, str) else ""
            rc = 124
        dt = time.time() - ts
        m = RESULT_RE.search(out)
        if m:
            status, detail = m.group(4), f"sparse={m.group(2)} klu={m.group(3)}"
        elif rc == 124:
            status, detail = "TIMEOUT", "(>1200s)"
        else:
            ok = "ALL PASS" in out or (rc == 0 and "FAIL" not in out)
            status = "OK" if (rc == 0 and ok) else "FAILURE"
            detail = f"rc={rc}"
        results.append((stem, status, detail))
        print(f"[{i:3}/{len(todo)}] {status:8} {stem:28} {detail:26} {dt:6.1f}s",
              flush=True)

    bad = [r for r in results if r[1] != "OK"]
    print("\n" + "=" * 70)
    print(f"TOTAL {len(results)}  OK {len(results)-len(bad)}  NOT-OK {len(bad)}"
          f"   ({time.time()-t0:.0f}s)")
    if bad:
        print("\nNOT OK:")
        for stem, status, detail in bad:
            print(f"  {status:8} {stem:28} {detail}")
    else:
        print("ALL OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
