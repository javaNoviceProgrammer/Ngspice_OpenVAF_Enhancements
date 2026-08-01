#!/usr/bin/env python3
"""Figures for ngspice_temperature.md.

Every figure comes from a simulation run here -- nothing is sketched. A small
Verilog-A probe that reports `$temperature`, `$vt` and `$mfactor` as
operating-point variables is written out, compiled with openvaf-r, and driven
through the same netlist forms the document describes. Where a built-in device
can answer the same question it is put in the same deck and plotted alongside,
because "the OSDI number moved" is not evidence -- "the OSDI number equals what
the equivalent built-in gives" is.

Usage:  python3 docs/internals/ngspice_internals/make_temperature_figs.py
"""
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
OUT = os.path.join(HERE, "ngspice_temperature_figs")
WORK = os.path.join(OUT, "_work")
NG = os.environ.get("NGSPICE_BIN", os.path.join(ROOT, "ngspice-46/build/src/ngspice"))
KELVIN = 273.15


def find_vaf():
    local = os.path.join(ROOT, "OpenVAF-master-20260610/target/release/openvaf-r")
    if os.path.exists(local):
        return local
    for sub in ("macos/apple-silicon", "macos/intel", "linux/intel", "linux/arm"):
        p = os.path.join(ROOT, "bin", sub, "openvaf-r")
        if os.path.exists(p):
            return p
    sys.exit("openvaf-r not found")


VAF = os.environ.get("OPENVAF_BIN") or find_vaf()

# ---------------------------------------------------------------- the probe
PROBE = """`include "disciplines.vams"
`include "constants.vams"
module probe(p,n);
 inout p,n; electrical p,n;
 (* desc="mfact" *) real mfact;
 (* desc="tdev"  *) real tdev;
 (* desc="vt"    *) real vt;
 analog begin
   mfact = $mfactor;
   tdev  = $temperature;
   vt    = $vt;
   I(p,n) <+ V(p,n)*1e-3;
 end
endmodule
"""

# the same probe, but owning `m` and scaling by it -- the CMC convention
PROBE_M = """`include "disciplines.vams"
`include "constants.vams"
module probem(p,n);
 inout p,n; electrical p,n;
 (*type="instance"*) parameter real m = 1.0;
 (* desc="mfact" *) real mfact;
 analog begin
   mfact = $mfactor;
   I(p,n) <+ m*V(p,n)*1e-3;
 end
endmodule
"""


def compile_va(src, stem):
    d = os.path.join(WORK, stem)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, f"{stem}.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([VAF, os.path.join(d, f"{stem}.va"), "-o", os.path.join(d, f"{stem}.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    if r.returncode != 0:
        sys.exit(f"compiling {stem} failed:\n{r.stdout}{r.stderr}")
    return d


def run(d, deck, guard=60):
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", f"alarm {guard}; exec @ARGV", NG, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def scalar(out, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-+0-9.eE]+)", out)
    return float(m.group(1)) if m else None


def op(d, osdi, net, cards="", prints=("@n1[tdev]",), src="V1 a 0 dc 1"):
    """One operating point. `prints` names extra vectors to report.

    Pass prints=() for a device inside a subcircuit: its opvars live under the
    hierarchical name (`@n.x1.n1[...]`), and naming a vector that does not
    resolve makes ngspice abandon the WHOLE print line -- so `i(v1)` would go
    missing too and every such point would silently read as NaN.
    """
    extra = (" " + " ".join(prints)) if prints else ""
    deck = (f"t\n.control\npre_osdi {osdi}\n.endc\n{src}\n{net}\n{cards}\n"
            ".control\noption noacct\nset numdgt=12\nop\nprint i(v1)" + extra
            + "\n.endc\n.end\n")
    return run(d, deck)


def builtin_T(d, rline, cards=""):
    """A built-in resistor used as a thermometer: R(T)=R0*(1+tc1*(T-Tnom))."""
    deck = (f"t\n{cards}\nV1 a 0 dc 1\n{rline}\n"
            ".control\noption noacct\nset numdgt=12\nop\nprint i(v1)\n.endc\n.end\n")
    out = run(d, deck)
    m = re.search(r"^i\(v1\)\s*=\s*([-+0-9.eE]+)", out, re.M)
    if not m:
        return None
    r = 1.0 / abs(float(m.group(1)))
    return (r / 1000.0 - 1.0) / 0.01 + 27.0 + KELVIN


