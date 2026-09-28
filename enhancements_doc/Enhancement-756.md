# Enhancement-756: a `set temp` survives `reset`, the loop commands' internal resets included, and `unset temp` gives the deck's temperature back — the variable stayed set while the rebuilt circuit ran at the deck's temperature, and an `unset` re-applied the value being removed, or ran the next analysis at 0 °C behind a stray debug line

**Scope:** plumbing hunt N1 and workflows hunt F14, the same defect seen
twice, plus what `unset` did on the way. Front end only, eight files:
`spiceif.c`/`spiceif.h` (the record of set options, the snapshot a reset
keeps, the rebuild an unset does), `runcoms2.c` (`reset` keeps them),
`options.c` (`set` is recorded, `unset` rebuilds), `variable.c` (`unset`
removes the variable it found and says nothing), `inp.c` (the deck's option
cards parsed by a helper the rebuild can call; the deck's `.temp` remembered)
and `include/ngspice/ftedefs.h`/`fteext.h`. Any simulator option set as a
variable is covered, `temp`, `tnom`, `reltol` alike; the compiler is
unchanged.

**Suites:** `sweeptemp` 29 of 29 (21 of 29 on the E-755 binary: eight new
checks discriminate, the ninth is the control), `mcpolicy` 47 of 47 per
solver (46 of 47 on E-755: the loop command's internal resets), `autoopts`,
`loopguard`, `aging`, `sensrestore`, `collapsestate`, `inputguard`,
`autocorner` and `altermulti` unchanged; the full sweep 533 of 533.

## What was wrong

`set temp=100` in a control block is honoured by the next `op`; after a
`reset` the run is back at the deck's temperature, and stays there, while
`echo $temp` still answers 100. Measured on a diode at 1 mA:

```
set temp=100 / op        Doing analysis at TEMP = 100     v(a) = 0.523
reset / op               Doing analysis at TEMP = 27      v(a) = 0.655
```

`set temp` reaches the circuit through `cp_usrset()` and `if_option()`,
which write the circuit's default option block; `reset` frees the circuit
and rebuilds that block from the deck alone, and nothing looked at the
variable again. The loop commands' internal resets are the same `reset`, so
`montecarlo`, `wcd` and `highsigma` typed after a `set temp` sampled at the
deck's temperature and left the circuit there. `.temp` and `.option temp` on
the deck survived, being deck text.

`unset temp` was worse than useless. It went through the same `cp_usrset()`
with the variable's old value, so the circuit kept what was being removed
(`set temp=40 / op / unset temp / op` ran at 40 twice), it printed a
leftover `it's a US_SIMVAR!` on stderr, and it unlinked only a same-named
entry of the deck's option list, so the variable it had found stayed set.
After a reset it was a wrong answer: `set temp=100 / op / reset / unset temp
/ op` ran the last analysis at 0 °C.

## What changed

* **A record of the options the user set onto the circuit.** `cp_usrset()`
  notes the name whenever `if_option()` accepts a set of a simulator option;
  a new deck starts with an empty record. The deck's own `.temp` card, which
  is implemented as a `set temp`, is left out of it.
* **`reset` keeps them.** `com_rset()` snapshots the recorded variables
  before the circuit goes (they live in the circuit's own variable list and
  would die with it) and re-sets each one after the reload, through
  `cp_vset()`, so the variable and the circuit agree again. That matters for
  a deck with a `.temp` card, whose reload overwrites the variable with the
  deck's value: the user's value comes back on top. A user's `reset` and the
  loop commands' internal ones take the same path.
* **`unset` rebuilds.** For a simulator option, `cp_usrset()` now rebuilds
  the default option block from scratch: the application defaults (a fresh
  task's), the deck's `.options` cards re-parsed by the helper factored out
  of the deck loader (a user's `set` replaces the deck's entry in the
  circuit's list, so the cards are the only record of what the deck said),
  the deck's `.temp`, then every other recorded variable. `cp_remvar()`
  removes the variable it found, wherever it lives, and the debug line is
  gone.

Measured after the change, the divider of the `sweeptemp` suite
(R1 = 1 kΩ (1 + 0.01 (T − 27)) over 1 kΩ):

| sequence | before | now |
|---|---|---|
| `set temp=100` / op / reset / op / op | 100, 27, 27 | 100, 100, 100 |
| `.option temp=60`: op / set 100 / op / reset / op / unset / op | 60, 100, 60, 27 | 60, 100, 100, 60 |
| `.temp 60` card, the same sequence | 60, 100, 60, 27 | 60, 100, 100, 60 |
| set 40 / op / unset / op | 40, 40 | 40, 27 |
| set 100 / op / reset / unset / op | 100, 0 | 100, 27 |
| `set tnom=100` / op / reset / op / unset / op | TNOM 100, 27, 27 | 100, 100, 27 |
| `set reltol=1e-6` / op / reset / op, then unset | 0.001 after the reset | 1e-6, then 0.001 |
| `set temp=100`, `montecarlo` on an osdimc deck, op | the op at 27 | at 100 |

## What this does not do

A `set temp` typed before any circuit is loaded, in a `.spiceinit` or an
interactive session before `source`, has never reached a circuit and still
does not, on a source or on a reset alike: only what was set onto the loaded
circuit is replayed. `unset` of an option puts the deck's value back whoever
set it, so an `unset temp` on a deck whose `.option temp=60` the user never
touched keeps the circuit at 60 and only removes the variable. The `option`
command and the `.options` cards are unchanged.
