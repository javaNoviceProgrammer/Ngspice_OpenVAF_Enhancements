# Enhancement-614: a never-given statistical parameter follows the parameter its default reads

**Scope:** `src/osdi/osdisetup.c` — the `.option osdimc` nominal table gets a `stale`
flag; `OSDImcNoteUserWrite()` (the hook every `alter`/`altermod` reaches through
`doset_user()`) marks the never-given statistical parameters of the written device
stale and clears their given flag, `osdimc_capture()` re-reads a stale entry after the
model's setup has re-resolved its default, `OSDImcNewRun()` defers the trial's draws to
that capture, and the option-off restore skips a stale entry; the same hook marks a
parameter the user wrote as given, so the restore keeps the user's value.
`src/frontend/spiceif.c` — `doset_user()` reports integer writes to the hook as well.
`examples/osdimc_examples/` grows 29 → 36 checks per solver with a new `smcdep.va`;
handbook [§3.6](../docs/handbook/03-ngspice-workflows.md), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §7, the
suite README. **ngspice only.** F2 and F3 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`osdimc_examples`](../examples/osdimc_examples/) 36 of 36 per solver, both
solvers; the ten suites that exercise `osdimc` green; full sweep 505 of 505.

## What was wrong

```verilog
module leaf(p, n);  ...  (* std=25.0 *) parameter real r = 1000.0 from (0:inf);
module top(p, n);   ...  parameter real rl = 1000.0;
                         leaf #(.r(rl)) c1(p, m);   leaf c2(m, n);
```
```spice
.option osdimc mcseed=1
N1 a 0 tm
.model tm top rl=1k
.control
op                                   ; baseline
op
print @tm[rl] @tm[c1__r]             ; 1000     998.21   (c1 draws around 1000 -- fine)
altermod tm rl=500
op
print @tm[rl] @tm[c1__r]             ; 500      1011.62  <- 1000 + 11.62: the old nominal
unset osdimc
op
print @tm[rl] @tm[c1__r]             ; 500      500      (the binding holds when nothing draws)
.endc
```

The flattened child parameter `c1__r` is never on the model card: the model's own setup
resolves it from its default expression, which is the parent's `rl`. The nominal table
captured that value at the **first** setup — 1000 — and never looked again, because
the only thing that ever changed a captured nominal was a user write to *that*
parameter (the E-531/F1 recentre). `altermod tm rl=500` recentred `rl`, which has no
statistics, and left `c1__r` drawing around 1000: the device ran at 1011 Ω where 500
was set, with no message. The same for a plain `parameter real rb = rl`, for an
instance default that reads an instance parameter (`dr = 100 * mult` after
`alter @n1[mult]=3`), and for a default that reads an integer (`rn = 100 * nseg` after
`altermod dm nseg=4` — the hook was not even called for an integer write). A
`montecarlo` loop was right all along: its internal re-source drops the table and the
nominals are re-resolved; only a plain run after the write was wrong.

**F3**, the same seam from the other side: `alter @n1[dr]=50` of a parameter the deck
never gave recentred it (draws around 50), but `unset osdimc` wrote 0 back. The E-555
restore clears the given flag of a parameter the *deck* never gave so the model's setup
puts its default back — right for a draw, wrong for a value the user typed, because the
table still said "never given".

## What changed

- **A user write marks the never-given statistical parameters of its device stale.**
  `OSDImcNoteUserWrite()` — after the recentre of the written parameter, if it is
  statistical — walks the table for the model's own entries and, for a model write, for
  those of each of its instances (an instance write, for that instance's): every entry
  whose parameter the deck never gave is marked `stale` and its given flag cleared
  through the E-555 entry point, so the model's next setup re-resolves the default. The
  parameter just written is not stale: it is given now.
- **The next run re-reads a stale nominal before it draws.** `OSDImcNewRun()` treats a
  table with a stale entry as it treats an empty one — the draws are pending — and
  `OSDIsetup` applies them after its setup loops and `osdimc_capture()` have run;
  the capture, which used to insert only missing entries, now also refreshes a stale
  one (its nominal and given flag) from the value the setup resolved. The draw itself is
  unchanged — a pure function of (seed, trial, owner, id) — so `c1__r` moves from
  `1000 + δ` to `500 + δ` with the same δ, and a deck that never writes a parameter
  behaves bit-for-bit as before.
- **The option-off restore** skips a stale entry (the setup re-resolves it; writing the
  stale nominal first was pointless) and, for a parameter the user gave, restores the
  user's value: the hook sets the entry's given flag when a user writes a statistical
  parameter, so the E-555 clear no longer applies to it (F3).
- **Integer writes reach the hook** (`doset_user()`): they recentre nothing — a
  statistical parameter is real — but a real default may read them.

```
altermod tm rl=500
op
print @tm[rl] @tm[c1__r]             ; 500      511.62   (500 + the same 11.62)
```

What does not change: a machine write (a `.dc` parameter sweep, `sweep`'s points and
restores, `sens`, an optimizer's candidates) still neither recentres nor re-resolves —
the E-537 bracket returns before any of this; a `montecarlo` loop's per-sample re-source
still re-resolves everything as it did; the E-555 gate (a never-given parameter the
model tests with `$param_given` is not drawn) still holds after a re-resolution, and
`altermod` of such a parameter — "or altermod it, to vary it", as the note says — now
does make it given.

## Verification

| check | result |
|---|---|
| `leaf #(.r(rl)) c1`, `altermod tm rl=500` | `c1__r` draws around 500 (`c2__r` still around 1000); `i(v1)` is the current of the drawn values; `unset osdimc` restores 500 and 1000 exactly |
| trial 3's δ with the nominal at 500 vs at 1000 | identical (to the printed 10 digits) |
| `rb = rl` after `altermod dm rl=500`; `rn = 100*nseg` after the integer `altermod dm nseg=4`; the instance `dr = 100*mult` after `alter @n1[mult]=3` | each draws around its new default; off restores 500 / 400 / 300 |
| `altermod tm c1__r=700` then `altermod tm rl=300` | `c1__r` keeps drawing around 700 — user-given, not re-resolved; off restores 700 |
| F3: `alter @n1[dr]=50` of a never-given parameter, `unset osdimc` | 50 restored, not 0 |
| `altermod tm rl=2k` while the option is off | 2000 off; the baseline 2000 when set again; then draws around 2000 |
| the 29 existing checks; `paramgiven`, `mcpolicy`, `osdidist`, `wcd`, `huntfix`, `dcxsweep`, `constguard`, `autoopts`, `savemc` | unchanged |
| `osdimc_examples` | 36 / 36, both solvers |
| full sweep | 505 of 505 |