STYLE = dict(linewidth=1.8)
OSDI_C, BUILT_C, IDEAL_C = "#1f77b4", "#d62728", "#7f7f7f"


def finish(fig, ax_or_axes, name):
    axes = ax_or_axes if isinstance(ax_or_axes, (list, np.ndarray)) else [ax_or_axes]
    for ax in np.ravel(axes):
        ax.grid(True, alpha=0.3, linewidth=0.6)
    fig.tight_layout()
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=160)
    plt.close(fig)
    print("  wrote", os.path.relpath(p, ROOT))


# ============================================================ figure 1
def fig_temperature_routes(d, osdi):
    """$temperature vs the netlist value, for each of the four routes."""
    tset = np.arange(-40, 151, 10.0)
    routes = {
        "instance `temp=`":   (lambda v: (f"N1 a 0 mm temp={v}", ""),
                               lambda v: v + KELVIN),
        "`.temp`":            (lambda v: ("N1 a 0 mm", f".temp {v}"),
                               lambda v: v + KELVIN),
        "instance `dtemp=`":  (lambda v: (f"N1 a 0 mm dtemp={v}", ""),
                               lambda v: 27.0 + KELVIN + v),
        "instance `dt=`":     (lambda v: (f"N1 a 0 mm dt={v}", ""),
                               lambda v: 27.0 + KELVIN + v),
    }
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    # the reference line goes down FIRST and wide, so the measured points sit
    # visibly on top of it rather than hiding it
    ax.plot(tset, [v + KELVIN for v in tset], "-", color="#cccccc", linewidth=6,
            solid_capstyle="round", label="ideal for `temp`/`.temp`  (T + 273.15)",
            zorder=1)
    ax.plot(tset, [27.0 + KELVIN + v for v in tset], "-", color="#e8e8b0", linewidth=6,
            solid_capstyle="round", label="ideal for `dtemp`/`dt`  (300.15 + Δ)",
            zorder=1)
    for i, (label, (mk, ideal)) in enumerate(routes.items()):
        got = []
        for v in tset:
            net, cards = mk(v)
            got.append(scalar(op(d, osdi, net, cards + "\n.model mm probe()"), "@n1[tdev]"))
        ax.plot(tset, got, marker="o", ms=3.5, label=label,
                color=plt.cm.viridis(i / 3.4), zorder=3, **STYLE)
    ax.set_xlabel("netlist value  [°C for temp/.temp,  ΔK for dtemp/dt]")
    ax.set_ylabel("$temperature reported by the model  [K]")
    ax.set_title("Every temperature route reaches an OSDI device")
    ax.legend(fontsize=8, loc="upper left")
    finish(fig, ax, "temperature_routes.png")


# ============================================================ figure 2
def fig_osdi_vs_builtin(d, osdi):
    """OSDI $temperature against a built-in resistor in the same deck."""
    tset = np.arange(-40, 151, 10.0)
    osdi_T, built_T = [], []
    for v in tset:
        osdi_T.append(scalar(op(d, osdi, f"N1 a 0 mm temp={v}", ".model mm probe()"),
                             "@n1[tdev]"))
        built_T.append(builtin_T(d, f"R1 a 0 1k tc1=0.01 temp={v}"))
    osdi_T = np.array(osdi_T, float)
    built_T = np.array(built_T, float)
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(7.2, 5.6),
                                  gridspec_kw=dict(height_ratios=[2.4, 1]))
    ax.plot(tset, osdi_T, marker="o", ms=4, color=OSDI_C, label="OSDI: $temperature", **STYLE)
    ax.plot(tset, built_T, marker="x", ms=5, ls="--", color=BUILT_C,
            label="built-in resistor, read back through R(T)", **STYLE)
    ax.set_ylabel("device temperature  [K]")
    ax.set_title("`temp=` on an OSDI device and on a built-in agree")
    ax.legend(fontsize=9)
    ax2.plot(tset, (osdi_T - built_T) * 1e9, marker="o", ms=3, color="#2ca02c", **STYLE)
    ax2.set_xlabel("instance temp=  [°C]")
    ax2.set_ylabel("difference  [nK]")
    ax2.set_title("difference between the two, in nanokelvin", fontsize=9)
    finish(fig, [ax, ax2], "osdi_vs_builtin_temp.png")


