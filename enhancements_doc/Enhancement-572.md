# Enhancement-572: a dig into `.option autobus`, `autoadapt`, `saveused` and `automc` — a one-bit bus binds its bit, the deck's output cards are saved, a split node and a reused bus base are named, a bad seed is said

**Scope:** a probe battery over the four options (some fifty decks, both solvers), and
what it found. `src/spicelib/parser/inp2n.c` (autobus, autoadapt), `inppas3.c`,
`src/frontend/dotcards.c` (saveused), `inp.c`, `spiceif.c` (the known-option list),
`src/osdi/osdisetup.c` (the `mcseed` reader), `src/include/ngspice/inpdefs.h`.
**ngspice only.**

**Suites:** new [`autoopts_examples`](../examples/autoopts_examples/) (27 checks per
solver, both solvers); `autobus`, `autoadapt`, `busmixed`, `busname`, `saveused`,
`osdimc`, `ctrlnode`, `silentports`, `groundports`, `portconnected`, `floatnode` pass;
full sweep 471 of 471 on both solvers.

## The survey

The four options were read as designed, then pushed where their own suites had not
gone: unusual port shapes, parameters after the model name, a bus base reused as a
node, one-bit and descending buses, subcircuit formals, the deck's dot cards, `sweep`
and `montecarlo` under the option, every spelling of on and off, garbage seeds. The two
solvers agreed on every value throughout; what follows is what the options themselves
did.

| probe | before | now |
|---|---|---|
| `autobus`: `N1 a b bus1` for `inout [0:0] a` | v(b) = 0 — the token `a` bound as the node `a`, not `a[0]` | 0.5, as the explicit line |
| `autobus`: `Rx a 0 1k` beside `N1 a b busdev` | silent; the resistor on a node nothing else touched | named, with `a[0]` offered |
| `saveused`: `.meas tran vmax max v(out)` beside a block printing only v(in) | "no such vector as 'v(out)'" | the measure works, `out` kept |
| `saveused`: `.print tran v(out)`, `.four 1k v(out)` | an empty table; "no such vector" | filled; the Fourier line |
| `autoadapt`: `print v(b[0])` after `b` was split | "vector b is not available", the line dropped | the split named, the line quoted, `b_f`/`b_r` offered |
| `automc`: `mcseed=1.5`, `mcseed=abc` | seed 1, silently | seed 1, said |
| `nosaveused`, `noautobus`, `noautoadapt`, `noautomc`, `noosdimc` | honoured, reported "unknown option" | registered |

And what held, pinned as documented behaviour: a bus declared `[3:0]` expands to the
terminals the compiler names, which are `a[0]` … `a[3]` in that order whatever the
declaration direction, so a hand-written line in declaration order is the one that is
wrong; parameters after the model name survive the expansion; one token for two bus
ports of different width shares the low bits; a one-bit bus through a subcircuit formal
binds; `autoadapt` refuses a `.adapt` name that selects nothing, works under
`autobus=kicad`, and its `_f`/`_r` sides come from the port index; `saveused` leaves
`.probe` and `.save` alone, collects `i(v1)`, `v(x1.mid)`, expression arguments and
`if` conditions, and does not disturb `sweep -output` or `montecarlo -spec`. Under
`automc`, every run-class command is one trial: a whole `sweep` is one trial (all its
points at one draw, the next command a fresh one), an `op` and a following `tran` in one
block are two trials, `montecarlo` draws every sample (the warm and cold loops alike),
the off-words `osdimc=0`, `automc=no` and `noosdimc` leave every parameter at its
nominal, and a seed of 0, a negative seed and no seed each give a deterministic
ensemble.

## What was wrong

**A one-bit bus port was never expanded.** Enhancement-444 expands a line whose token
count equals the *port* count and is below the *terminal* count; that is what tells the
shorthand from a fully written line. A port `inout [0:0] a` is one terminal, so a model
of one such port and a scalar has two ports and two terminals, and `N1 a b bus1` is
neither shorter nor longer than its terminal list. It bound positionally: `a` onto the
terminal `a[0]` as the node `a` — a node nothing else in the deck touches, since the
deck drives `a[0]` — and the device sat on a floating node and read 0 V, with nothing
said. Every other width expanded.

