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
    python3 run_regression.py --jobs 8   # eight suites at a time (NG_JOBS=8 works too)
Exit code is non-zero if any run is not OK.

`--jobs N` (Enhancement-576) runs N suites at once. Every suite works in its own
directory and cleans its own scratch files, and none writes outside it, so
they do not collide; the per-suite lines then come in COMPLETION order, each
numbered by how many have finished. The few suites that assert a speed ratio
(`SERIAL` below) are held back and run one at a time after the parallel batch,
because a loaded machine would move the ratio they measure. The default stays
sequential: a sweep on a shared or noisy machine is easier to read that way.
"""
import concurrent.futures
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

# Enhancement-576: suites whose verdict is a SPEED ratio measured on the machine
# -- benchmark (OSDI against built-in), nested_cond (compile time against
# nesting depth), reusesetup ([26], the setup reuse against a rebuild). Run
# alongside seven other suites the ratio is noise; they run alone, last.
SERIAL = {"benchmark", "nested_cond", "reusesetup"}


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


def parse_jobs(argv):
    """`--jobs N`, `--jobs=N`, `-j N`, `-jN`, else NG_JOBS, else 1. Returns
    (jobs, argv without those tokens)."""
    jobs = os.environ.get("NG_JOBS", "1")
    rest = []
    k = 0
    while k < len(argv):
        a = argv[k]
        if a in ("--jobs", "-j") and k + 1 < len(argv):
            jobs = argv[k + 1]
            k += 2
            continue
        if a.startswith("--jobs="):
            jobs = a[len("--jobs="):]
        elif a.startswith("-j") and len(a) > 2 and a[2:].isdigit():
            jobs = a[2:]
        else:
            rest.append(a)
        k += 1
    try:
        n = int(jobs)
    except ValueError:
        print(f"run_regression: --jobs wants a number, not {jobs!r}", file=sys.stderr)
        return None, rest
    return max(1, n), rest


def run_one(script):
    """Run one verify script from its own directory; (stem, status, detail, seconds)."""
    stem = stem_of(script)
    d = os.path.dirname(script)
    ts = time.time()
    try:
        # stdin=DEVNULL so no test can inherit a live stdin and leave an
        # ngspice spinning at the interactive prompt (see _setup.py).
        # Enhancement-574: a dumb terminal and NO_COLOR for every suite, so
        # no compiler or simulator colours the output a script parses
        # (_setup.py sets the same for its own children; this covers a
        # script that does not import it).
        r = subprocess.run([sys.executable, os.path.basename(script)], cwd=d,
                           capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=1200,
                           env=dict(os.environ, TERM="dumb", NO_COLOR="1"))
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
    return stem, status, detail, dt


def main(argv):
    if not preflight():
        return 2
    jobs, argv = parse_jobs(argv)
    if jobs is None:
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
    n = len(todo)

    def report(i, r):
        stem, status, detail, dt = r
        print(f"[{i:3}/{n}] {status:8} {stem:28} {detail:26} {dt:6.1f}s", flush=True)

    if jobs <= 1:
        for i, s in enumerate(todo, 1):
            r = run_one(s)
            results.append(r)
            report(i, r)
    else:
        parallel = [s for s in todo if stem_of(s) not in SERIAL]
        serial = [s for s in todo if stem_of(s) in SERIAL]
        print(f"run_regression: {jobs} suites at a time; "
              f"{len(serial)} timing-sensitive suite{'s' if len(serial) != 1 else ''} "
              f"run alone at the end ({', '.join(stem_of(s) for s in serial)})\n", flush=True)
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            for r in pool.map(run_one, parallel):   # completion is reported in submission order
                done += 1
                results.append(r)
                report(done, r)
        for s in serial:
            r = run_one(s)
            done += 1
            results.append(r)
            report(done, r)
    results = [r[:3] for r in results]

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