# ============================================================ figure 3
def fig_vt(d, osdi):
    """$vt against k*T/q, and the constants-vintage offset that makes a ratio
    test the right check."""
    tset = np.arange(-40, 201, 10.0)
    T, vt = [], []
    for v in tset:
        out = op(d, osdi, f"N1 a 0 mm temp={v}", ".model mm probe()",
                 prints=("@n1[tdev]", "@n1[vt]"))
        T.append(scalar(out, "@n1[tdev]"))
        vt.append(scalar(out, "@n1[vt]"))
    T, vt = np.array(T, float), np.array(vt, float)
    k, q = 1.380649e-23, 1.602176634e-19          # CODATA 2018
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(7.2, 5.6),
                                  gridspec_kw=dict(height_ratios=[2.2, 1]))
    ax.plot(T, vt * 1e3, marker="o", ms=3.5, color=OSDI_C, label="$vt reported", **STYLE)
    ax.plot(T, k * T / q * 1e3, "--", color=IDEAL_C, linewidth=1.2,
            label="kT/q, CODATA 2018", **{})
    ax.set_ylabel("thermal voltage  [mV]")
    ax.set_title("$vt tracks $temperature")
    ax.legend(fontsize=9)
    ppm = (vt - k * T / q) / (k * T / q) * 1e6
    ax2.plot(T, ppm, marker="o", ms=3, color="#9467bd", **STYLE)
    ax2.axhline(0, color=IDEAL_C, linewidth=0.8)
    ax2.set_xlabel("$temperature  [K]")
    ax2.set_ylabel("deviation  [ppm]")
    ax2.set_title("constant-vintage offset: a few ppm, flat in T -- which is why the "
                  "suite compares RATIOS", fontsize=9)
    finish(fig, [ax, ax2], "vt_vs_temperature.png")


# ============================================================ figure 4
def fig_multiplier(d, osdi, dm, osdim):
    """Current vs multiplier for every route, against a built-in resistor."""
    ms = np.array([0.5, 1, 2, 3, 4, 5, 6, 8, 10], float)
    subs = ("\n.subckt s p n\nN1 p n mm\n.ends"
            "\n.subckt s3 p n\nN1 p n mm m=3\n.ends"
            "\n.model mm probe()\n")
    rsubs = ("\n.subckt sr p n\nR1 p n 1k\n.ends"
             "\n.subckt sr3 p n\nR1 p n 1k m=3\n.ends\n")

    def cur(out):
        m = re.search(r"^i\(v1\)\s*=\s*([-+0-9.eE]+)", out, re.M)
        return abs(float(m.group(1))) if m else np.nan

    dev = [cur(op(d, osdi, f"N1 a 0 mm m={v}", ".model mm probe()", prints=())) for v in ms]
    sub = [cur(op(d, osdi, f"X1 a 0 s m={v}", subs, prints=())) for v in ms]
    both = [cur(op(d, osdi, f"X1 a 0 s3 m={v}", subs, prints=())) for v in ms]
    ownm = [cur(op(dm, osdim, f"X1 a 0 s m={v}",
                   "\n.subckt s p n\nN1 p n mm\n.ends\n.model mm probem()\n",
                   prints=())) for v in ms]
    bdev = [cur(run(d, f"t\nV1 a 0 dc 1\nR1 a 0 1k m={v}\n"
                       ".control\noption noacct\nset numdgt=12\nop\nprint i(v1)\n.endc\n.end\n"))
            for v in ms]

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    ax.plot(ms, np.array(dev) * 1e3, marker="o", ms=5, color=OSDI_C,
            label="OSDI, device `m=`", **STYLE)
    ax.plot(ms, np.array(bdev) * 1e3, marker="x", ms=7, ls="none", color=BUILT_C,
            label="built-in resistor, device `m=`")
    ax.plot(ms, np.array(sub) * 1e3, marker="s", ms=4, ls="--", color="#2ca02c",
            label="OSDI in a subckt, `X ... m=`", **STYLE)
    ax.plot(ms, np.array(ownm) * 1e3, marker="^", ms=4, ls=":", color="#ff7f0e",
            label="model owns `m` and scales by it", **STYLE)
    ax.plot(ms, np.array(both) * 1e3, marker="d", ms=4, ls="-.", color="#8c564b",
            label="X `m=` over a device with `m=3`  (product)", **STYLE)
    ax.set_xlabel("multiplier written in the netlist")
    ax.set_ylabel("|i(v1)|  [mA]")
    ax.set_title("The multiplier reaches an OSDI device by every route")
    ax.legend(fontsize=8, loc="upper left")
    finish(fig, ax, "multiplier_routes.png")


