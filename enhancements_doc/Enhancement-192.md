# Enhancement-192 — Auto-checkpoint on interrupt (`set autosave=<file>`)

A follow-up to the [Enhancement-131](Enhancement-131.md) transient checkpoint / restart commands, prompted by the question "does `savestate` fire on a Ctrl-C?" — it did not. E-131 gave `savestate` / `loadstate`, but a checkpoint had to be taken **by hand**, so interrupting a long run lost its progress. E-192 makes an interrupted transient write one **automatically**, opt-in via a variable:

```
set autosave=mylongrun.chk
run          # ... press Ctrl-C ...
```

A Ctrl-C during that `run` now writes `mylongrun.chk` before control returns to the prompt; `loadstate mylongrun.chk` (even in a fresh process) resumes it.

## The safe hook point

Writing a file — buffered I/O, `malloc` — from inside a signal handler is undefined behaviour, so E-192 deliberately does **not** checkpoint in `ft_sigintr`. Instead it uses the path ngspice already unwinds through on an interrupt:

- `ft_sigintr` only sets a flag (`ft_intrpt`) and returns (during a run `ft_setflag` is TRUE, so it does not `longjmp`);
- at the next **accepted timepoint**, `dctran`'s `SPfrontEnd->IFpauseTest()` → `OUTstopnow()` sees the flag and returns 1, so `dctran` returns `E_PAUSE`;
- `E_PAUSE` propagates through `if_run` (which maps it to return code 1) up to `dosim` (`frontend/runcoms.c`), where the run reports "interrupted".

E-192 hooks exactly that `err == 1` branch. So the checkpoint is written on the **main thread**, at a **consistent timestep boundary**, with ordinary I/O — never in signal context. A genuine SIGINT, a `stop when …` breakpoint, and a Verilog-A `$stop` all funnel through this same branch (they differ only in how the flag gets set, upstream of the E-192 code).

## The change

- `com_checkpoint.c`: the body of `com_savestate` is factored into `bool ckt_write_checkpoint(CKTcircuit *ckt, const char *fname)`; the command is now a thin wrapper. The autosave hook calls the **same** function, so an autosave file is byte-for-byte what `savestate` would have written.
- `runcoms.c` (`dosim`, the `err == 1` interrupted branch): if `cp_getvar("autosave", …)` yields a filename and the interrupted run was a transient (`CKTmode & MODETRAN`, `CKTtime > 0`), it calls `ckt_write_checkpoint`.

It is **opt-in** (no `autosave` variable ⇒ behaviour is exactly as before, nothing written) and **transient-only** (the `MODETRAN` / `CKTtime` guard keeps it from writing stale state after, e.g., an interrupted AC run).

The signal handler itself is only installed in **interactive** mode (`!ft_batchmode`), so this targets an interactive Ctrl-C — the scenario where ngspice returns to the prompt. In batch (`-b`) mode a Ctrl-C still terminates the process, unchanged.

## Correctness

Because the autosave path is the same writer as `savestate`, an autosave checkpoint is **byte-identical** to a manual `savestate` taken at the same pause point, and `loadstate` resumes it exactly — the E-131 round-trip already verified bit-identical continuation. The E-192 example confirms all of this, including with a **real SIGINT**.

## Verification

[`examples/autosave_examples/verify_autosave.py`](../examples/autosave_examples/verify_autosave.py) — 5 checks: (1) with `set autosave`, an interrupted (`stop`-paused) transient writes a checkpoint; (2) it is byte-identical to a manual `savestate` at the same pause; (3) it loads and resumes via `loadstate`; (4) the opt-in gate — without the variable, an interrupt writes nothing; (5) a genuine **Ctrl-C (SIGINT)** driven through a PTY (so ngspice runs interactive) fires the autosave — lenient, since a machine fast enough to finish the run before the signal lands just skips it, the identical hook being covered by 1–4. Checks 1–4 use a `stop` breakpoint to hit the exact interrupt path deterministically. A [`autosave_demo.cir`](../examples/autosave_examples/) shows the checkpoint being written mid-run. Full example regression: 156/156.
