# Enhancement-727: the `saveused` scan reads a vector named bare inside an expression on an output command, in a `meas` (`find out`, `when out=0.2`), behind `$&`, and keeps a subcircuit node or a branch current whole (`x1.mid`, `v1#branch`) — `print v(in) mag(out)` had lost `out`, `meas tran m find out at=0.5u` failed "no such vector", `echo $&mid` said "no such variable" and `let y = x1.mid*2` was "RHS invalid", while `print out*2` alone worked by accident and now prunes

**Scope:** F5 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/frontend/dotcards.c` (`e469_scan_bare`: every command's
expression tokens, the `meas` words, the file after a `>`; `e469_add_expr_names`: dots
and hashes inside a name; `e469_scan_refs`: `$&name`; `e469_meas_cmds` in place of
`e469_no_bare`). [`examples/saveused_examples/`](../examples/saveused_examples/)
(section E-727, 9 checks, 44 per solver);
[`examples/saveforms_examples/`](../examples/saveforms_examples/) ([5] and [7]
re-pinned, 16 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
The hunt page.

**Suites:** `saveused` 44 of 44 per solver, both solvers (34 of 44 on the E-722
binaries, with [E-726](Enhancement-726.md)'s checks); `saveforms` 16 of 16 (16 of 16
on the E-722 binaries: the re-pinned probes hold there too); `autocorner` 26 of 26 with
[E-725](Enhancement-725.md), `savekw` 46 of 46, `savenoise` 11 of 11, `multisave` 9 of
9, `savemiss` 11 of 11, `saveguard` 38 of 38, `autosave` 5 of 5, `savecur` 22 of 22,
`savecuroff` 20 of 20, `savecorner` 29 of 29, `autoopts` 43 of 43, `savemc` 37 of 37,
`reusedev` 16 of 16 unchanged; no new build warnings; full sweep, run alone.

## What was wrong

The RC divider under `.option saveused`:

| block | E-722 |
|---|---|
| `op` / `print v(in) mag(out)` | `in` saved; "vector out is not available" |
| `tran 0.1u 1u` / `meas tran m find out at=0.5u` / `print v(in)` | "meas … failed! Error: no such vector as out" |
| the same with `when out=0.2 rise=1` | "no such vector as 'out'" |
| `op` / `print v(out)` / `echo mid is $&mid` | "Error: &mid: no such variable" |
| `op` / `print v(out)` / `if ($&mid > 0.4) …` | the same, then "PPerror: syntax error" |
| `op` / `let y = x1.mid*2` / `print y` (a subcircuit) | "vector x1.mid is not available … RHS invalid" |
| `op` / `print out*2` alone | works: nothing collected, the option stood aside |

The scan ([E-469](Enhancement-469.md)) took `v()`, `i()`, `@dev[param]`
([E-591](Enhancement-591.md)'s accessor spellings too) from every line and bare words
from the output commands; a token holding an operator character was left alone on an
output command, on the ground that the reference scan covers the accessor forms there
and "splitting would only add noise" — the names inside were pulled out for `let`
alone (E-469's F2). `meas` was kept out of the bare-word scan altogether
([E-496](Enhancement-496.md): its `tran`, `m1`, `find`, `at` are grammar), so a vector
named bare in a measure was never seen. `$&name` — the value of a vector in an `echo`,
an `if`, a `set` — is neither an accessor nor a bare word on an output command. And
the expression-name scan split an identifier at a dot or a hash, so `x1.mid` became
`x1` and `mid` and `v1#branch` became `v1` and `branch`, none of them the vector read.
Each is the class of the second dig's F2 (the accessor spellings), and each is the
failure the option must not have: under-saving turns a performance option into a wrong
answer.

## What changed

- **Expressions on every command that takes one.** A token with an operator character
  is split into its names on an output command as on a `let` (`mag(out)` gives `mag`
  and `out`; `out*2` gives `out`). The noise is a function name or a keyword per token,
  inferred, so it costs a slot and warns about nothing (E-496's mark).
- **`meas` and `measure`.** The analysis and the result name are skipped; every other
  word — alone, or either side of an `=` — is taken (`find out at=0.5u` gives `find`,
  `out`, `at`, `u`; `when out=0.2` gives `when`, `out`). No keyword list stands between
  the scan and a node that happens to be called `max`.
- **`$&name`** on any line registers `name` (`$&mid`, `$&v1#branch`, `$&tran1.out`
  under [E-726](Enhancement-726.md)'s dot rule); `$&v(in,out)` and `$&i(v1)` are left
  to the accessor scan, which already read them.
- **A name is whole.** The expression-name scan keeps a dot followed by an identifier
  character, and a hash, inside a name: `x1.mid`, `v1#branch`; a plot-qualified
  `tran1.out` inside an expression gives `out` too (E-726).
- **The file after a redirect** (`print v(out) > f.txt`) is skipped, as the first
  argument of `wrdata` always was.

The policy is E-469's own: "over-saving costs a little memory; under-saving costs the
answer". A block whose only reference was an expression — `print out*2` — used to keep
everything because nothing was collected; it now keeps `out`, which is what the option
is for.

## Verification

`saveused` section E-727: `print v(in) mag(out)` keeps `in` and `out`; `print out*2`
alone restricts to `out`; `wrdata f out*2` beside a print keeps `out` and `mid`;
`meas dc m find out at=0.5` keeps `out` and reads 0.1667; `meas dc m2 when mid=0.5`
keeps `mid` and reads 0.75; `echo mid is $&mid` after an `op` prints 0.666667 with
`mid` kept; `if ($&mid > 0.4)` takes its branch; `$&i(v1)` adds nothing beyond the
accessor scan's `v1#branch`; `let y = x1.mid*2` in a subcircuit deck keeps `x1.mid`
whole and reads 1.3333. On the E-722 binaries eight of the nine fail as the hunt saw;
the `$&i(v1)` check pins what was already so. `saveforms` [5] and [7] re-pinned: their
probe was `print length(in)`, which names `in` and so, under this change, saves it;
`display` now lists the plot without naming anything, and the two checks — `out` kept,
`in` not — hold on both binaries.

By hand: the hunt's harness D [D1], [D2] and [D3] on both binaries; a batch `.meas
tran m find out at=0.5u` card, which fails "no such vector as out" with and without the
option on the E-722 binaries — ngspice's own, the card wants `v(out)` — and is
therefore not scanned for bare words; the fourteen suites; the sweep.

## What this does not do

- A batch `.meas` card's bare vector stays as ngspice has it (above); the card's
  `v()`, `i()` and `@dev[param]` forms are collected as [E-572](Enhancement-572.md)
  left them.
- A `$&` followed by an expression in parentheses is not a form ngspice reads
  (`$&v(in,out)` splits at the comma in `echo` on every binary); nothing is registered
  for it beyond the accessor scan's own.
- The keywords a `meas` line carries are saved as names. They match nothing, are
  inferred, and are never reported; a control block full of measures spends a few
  slots on `find` and `at`.
