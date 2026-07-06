"""Shared pieces of the Enhancement-74 performance benchmark: toolchain
resolution, deck generators for the OSDI-vs-built-in twin circuits, and the
timing harness. Used by run_benchmark.py (the full benchmark) and
verify_benchmark.py (the fast deterministic checks)."""
import os
import platform
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the examples/ dir, for _setup.py
from _setup import VAF as OPENVAF, NG as NGSPICE

# the VA-Models corpus (for the compile-time benchmark); absent => skip
CORPUS = os.path.join(HERE, "..", "..", "VA_TEST", "VA-Models-main", "code")

# flagship compact models for the compile-time benchmark (exact case for
# case-sensitive filesystems)
COMPILE_MODELS = [
    ("BSIM4 (4.8)",     "bsim4/vacode/bsim4.va"),
    ("BSIM6 (6.1.1)",   "bsim6/vacode/BSIM6.1.1.va"),
    ("BSIM-BULK",       "bsimbulk/vacode/bsimbulk.va"),
    ("BSIM-CMG",        "bsimcmg/vacode/bsimcmg.va"),
    ("BSIM-SOI",        "bsimsoi/vacode/bsimsoi.va"),
    ("PSP 103",         "psp103/vacode/psp103.va"),
    ("PSP 102",         "psp102/vacode/psp102.va"),
    ("HiCUM L2 (3.0)",  "hicum2/vacode/hicumL2V3p0p0.va"),
    ("MEXTRAM 505",     "mextram/vacode/bjt505.va"),
    ("EKV 3",           "ekv3/vacode/ekv3.va"),
    ("ASM-HEMT",        "ASMHEMT/vacode/asmhemt.va"),
    ("diode_cmc",       "diode_cmc/vacode/diode_cmc.va"),
]


def machine_info():
    info = f"{platform.system()} {platform.release()}, {platform.machine()}"
    try:
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if cpu:
            info = f"{cpu} — {info}"
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def count_loc(src, seen=None):
    """Lines of the file plus everything it `include`s (many corpus tops
    are thin wrappers around .include bodies)."""
    import re
    if seen is None:
        seen = set()
    src = os.path.abspath(src)
    if src in seen or not os.path.isfile(src):
        return 0
    seen.add(src)
    total = 0
    inc = re.compile(r'`include\s+"([^"]+)"')
    for line in open(src, errors="replace"):
        total += 1
        m = inc.search(line)
        if m and not m.group(1).endswith(".vams"):
            total += count_loc(os.path.join(os.path.dirname(src), m.group(1)), seen)
    return total


def compile_va(src, out, timeout=600):
    """Compile one .va, return wall seconds (raises on failure).

    Paths are passed relative to the example dir: openvaf-r embeds the
    source path it is given (and the compile cwd) into the .osdi, and the
    committed artifacts must stay free of absolute paths."""
    src = os.path.relpath(src, HERE)
    out = os.path.relpath(out, HERE)
    t0 = time.monotonic()
    p = subprocess.run([OPENVAF, src, "-o", out], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout)
    dt = time.monotonic() - t0
    if p.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"compile failed for {src}:\n{p.stderr or p.stdout}")
    return dt


def run_ngspice(deck_name, timeout=600):
    """Run one deck in batch mode, return wall seconds."""
    t0 = time.monotonic()
    p = subprocess.run([NGSPICE, "-b", deck_name], cwd=HERE,
                       capture_output=True, text=True, timeout=timeout)
    dt = time.monotonic() - t0
    if p.returncode != 0:
        raise RuntimeError(f"ngspice failed on {deck_name}:\n{p.stderr[-2000:]}")
    return dt


def median_time(deck_name, runs=3):
    return statistics.median(run_ngspice(deck_name) for _ in range(runs))


def write_deck(name, text):
    with open(os.path.join(HERE, name), "w") as fh:
        fh.write(text)


