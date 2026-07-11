#!/usr/bin/env python3
"""Generate envelope_ringup.png: EF envelope samples overlaid on the full-transient
carrier waveform + its amplitude, for the high-Q tank demo. Runs the committed
ngspice. Usage: python3 make_envelope_fig.py"""
import math, os, subprocess, sys, tempfile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _setup import NG as NGSPICE

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = tempfile.mkdtemp(prefix="ef_fig_")
FC = 5.032921e6; T = 1.0 / FC
TANK = f"v1 s 0 sin(0 1 {FC:.6e})\nl1 s a 1u\nc1 a 0 1n\nr1 a 0 100k\n"


def run(deck, fname, vec):
    with open(os.path.join(SCRATCH, "d.cir"), "w") as f:
        f.write(deck)
    subprocess.run([NGSPICE, "-b", "d.cir"], capture_output=True, text=True,
                   cwd=SCRATCH, timeout=180)
    xs, ys = [], []
    p = os.path.join(SCRATCH, fname)
    for line in open(p):
        q = line.split()
        if len(q) >= 2:
            try: xs.append(float(q[0])); ys.append(float(q[1]))
            except ValueError: pass
    return xs, ys


et, ea = run(f"* ef\n{TANK}.control\nenvelope a {FC:.6e} 596u\nwrdata ef.txt a_amp\n.endc\n.end\n",
             "ef.txt", "a_amp")
tt, vv = run(f"* tr\n{TANK}.control\ntran {T/128:.6e} 596u\nwrdata tr.txt v(a)\n.endc\n.end\n",
             "tr.txt", "v(a)")

# full-transient amplitude envelope, computed as 2|V1| over each carrier period
def fund(tc):
    re_ = im_ = 0.0; prev = None
    for i in range(len(tt)):
        if tt[i] < tc or tt[i] >= tc + T: continue
        w = 2*math.pi*FC*(tt[i]-tc); gr = vv[i]*math.cos(w); gi = -vv[i]*math.sin(w)
        if prev is not None:
            dt = tt[i]-prev[0]; re_ += 0.5*(gr+prev[1])*dt; im_ += 0.5*(gi+prev[2])*dt
        prev = (tt[i], gr, gi)
    return 2.0*math.hypot(re_, im_)/T
env_t = [k*20*T for k in range(int(596e-6/(20*T)))]
env_a = [fund(tc) for tc in env_t]

fig, ax = plt.subplots(figsize=(9, 4.6))
ax.plot([t*1e6 for t in env_t], env_a, "-", color="#5b8fb9", lw=2.2,
        label="full-transient amplitude 2|V1| (~3000 periods)", zorder=1)
ax.plot([t*1e6 for t in et], ea, "o", color="#d1495b", ms=6,
        label=f"envelope-following samples ({len(et)} pts)", zorder=3)
ax.set_xlabel("time  (us)"); ax.set_ylabel("amplitude  2|V1|(a)  (V)")
ax.set_title(f"Envelope following: high-Q tank ring-up (Q~3160)\n"
             f"{len(et)} envelope samples reproduce ~3000 carrier periods")
ax.legend(loc="lower right", fontsize=9); ax.grid(alpha=0.25)
ax.set_ylim(bottom=0)

# inset: a few carrier cycles near the middle, to show the fast underlying signal
axin = ax.inset_axes([0.09, 0.52, 0.34, 0.4])
w0, w1 = 300e-6, 300e-6 + 4*T
xin = [t*1e6 for t in tt if w0 <= t <= w1]; yin = [v for t, v in zip(tt, vv) if w0 <= t <= w1]
axin.plot(xin, yin, color="#5b8fb9", lw=1.0)
axin.set_title("carrier (4 cycles @ 5 MHz)", fontsize=7); axin.tick_params(labelsize=6)
fig.tight_layout()
out = os.path.join(HERE, "envelope_ringup.png")
fig.savefig(out, dpi=110)
print("wrote", out)