**A bus base reused as a plain node.** `N1 a b busdev` makes `a[0]` … `a[4]`; a
`Rx a 0 1k` on the same deck connects to a node called `a`, which is none of them. That
is by design — a bus and a scalar are different things — but nothing said so, and the
resistor sat on a node nothing else touched. Under Enhancement-569 it is at least held
and named as floating, which names the symptom.

**`saveused` read only the control block.** Its scan collects every vector the block
mentions and saves those alone; the deck's own output cards — `.meas`, `.print`,
`.plot`, `.four` — read vectors after the block has run and were never looked at. A
`.meas tran vmax max v(out)` beside a control block that printed v(in) failed with "no
such vector as 'v(out)'", and a `.print tran v(out)` printed an empty table, under an
option whose one promise (Enhancement-469) is that the deck still works.

**A split node named in the control block.** `autoadapt` renames the shared bus node
`b` into `b_f` and `b_r`; a `print v(b[0])` written for the deck as the author sees it
then fails as "vector b is not available" — the `[0]` read as vector indexing — and the
whole print line is dropped, naming neither the split nor the cure. Enhancement-463
already refuses a *device* that uses a bit of the split bus; a control-block reference is
not a device and was invisible.

**A bad seed was silent.** `mcseed` was probed as an integer at three sites; a real
(`mcseed=1.5`, published as such) coerced to 1 since Enhancement-467 and a string
(`mcseed=abc`) failed the probe, so both ran the ensemble of seed 1 — indistinguishable
from the one asked for.

**The OFF spellings drew "unknown option".** Enhancement-469 documents `.option
nosaveused` and Enhancement-466 `.option noautoadapt` as the off-words, and they are
honoured; none of the five `no` spellings was in the known-option list, so each printed
the warning Enhancement-511 removed for `osdicache` and `seedinfo`.

## What changed

- `INP2N` adds a branch for a line whose token count equals the terminal count under
  `.option autobus`: a bracket-free token on a one-bit bus port takes the model's own
  index (`a` → `a[0]`, `a_0_` under KiCad); an already-indexed token and ground are left
  as written, so a fully spelled line is unaffected, as E-444 promises.
- Every shorthand expansion notes its base; `INPreportBusBases()`, called from pass 3
  beside Enhancement-492's control-node report, warns once per base that the deck also
  uses as a plain node, naming the instance, the bit count and the bit spelling to write.
- `ft_saveused()` also scans the deck's `.meas`, `.print`, `.plot` and `.four` cards for
  the `v()`, `i()` and `@dev[param]` forms. They add to the set and never decide whether
  the option acts: a deck whose only output is a dot card is left alone, as before.
- `autoadapt` notes each split; `INPadaptCheckControls()`, called from `inp.c` right after
  `ft_saveused()`, warns when the control block or a dot card names a bit of a split node
  — `b[..]` or the KiCad `b_0` — quoting the line and offering `b_f` / `b_r`. Silent when
  the block refers to the new names.
- `osdimc_seed()` is the one reader of `mcseed`: a real is truncated and said, a string
  refused and said, each once; the three sites call it.
- The five `no` spellings are registered.

## Verification

| check | result |
|---|---|
| `N1 a b bus1` for a one-bit port; ground on it; through a subcircuit formal | 0.5 = the explicit line (was 0); 0; 0.5 — both solvers |
| `Rx a 0 1k` beside `N1 a b busdev`; the same under `autobus=kicad`; the bus alone | named with `a[0]`; named with `a_0_`; silent |
| `.meas`, `.print`, `.four` cards under `saveused`; a block printing v(in) alone | the measure works and `out` is kept; the table is filled; the Fourier line; `out` still not kept |
| `print v(b[0])` after a split; `print v(b_f[0])` | named, quoted, cured; silent, 0.67213 |
| `mcseed=1.5`; `mcseed=abc`; seed 0, −5, none | said and the seed-1 ensemble; said and the default; deterministic |
| four ops; `op op sweep op`; `op tran`; `montecarlo -warm` on a ±0.02 % band; `osdimc=0`, `automc=no`, `noosdimc` | trials 1..4; the sweep's points at trial 3, the next op trial 4; trials 2 and 3; 0 of 6 pass; nominal, no warning |
| `nosaveused`, `noautobus`, `noautoadapt`, `noautomc`; an unknown name | no warning; still flagged |
| `autoopts_examples`; the eleven suites above; full sweep | 27 / 27 both solvers; all pass; 471 of 471 |
