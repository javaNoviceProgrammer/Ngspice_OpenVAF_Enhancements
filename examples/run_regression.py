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

On Linux (Enhancement-773) a suite whose process group holds more than
NG_SUITE_MEM_MB (4096) of memory is stopped and reported as MEMORY, with its
processes, the deck each ngspice was running and a sample of its output in
_failures/<suite>.log -- a runaway suite must not take the machine with it.

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
import shutil
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _setup import REGRESSION_EXCLUDE, platform_excluded, platform_key

RESULT_RE = re.compile(
    r"BOTH-SOLVER RESULT \[([^\]]+)\]:\s*sparse=(\S+)\s+klu=(\S+)\s*=>\s*(\S+)")

# Enhancement-576: suites whose verdict is a SPEED ratio measured on the machine
# -- benchmark (OSDI against built-in), nested_cond (compile time against
# nesting depth), reusesetup ([26], the setup reuse against a rebuild). Run
# alongside seven other suites the ratio is noise; they run alone, last.
SERIAL = {"benchmark", "nested_cond", "reusesetup",
          # Enhancement-772: a scaling ratio (abstolperf) and output-path
          # timings (progressbar) the first Linux CI run pushed over their
          # bounds while sharing the runner's cores
          "abstolperf", "progressbar",
          # Enhancement-773: plotname's per-point flatness ratio (1.74 against
          # 1.6 beside two other suites on the 3-core macOS runner)
          "plotname"}


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


# Enhancement-773: a suite whose process group (the script and every ngspice or
# openvaf-r it runs) holds more than this much memory is stopped and reported as
# MEMORY, with what its processes were running. On the linux-arm CI runner three
# suites' scripts grew by ~70 MB/s each -- a child writing output without end
# into a captured pipe -- until the 16 GB machine ran out and the runner shut
# down, taking the whole sweep and its log with it. Linux only (it reads /proc).
MEM_CAP_MB = int(os.environ.get("NG_SUITE_MEM_MB", "4096"))
HAVE_PROC = sys.platform.startswith("linux") and os.path.isdir("/proc/self")


def _group_procs(pgid):
    """[(pid, rss_kb, cmdline, cwd)] for the processes of process group PGID."""
    procs = []
    for d in glob.glob("/proc/[0-9]*"):
        try:
            st = open(d + "/stat").read()
            if int(st[st.rindex(")") + 2:].split()[2]) != pgid:   # state ppid pgrp
                continue
            rss = 0
            for line in open(d + "/status"):
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                    break
            cmd = open(d + "/cmdline", "rb").read().replace(b"\0", b" ")
            try:
                cwd = os.readlink(d + "/cwd")
            except OSError:
                cwd = "?"
            procs.append((int(d[6:]), rss, cmd.decode(errors="replace").strip(), cwd))
        except (OSError, ValueError, IndexError):
            continue
    return procs


def _memory_report(stem, procs):
    """What a runaway suite's processes were doing: their command lines, the
    deck each ngspice was running (copied to _failures/<suite>.deck-<pid>), and
    up to 16 kB of what each was writing, read from its own output pipe."""
    fdir = os.path.join(HERE, "_failures")
    os.makedirs(fdir, exist_ok=True)
    lines = [f"MEMORY: the process group passed {MEM_CAP_MB} MB and was stopped"]
    for pid, rss, cmd, cwd in sorted(procs, key=lambda p: -p[1]):
        lines.append(f"  pid {pid}  {rss // 1024} MB  cwd {cwd}\n    {cmd}")
        words = cmd.split()
        if words and os.path.basename(words[0]).startswith("ngspice"):
            deck = os.path.join(cwd, words[-1]) if words[-1] and not words[-1].startswith("-") else ""
            if deck and os.path.isfile(deck):
                try:
                    shutil.copy(deck, os.path.join(fdir, f"{stem}.deck-{pid}"))
                    lines.append(f"    deck copied to _failures/{stem}.deck-{pid}")
                except OSError:
                    pass
            try:
                fd = os.open(f"/proc/{pid}/fd/1", os.O_RDONLY | os.O_NONBLOCK)
                try:
                    sample = os.read(fd, 16384).decode(errors="replace")
                finally:
                    os.close(fd)
                lines.append("    its output (a sample from the pipe):\n" + sample[-4000:])
            except OSError as e:
                lines.append(f"    (its output could not be sampled: {e})")
    return "\n".join(lines) + "\n\n"


