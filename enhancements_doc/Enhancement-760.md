# Enhancement-760: the compiled load path's fixed per-iteration bookkeeping is hoisted — one compiled instance cost 0.6 µs of load per Newton iteration against 0.08 µs built in, none of it model evaluation (a 64-slot walk freeing NULL pointers, three option lookups by name, a version string parsed, a 64-slot file walk); it is 0.11 µs now, 1.3× the built-in resistor

**Scope:** O1 of the 2026-09-28 speed, robustness and correctness hunt, the remainder of
its F1 (E-758). ngspice: `osdi/osdicallbacks.c` (the repeated-message ring keeps a count
of live slots and its per-iteration summary returns at once when none is held),
`osdi/osdiload.c` (`osdi_options_refresh()` re-reads `noosdilim`, `osdilim_verbose` and
`scale` only when the variable state stamp changes; the simulator version is parsed
once), `frontend/variable.c` and `include/ngspice/cpextern.h` (`struct cp_var_state` and
`cp_var_state_refresh()`: a generation counter advanced by every `set` and `unset`, plus
the current circuit, the current plot and the heads of the four lists `cp_getvar` walks).
Compiler runtime: `osdi/stdlib.c` (`osdi_io_iter_begin` returns at once when no stream is
readable and nothing is deferred; `osdi_readable_any`, set where a stream becomes
readable and recomputed by the accepted-point flush). Nothing a model or a deck can
observe changes: a `set` or `.option` still reaches the next run, the repeated-message
summary still prints, file reads still replay across a rejected iteration.

**Suites:** `lrmkernel` 53 of 53 per solver (52 of 53 on the E-759 toolchain: the ratio
check of the new section [7]), `osdilimit`, `display`, `rtdomain`, `fileio`, `stringio`,
`lrmio`, `lrmsysio`, `fgetc`, `ungetc`, `scanbody`, `alias`, `lrmvoice`, `sweeptemp` and
`mcpolicy` unchanged; the full sweep 534 of 534.

## What was left after E-758

E-758 removed the `getcwd()` from every load call and left a fixed cost of about 0.6 µs
per Newton iteration for one compiled instance, against 0.08 µs for one built-in resistor
in the same circuit. A `sample` profile of a one-instance transient of 1.2 M iterations
(the hunt's `prof` deck: a compiled 1 kΩ into a built-in 1 pF, driven by a 10 MHz pulse
at a 0.1 ns step) put the OSDIload samples almost entirely outside model evaluation:

| where | share of OSDIload samples | what it did per iteration |
|---|---|---|
| `osdi_display_repeat_summary` | about 60 % | walked the 64-slot ring of coalesced messages and called `tfree` on two NULL pointers per slot: 128 calls that did nothing |
| `cp_getvar` × 3 | about 25 % | looked up `noosdilim`, `osdilim_verbose` and `scale` by name: each a `cp_usrvar` probe plus four list walks with `strcmp` |
| `strtod(PACKAGE_VERSION)` | about 3 % | parsed the version string for `$simparam("simulatorVersion")` |
| `osdi_io_iter_begin` (runtime) | about 9 % | walked the 64 file slots to rewind readable streams, with none open |

The repeated-message summary (E-543's F4) has to run at the start of every Newton
iteration, because that is when a run of coalesced messages ends; the walk it did to find
out that nothing was coalesced was the cost. The option lookups were per call because
nothing told the load path when a variable had changed. The version parse was an
oversight. The file walk was the runtime's, compiled into every `.osdi`.

## What changed

- **A live-slot count on the repeat ring.** `rep_live` counts the slots holding a text;
  the summary walks the ring only while it is positive, and a slot with no text returns
  from `osdi_repeat_summarize` before freeing anything. Coalescing itself is untouched:
  the `display` suite's "was repeated 3 more times" lines still print.
- **A variable state stamp.** `cp_var_state_refresh()` in `variable.c` compares a caller's
  stamp against the current generation (advanced by every `cp_vset` and `cp_remvar`), the
  current circuit and plot, and the heads of the four lists `cp_getvar` consults
  (`variables`, the plot's environment, the circuit's option variables, and the user
  variables come through the generation). The load path re-reads its three options only
  when the stamp moved, which happens between runs and never inside an analysis. A list
  rebuilt behind `cp_vset`'s back (E-756's `reset` restoring the circuit's options)
  changes a head pointer and is caught the same way.
- **The version parsed once.** A static, filled on the first `get_simparams` call.
- **The runtime's file hook returns early.** `osdi_readable_any` is set wherever a slot
  becomes readable (the four open paths) and recomputed by `osdi_io_flush` at each
  accepted point; `osdi_io_iter_begin` returns at once when it is clear and nothing is
  deferred. A model that never opens a file, which is nearly all of them, pays a load and
  a compare. An `.osdi` compiled before this keeps its old hook and works as before.

## Measured

| deck | E-759 | now |
|---|---|---|
| one compiled resistor, 1.2 M iterations: load time | 0.767 s (0.63 µs per iteration) | 0.136 s (0.11 µs) |
| the same, total transient time | 2.12 s | 1.32 s |
| the same with a built-in resistor | 1.20 s (load 0.092 s) | unchanged |
| the E-752 10 Gb/s PRBS through a compiled 50 Ω / 0.4 pF, 3000 bits | 0.28 s (E-757: 3.07 s) | 0.155 s |
| the 500 MHz switching run of the F2 hunt, 1 ns step | 0.13 s (E-757: 1.06 s) | 0.073 s |
| lrmkernel [7]: compiled against built-in load per iteration, 20 000 iterations | 0.57–0.66 µs against 0.12 µs (5×) | 0.156 µs against 0.122 µs (1.3×) |

The remaining difference to the built-in resistor is the model evaluation itself and the
per-instance OSDI bookkeeping (14–20 ns per instance-iteration, O1's second number),
which is proportional work, not a floor.

## Checks

`lrmkernel` section [7], with `optprobe.va` (a resistor whose initial step prints
`$simparam("scale")`):

| check | result |
|---|---|
| `op`, `set scale=2.5`, `op`, `unset scale`, `op` | the probe reads 1, 2.5, 1: a `set` between runs reaches the next run |
| a deck with `.option scale=4` | the first run reads 4 (the circuit's own list) |
| `op`, `set osdilim_verbose`, `op` | the limiter decision is reported after the `set`, not before |
| one compiled instance against one built-in resistor over 20 000 iterations | load per iteration under 4× the built-in (was 5×) |

## What the profile also showed

The same profile put 48 % of the compiled transient — and the same share of the built-in
one — in `CKTdump → OUTpData`: a free-memory query (`host_statistics` and a Mach port
trap on macOS) and a `clock()` (a `getrusage` call) on every accepted point, plus a
`cp_getvar("no_mem_check")`. About 1 µs per point, paid by every transient regardless of
its devices. That is the hunt page's F3, not part of this enhancement.
