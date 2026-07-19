#!/usr/bin/env python3
"""Enhancement-234: the `loadpull` power-amplifier load-/source-pull analysis.

Load-pull sweeps the LOAD impedance a device/PA output sees over a grid inside the
Smith chart and, at each point, runs a large-signal .tran, extracts the
fundamental by a direct DFT, and reports contours of output power / gain / PAE /
drain efficiency.  `-source <Rs> <Ls> <Cs>` sweeps the SOURCE impedance instead
(source-pull).  It rides the existing .tran engine and the `alter` mechanism, and
the contours render with `pyplot -contour` (E-218).

Checks:
 1. Analytic max-power transfer -- a LINEAR Thevenin source (Vs = 1 V, Zs = 50+j30)
    delivers Pmax = |Vs|^2 / (8 Rs) = 2.5 mW = 3.979 dBm into a conjugate-matched
    load, so Pout must peak at Gamma_L = conj(Gamma_s) with that value.
 2. A behavioral PA gives PHYSICAL gain / PAE / efficiency (0 < PAE < eff < 100%),
    which also guards the E-234 fix: the branch-current metrics were corrupted by
    an INPretrieve use-after-free that freed the source's name on re-setup.
 3. Source-pull runs and finds an optimum.

Runs ngspice in pipe mode (`-p`): the `loadpull` command drives everything.
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck, script):
    """Write `deck` to a temp .cir, run `script` (ngspice commands) in pipe mode."""
    cir = os.path.join(HERE, "_lp.cir")
    open(cir, "w").write(deck)
    full = f"source {cir}\n" + script + "\nquit\n"
    r = subprocess.run([NGSPICE, "-p"], input=full, capture_output=True,
                       text=True, timeout=300)
    return r.stdout.replace("\r", "\n") + r.stderr


# ---------------------------------------------------------------- 1. oracle
# Vs=1V at 1 GHz, Zs = 50 + j30 (Ls = 30/(2*pi*1e9)); optimum Gamma_L = conj(Gamma_s)
LIN = """* loadpull max-power-transfer oracle (linear)
Vs src 0 dc 0 sin(0 1 1e9)
Rs src n1 50
Ls n1 out 4.7746n
RL out l1 50
LL l1 l2 1e-15
CL l2 0 1e-3
.end
"""
out = run(LIN, "loadpull -load RL LL CL -out out -drive Vs -f 1e9 -n 21 -gmax 0.85")
m = re.search(r"peak Pout\s*=\s*([-\d.]+)\s*dBm", out)
peak = float(m.group(1)) if m else None
mg = re.search(r"optimum Gamma\s*=\s*([\d.]+)\s*angle\s*([-\d.]+)", out)
# conj(Gamma_s): Gamma_s = j30/(100+j30) -> |0.2873| angle +73.3 deg -> conj = -73.3
ok_p = peak is not None and abs(peak - 3.979) < 0.05
ok_g = mg is not None and abs(float(mg.group(1)) - 0.287) < 0.06 and \
    abs(float(mg.group(2)) - (-73.3)) < 12.0
check("max-power-transfer: peak Pout ~ 3.979 dBm (analytic |Vs|^2/8Rs)",
      ok_p, f"peak={peak} dBm" if peak is not None else "no Pout")
check("max-power-transfer: optimum Gamma_L ~ conj(Gamma_s) (0.287 / -73 deg)",
      ok_g, f"{mg.group(1)} / {mg.group(2)} deg" if mg else "no optimum")

# ---------------------------------------------------------------- 2. PA metrics
PA = """* behavioral class-A-ish PA
Vdr dr 0 dc 0 sin(0.3 0.4 1e9)
Rg dr g 50
Rgate g 0 200
Vdd dd 0 dc 5
Lchoke dd out 1u
Bdev out 0 I = 0.05*(1 + tanh((v(g)-0.3)/0.15))
RL out l1 50
LL l1 l2 1e-15
CL l2 0 1e-3
.end
"""
out = run(PA, "loadpull -load RL LL CL -out out -drive Vdr -supply Vdd -f 1e9 "
              "-n 9 -gmax 0.6 -nper 30\n"
              "let g_mx=vecmax(gain_db)\nlet e_mx=vecmax(eff)\n"
              "let p_mx=vecmax(pae)\nlet e_mn=vecmin(eff)\n"
              "print g_mx e_mx p_mx e_mn")


def val(name):
    m = re.search(name + r"\s*=\s*([-\d.eE+]+)", out)
    return float(m.group(1)) if m else None


g_mx, e_mx, p_mx, e_mn = val("g_mx"), val("e_mx"), val("p_mx"), val("e_mn")
ok = (g_mx is not None and e_mx is not None and p_mx is not None and
      g_mx > 3.0 and 0.0 < e_mn and e_mx < 100.0 and p_mx < e_mx)
check("PA: physical gain/PAE/efficiency (gain>0, 0<PAE<eff<100%)", ok,
      f"gain={g_mx:.1f}dB eff={e_mx:.1f}% pae={p_mx:.1f}%" if ok else
      f"gain={g_mx} eff={e_mx} pae={p_mx}")

# ---------------------------------------------------------------- 3. source-pull
SRC = """* source-pull: swept source impedance, fixed 50-ohm load
Vs src 0 dc 0 sin(0 1 1e9)
Rs src n1 50
Ls n1 out 1e-15
Cs out l0 1e-3
RL out 0 50
.end
"""
out = run(SRC, "loadpull -source Rs Ls Cs -out out -drive Vs -f 1e9 -n 9 -gmax 0.6")
ok = "Source-pull result" in out and re.search(r"optimum Gamma", out) is not None
check("source-pull runs and reports an optimum", ok,
      "" if ok else out[-200:])

# tidy
for f in ("_lp.cir",):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