# ============================================================ figure 5
def fig_nesting(d, osdi):
    """Nested subcircuit multipliers compound."""
    subs = ("\n.subckt s p n\nN1 p n mm\n.ends"
            "\n.subckt s3 p n\nN1 p n mm m=3\n.ends"
            "\n.subckt t2 p n\nX2 p n s m=3\n.ends"
            "\n.subckt u3 p n\nX3 p n s m=5\n.ends"
            "\n.subckt u2 p n\nX2 p n u3 m=3\n.ends"
            "\n.model mm probe()\n")

    def cur(net):
        out = op(d, osdi, net, subs, prints=())
        m = re.search(r"^i\(v1\)\s*=\s*([-+0-9.eE]+)", out, re.M)
        return abs(float(m.group(1))) * 1e3 if m else np.nan

    cases = [
        ("plain\n(1x)",                "X1 a 0 s",      1),
        ("X m=2\n(2x)",                "X1 a 0 s m=2",  2),
        ("X m=2 over\ndevice m=3\n(6x)", "X1 a 0 s3 m=2", 6),
        ("X2 nested\n2 x 3\n(6x)",     "X1 a 0 t2 m=2", 6),
        ("X3 nested\n2 x 3 x 5\n(30x)", "X1 a 0 u2 m=2", 30),
    ]
    labels = [c[0] for c in cases]
    got = [cur(c[1]) for c in cases]
    want = [c[2] for c in cases]

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    ax.bar(x - 0.19, got, 0.38, color=OSDI_C, label="measured |i(v1)| [mA]")
    ax.bar(x + 0.19, want, 0.38, color=IDEAL_C, alpha=0.65, label="expected multiplier")
    for xi, (g, w) in enumerate(zip(got, want)):
        ax.text(xi, max(g, w) * 1.05, f"{g:.4g}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, max(want) * 1.22)
    ax.set_ylabel("|i(v1)| [mA]   /   multiplier")
    ax.set_title("Nested subcircuit multipliers compound (E-394)")
    ax.legend(fontsize=9)
    finish(fig, ax, "multiplier_nesting.png")


# ============================================================ figure 6
def fig_sweep(d, osdi):
    """The `sweep` command stepping each of the four knobs."""
    fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.0))

    def sweep(knob, spec, out_expr):
        deck = (f"t\n.control\npre_osdi {osdi}\n.endc\nV1 a 0 dc 1\nN1 a 0 mm\n"
                ".model mm probe()\n.control\noption noacct\nset numdgt=12\n"
                f"sweep {knob} {spec} -analysis op -output oo={out_expr}\n"
                "setplot sweep1\nprint oo\n.endc\n.end\n")
        o = run(d, deck)
        return [float(v) for v in re.findall(r"^\s*\d+\s+([-+0-9.eE]+)\s*$", o, re.M)]

    tvals = np.arange(0, 101, 25.0)
    axes[0].plot(tvals, sweep("@n1[temp]", "0 100 25", "@n1[tdev]"),
                 marker="o", color=OSDI_C, label="sweep @n1[temp]", **STYLE)
    dvals = np.arange(0, 41, 10.0)
    axes[0].plot(dvals, sweep("@n1[dtemp]", "0 40 10", "@n1[tdev]"),
                 marker="s", color="#2ca02c", label="sweep @n1[dtemp]", **STYLE)
    axes[0].plot(dvals, sweep("@n1[dt]", "0 40 10", "@n1[tdev]"),
                 marker="^", ls="--", color="#ff7f0e", label="sweep @n1[dt]", **STYLE)
    axes[0].set_xlabel("knob value")
    axes[0].set_ylabel("$temperature  [K]")
    axes[0].set_title("`sweep` over the temperature knobs")
    axes[0].legend(fontsize=8)

    mvals = np.arange(1, 5.0)
    axes[1].plot(mvals, np.abs(sweep("@n1[m]", "1 4 1", "i(v1)")) * 1e3,
                 marker="o", color=OSDI_C, label="sweep @n1[m]", **STYLE)
    axes[1].plot(mvals, mvals, "--", color=IDEAL_C, linewidth=1.2, label="ideal m x 1 mA")
    axes[1].set_xlabel("m")
    axes[1].set_ylabel("|i(v1)|  [mA]")
    axes[1].set_title("`sweep` over the multiplier")
    axes[1].legend(fontsize=8)
    finish(fig, axes, "sweep_knobs.png")


