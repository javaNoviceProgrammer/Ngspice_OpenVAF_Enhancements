# Enhancement-669: any number of declared corners can be selected, the loops take 255 and say when a circuit declares more, a corner name is limited to 79 characters at compile time, and a longer name no longer aborts ngspice

**Scope:** F14 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/frontend/variable.c` (`cp_getvar`'s string read), `src/frontend/plotting/graf.c`
(`ticchar` passes its buffer's size), `src/osdi/osdisetup.c` (`osdimc_corner`
256 wide, `osdimc_corner_read`, `osdimc_corner_collect_total`,
`osdimc_corner_declared`, `osdimc_corner_check`, `osdimc_corner_say_missing`,
`OSDImcCornerTotal`, `OSDImcCornerDeclared`), `src/include/ngspice/osdiitf.h`,
`src/frontend/com_sweep.c` (`CO_MAXCORNERS` 256, `com_corners`,
`autocorner_run`). Compiler: `sim_back/src/module_info.rs` (`CORNER_NAME_MAX`,
`CornerNameTooLong`). `examples/vacorner_examples/` (four checks added, 35 per
solver). Handbook [§2](../docs/handbook/02-verilog-a-language.md) and
[§3.7](../docs/handbook/03-ngspice-workflows.md).

**Suites:** [`vacorner_examples`](../examples/vacorner_examples/) 35 of 35 per
solver, both solvers (the four new checks fail on the E-666 binaries);
`cornerscmd`, `autocorner`, `hunt17diag`, `lrmcorner`, `savemc`, `wcd`,
`mcyield` unchanged; compiler workspace tests green apart from the known
sourcegen drift; full sweep 530 of 530.

## What was wrong

A model declaring `c0 … c69` compiled without a word. Then:

- `.option corner=c69` was *no loaded Verilog-A model declares a corner of
  that name (declared: c0, c1, …, c63)*: the check collected the names into a
  64-slot list and dropped the rest in silence, so a declared corner was
  reported as undeclared. `corners` and `autocorner` ran 64 of the 70, their
  banners listing the 64, nothing saying what was left out; `corners -list
  c69` was refused the same way.
- A corner named with 90 characters compiled. In ngspice every read of the
  `corner` variable went into an 80-byte buffer, and `cp_getvar`'s string
  read kept `rsize` characters and copied them with the NUL — one byte past
  the buffer every caller sizes with `sizeof buf`. A name of 80 characters or
  more **aborted ngspice** with a smashed stack (exit 134), after the
  *limited to 80 chars* warning; the hunt saw the truncated name refused,
  which is the same overflow landing elsewhere.

## What changed

- **The string reader keeps `rsize - 1` characters.** `rsize` is the caller's
  buffer size; the copy and its NUL now fit it. The one caller that passed a
  character count (`ticchar`, 1 into a 2-byte field) passes the field's size.
  The warning names the characters kept.
- **A selected corner is looked up directly.** `osdimc_corner_check` scans
  every loaded model's corner table for the name — no list, no cap. The
  *declared:* list in its refusal, and in the once-per-type *declares no
  corner of that name* note, is capped at 256 and ends *… and N more*.
- **The loops take 255 beside `tt` and say when a circuit declares more.**
  `CO_MAXCORNERS` is 256; `corners` and `autocorner` fill their set from the
  first 255 declared names and print *the circuit declares 300 corners; this
  loop takes the first 255 (its limit) — `-list` names any of them*.
  `corners -list` judges each name by the direct lookup, so a name beyond the
  first 255 runs. The names and plots strings grew to hold them.
- **The corner buffer is 256 wide, and an overflow is said.** `osdimc_corner`
  and the loops' saved-corner buffers hold 255 characters; a name the read
  had to cut is refused as *the name is longer than 255 characters, more than
  ngspice can select (a compiled corner name is at most 79)* instead of the
  remnant being looked up.
- **The compiler refuses a corner name longer than 79 characters** — the
  contract, with the simulator's margin above it for objects from older
  compilers: *corner 'czzz…' is 80 characters long; a corner name is limited
  to 79 characters*, with the help that ngspice selects a corner through its
  `corner` variable.

## Verification

| check | result |
|---|---|
| 70 corners: `.option corner=c69`; `corners`; `.option autocorner`, `op` | 169; 71 corners, row 70 `c69 169`, `$corners_n` 71; *op at 71 corners*, `$autocorner_n` 71 |
| 300 corners: `.option corner=c299`; `corner=nosuch`; `corners`; `corners -list c299 c0`; `autocorner` | 399; the list ends *c255 … and 44 more*; *declares 300 corners; this loop takes the first 255*, `$corners_n` 256; the listed pair runs, `c299 399`; the pass says the same, `$autocorner_n` 256 |
| a 79-character name through `.option corner=`, `set corner=` and the loop; an 80-character one compiled | 120 three times, no warning; refused at compile time, no object |
| `.option corner=` with 300 characters | the *limited to 255 chars* warning, the refusal, exit status 1 — no abort |
| the E-666 binaries on the suite | the four new checks fail (7 of 35 with E-668's) |

Full sweep 530 of 530 on both solvers.

## What this does not do

- 255 is the loops' limit, not the selection's: `.option corner=` and
  `corners -list` reach any declared corner.
- The compiler does not cap how many corners a model declares.
