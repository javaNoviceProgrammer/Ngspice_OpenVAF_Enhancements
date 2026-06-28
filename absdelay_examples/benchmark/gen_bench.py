#!/usr/bin/env python3
"""Generate absdelay benchmark netlists for KLU-vs-SPARSE comparison (version2).

Topology: an L x L resistor MESH whose left column is driven by a chain of
absdelay buffers (the signal spine).  The 2D mesh gives the matrix realistic
fill where sparse-ordering quality matters, so it exposes the difference
between KLU (AMD/BTF ordering, symbolic reuse) and the default Sparse 1.3
(Markowitz).  A 1D delay line alone is trivially banded and shows no gap.

n = L*L nodes.  Same circuit is emitted for dc / ac / tran.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
# Path to the compiled absdelay model. run_benchmark.sh exports ABSDELAY_OSDI
# (a platform-specific build); fall back to the in-tree .build copy.
OSDI = os.path.abspath(
    os.environ.get("ABSDELAY_OSDI", os.path.join(HERE, "..", ".build", "absdelay.osdi"))
)

def make(L, analysis):
    out = [f"* absdelay {L}x{L} mesh benchmark ({analysis}) — {L*L} nodes",
           "* solver (KLU/SPARSE) selected by run_benchmark.sh",
           ".model dly absdelay_dly (delay=1n)"]
    # left column = absdelay delay-line driven from 'in'
    for i in range(L):
        src = "in" if i == 0 else f"g_{i-1}_0"
        out.append(f"Ndly{i} {src} g_{i}_0 dly")
    # 2D resistor mesh + leak to ground
    for i in range(L):
        for j in range(L):
            if j+1 < L:           out.append(f"Rh_{i}_{j} g_{i}_{j} g_{i}_{j+1} 100k")
            if i+1 < L and j > 0:  out.append(f"Rv_{i}_{j} g_{i}_{j} g_{i+1}_{j} 100k")
            out.append(f"Rg_{i}_{j} g_{i}_{j} 0 10meg")
    if analysis == "dc":
        out += ["Vin in 0 DC 1.0", ".dc Vin -1 1 0.02"]                 # 101 pts
    elif analysis == "ac":
        out += ["Vin in 0 AC 1", ".ac dec 20 1MEG 1G"]                   # ~61 pts
    else:
        out += ["Vin in 0 PULSE(0 1 0 0.2n 0.2n 4.8n 10n)",
                ".tran 0.2n 40n uic"]                                    # 200 steps
    out += [".control", f"  pre_osdi {OSDI}", "  run", ".endc", ".end"]
    return "\n".join(out) + "\n"

if __name__ == "__main__":
    sizes = [int(x) for x in sys.argv[1].split(",")]
    os.makedirs(os.path.join(HERE, "cir"), exist_ok=True)
    for L in sizes:
        for a in ("dc", "ac", "tran"):
            open(os.path.join(HERE, "cir", f"mesh_{L}_{a}.cir"), "w").write(make(L, a))
    print("generated meshes:", sizes, "(nodes:", [L*L for L in sizes], ")")
