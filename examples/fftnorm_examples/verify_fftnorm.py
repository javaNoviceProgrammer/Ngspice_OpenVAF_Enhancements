#!/usr/bin/env python3
"""Enhancement-241: fix the fft/spec amplitude normalization for non-power-of-2 records.

ngspice's built-in `fft` (and `spec`) command, when NOT linked against FFTW3, uses
a radix-2 FFT that zero-pads the `length` input samples up to the next power of two
`N`. The single-sided amplitude scale was computed from the PADDED size (`N/2`)
instead of the true sample count (`length/2`):

    scale = ((double)N)/2;      /* com_fft.c -- WRONG */

so every FFT whose sample count is not a power of two reported amplitudes too
small by `length/N` -- up to 2x. A pure DC offset (which has no windowing/
scalloping ambiguity, it is always exactly bin 0) read `D * length/N` instead of
`D`. The FFTW3 code path already used `length/2` and was correct; E-241 makes the
non-FFTW path match it (and likewise fixes `spec`'s `N*N` -> `length*length`
power normalization). After the fix, the amplitude equals the true single-sided
spectrum `2|X|/length`, independent of how zero-padding rounds the record up.

The DC bin is the clean discriminator (no scalloping): a signal with DC offset D
must report DC = D no matter how many samples were taken.

Checks (interactive pipe mode). `set specwindow=none` selects a rectangular
window; integer-period windows keep the tone bin-aligned (no leakage).
 1. a DC offset of 2.0 reads back as 2.0 for a NON-power-of-2 record (pre-fix it
    read 2.0*length/N, e.g. ~1.46);
 2. the DC reading is INDEPENDENT of the (non-power-of-2) sample count -- four
    different record lengths all give 2.0;
 3. a pure tone of amplitude 1.0 (no DC), bin-aligned, reads back 1.0;
 4. `spec` (PSD) peak of a tone is likewise length-independent.
"""
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


def fft_dc_tone(deck_body, tstep, tstop, cmd="fft", pick="dc"):
    """Return the requested value from an fft/spec of `deck_body`."""
    cir = os.path.join(HERE, "_fn.cir")
    open(cir, "w").write(f"* fftnorm\n{deck_body}\n.end\n")
    if pick == "dc":
        getter = "let val=mag(v(1))[0]\n"
    else:  # peak excluding DC
        getter = "let mg=mag(v(1))\nlet mg[0]=0\nlet val=vecmax(mg)\n"
    script = (f"source {cir}\nset specwindow=none\n"
              f"tran {tstep} {tstop} 0 {tstep} uic\nlinearize\n"
              f"{cmd} v(1)\n{getter}print val\nquit\n")
    r = subprocess.run([NGSPICE, "-p"], input=script, capture_output=True,
                       text=True, timeout=60)
    m = re.search(r"^val\s*=\s*([-\d.eE+]+)", r.stdout.replace("\r", "\n"), re.M)
    return float(m.group(1)) if m else None


DC_TONE = "v1 1 0 dc 0 sin(2.0 1.0 1000)"   # DC=2, tone A=1 at 1 kHz
TONE = "v1 1 0 dc 0 sin(0 1.0 1000)"        # pure tone A=1 at 1 kHz
r1 = "r1 1 0 1k"

# 1: DC recovery on a non-power-of-2 record (1001 samples -> padded to 1024)
dc = fft_dc_tone(f"{DC_TONE}\n{r1}", "16u", "16m")
check("DC offset 2.0 reads 2.0 on a non-power-of-2 record (was ~1.95=2*len/N)",
      dc is not None and abs(dc - 2.0) < 2e-3, f"DC={dc}")

# 2: the worst case -- a record just over a power of two (length 1025 -> pad 2048),
# where the pre-fix bug halved the amplitude (2.0 * 1025/2048 ~ 1.0)
dc = fft_dc_tone(f"{DC_TONE}\n{r1}", "15.625u", "16m")
check("DC=2.0 on a maximally-padded record (was ~1.0 = 2*1025/2048)",
      dc is not None and abs(dc - 2.0) < 2e-3, f"DC={dc}")

# 3: DC reading independent of sample count (four different non-power-of-2 lengths
#    padding from ~1.02x up to ~2x)
cfgs = [("16u", "16m"), ("10u", "16m"), ("8u", "24m"), ("15.625u", "16m")]
dcs = [fft_dc_tone(f"{DC_TONE}\n{r1}", ts, tp) for ts, tp in cfgs]
ok = all(d is not None and abs(d - 2.0) < 2e-3 for d in dcs)
check("DC reading is independent of (non-power-of-2) sample count",
      ok, "DC=" + ", ".join(f"{d:.4f}" if d is not None else "None" for d in dcs))

# 4: spec (PSD) tone peak is length-independent
sp = [fft_dc_tone(f"{TONE}\n{r1}", ts, tp, cmd="spec", pick="tone")
      for ts, tp in [("16u", "16m"), ("10u", "16m"), ("8u", "24m")]]
ok = all(s is not None for s in sp) and (max(sp) - min(sp)) < 2e-2
check("spec PSD tone peak is length-independent", ok,
      "peaks=" + ", ".join(f"{s:.4f}" if s is not None else "None" for s in sp))

p = os.path.join(HERE, "_fn.cir")
if os.path.exists(p):
    os.remove(p)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
