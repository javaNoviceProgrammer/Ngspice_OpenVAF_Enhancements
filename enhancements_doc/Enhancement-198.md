# Enhancement-198 — `stb` stability / loop-gain analysis

A new front-end command that measures a feedback loop's small-signal **loop gain**
`T(f)` and reports its **phase margin** and **gain margin** — the everyday
stability check for op-amps, regulators, LDOs, PLLs and any other feedback design.
ngspice had no built-in for this; you had to hand-roll a `.control` script. `stb`
is the one-command equivalent of Spectre's `stb` analysis (the Middlebrook–Tian
injection-probe method).

## Usage

```
stb <Vprobe> <Iprobe> (dec|oct|lin <N> <fstart> <fstop>)
```

Mark the loop break — a single wire carrying the feedback signal — with a **probe
pair** between the driving node `A` and the loaded node `B`. Both are quiescent, so
the DC operating point is untouched:

```
Vstb A B dc 0 ac 0      series 0 V source  (+node = driver A, -node = load B)
Istb 0 B dc 0 ac 0      shunt 0 A source   (ground -> load node B)
```

```
stb Vstb Istb dec 20 1 100meg
```

## Why double injection

Break a loop and inject a single test signal, and the **loading** at the break
corrupts the measurement: a series *voltage* injection reads the true loop gain
only if the break is from a zero-impedance source into an infinite-impedance load.
Middlebrook and Tian's **double injection** cancels the loading error by combining
a voltage and a current injection. `stb` runs two AC sweeps, altering the probe AC
magnitudes:

```
voltage injection (Vstb ac=1, Istb ac=0):   Tv = -v(A)/v(B)
current injection (Vstb ac=0, Istb ac=1):   Ti = -i(Vstb)/(i(Vstb) + 1)
loop gain            T = (Tv·Ti - 1) / (Tv + Ti + 2)
```

The combined `T` is **independent of where in the loop the probe sits** — the
defining property a single injection lacks, and the example verifies it directly
(a loaded break gives the same margins as a clean break in the same loop).

**A singularity-free form.** In the common clean-break case the load impedance is
high, so `i(Vstb) -> -1` (all the injected current returns through the shorted
voltage probe) and `Ti -> inf`. Computing `Ti = -a/(a+1)` then divides by zero.
`stb` substitutes `Ti` and clears the `(a+1)` denominator, evaluating the exact
equivalent

```
T = -(Tv·a + a + 1) / (Tv·a + Tv + a + 2),   a = i(Vstb),
```

which stays finite at `a = -1`, where it reduces cleanly to `T = Tv`.

## Output

The complex loop gain is stored as the vector **`loopgain`** (vs `frequency`) in a
new `stb` plot, and the margins are printed:

```
Stability (loop gain via Tian double injection at vstb):
  DC loop gain    : 79.13 dB
  phase margin    : 83.10 deg  (at fc = 90497 Hz)
  gain margin     : 32.88 dB   (at f  = 1.732e+06 Hz)
```

```
plot db(loopgain)                 magnitude (dB)
plot 180/PI*cph(loopgain)         phase (deg, unwrapped)
```

The phase margin is `180 + angle(T)` at the first `|T| = 1` (0 dB) crossing; the
gain margin is `-|T|_dB` at the first `angle(T) = -180 deg` crossing. Both
crossovers are log-interpolated on an unwrapped phase.

## Implementation

`frontend/com_stb.c` (registered in `commands.c`, declared in `com_commands.h`).
The probe's two terminal node names are recovered from the voltage source via
`CKTinst2Node`; the two injections are driven by dispatching `alter` and `ac`
through the command table (as `com_optimize`/`com_sweep` do), and the resulting
complex vectors (`v(A)`, `v(B)`, `Vstb#branch`, `frequency`) are read with
`ft_evaluate`. It reuses the AC analysis, so it works under both the Sparse and KLU
solvers.

## Verification

[`examples/stb_examples/verify_stb.py`](../examples/stb_examples/verify_stb.py) —
5 checks: the phase and gain margin match the **closed-form** loop gain of an
ideal-output op-amp loop; a **loaded** break (finite op-amp output impedance) gives
the **same** margins as a clean high-impedance break in the same loop (proving the
current injection corrects the loading — a single voltage injection would be ~10 %
off and diverge past crossover); a higher-gain design's **reduced** phase margin is
tracked and matches analytics; the complex `loopgain` vector is stored; and an
unknown probe source is reported cleanly. Front-end command, independent of the
linear solver, so it runs once. Full example regression: 162/162.
