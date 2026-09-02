# `lrmio_examples` — Enhancement-539

Pins the five LRM divergences the 2026-09-02 re-audit found and
[Enhancement-539](../../enhancements_doc/Enhancement-539.md) fixed, plus the one
finding that audit **withdrew**.

```bash
python3 verify_lrmio.py
```

**17 checks**, both solvers. Against the previously shipped binaries the same
suite scores **6/17**, so every check discriminates.

## What each fixture covers

| fixture | clause | property |
|---|---|---|
| `lrmio_mcd.va` | LRM 9.5.1 | `$fopen(name)` returns a **one-hot** multichannel descriptor with bit 0 clear (bit 0 is stdout); OR-ing two of them writes to **both** files; a `$fopen(name, mode)` file descriptor lives in a disjoint namespace |
| `lrmio_read.va` | LRM 9.5.1 / IEEE 1364 | `$fclose` + `$fopen` for reading restarts at byte 0; `$fscanf` leaves the **remainder** of the line for a following `$fgets`; a plain `$fgets` + `$sscanf` does **not** reposition the descriptor |
| `lrmio_m.va` | LRM 9.4.4 | `%m` prints the **instance** name — four instances give four distinct names, hierarchical inside a subcircuit |
| `lrmio_nat.va` | LRM 3.6.1 | a nature's declared `abstol` reaches the convergence test, and an explicit `.option vntol` takes precedence over it |

## Why the `.option` precedence is pinned

`disciplines.vams` declares `abstol` on the **standard** natures too (`Voltage`
is `1u`, `Current` is `1p`), so the nature path is not exotic — it runs for
every OSDI node in every deck. Those values equal ngspice's own defaults, so
they change nothing by themselves; they stop being harmless the moment a user
*loosens* a tolerance to get a stubborn circuit to converge. An explicit
`vntol`/`abstol` therefore wins over the nature, and check [14] pins that a
deck setting one still solves with the nature path active.

## The withdrawn finding is pinned too

Check [15] compiles a `$rdist_uniform` call inside a loop and requires lint
**L019** to fire. The audit had reported the non-advancing seed as a silent
defect; it is neither silent nor a defect — an advancing seed would return a
different value on every Newton iteration and break convergence, which is why
the design is deliberate (Enhancement-10 §1, `../rng_examples/README.md`). The
check exists so the *diagnostic* cannot regress, since that is the part a model
author actually depends on.

## Reading the results

`lrmio_read.va` reports through `lrmio_out.txt` rather than operating-point
variables, because strings are not readable via `@instance[name]`. The values
retain the trailing newline `$fgets` returns, which is why the checker matches
up to the closing bracket rather than to end of line.
