#!/usr/bin/env python3
"""large_bench.py -- large-circuit speed + correctness sweep: ngspice + OSDI,
Sparse 1.3 vs KLU, OSDI vs built-in twins. The companion of run_benchmark.py
(Enhancement-74) for the THOUSANDS-of-devices regime; the study it was written
for is docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md.

Jobs are (circuit, size, kind, solver). Each writes one deck, runs it in batch
mode with a timeout, parses the two `rusage all` blocks (op, tran), and keeps
the op solution (every node voltage) and two transient probe waveforms for the
cross-comparisons. Results accumulate in large_results.json, so the sweep can
be run in chunks (`--budget` seconds per invocation) and resumed; `--report`
prints the tables. Models are compiled from the VA-Models corpus on demand.

  python3 large_bench.py --maxsize 300      # the small tier, a few minutes
  python3 large_bench.py                    # everything (the 20 000-stage chain
                                            # alone is ~3.5 min under Sparse)
  python3 large_bench.py --report
"""
import json, os, re, subprocess, sys, time, bisect, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE            # noqa: E402
from bench_common import CORPUS, compile_va  # noqa: E402

NG = NGSPICE
RES = os.path.join(HERE, "large_results.json")
DIODE_CARD = "is=1e-14 n=1.2 cjo=2p vj=0.8 m=0.4 tt=5n"
VADIODE_CARD = DIODE_CARD.replace("is=", "is_=")
MODELS = {                       # osdi file -> corpus source (compiled if missing)
    "psp103.osdi": "psp103/vacode/psp103.va",
    "hicuml2.osdi": "hicum2/vacode/hicumL2V3p0p0.va",
    "nres.osdi": os.path.join(HERE, "nres.va"),
    "vadiode.osdi": os.path.join(HERE, "vadiode.va"),
}

def ensure_models():
    for osdi, va in MODELS.items():
        out = os.path.join(HERE, osdi)
        if os.path.exists(out):
            continue
        src = va if os.path.isabs(va) else os.path.join(CORPUS, va)
        print(f"compiling {osdi} from {os.path.relpath(src, HERE)} ...", flush=True)
        compile_va(src, out)

# ----------------------------------------------------------------- decks ---
def solver_card(solver):
    return ".option klu" if solver == "klu" else ".option sparse"

def control(pre, probes, jid, tstep, tstop):
    L = [".control"]
    if pre:
        L.append(f"pre_osdi {pre}")
    L += ["op", "rusage all", f"wrdata _{jid}_op.txt allv",
          f"tran {tstep} {tstop}", "rusage all",
          f"wrdata _{jid}_tr.txt " + " ".join(probes), "quit", ".endc", ".end"]
    return L

def chain(size, kind, solver, jid):
    """size-stage inverter chain; 2*size MOSFETs. Chain-like topology."""
    N = size
    L = [f"* inverter chain {kind} {solver} N={N}", solver_card(solver),
         "vdd vdd 0 dc 1.2", "vin s0 0 dc 0 pulse(0 1.2 0.2n 30p 30p 1n 2n)"]
    for i in range(1, N + 1):
        if kind == "bsim4":
            L.append(f"np{i} s{i} s{i-1} vdd vdd pmv")
            L.append(f"nn{i} s{i} s{i-1} 0 0 nmv")
        elif kind == "bsim4bi":
            L.append(f"mp{i} s{i} s{i-1} vdd vdd pmb W=2u L=0.2u")
            L.append(f"mn{i} s{i} s{i-1} 0 0 nmb W=1u L=0.2u")
        elif kind == "psp103":
            L.append(f"np{i} s{i} s{i-1} vdd vdd pmv")
            L.append(f"nn{i} s{i} s{i-1} 0 0 nmv")
        L.append(f"c{i} s{i} 0 5f")
    if kind == "bsim4":
        L += [".model nmv bsim4va(type=1 w=1e-6 l=0.2e-6)",
              ".model pmv bsim4va(type=-1 w=2e-6 l=0.2e-6)"]
        pre = "bsim4va.osdi"
    elif kind == "bsim4bi":
        L += [".model nmb nmos(level=14 version=4.8)",
              ".model pmb pmos(level=14 version=4.8)"]
        pre = None
    else:
        L += [".model nmv psp103va(type=1 w=1e-6 l=0.1e-6)",
              ".model pmv psp103va(type=-1 w=2e-6 l=0.1e-6)"]
        pre = "psp103.osdi"
    L += control(pre, ["v(s5)", "v(s20)"], jid, "20p", "3n")
    return "\n".join(L) + "\n"

