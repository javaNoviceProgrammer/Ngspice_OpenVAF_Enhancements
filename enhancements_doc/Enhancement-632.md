# Enhancement-632: the loop commands stop on a circuit built against a reloaded object

**Scope:** `src/frontend/spiceif.c` / `spiceif.h` — `if_refuse_stale(what)` says the E-560
message (prefixed with the asking command) and returns TRUE on a circuit `osdi -f` has
left behind; `if_run` uses it and returns 3 — a run that did *not start* — where it
returned 1, an interrupt. `src/frontend/com_sweep.c` — `montecarlo`, `highsigma`, `sweep`
and `wcd` refuse up front through it. `examples/osdireload_examples/` grows 10 → 13
checks. **ngspice only.** F20 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`osdireload_examples`](../examples/osdireload_examples/) 13 of 13; `mcpolicy`,
`sweepguard`, `wcd`, `highsigma`, `lhs` green; full sweep 506 of 506.

## What was wrong

After `osdi -f` swaps a registered object, a circuit built against the previous one is
marked and E-560's `if_run` refuses to run it ("… `reset` (or re-`source`) the deck to
rebuild it against the reloaded object"), because the new object's code may not fit the
old layout's data. A plain `op`, `dc`, `tran` were refused. But:

- `montecarlo` and `highsigma` ran every sample — on the reset path a `reset` per sample
  rebuilt the circuit (legitimately, but past the note that said "refused until then"),
  and on the fast path, which resets nothing, the samples were pushed into the stale
  circuit and run through refusals that nothing noticed;
- `sweep` had each point's inner `op` refused and still reported "3 points into plot
  'sweep1'" — the pushed values read back as if run;
- `wcd` turned the refusals into "the metric does not respond to any statistical
  parameter (zero gradient)".

The refusal returned 1 from `if_run`, which `dosim()` takes for an *interrupt*: "op
simulation interrupted", `sim_status` left clean — so every loop that asks
`sw_run_failed()` after its inner run was told the run was fine.

## What changed

- **The refusal is a run that did not start.** `if_run` returns 3 for it: "op simulation
  not started", `sim_status` set — so any command that runs analyses in a loop (`optimize`,
  `loadpull`, `aging`, `emir` included) sees a failed run instead of a phantom success.
- **The four loop commands refuse up front**, with the same message and their own name:
  `Error: sweep: circuit "…" was built against "m.osdi" before `osdi -f` reloaded it, and
  cannot run on the new object's code; `reset` (or re-`source`) the deck …`. Nothing is
  drawn, pushed or recorded. After the `reset` they run on the rebuilt circuit.

```
ngspice -> osdi -f m.osdi
Note(osdi): circuit "* reload" was built against the previous "m.osdi" and keeps its data; `reset` (or re-`source`) it before its next run, which is refused until then
ngspice -> montecarlo 3 -seed 1 -analysis op -expr rr=@rm[r]
Error: montecarlo: circuit "* reload" was built against "m.osdi" before `osdi -f` reloaded it, and cannot run on the new object's code; `reset` (or re-`source`) the deck to rebuild it against the reloaded object
ngspice -> reset
ngspice -> montecarlo 2 -seed 1 -analysis op -expr rr=@rm[r]
montecarlo: 2 random samples, analysis 'op', no yield (no -spec), seed 1
```

## Verification

| check | result |
|---|---|
| `osdi -f` then `montecarlo`, `highsigma`, `sweep`, `wcd` | each refused up front, in that order, with its name in the message; no samples, no "points into plot", no "zero gradient", no `sweep1` plot |
| the plain `op` | "op simulation not started", not "interrupted" |
| `reset`, then `montecarlo 2` | runs: two samples at the 2 kΩ object's −0.5 mA |
| the 10 existing checks (E-229's reload, E-560's F16 refusal, E-629's paths) | unchanged |
| `osdireload_examples` | 13 / 13 |
| full sweep | 506 of 506 |