def run_one(script):
    """Run one verify script from its own directory; (stem, status, detail, seconds)."""
    stem = stem_of(script)
    d = os.path.dirname(script)
    ts = time.time()
    # stdin=DEVNULL so no test can inherit a live stdin and leave an
    # ngspice spinning at the interactive prompt (see _setup.py).
    # Enhancement-574: a dumb terminal and NO_COLOR for every suite, so
    # no compiler or simulator colours the output a script parses
    # (_setup.py sets the same for its own children; this covers a
    # script that does not import it).
    # Enhancement-773: its own session (POSIX), so the group can be measured
    # and stopped as a whole; output and errors in one stream.
    posix = os.name == "posix"
    p = subprocess.Popen([sys.executable, os.path.basename(script)], cwd=d,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=posix,
                         env=dict(os.environ, TERM="dumb", NO_COLOR="1"))
    chunks = []
    reader = threading.Thread(
        target=lambda: chunks.extend(iter(lambda: p.stdout.read(65536), b"")), daemon=True)
    reader.start()

    def stop():
        try:
            os.killpg(p.pid, signal.SIGKILL) if posix else p.kill()
        except OSError:
            pass

    note = ""
    rc = None
    watch = HAVE_PROC
    while rc is None:
        try:
            rc = p.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            if time.time() - ts > 1200:
                stop()
                p.wait()
                rc = 124
            elif watch:
                try:
                    procs = _group_procs(p.pid)
                    if sum(r for _, r, _, _ in procs) // 1024 > MEM_CAP_MB:
                        try:
                            note = _memory_report(stem, procs)
                        except Exception as e:      # the report must not lose the kill
                            note = f"MEMORY: the process group passed {MEM_CAP_MB} MB ({e})\n\n"
                        stop()
                        p.wait()
                        rc = 137
                except Exception:
                    watch = False                   # a watchdog fault never stops the sweep
    reader.join(timeout=10)
    out = note + b"".join(chunks).decode("utf-8", errors="replace")
    dt = time.time() - ts
    m = RESULT_RE.search(out)
    if note:
        status, detail = "MEMORY", f"(>{MEM_CAP_MB} MB)"
    elif m:
        status, detail = m.group(4), f"sparse={m.group(2)} klu={m.group(3)}"
    elif rc == 124:
        status, detail = "TIMEOUT", "(>1200s)"
    else:
        ok = "ALL PASS" in out or (rc == 0 and "FAIL" not in out)
        status = "OK" if (rc == 0 and ok) else "FAILURE"
        detail = f"rc={rc}"
    if status != "OK":
        # Enhancement-579: keep a failing suite's output. A parallel sweep prints
        # one line per suite and nothing else, so a failure that does not repeat
        # standalone (this fold's compiler race showed up as two or three
        # different suites failing on one solver per sweep) left nothing to read.
        try:
            fdir = os.path.join(HERE, "_failures")
            os.makedirs(fdir, exist_ok=True)
            with open(os.path.join(fdir, f"{stem}.log"), "w") as fh:
                fh.write(out)
        except OSError:
            pass
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
    on_platform = platform_excluded()      # Enhancement-774
    skipped_here = []
    todo = []
    for s in scripts:
        stem = stem_of(s)
        if only and stem not in only:
            continue
        if not only and not include_all and stem in REGRESSION_EXCLUDE:
            excluded.append(stem)
            continue
        if not only and not include_all and stem in on_platform:
            skipped_here.append(stem)
            continue
        todo.append(s)

    if excluded:
        print(f"Excluding (not in the routine sweep; use --all to include): "
              f"{', '.join(sorted(set(excluded)))}\n")
    if skipped_here:
        system, machine = platform_key()
        print(f"Excluding on this platform ({system} {machine}; a known open problem "
              f"there, see PLATFORM_EXCLUDE in _setup.py; --all includes them):")
        for stem in sorted(skipped_here):
            print(f"  {stem:20} {on_platform[stem]}")
        print()

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
        print(f"\n  (each failing suite's full output is in {os.path.join(HERE, '_failures')}/<suite>.log)")
    else:
        print("ALL OK")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
