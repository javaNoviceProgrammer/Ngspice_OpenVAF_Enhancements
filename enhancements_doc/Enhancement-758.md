# Enhancement-758: the compiled load path no longer reads the working directory on every Newton iteration — `$simparam$str("cwd")` was refreshed with a `getcwd()` per load call, ~12 µs on macOS whatever the circuit size, 89 % of a long single-instance transient and 10× on a 10 Gb/s PRBS through a compiled RC; it is cached now and re-read after `cd`

**Scope:** F1 of the 2026-09-28 speed, robustness and correctness hunt. ngspice only:
`osdi/osdiload.c` (`osdi_cwd()` caches; `OSDIcwdChanged()` invalidates),
`include/ngspice/osdiitf.h` (its declaration) and `frontend/com_chdir.c` (the `cd`
command, the one `chdir()` in the tree, invalidates after a successful change). Nothing a
model can observe changes: the answer to `$simparam$str("cwd")` is the same string, and
it follows a `cd` between runs as before.

**Suites:** `lrmkernel` 48 of 48 per solver (47 of 48 on the E-757 binary: the timing
check), `rangeguard` 75 of 75, `osdilimit`, `hunt12diag` and `instknobs` unchanged; the
full sweep 534 of 534.

## What was wrong

A 300-stage compiled RC ladder loaded 7.7× slower than the built-in one for identical
iteration and timepoint counts. The cost was not per instance: one compiled resistor
cost 12.08 µs of load per Newton iteration, a hundred of them 13.6 µs, a hundred over a
hundred model cards 13.7 µs, one built-in resistor 0.06 µs. A `sample` profile of a
single-instance transient of 1 215 614 iterations (14.42 s, of which 12.81 s load) put
2303 of 3394 samples under `__open_nocancel`, with `stat`, `fstat`, `fcntl` and `close`
behind it, all on one path:

```
OSDIload -> get_simparams -> __private_getcwd -> __getcwd -> open$NOCANCEL
```

`get_simparams()` fills the `$simparam$str` table on every load call, and the `"cwd"`
entry the kernel audit (E-527) added was "refreshed per query" through `getcwd()`; on
macOS that opens and stats the directory chain. Every deck that loads a compiled model
paid it, whether or not any model ever asked for `cwd`, and `OSDIload` runs once per
Newton iteration for all compiled models together, so the cost was a floor under every
iteration: a small circuit was dominated by it, a large one hid it behind per-instance
work.

Measured on the E-757 binary: the E-752 10 Gb/s PRBS7 stream, 3000 bits, through a
compiled 50 Ω / 0.4 pF channel took 3.07 s (2.86 s load over 138 122 iterations) where
the built-in RC took 0.14 s over the same 69 062 timepoints; a 500 MHz switching run,
1.06 s against 0.10 s.

## What changed

`osdi_cwd()` keeps the string and re-reads it only when told it is stale. The process
directory changes through the `cd` command alone (`com_chdir.c` holds the only
`chdir()` call in the tree; a `shell` command runs in a child process), so a successful
`cd` calls `OSDIcwdChanged()`, and the next load call reads the new directory once.

| run | E-757 | now |
|---|---|---|
| one compiled resistor, load per Newton iteration | 12.08 µs | 0.63 µs |
| a hundred compiled resistors, per iteration | 13.6 µs | 2.04 µs |
| PRBS7 10 Gb/s through a compiled RC, 3000 bits | 3.07 s | 0.28 s (built-in RC 0.14 s) |
| a compiled switch at 500 MHz for 2 µs | 1.06 s | 0.15 s (built-in `sw` 0.10 s) |

The remaining ~0.6 µs per iteration is the layer's other per-iteration work (the
display and file-output iteration hooks, two `cp_getvar` lookups for `noosdilim` and
`osdilim_verbose`, the simparam table fill), about 0.1 % of what was there.

## Verification

The `lrmkernel` suite (the kernel audit's) gains a model that strobes
`$simparam$str("cwd")` at every analysis start: the first `op` reports the suite's own
directory, an `op` after `cd <tmpdir>` reports the new one (the invalidation), and a
one-instance transient of 4066 iterations loads in under 6 µs per iteration (1.0 µs
measured; 12.6 and 13.6 µs on the E-757 binary under the two solvers). `rangeguard`,
which pins the served `$simparam$str` names, is unchanged.

## What this does not do

The per-instance cost of a compiled model (about 20 ns for a trivial one against 9 ns
built in; 1.0 µs against 0.54 µs for BSIM4) and the per-iteration hooks are as they were;
the hunt's O1 and O2 record them. Linux pays a cheaper `getcwd()` (one syscall) and gains
less. A directory change made by anything other than `cd` — there is no such thing in
ngspice today — would not be seen until the next `cd`.
