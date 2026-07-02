# `timer()` example (version9)

Self-contained correctness example for OpenVAF's new **`@(timer(t0, period))`**
event-control support (Enhancement-8, Feature A), covering **DC**, **AC**,
and **transient** analysis. Uses the **version9** toolchain:

- compiler : `../OpenVAF-master/target/release/openvaf-r` (built with `--features openvaf-driver/llvm18`)
- simulator: `../ngspice-46/build/src/ngspice` (locally built, OSDI-capable — not the system-wide `ngspice`)

See `../Enhancement-8.md` for the full implementation writeup, and
`../cross_examples/README.md` for the shared "known limitations" that also
apply to `timer`.

## The model

`timer_demo.va`: `@(timer(t0, period)) count = count + 1.0;` — fires once at
`t0`, then periodically every `period` seconds after, incrementing a
persistent tick counter exposed on `V(out)`. Also reports each firing via
`$strobe` (observable in ngspice's console output).

## Running

```sh
../OpenVAF-master/target/release/openvaf-r timer_demo.va -o timer_demo.osdi
../ngspice-46/build/src/ngspice -b dc_sim_timer.cir
../ngspice-46/build/src/ngspice -b ac_sim_timer.cir
../ngspice-46/build/src/ngspice -b tran_timer.cir
python3 plot_timer.py   # -> timer_dc.png, timer_ac.png, timer_tran.png
```

## DC / AC: documented non-behavior

`timer_demo.va` has no voltage input port (it's a purely time-triggered
generator, `V(out) <+ count;`) — so unlike `above()`/`cross()`'s demos,
there's no natural node to sweep:

- **DC** (`dc_sim_timer.cir`) sweeps `TEMP` instead of a voltage. A DC
  operating-point solve has no notion of elapsed time, so `t0` is never
  reached — `timer_dc.png` shows `V(out) = count` pinned at exactly `0`
  from -40°C to 125°C.
- **AC** (`ac_sim_timer.cir`) injects a probe current directly into `out`
  and measures its response. The AC operating point is likewise a single
  fixed (t=0) bias, so `count` stays `0` and `V(out) <+ count` behaves as a
  stiff (zero small-signal impedance) contribution — `timer_ac.png` shows
  the response pinned at (numerically) zero from 1Hz to 1MHz.

Both are "documented non-behavior" checks, same convention as
`cross_examples/README.md`'s DC/AC. `timer()`'s actual (real, periodic,
persistent-counter) behavior only shows up in the transient plot.

## Transient: the real event-detection behavior

`timer_tran.png` shows `V(out) = count` as a staircase, stepping up by 1
exactly at `t0` and every `period` after.

## Results (raw firing data)

`tran_timer.cir` sets `t0 = 2ms`, `period = 1ms`, over a 7ms transient sweep.
Expected: first firing at t=2ms, then every 1ms after (2,3,4,5,6ms), plus
whatever the last accepted timepoint near t=7ms happens to be:

```
timer fired at t=0.0020028 count=1
timer fired at t=0.0030028 count=2
timer fired at t=0.0040028 count=3
timer fired at t=0.0050028 count=4
timer fired at t=0.0060028 count=5
timer fired at t=0.007 count=6
```

Matches exactly (first firing at t0, then period-spaced, `count` incrementing
by exactly 1 per firing — persistent state working correctly).

## Compile-time verification (`--dump-unopt-mir`)

`--dump-unopt-mir` confirms `timer`'s scheduling logic compiles to a real,
non-dead-code conditional branch:
```
v21 = fge v20, v19    // fired = Abstime >= next_fire_time
v22 = fadd v19, v16   // rescheduled = next_fire_time + period
br v21, block5, block6
```

## Known limitations

See `../cross_examples/README.md` — the "no persistent state inside the
event body" compiler bug that used to block this example's tick counter has
been fixed (see `../Enhancement-8.md` §2, limitation 1); the
"eval-granularity, not exact-time-forced" detection design still applies.
The "first `.model`-card override ignored" ngspice bug that used to affect
`t0` here has also been fixed (see `../Enhancement-8.md` §2, limitation 3) —
no workaround needed anymore.