def mesh(size, kind, solver, jid):
    """M x M grid of 1k resistors with a diode to ground at every node;
    corner driven by a pulse, opposite corner loaded. Dense fill-in."""
    M = size
    n = lambda i, j: f"n{i}_{j}"
    L = [f"* R-D mesh {kind} {solver} M={M}", solver_card(solver),
         f"vin {n(0,0)} 0 dc 0 pulse(0 1 0.2n 0.1n 0.1n 2n 4n)",
         f"rl {n(M-1,M-1)} 0 100"]
    k = 0
    for i in range(M):
        for j in range(M):
            if j + 1 < M:
                k += 1
                L.append((f"nr{k} {n(i,j)} {n(i,j+1)} rmod" if kind == "osdi"
                          else f"r{k} {n(i,j)} {n(i,j+1)} 1k"))
            if i + 1 < M:
                k += 1
                L.append((f"nr{k} {n(i,j)} {n(i+1,j)} rmod" if kind == "osdi"
                          else f"r{k} {n(i,j)} {n(i+1,j)} 1k"))
            if (i, j) != (0, 0):
                L.append((f"nd{i}_{j} {n(i,j)} 0 dmod" if kind == "osdi"
                          else f"d{i}_{j} {n(i,j)} 0 dmod"))
    if kind == "osdi":
        L += [".model rmod nres(r=1k)", f".model dmod vadiode({VADIODE_CARD})"]
        pre = "nres.osdi vadiode.osdi"
    else:
        L += [f".model dmod d({DIODE_CARD})"]
        pre = None
    c = M // 2
    L += control(pre, [f"v({n(1,1)})", f"v({n(c,c)})"], jid, "50p", "3n")
    return "\n".join(L) + "\n"

def mosgrid(size, kind, solver, jid):
    """M x M grid of BSIM4 inverters: cell (i,j) is driven by cell (i-1,j)
    and resistively coupled (10k) to cell (i,j-1). 2-D coupling with a real
    compact model; 2*M*M MOSFETs."""
    M = size
    o = lambda i, j: f"o{i}_{j}"
    L = [f"* BSIM4 grid {kind} {solver} M={M}", solver_card(solver),
         "vdd vdd 0 dc 1.2", "vin in 0 dc 0 pulse(0 1.2 0.2n 30p 30p 1n 2n)"]
    for i in range(M):
        for j in range(M):
            g = "in" if i == 0 else o(i - 1, j)
            if kind == "bsim4":
                L.append(f"np{i}_{j} {o(i,j)} {g} vdd vdd pmv")
                L.append(f"nn{i}_{j} {o(i,j)} {g} 0 0 nmv")
            else:
                L.append(f"mp{i}_{j} {o(i,j)} {g} vdd vdd pmb W=2u L=0.2u")
                L.append(f"mn{i}_{j} {o(i,j)} {g} 0 0 nmb W=1u L=0.2u")
            L.append(f"c{i}_{j} {o(i,j)} 0 5f")
            if j > 0:
                L.append(f"rc{i}_{j} {o(i,j)} {o(i,j-1)} 10k")
    if kind == "bsim4":
        L += [".model nmv bsim4va(type=1 w=1e-6 l=0.2e-6)",
              ".model pmv bsim4va(type=-1 w=2e-6 l=0.2e-6)"]
        pre = "bsim4va.osdi"
    else:
        L += [".model nmb nmos(level=14 version=4.8)",
              ".model pmb pmos(level=14 version=4.8)"]
        pre = None
    L += control(pre, [f"v({o(0,1)})", f"v({o(3,3)})"], jid, "20p", "2n")
    return "\n".join(L) + "\n"

