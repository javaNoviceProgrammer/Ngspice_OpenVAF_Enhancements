# Enhancement-131 — transient checkpoint / restart

Two new front-end commands, **`savestate`** and **`loadstate`**, let a (long)
transient run be saved to disk and later resumed — **including in a fresh ngspice
process**. A multi-hour analysis can now survive a crash, be split across
sessions, or be moved to another machine.

Stock ngspice can only continue a *paused* run **in memory** (`stop` … `resume`):
the integration state lives in the `CKTcircuit`, so once the process exits it is
gone. Enhancement-131 serializes that state to a file and rehydrates it into an
identically-built circuit, then continues the transient exactly where it left off.

## Usage

```
* run part of a transient and checkpoint it
.tran 1u 1m
.control
run
savestate run.ckpt          ; dump the current transient state to disk
.endc
.end
```

```
* later -- possibly a fresh process -- resume and continue to 2 ms
.tran 1u 2m                 ; the .tran tstop is the new end time
.control
loadstate run.ckpt          ; restore the state and continue the run
wrdata out.dat v(out)
.endc
.end
```

- **`savestate <file>`** — write the active circuit's current transient state.
  Valid after a transient has advanced (`CKTtime > 0`); the file is binary and
  specific to the machine/build that wrote it.
- **`loadstate <file>`** — restore the state into the active circuit (which must be
  the **same** deck) and continue the transient defined by the deck's `.tran`
  line. The `.tran` **tstop** becomes the new end time, so the run may be resumed
  to its original end (crash recovery) or **extended** past it.

Checkpoint files store a signature (equation count, matrix size, state-vector
length, integration order); restoring into a different circuit is rejected with a
clear message rather than crashing.

## What is saved

Exactly the state the in-memory `resume` relies on, per `CKTcircuit`:

- the solution vector `CKTrhsOld` (and `CKTirhsOld`), sized `SMPmatSize+1`;
- the device **integration history** `CKTstates[0..7]` (charges, currents and
  their divided differences), each `CKTnumStates` long;
- the current `CKTtime`, `CKTdelta`, `CKTsaveDelta`, `CKTdeltaOld[7]`, `CKTorder`,
  `CKTmode`, `CKTminBreak`, `CKTdelmin`;
- the pending breakpoint table `CKTbreaks`.

## How it works

`loadstate`:

1. builds the circuit if it is not set up yet (`CKTsetup` / `CKTtemp`), so the
   state vectors exist to fill;
2. validates the file signature against the circuit — the solution vector length
   is keyed off `SMPmatSize(matrix)` (which is **not** `CKTmaxEqNum`, and is what
   `NIreinit` actually allocates), so the reads cannot overrun;
3. pours the saved arrays back into `CKTrhsOld` / `CKTstates` / `CKTbreaks` and the
   scalar time/step/order fields;
4. sets a new one-shot `ckt->CKTcheckpoint` flag and drives the analysis through
   the existing `resume` path (`if_run(ckt, "resume", …)`).

`DCtran()` gains a **checkpoint branch** (guarded by `CKTcheckpoint`) that, unlike
the in-memory resume, opens a **fresh** output plot — there is no live plot to
`666`-relink across a reload — and then jumps into the time-stepping loop with the
restored state. It also:

- initializes the XSPICE temporary-breakpoint markers
  (`g_mif_info.breakpoint.current/last = 1e30`) — the in-memory resume inherits
  these from the original run, but a fresh process must set them, or the stepping
  loop forces `CKTdelta = breakpoint.current − CKTtime = −CKTtime`;
- rebuilds a minimal breakpoint list (dropping any restored breakpoints at/before
  the resume time, keeping genuine future ones, and ensuring the — possibly
  extended — final time is present). Sources (`PULSE`, `SIN`, …) re-schedule their
  own future edges as the run proceeds.

`CKTcheckpoint` is a new zero-initialized bit-field on `CKTcircuit`, so ordinary
runs never take the branch.

**Solver scope.** Checkpoint/restart is supported with the default **Sparse 1.3**
solver. Under **KLU** the symbolic/numeric factorization objects are only built
during a full run's operating point and are absent on the restore path; both
`savestate` and `loadstate` reject KLU with a clear message (`remove '.option
klu'`) rather than crashing.

## Verification

`verify_checkpoint.py` runs, for each circuit, an **uninterrupted** reference
transient (0 → T2), then a split run: part 1 (0 → T1) + `savestate`, then — in a
**separate ngspice process** — `loadstate` and continue to T2. The resumed
waveform must match the reference at the end and at an interior sample time
(`meas … FIND v(out) AT=…`). 19/19 checks pass:

- **RC step** (linear, `uic` charging) — resumed end/interior values **bit-identical**.
- **RC pulse** (`PULSE` source) — exercises breakpoint save/restore and source
  re-scheduling; end value bit-identical, `0.5831499` either way.
- **Diode rectifier** (nonlinear built-in `D`, sine drive) — end value bit-identical
  after 1150 nonlinear steps.
- **OSDI diode** (compiled Verilog-A, reactive + nonlinear) — end value matches to
  ~2×10⁻⁷ (OSDI devices carry a little instance-internal state outside `CKTstates`).
- **same-session** `savestate`+`loadstate` reaches `1−e⁻² = 0.8647`.
- **robustness** — a checkpoint restored into a different circuit is rejected; the
  KLU solver is rejected with a clear message and writes no file.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/frontend/com_checkpoint.c` / `.h` | new — the `savestate` / `loadstate` commands (binary serialize / restore, signature validation, KLU guard) |
| `ngspice-46/src/frontend/commands.c`, `com_commands.h`, `Makefile.am` (+`Makefile.in`) | register + build the two commands |
| `ngspice-46/src/spicelib/analysis/dctran.c` | the `DCtran()` checkpoint branch (fresh plot + restored-state continuation + breakpoint fix-up + XSPICE marker init) |
| `ngspice-46/src/include/ngspice/cktdefs.h` | new one-shot `CKTcheckpoint` bit-field |
| `examples/checkpoint_examples/` | `verify_checkpoint.py`, `ckdiode.va` |

## Scope

Disk checkpoint/restart of a **transient** run, verified bit-identical (built-in
devices, Sparse solver) across linear, breakpoint-driven, nonlinear and OSDI
circuits, including a fresh process. Natural follow-ups: KLU support (rebuild the
factorization on restore), checkpointing other analyses, an architecture-portable
file format, and a periodic auto-checkpoint option during a long run.
