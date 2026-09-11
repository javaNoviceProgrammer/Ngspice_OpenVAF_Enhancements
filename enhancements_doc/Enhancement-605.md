# Enhancement-605: a `.probe` card in a deck that opens with a `.control` block

**Scope:** `src/frontend/inpc_probe.c` (`probe_head`: the head insertions placed past
a leading `.control` block; `deck` no longer moved onto the inserted card),
`examples/probeblock_examples/` (new, 5 checks per solver). **ngspice only.** Finding
N3 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)),
a stock ngspice defect that every OSDI deck with a `.probe` met.

**Suites:** [`probeblock_examples`](../examples/probeblock_examples/) 5 of 5 per
solver, both solvers; `probeshort` and the other `.probe` suites unchanged; full sweep
502 of 502 (one sweep, Enhancements 604–608 folded together).

## What was wrong

```
.control
pre_osdi rc.osdi
.endc
...
.probe v(out)
```

```
.save: no such command available in ngspice
```

`inp_probe` adds a `.save all` card when the deck has no save of its own, and
inserted it right after the first card after the title. A deck that opens with a
`.control` block — every OSDI deck does, for `pre_osdi` — got the card **inside** that
block, where it ran as a command and was lost; the probe still worked through the
vectors the probes themselves register, so the line read as a spurious error. The
`.save` line the probes generate for their vectors, and a differential probe's source,
went to the same place. And `deck` was moved onto the inserted card, so the walks that
follow started one card late.

## What changed

- `probe_head(deck)`: a line meant for the head of the deck goes after the `.endc` of
  a `.control` block that opens it, and after the first card otherwise — at all three
  head-insertion sites.
- `deck` stays on the first card.

## Verification

| check | result |
|---|---|
| a leading `.control` block, then `.probe v(out)` | no ".save: no such command"; 0.5 V printed |
| ...with `.probe i(r1) v(out)` | `r1#branch` 0.5 mA |
| an OSDI deck (`pre_osdi` block first) with `.probe alli` | quiet, complete |
| no leading block, the probed device on the deck's first line | unchanged |
| the deck's own `.save` beside a `.probe`, leading block | the generated `.save` line past the block too |

Full sweep 502 of 502 on both solvers.