def hicum(size, kind, solver, jid):
    """size common-emitter HiCUM L2 stages sharing one supply (block-diagonal
    plus one shared node); per-instance cost of a heavy bipolar model."""
    N = size
    L = [f"* HiCUM L2 stages {kind} {solver} N={N}", solver_card(solver),
         "vcc vcc 0 dc 3", "vin in 0 dc 0.8 sin(0.8 0.01 1g)"]
    for i in range(1, N + 1):
        L += [f"rb{i} in b{i} 1k", f"rc{i} vcc c{i} 1k",
              f"nq{i} c{i} b{i} 0 0 0 npnh"]
    L += [".model npnh hicumL2va()"]
    L += control("hicuml2.osdi", ["v(c1)", f"v(c{N})"], jid, "20p", "3n")
    return "\n".join(L) + "\n"

GEN = {"chain": chain, "mesh": mesh, "mosgrid": mosgrid, "hicum": hicum}
JOBS = [  # (circuit, size, kinds)
    ("chain", 100, ["bsim4", "bsim4bi", "psp103"]),
    ("mesh", 30, ["osdi", "bi"]),
    ("mosgrid", 20, ["bsim4", "bi"]),
    ("hicum", 300, ["osdi"]),
    ("chain", 1000, ["bsim4", "bsim4bi", "psp103"]),
    ("mesh", 60, ["osdi", "bi"]),
    ("mosgrid", 40, ["bsim4", "bi"]),
    ("hicum", 1000, ["osdi"]),
    ("chain", 5000, ["bsim4", "bsim4bi"]),
    ("mesh", 100, ["osdi", "bi"]),
    ("mosgrid", 70, ["bsim4", "bi"]),
    ("chain", 20000, ["bsim4"], ["klu", "sparse"]),
    ("mesh", 150, ["osdi"], ["klu", "sparse"]),
    ("mosgrid", 100, ["bsim4"], ["klu"]),
]
SOLVERS = ["sparse", "klu"]

# --------------------------------------------------------------- running ---
STAT_KEYS = {
    "analysis_s": r"Total analysis time \(seconds\) = ([-\d.eE+]+)",
    "load_s": r"Matrix load time = ([-\d.eE+]+)",
    "reorder_s": r"Matrix reorder time = ([-\d.eE+]+)",
    "factor_s": r"Matrix factor time = ([-\d.eE+]+)",
    "solve_s": r"Matrix solve time = ([-\d.eE+]+)",
    "iters": r"Total iterations = (\d+)",
    "tran_iters": r"Transient iterations = (\d+)",
    "eqns": r"Circuit Equations = (\d+)",
    "nz_orig": r"Circuit original non-zeroes = (\d+)",
    "nz_fill": r"Circuit fill-in non-zeroes = (\d+)",
    "timepoints": r"Accepted timepoints = (\d+)",
    "rejected": r"Rejected timepoints = (\d+)",
    "mem_mb": r"Maximum ngspice program size =\s+([-\d.]+) MB",
    "parse_s": r"Netlist parsing time = ([-\d.eE+]+)",
    "loadnet_s": r"Netlist loading time = ([-\d.eE+]+)",
}

def parse_rusage(out):
    blocks = []
    for k, pat in STAT_KEYS.items():
        vals = re.findall(pat, out)
        for i, v in enumerate(vals):
            while len(blocks) <= i:
                blocks.append({})
            blocks[i][k] = float(v)
    return blocks

