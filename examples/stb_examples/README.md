# Loop-gain / stability analysis — `stb` (Enhancement-198)

`stb` measures a feedback loop's small-signal **loop gain** `T(f)` and reports its
**phase margin** and **gain margin** — the standard stability check for any analog
feedback design (op-amps, regulators, PLLs, …). ngspice had no built-in for it; you
had to hand-roll a `.control` script. `stb` is the one-command equivalent of
Spectre's `stb` / the Middlebrook–Tian probe.

```
stb <Vprobe> <Iprobe> (dec|oct|lin <N> <fstart> <fstop>)
```

## Why double injection

Break the loop and inject a test signal, and the *loading* at the break point
corrupts the measurement — a series **voltage** injection sees the wrong answer
unless the break happens to be from a zero-impedance source into an
infinite-impedance load. Middlebrook and Tian's **double injection** removes the
loading error by combining a voltage and a current injection:

```
voltage injection (Vprobe ac=1):   Tv = -v(A)/v(B)
current injection (Iprobe ac=1):   Ti = -i(Vprobe)/(i(Vprobe)+1)
loop gain          T = (Tv·Ti - 1) / (Tv + Ti + 2)
```

so the answer is independent of *where* in the loop you put the probe — the
defining property that a single injection lacks.

## The probe

Mark the break in the loop wire, between the driving node `A` and the loaded node
`B`, with a **probe pair** (both quiescent, so the DC bias is untouched):

```
Vstb A B dc 0 ac 0      series 0 V source  (+node = driver A, -node = load B)
Istb 0 B dc 0 ac 0      shunt 0 A source   (ground -> load node B)
```

Then:

```
stb Vstb Istb dec 20 1 100meg
```

The complex loop gain is stored as the vector **`loopgain`** (vs `frequency`) in a
new `stb` plot:

```
plot db(loopgain)                 magnitude in dB
plot 180/PI*cph(loopgain)         phase in degrees (unwrapped)
```

## The example

`stb_demo.cir` — a 3-pole op-amp macromodel (DC gain 10⁵; poles at 10 Hz / 1 MHz /
3 MHz) with a finite **1 kΩ output impedance**, closed in a β = 0.1 divider (a ×10
amplifier). The 1 kΩ output makes this a genuinely *loaded* break, so the double
injection is doing real work. It reports:

```
DC loop gain    : 79.13 dB
phase margin    : 83.10 deg  (at fc = 90497 Hz)
gain margin     : 32.88 dB   (at f  = 1.732 MHz)
```

## Verification

`verify_stb.py` — 5 checks: the phase/gain margin match the **closed-form** loop
gain of an ideal-output loop; a *loaded* break gives the **same** margins as a
clean break in the same loop (proving the current injection corrects the loading —
a single injection would not); a higher-gain design's **reduced** phase margin is
tracked and matches analytics; the complex `loopgain` vector is stored; and an
unknown probe is reported cleanly. It is a front-end command, independent of the
linear solver, so it runs once.

## Running

```sh
python3 verify_stb.py
ngspice -b stb_demo.cir
```
