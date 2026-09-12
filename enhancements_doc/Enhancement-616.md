# Enhancement-616: a loop command's netlist re-draw is the nominal the model's statistics sit on

**Scope:** `src/osdi/osdisetup.c` — `OSDImcNoteRedraw()`, a hook for the in-place
re-draw of a parameter's netlist random expression: the value becomes the parameter's
`.option osdimc` nominal and its pin goes; `src/include/ngspice/osdiitf.h` declares it;
`src/frontend/com_sweep.c` — `sw_fp_apply()` calls it after the direct slot write of a
random bind. `examples/osdimc_examples/` grows 36 → 39 checks per solver; the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §8, the
suite README. **ngspice only.** F18 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`osdimc_examples`](../examples/osdimc_examples/) 39 of 39 per solver, both
solvers; the eleven suites that exercise `osdimc` or `savemc` green; full sweep 505 of
505.

## What was wrong

One parameter can carry statistics on both channels: the netlist draws it
(`.model rm rstat r={agauss(1000,300,3)}`) and the model declares `(* std=25 *)` on it.
The guide's opening table says the two compose, and on the re-source path they do —
each `montecarlo` sample's internal `reset` drops the nominal table, the re-capture
takes the fresh netlist draw as the nominal, and the trial's δ goes on top. On the
**fast path** — the one `montecarlo` arms whenever every random expression sits in a
braced device or model slot, which is the common case — they did not:

```
osdimc: trial 2: rm:r = 1072.5  (nominal 1033.69) [sample 1 of -seed 1]
osdimc: trial 3: rm:r = 1049.41 (nominal 1033.69) [sample 2 of -seed 1]
osdimc: trial 4: rm:r = 1030.85 (nominal 1033.69) [sample 3 of -seed 1]
osdimc: trial 5: rm:r = 1050.46 (nominal 1033.69) [sample 4 of -seed 1]
```
```
trial,analysis,status,n1:dr,rm:r,@n1[dr],@rm[r]
1,op,ok,6.60750967316,1033.69087872,-0.201177170171,1072.49827271
2,op,ok,9.44033973078,909.889980173,4.42279554448,1049.4080103
3,op,ok,-2.03833780468,1021.26591378,12.7824371413,1030.84505468
4,op,ok,-1.29057894228,1110.89820302,9.79770906658,1050.4627358
```

The netlist channel drew 909.89 for sample 2 — the row records it — and the device ran
at 1049.41: the first sample's 1033.69 plus the trial's δ. The fast path writes each
re-drawn value through the ordinary machine setter; that write **pins** the parameter's
nominal entry (Enhancement-535, so a `sweep`'s point wins over the trial's draw); but
`montecarlo` runs without a hold, the pin is cleared at the start of every run, and the
draw applier then wrote nominal + δ over the fresh netlist value — the nominal being
whatever the first setup captured. The row contradicted itself by 38.8, 48.1, −31.2,
173.0 Ω, and the two paths of one command disagreed, which E-320 promises they never
do. The instance slot (`N1 a 0 rm dr={agauss(0,30,3)}`) behaved the same. Under a
`sweep` the pin *held* — for the whole sweep — so the model's statistics were silently
off that parameter at every point, where the reset path applies them.

## What changed

`sw_fp_apply()` reports a random bind's write to a new hook, `OSDImcNoteRedraw()`,
after the setter: the value **is the nominal for this sample** — exactly what the
re-source path's re-capture takes — and the pin is released. Nothing else changes: the
δ is the same pure function of (seed, sample, owner, id), a non-random bind (the swept
knob) is still pinned as E-535 requires, a user write still recentres through its own
hook, and a deck whose random expressions are not in the model's statistics is
untouched.

```
osdimc: trial 3: rm:r = 925.607 (nominal 909.89)  [sample 2 of -seed 1]
osdimc: trial 4: rm:r = 1018.42 (nominal 1021.27) [sample 3 of -seed 1]
```
```
2,op,ok,9.44033973078,909.889980173,7.2556256021,925.607111756
3,op,ok,-2.03833780468,1021.26591378,4.13658966342,1018.42008974
```

`@rm[r]` − `rm:r` is now δ on every row, and the same δ per sample as the re-source
path's (0.83, 33.29, −13.48, 39.05 in the suite's deck, whatever each path drew for the
netlist). Under `sweep` the sweep's one trial δ sits on each point's fresh draw.

What this does **not** change, and the guide now says: in a `repeat … reset … op`
loop the netlist channel varies and the model channel stays at its baseline on every
pass — a user `reset` restarts the trial sequence (Enhancement-535's contract, checked
by the suite's [26]) — and in a `repeat … op` loop the reverse; `montecarlo` is the
loop that varies both. Two paths still differ on the *swept* statistical parameter
itself: the fast path pins it at the swept value (E-535), the reset path re-captures
the swept value as a nominal and adds δ — an older seam, noted for the next hunt.

## Verification

| check | result |
|---|---|
| `montecarlo 4` on the fast path, `mm:r` and `n1:dr` random in the netlist and `(* std *)` in the model | four distinct netlist draws; each sample's verbose nominal is its row's draw; `@mm[r]` = `mm:r` + δ, δ ≠ 0 |
| the same deck on the re-source path (a bare draw in a B-source disarms the fast path) | the same δ per sample for `r` and for `dr` |
| `sweep k 0 20 10 op` with a random model bind, fast path | three fresh draws, the sweep's one δ on each; the swept `dr` pinned at 0/10/20 |
| the 36 existing checks; `paramgiven`, `mcpolicy`, `osdidist`, `wcd`, `huntfix`, `dcxsweep`, `constguard`, `autoopts`, `savemc`, `writemc` | unchanged |
| `osdimc_examples` | 39 / 39, both solvers |
| full sweep | 505 of 505 |