def run_job(circuit, size, kind, solver, timeout):
    jid = f"{circuit}{size}_{kind}_{solver}"
    deck = GEN[circuit](size, kind, solver, jid)
    with open(os.path.join(HERE, "_" + jid + ".cir"), "w") as f:
        f.write(deck)
    ndev = sum(1 for l in deck.splitlines() if l[:1] in "nmrdc" and not l.startswith(".") )
    t0 = time.monotonic()
    try:
        p = subprocess.run([NG, "-b", "_" + jid + ".cir"], cwd=HERE, capture_output=True,
                           text=True, timeout=timeout, errors="replace")
        wall = time.monotonic() - t0
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        wall = time.monotonic() - t0
        out = ((e.stdout or b"").decode("utf8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + \
              ((e.stderr or b"").decode("utf8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
        return {"jid": jid, "circuit": circuit, "size": size, "kind": kind,
                "solver": solver, "timeout": True, "wall_s": round(wall, 2),
                "lines": len(deck.splitlines()), "tail": out[-600:]}
    blocks = parse_rusage(out)
    r = {"jid": jid, "circuit": circuit, "size": size, "kind": kind, "solver": solver,
         "timeout": False, "rc": p.returncode, "wall_s": round(wall, 2),
         "lines": len(deck.splitlines()),
         "solver_line": (re.search(r"Using (.*) as Direct Linear Solver", out) or [None, "?"])[1],
         "op": blocks[0] if blocks else {}, "tran": blocks[1] if len(blocks) > 1 else {},
         "warnings": len(re.findall(r"(?i)warning", out)),
         "singular": len(re.findall(r"singular", out)),
         "errors": [l for l in out.splitlines() if "rror" in l][:5],
         "tail": out[-400:] if p.returncode != 0 else ""}
    return r

# ------------------------------------------------------------ comparing ---
def load_op(jid):
    try:
        with open(os.path.join(HERE, "_" + jid + "_op.txt")) as f:
            vals = [float(x) for x in f.read().split()]
        return vals[1::2]
    except Exception:
        return None

def load_wave(jid):
    try:
        t, v1, v2 = [], [], []
        with open(os.path.join(HERE, "_" + jid + "_tr.txt")) as f:
            for line in f:
                p = line.split()
                if len(p) >= 4:
                    t.append(float(p[0])); v1.append(float(p[1])); v2.append(float(p[3]))
        return t, v1, v2
    except Exception:
        return None

def interp(t, tv, vv):
    i = bisect.bisect_right(tv, t)
    if i <= 0: return vv[0]
    if i >= len(tv): return vv[-1]
    f = (t - tv[i-1]) / (tv[i] - tv[i-1])
    return vv[i-1] + f * (vv[i] - vv[i-1])

def wave_diff(a, b, samples=1000):
    if not a or not b: return None
    ta, a1, a2 = a; tb, b1, b2 = b
    t0, t1 = max(ta[0], tb[0]), min(ta[-1], tb[-1])
    worst = 0.0
    for k in range(samples):
        t = t0 + (t1 - t0) * k / (samples - 1)
        for va, vb in ((a1, b1), (a2, b2)):
            d = abs(interp(t, ta, va) - interp(t, tb, vb))
            worst = max(worst, d)
    return worst

def op_diff(a, b):
    if a is None or b is None or len(a) != len(b): return None
    return max(abs(x - y) for x, y in zip(a, b))

# ------------------------------------------------------------------ main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=480)
    ap.add_argument("--timeout", type=float, default=500)
    ap.add_argument("--only", default="")
    ap.add_argument("--maxsize", type=int, default=10**9)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the generated decks and dumps")
    a = ap.parse_args()
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    if a.report:
        report(res); return
    ensure_models()
    t_start = time.monotonic()
    for job in JOBS:
        circuit, size, kinds = job[0], job[1], job[2]
        solvers = job[3] if len(job) > 3 else SOLVERS
        if size > a.maxsize: continue
        if a.only and circuit not in a.only.split(","): continue
        for kind in kinds:
            for solver in solvers:
                jid = f"{circuit}{size}_{kind}_{solver}"
                if jid in res: continue
                if time.monotonic() - t_start > a.budget:
                    print(f"budget reached; next job {jid}"); return
                print(f"running {jid} ...", end="", flush=True)
                r = run_job(circuit, size, kind, solver, a.timeout)
                res[jid] = r
                json.dump(res, open(RES, "w"), indent=1)
                if r["timeout"]:
                    print(f" TIMEOUT after {r['wall_s']}s")
                else:
                    tr = r["tran"]; op = r["op"]
                    print(f" wall {r['wall_s']}s rc={r['rc']} op {op.get('analysis_s')}s "
                          f"tran {tr.get('analysis_s')}s pts {tr.get('timepoints')} "
                          f"eq {op.get('eqns')} fill {op.get('nz_fill')} mem {tr.get('mem_mb')}MB "
                          f"warn {r['warnings']} sing {r['singular']}")
    print("all jobs done")
    if not a.keep:
        for f in os.listdir(HERE):
            if re.match(r"^_(chain|mesh|mosgrid|hicum)\d+_.*\.cir$", f):
                os.remove(os.path.join(HERE, f))

def report(res):
    def g(jid): return res.get(jid)
    print("| job | kind | eqns | Sparse wall | KLU wall | ratio | op diff S/K | tran diff S/K | Sparse fill | KLU fill |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for job in JOBS:
        circuit, size, kinds = job[0], job[1], job[2]
        for kind in kinds:
            s, k = g(f"{circuit}{size}_{kind}_sparse"), g(f"{circuit}{size}_{kind}_klu")
            if not s and not k: continue
            def w(r): return "--" if not r else ("TIMEOUT" if r["timeout"] else f"{r['wall_s']:.2f} s")
            ratio = ""
            if s and k and not s["timeout"] and not k["timeout"]:
                ratio = f"{s['wall_s']/k['wall_s']:.2f}x"
            od = op_diff(load_op(f"{circuit}{size}_{kind}_sparse"), load_op(f"{circuit}{size}_{kind}_klu"))
            td = wave_diff(load_wave(f"{circuit}{size}_{kind}_sparse"), load_wave(f"{circuit}{size}_{kind}_klu"))
            eq = next((r["op"]["eqns"] for r in (s, k) if r and not r["timeout"] and r.get("op", {}).get("eqns")), 0)
            print(f"| {circuit} {size} | {kind} | {eq:.0f} | {w(s)} | {w(k)} | {ratio} | "
                  f"{'--' if od is None else f'{od:.1e}'} | {'--' if td is None else f'{td:.1e}'} | "
                  f"{s['op'].get('nz_fill','') if s and not s['timeout'] else ''} | "
                  f"{k['op'].get('nz_fill','') if k and not k['timeout'] else ''} |")
    print()
    print("| twin | size | solver | built-in wall | OSDI wall | OSDI/bi | tran probe diff |")
    print("|---|---:|---|---:|---:|---:|---:|")
    for job in JOBS:
        circuit, size, kinds = job[0], job[1], job[2]
        pairs = [("bsim4", "bsim4bi")] if circuit in ("chain",) else [("osdi", "bi")] if circuit == "mesh" else [("bsim4", "bi")] if circuit == "mosgrid" else []
        for o, b in pairs:
            if o not in kinds or b not in kinds: continue
            for solver in SOLVERS:
                ro, rb = g(f"{circuit}{size}_{o}_{solver}"), g(f"{circuit}{size}_{b}_{solver}")
                if not ro or not rb: continue
                td = wave_diff(load_wave(ro["jid"]), load_wave(rb["jid"]))
                def w(r): return "TIMEOUT" if r["timeout"] else f"{r['wall_s']:.2f} s"
                ratio = "" if ro["timeout"] or rb["timeout"] else f"{ro['wall_s']/rb['wall_s']:.2f}"
                print(f"| {circuit} | {size} | {solver} | {w(rb)} | {w(ro)} | {ratio} | {'--' if td is None else f'{td:.2e}'} |")

if __name__ == "__main__":
    main()