# ============================================================ figure 7
def fig_reconstruct(d, osdi):
    """@n1[temp] is the BASE temperature; the total is base + offset.

    Plotted as a bar from 0 to `temp`, a second bar stacked on it for `dtemp`
    (drawn downward when the offset is negative), and a marker at the device's
    actual temperature. The marker landing on the top of the stack IS the
    identity; the override case is the one where the offset bar vanishes.
    """
    CASES = [
        ("default",              "",                 ""),
        ("dtemp=10",             "",                 " dtemp=10"),
        ("temp=75",              "",                 " temp=75"),
        ("temp=75\ndtemp=10",    "",                " temp=75 dtemp=10"),
        (".temp 85",             ".temp 85",         ""),
        (".temp 85\ndtemp=10",   ".temp 85",        " dtemp=10"),
        (".temp 125\ndtemp=-30", ".temp 125",       " dtemp=-30"),
        (".option temp=-40\ndtemp=5", ".option temp=-40", " dtemp=5"),
    ]
    base, off, tot = [], [], []
    for _, cards, extra in CASES:
        out = op(d, osdi, "N1 a 0 mm" + extra, ".model mm probe()\n" + cards,
                 prints=("@n1[temp]", "@n1[dtemp]", "@n1[tdev]"))
        base.append(scalar(out, "@n1[temp]"))
        off.append(scalar(out, "@n1[dtemp]"))
        tot.append(scalar(out, "@n1[tdev]") - KELVIN)   # back to degC to compare
    base, off, tot = map(lambda v: np.array(v, float), (base, off, tot))

    x = np.arange(len(CASES))
    fig, ax = plt.subplots(figsize=(8.6, 4.6))
    ax.bar(x, base, 0.56, color=OSDI_C, label="@n1[temp]  -- the BASE temperature")
    # A negative offset spans DOWNWARD from the base, so drawn plain it reads as
    # if it were added. Hatch it so "removed" is unmistakable.
    pos = np.where(off >= 0, off, 0.0)
    neg = np.where(off < 0, off, 0.0)
    ax.bar(x, pos, 0.56, bottom=base, color="#ff7f0e",
           label="@n1[dtemp] > 0  -- offset added")
    ax.bar(x, neg, 0.56, bottom=base, color="#ff7f0e", alpha=0.55,
           hatch="///", edgecolor="white", linewidth=0.0,
           label="@n1[dtemp] < 0  -- offset removed")
    ax.plot(x, tot, "o", ms=9, mfc="none", mew=2.2, color="#111111",
            label="$temperature (converted back to degC)", zorder=5)
    ax.axhline(0, color="#888888", linewidth=0.8)
    for xi, (b, o_, t) in enumerate(zip(base, off, tot)):
        ax.text(xi, t + (4 if t >= 0 else -9), f"{t:g}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([c[0] for c in CASES], fontsize=8)
    ax.set_ylabel("temperature  [degC]")
    ax.set_title("`@n1[temp]` is the BASE temperature; the total is base + offset")
    ax.legend(fontsize=8, loc="upper left")
    ax.set_ylim(min(-55, tot.min() - 20), max(tot.max(), base.max()) * 1.35)
    finish(fig, ax, "temperature_reconstruct.png")


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    d = compile_va(PROBE, "probe")
    osdi = "probe.osdi"
    dm = compile_va(PROBE_M, "probem")
    osdim = "probem.osdi"
    # the multiplier figure drives both probes from one working directory
    shutil.copy(os.path.join(dm, "probem.osdi"), os.path.join(d, "probem.osdi"))
    print("figures for ngspice_temperature.md:")
    fig_temperature_routes(d, osdi)
    fig_osdi_vs_builtin(d, osdi)
    fig_vt(d, osdi)
    fig_multiplier(d, osdi, d, "probem.osdi")
    fig_nesting(d, osdi)
    fig_sweep(d, osdi)
    fig_reconstruct(d, osdi)
    shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
