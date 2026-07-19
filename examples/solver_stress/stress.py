#!/usr/bin/env python3
"""stress.py -- KLU vs SPARSE 1.3 large-circuit solver stress test.

ngspice ships SPARSE 1.3 (Markowitz reordering) as the default direct linear
solver; KLU (AMD ordering + BTF + numeric refactor) is opt-in via
`.options klu`.  For 1-D / tridiagonal circuits the two are equivalent and
KLU's setup overhead makes it slightly slower.  The interesting regime is
LARGE 2-D / 3-D meshes, where fill-in explodes and the quality (and cost) of
the fill-reducing ordering dominates -- exactly what separates the two.

This harness generates parametric resistor networks of three topologies and
sweeps their size, running each size under BOTH solvers with `.options acct`
so the accounting cleanly separates the *solver* cost (reorder / factor /
solve) from the identical device-load cost:

  ladder1d(N)  -- 1-D chain of N nodes            (tridiagonal, KLU's worst case)
  mesh2d(s)    -- s x s resistor grid, N = s^2     (2-D fill-in, KLU's sweet spot)
  mesh3d(s)    -- s x s x s resistor cube, N = s^3 (3-D fill-in, heavy)

Every node carries a 1 Meg shunt to ground (keeps the DC system nonsingular)
and neighbours are joined by 100 Ohm resistors; a 1 mA source injects at one
corner.  For each (topology, size) we record, per solver:
  * matrix reorder / factor / solve time and total analysis time  (from acct)
  * circuit fill-in non-zeroes
  * peak RSS  (/usr/bin/time -l)
  * DC-op correctness: max |V_klu - V_sparse| at two probe nodes.

Additionally a transient study drives one fixed 2-D mesh (caps at every node,
a pulsed current source) so the *repeated*-factorisation regime -- where KLU's
cheap numeric refactor pays off -- is measured too.

Writes results.json; plot_stress.py turns it into plots/*.png; RESULTS.md is
regenerated from the JSON.  Timing numbers are machine-dependent -- the
committed RESULTS.md records the reference machine.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
NG = os.environ.get("NGSPICE_BIN",
                    os.path.join(ROOT, "bin", "macos", "apple-silicon", "ngspice"))

# per-run wall-clock ceiling and the per-(topology,solver) analysis budget above
# which we stop growing the size (so a slow SPARSE reorder can't run for hours)
RUN_TIMEOUT = 240.0
ANALYSIS_CAP = 30.0


# ---------------------------------------------------------------- generators
def _inject(lines, inject_node):
    lines.append(f"Iin 0 {inject_node} 1m")


def ladder1d(n):
    """1-D chain n0..n_{n-1}: series 100 Ohm, 1 Meg shunt per node."""
    L = ["* ladder1d"]
    for i in range(n):
        L.append(f"Rg{i} n{i} 0 1meg")
        if i + 1 < n:
            L.append(f"Rs{i} n{i} n{i+1} 100")
    _inject(L, "n0")
    return "\n".join(L), n, ("n0", f"n{n-1}")


def mesh2d(s):
    """s x s grid n{i}_{j}: 100 Ohm to E/S neighbours, 1 Meg shunt per node."""
    L = ["* mesh2d"]
    for i in range(s):
        for j in range(s):
            nd = f"n{i}_{j}"
            L.append(f"Rg{i}_{j} {nd} 0 1meg")
            if i + 1 < s:
                L.append(f"Rx{i}_{j} {nd} n{i+1}_{j} 100")
            if j + 1 < s:
                L.append(f"Ry{i}_{j} {nd} n{i}_{j+1} 100")
    _inject(L, "n0_0")
    return "\n".join(L), s * s, ("n0_0", f"n{s-1}_{s-1}")


def mesh3d(s):
    """s x s x s cube n{i}_{j}_{k}: 100 Ohm to +x/+y/+z, 1 Meg shunt per node."""
    L = ["* mesh3d"]
    for i in range(s):
        for j in range(s):
            for k in range(s):
                nd = f"n{i}_{j}_{k}"
                L.append(f"Rg{i}_{j}_{k} {nd} 0 1meg")
                if i + 1 < s:
                    L.append(f"Rx{i}_{j}_{k} {nd} n{i+1}_{j}_{k} 100")
                if j + 1 < s:
                    L.append(f"Ry{i}_{j}_{k} {nd} n{i}_{j+1}_{k} 100")
                if k + 1 < s:
                    L.append(f"Rz{i}_{j}_{k} {nd} n{i}_{j}_{k+1} 100")
    _inject(L, "n0_0_0")
    return "\n".join(L), s * s * s, ("n0_0_0", f"n{s-1}_{s-1}_{s-1}")


# ---------------------------------------------------------------- run + parse
_ACCT = {
    "elapsed":  r"Total elapsed time \(seconds\)\s*=\s*([-\d.eE+]+)",
    "fillin":   r"Circuit fill-in non-zeroes\s*=\s*([-\d.eE+]+)",
    "analysis": r"Total analysis time \(seconds\)\s*=\s*([-\d.eE+]+)",
    "load":     r"Matrix load time\s*=\s*([-\d.eE+]+)",
    "reorder":  r"Matrix reorder time\s*=\s*([-\d.eE+]+)",
    "factor":   r"Matrix factor time\s*=\s*([-\d.eE+]+)",
    "solve":    r"Matrix solve time\s*=\s*([-\d.eE+]+)",
    "tfactor":  r"Transient factor time\s*=\s*([-\d.eE+]+)",
    "tsolve":   r"Transient solve time\s*=\s*([-\d.eE+]+)",
}


def _parse_acct(text):
    out = {}
    for k, pat in _ACCT.items():
        m = re.search(pat, text)
        out[k] = float(m.group(1)) if m else None
    return out


def _run(deck_text, klu):
    """Write the deck, run under /usr/bin/time -l, return (acct_dict, rss_bytes,
    wall_seconds).  `.options klu` is inserted right after the title line."""
    lines = deck_text.split("\n")
    head = [lines[0], ".options acct"]
    if klu:
        head.append(".options klu")
    deck = "\n".join(head + lines[1:] + [".op", ".end"])
    path = os.path.join(HERE, "_stress.cir")
    open(path, "w").write(deck)
    t0 = time.time()
    try:
        r = subprocess.run(["/usr/bin/time", "-l", NG, "-b", path],
                           capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, None, RUN_TIMEOUT
    wall = time.time() - t0
    txt = r.stdout + r.stderr
    acct = _parse_acct(txt)
    m = re.search(r"([\d]+)\s+maximum resident set size", txt)
    rss = int(m.group(1)) if m else None
    return acct, rss, wall


def _probe(deck_text, klu, probes):
    """Control-block run: op + print the probe node voltages.  Returns dict."""
    lines = deck_text.split("\n")
    head = [lines[0]]
    if klu:
        head.append(".options klu")
    body = ["\n".join(head + lines[1:]),
            ".control", "op",
            "print " + " ".join(f"v({p})" for p in probes),
            ".endc", ".end"]
    path = os.path.join(HERE, "_probe.cir")
    open(path, "w").write("\n".join(body))
    r = subprocess.run([NG, "-b", path], capture_output=True, text=True,
                      timeout=RUN_TIMEOUT)
    txt = r.stdout + r.stderr
    vals = {}
    for p in probes:
        m = re.search(re.escape(f"v({p})") + r"\s*=\s*([-\d.eE+]+)", txt)
        vals[p] = float(m.group(1)) if m else None
    return vals


# ---------------------------------------------------------------- the sweep
TOPOLOGIES = {
    "ladder1d": (ladder1d, [1000, 2000, 5000, 10000, 20000, 40000, 80000]),
    "mesh2d":   (mesh2d,   [16, 24, 32, 45, 64, 90, 128, 160, 200]),
    "mesh3d":   (mesh3d,   [6, 8, 10, 13, 16, 20, 24, 28]),
}


def sweep():
    results = {}
    for name, (gen, sizes) in TOPOLOGIES.items():
        print(f"\n=== {name} ===")
        rows = []
        cap_hit = {False: False, True: False}   # per-solver: stop growing?
        for s in sizes:
            deck, nnodes, probes = gen(s)
            row = {"param": s, "nodes": nnodes}
            for klu in (False, True):
                tag = "klu" if klu else "sparse"
                if cap_hit[klu]:
                    print(f"  {name}({s:>6}) N={nnodes:>7} {tag:6s} "
                          f"skipped (budget)")
                    continue
                acct, rss, wall = _run(deck, klu)
                if acct is None:                 # timed out
                    cap_hit[klu] = True
                    print(f"  {name}({s:>6}) N={nnodes:>7} {tag:6s} TIMEOUT")
                    continue
                row[tag] = {"acct": acct, "rss": rss, "wall": wall}
                a = acct
                print(f"  {name}({s:>6}) N={nnodes:>7} {tag:6s} "
                      f"reorder={a['reorder']:.4g} factor={a['factor']:.4g} "
                      f"solve={a['solve']:.4g} analysis={a['analysis']:.4g} "
                      f"nz={a['fillin']:.0f} rss={rss/1e6:.0f}MB")
                if a["analysis"] and a["analysis"] > ANALYSIS_CAP:
                    cap_hit[klu] = True
            # correctness: compare probe voltages KLU vs SPARSE (mid sizes only,
            # to keep the sweep quick -- the physics is size-independent)
            if "klu" in row and "sparse" in row and nnodes <= 20000:
                vk = _probe(deck, True, probes)
                vs = _probe(deck, False, probes)
                diffs = [abs(vk[p] - vs[p]) for p in probes
                         if vk[p] is not None and vs[p] is not None]
                row["max_vdiff"] = max(diffs) if diffs else None
            rows.append(row)
        results[name] = rows
    return results


# --------------------------------------------------- transient (refactor regime)
def transient_study(side=64):
    """Fixed 2-D mesh with a cap at every node + pulsed inject; a fixed-step
    .tran so both solvers do the SAME number of factorisations.  Isolates the
    transient factor/solve cost (KLU numeric-refactor vs SPARSE)."""
    deck, nnodes, probes = mesh2d(side)
    lines = deck.split("\n")
    caps = [f"Cg{i} n{i//side}_{i%side} 0 1p" for i in range(side * side)]
    body = [l for l in lines if not l.startswith("Iin")]
    body.append("Ipulse 0 n0_0 pulse(0 1m 0 1n 1n 50n 100n)")
    tran = ".tran 1n 200n"
    out = {"side": side, "nodes": nnodes}
    for klu in (False, True):
        head = [body[0], ".options acct"]
        if klu:
            head.append(".options klu")
        deck_t = "\n".join(head + body[1:] + caps +
                           [".print tran v(n0_0)", tran, ".end"])
        path = os.path.join(HERE, "_tran.cir")
        open(path, "w").write(deck_t)
        t0 = time.time()
        r = subprocess.run([NG, "-b", path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)
        wall = time.time() - t0
        acct = _parse_acct(r.stdout + r.stderr)
        m = re.search(r"Transient iterations\s*=\s*(\d+)", r.stdout + r.stderr)
        acct["titer"] = int(m.group(1)) if m else None
        out["klu" if klu else "sparse"] = {"acct": acct, "wall": wall}
        tag = "klu" if klu else "sparse"
        print(f"  tran mesh2d({side}) {tag:6s} "
              f"tfactor={acct['tfactor']} tsolve={acct['tsolve']} "
              f"analysis={acct['analysis']} wall={wall:.2f}")
    return out


def main():
    if not os.path.isfile(NG):
        sys.exit(f"ngspice not found at {NG}")
    res = {"machine": subprocess.run(["uname", "-mrs"], capture_output=True,
                                     text=True).stdout.strip(),
           "ngspice": os.path.relpath(NG, ROOT)}
    res["sweep"] = sweep()
    print("\n=== transient study ===")
    res["transient"] = transient_study()
    for junk in ("_stress.cir", "_probe.cir", "_tran.cir"):
        p = os.path.join(HERE, junk)
        if os.path.exists(p):
            os.remove(p)
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("\nwrote results.json")


if __name__ == "__main__":
    main()
