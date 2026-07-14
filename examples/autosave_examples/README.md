# Auto-checkpoint on interrupt — `set autosave=<file>` (Enhancement-192)

[Enhancement-131](../../enhancements_doc/Enhancement-131.md) added `savestate` /
`loadstate` so a long transient can be checkpointed to disk and resumed later
(even in a fresh process). But the checkpoint had to be taken **by hand** — if a
run was interrupted, its progress was lost. E-192 makes an interrupted transient
write one **automatically**, when the user opts in:

```
set autosave=mylongrun.chk
run
```

Now a **Ctrl-C** during that `run` (or any pause) writes `mylongrun.chk` before
control returns to the prompt. Resume it later — even in a new session — with:

```
loadstate mylongrun.chk
run
```

## Why it is safe to do this

Writing a file (buffers, `malloc`) from inside a signal handler is undefined
behaviour. E-192 does **not** do that. On a real interrupt, ngspice's transient
loop sets a flag; at the next **accepted timepoint** `dctran`'s `IFpauseTest`
sees it and returns `E_PAUSE`, which unwinds cleanly — on the **main thread**,
not in the signal handler — back to `dosim`, where the run reports "interrupted"
(`err == 1`). E-192 hooks exactly that branch. So the checkpoint is written at a
consistent timestep boundary, with ordinary buffered I/O, from normal code.

A genuine Ctrl-C (SIGINT), a `stop when …` breakpoint, and a Verilog-A `$stop`
all funnel through this same `err == 1` branch — they differ only in how the
interrupt flag gets set, upstream of the E-192 code.

## Guarantees

- **Opt-in.** With no `autosave` variable, interrupt behaviour is unchanged — no
  file is written.
- **Transient only.** The hook fires only when the interrupted run was a
  transient (`CKTmode & MODETRAN`, `CKTtime > 0`), so the saved integration
  state is meaningful.
- **A real, valid checkpoint.** The autosave path calls the *same* writer as the
  `savestate` command (factored into `ckt_write_checkpoint`), so an autosave file
  is **byte-identical** to a manual `savestate` taken at the same pause, and
  `loadstate` resumes it exactly.

## Verification

`verify_autosave.py` — 5 checks:

1. with `set autosave`, an interrupted (`stop`-paused) transient writes a checkpoint;
2. that checkpoint is **byte-identical** to a manual `savestate` at the same pause;
3. the autosave checkpoint **loads and resumes** (`loadstate`);
4. the **opt-in gate**: without the variable, an interrupt writes nothing;
5. a **genuine Ctrl-C (SIGINT)**, driven through a PTY so ngspice runs
   interactive (the signal handler is only installed in interactive mode), fires
   the autosave. Check 5 is lenient — a machine fast enough to finish the run
   before the signal lands simply skips it, since the identical hook is already
   proven deterministically by checks 1–4.

Checks 1–4 use a `stop when …` breakpoint so they trigger the exact interrupt
path deterministically (no signal-timing race).

## Running

```sh
python3 verify_autosave.py
ngspice -b autosave_demo.cir
```

Interactively, the real thing is simply:

```
ngspice> set autosave=run.chk
ngspice> run          # ... press Ctrl-C ...
ngspice> loadstate run.chk
ngspice> run
```