def rc_ladder_deck(kind, n, tstep, tstop, out_txt):
    """RC ladder: n series-R/shunt-C segments, pulse-driven."""
    lines = [f"* rc ladder {kind} N={n}",
             "v1 n0 0 dc 0 pulse(0 1 0 1n 1n 5u 10u)"]
    for i in range(1, n + 1):
        if kind == "osdi":
            lines.append(f"nx{i} n{i-1} n{i} segmod")
        else:
            lines.append(f"r{i} n{i-1} n{i} 1k")
            lines.append(f"c{i} n{i} 0 1n")
    if kind == "osdi":
        lines.append(".model segmod rcseg(r=1k c=1n)")
    lines += [".control"]
    if kind == "osdi":
        lines.append("pre_osdi rcseg.osdi")
    # save only the probe node: batch tran otherwise stores every node
    # vector (N x points doubles), which pollutes the timing and can trip
    # ngspice's plot-memory guard on large ladders
    lines += [f"save v(n{n})",
              f"tran {tstep} {tstop}",
              f"wrdata {out_txt} v(n{n})", "quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"


DIODE_CARD = "is=1e-14 n=1.2 cjo=2p vj=0.8 m=0.4 tt=5n"
VADIODE_CARD = DIODE_CARD.replace("is=", "is_=")


def rectifier_deck(kind, n, tstep, tstop, out_txt):
    """n independent half-wave rectifier cells (diode + RC load), one source."""
    lines = [f"* rectifier bank {kind} N={n}",
             "vin in 0 dc 0 sin(0 2 100k)"]
    for i in range(1, n + 1):
        if kind == "osdi":
            lines.append(f"nd{i} in o{i} dva")
        else:
            lines.append(f"d{i} in o{i} dbi")
        lines.append(f"r{i} o{i} 0 1k")
        lines.append(f"c{i} o{i} 0 10n")
    if kind == "osdi":
        lines.append(f".model dva vadiode({VADIODE_CARD})")
    else:
        lines.append(f".model dbi d({DIODE_CARD})")
    lines += [".control"]
    if kind == "osdi":
        lines.append("pre_osdi vadiode.osdi")
    lines += ["save v(o1)",
              f"tran {tstep} {tstop}",
              f"wrdata {out_txt} v(o1)", "quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def bsim4_deck(kind, tstep, tstop, out_txt, osdi_file="bsim4va.osdi"):
    """One BSIM4 common-source stage, sine on the gate."""
    lines = [f"* bsim4 stage {kind}",
             "vdd vdd 0 dc 1.2",
             "rload vdd d 1k",
             "vg g 0 dc 0.6 sin(0.6 0.5 1meg)"]
    if kind == "osdi":
        lines += ["n1 d g 0 0 mos_va", ".model mos_va bsim4va()"]
    else:
        lines += ["m1 d g 0 0 mos_bi", ".model mos_bi nmos(level=14 version=4.8)"]
    lines += [".control"]
    if kind == "osdi":
        lines.append(f"pre_osdi {osdi_file}")
    lines += ["save v(d)",
              f"tran {tstep} {tstop}",
              f"wrdata {out_txt} v(d)", "quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def load_wave(txt_name):
    """Read a wrdata file -> (t, v) column lists."""
    t, v = [], []
    with open(os.path.join(HERE, txt_name)) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2:
                t.append(float(parts[0]))
                v.append(float(parts[1]))
    return t, v


def max_wave_diff(txt_a, txt_b, samples=2000):
    """Max |a-b| after interpolating both onto a common time grid."""
    ta, va = load_wave(txt_a)
    tb, vb = load_wave(txt_b)
    t0, t1 = max(ta[0], tb[0]), min(ta[-1], tb[-1])

    def interp(t, tv, vv):
        # tv is sorted; linear interpolation
        import bisect
        i = bisect.bisect_right(tv, t)
        if i <= 0:
            return vv[0]
        if i >= len(tv):
            return vv[-1]
        f = (t - tv[i - 1]) / (tv[i] - tv[i - 1])
        return vv[i - 1] + f * (vv[i] - vv[i - 1])

    worst = 0.0
    for k in range(samples):
        t = t0 + (t1 - t0) * k / (samples - 1)
        d = abs(interp(t, ta, va) - interp(t, tb, vb))
        if d > worst:
            worst = d
    return worst
