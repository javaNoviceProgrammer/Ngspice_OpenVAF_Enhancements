# Enhancement-384 — `sens` poisoned the session, and five more around the RF ports

Six defects, found by hunting around `sens` and the S-parameter ports. One of
them is serious; the rest were found on the way to it, or by asking what else
the same seam got wrong.

## [2] A transient after `sens` returned exactly zero

```
tran 20n 2u   ->  v(in)[5] = 2.010484e-02
sens v(out)
tran 20n 2u   ->  v(in)[5] = 0.000000e+00
```

Every node, including `v(in)` — the node the source drives. No warning, no error.
Three components reproduce it, and it reproduces on the shipped binary.

**The cause is not in `sens`.** `VSRCparam`'s `pwr` and `freq` cases did

```c
here->VSRCfunctionType = PORT;      /* unconditionally */
```

and *every* voltage source carries those parameters, not just ports. `sens`
perturbs every settable real parameter of every device, so it wrote `pwr`/`freq`
on ordinary sources, flipped them to `PORT` (power 0), restored the **value**
afterwards — and never the function type. The deck's `SIN` was gone for the rest
of the session.

`sens` was only the messenger. `alter @v1[pwr]=0` did the same damage in one
line:

```
tran        ->  2.0104838325e-02
alter @v1[pwr]=0
tran        ->  0.0000000000e+00
```

The fix is to claim the source as a `PORT` only when it does not already carry an
explicit waveform (`if (!here->VSRCfuncTGiven)`). A genuine port source declares
no `SIN`/`PULSE`/`PWL`, so it is unaffected.

**Blast radius, measured before the fix:** `tran` and `envelope` zeroed;
`hb`/`pss` failing with `|F|=nan` while blaming the user's circuit ("*the circuit
may be singular*"); `op`/`dc` about **60× less accurate** (6.7e-8 against a
tight-tolerance reference, versus 1.1e-9 normally); `ac`/`tf`/`pz` shifted 1e-7 to
2e-6. Only `reset` cleared it. Pure batch decks (`.sens` + `.tran` cards) were
safe — it needed the transient to be issued as a control command.

## [1] `sens` ended the process on any deck with a `portnum` source

```
Internal Error: node allocation in DEVsetup() during sensitivity analysis,
this will cause serious troubles !, please report this issue !
```

`vsrcset.c` allocates the port's internal `res` node with no already-allocated
guard — unlike the branch-current node ten lines above, which has one.
`cktsens.c` calls each device's `DEVsetup` a second time to build its
perturbation matrix, checks that no node was added, and calls
`controlled_exit()` when one was. The fix is the guard the neighbouring
allocation already uses.

## [3] `sp` with no ports ended the process

Forgetting `portnum` is an ordinary deck mistake; it called
`controlled_exit(EXIT_BAD)`, taking everything computed so far with it. It now
reports the error, names the fix, and returns `E_NOTFOUND`.

## [4] `sp` with `z0 ≤ 0` silently produced a partial, wrong answer

`vsrctemp.c` demoted such a port to "not a port" without a word, so `sp` simply
ran with the ports that were left. A 2-port with `z0=0` on port 2 produced a plot
holding **only `S_1_1`** — no `S_1_2`, `S_2_1` or `S_2_2` — and an `S_1_1` of
0.9512 where the correct value is 0.9089. A reference impedance of zero is not a
modelling choice, it is a typo, and `z0` is a divisor (`Y0 = 1/z0`,
`ki = 0.5/sqrt(z0)`). It is now a parameter error.

## [5] OSDI: a model declaring `DT` got a bogus `dtemp` that was silently ignored

`osdiregistry.c` tested `dt`/`temp` with case-**sensitive** `strcmp` in one branch
and `strcasecmp` in the next. ngspice looks parameters up case-insensitively, so
`DT` and `dt` name the same knob and must classify the same way — they did not,
and a model declaring `DT` had ngspice's synthesized `dt`/`dtemp` aliases built
over its own parameter. Writing `dtemp=50` was then accepted with no diagnostic
and silently ignored.

This is the identical mistake [E-335](Enhancement-335.md) fixed one line above for
`m`, left in place for `dt` and `temp`. All the tests are now uniformly
case-insensitive.

## [6] Two parameter-table inconsistencies ngspice itself reports

`check_ifparm` is ngspice's own consistency checker and **nothing in this repo
ever ran it**. It reports two:

- `dio.c` — `tref` aliases `tnom` (same id) but was `IOPUR`, dropping
  `IF_NONSENSE`, the flag that keeps a parameter **out of sensitivity analysis**.
  Two spellings of one parameter disagreed about whether they were
  sensitivity-able. There was no `NONSENSE|UNINTERESTING|REDUNDANT` macro to
  spell it correctly with, so `IOPXUR` was added.
- `mes.c` — `m` was flagged `IF_REDUNDANT` ("alias of the preceding entry")
  while carrying its own id `MES_M`, not `area`'s `MES_AREA`.

An independent checker written over all **972 device files** found these two and
no others, so the tables are otherwise sound.

## Why [2] survived a campaign aimed at exactly this

This project already has a cross-analysis sequence fuzzer, and `sens` **is** in
its pool. Two blind spots stacked:

* Its netlist carries `portnum 1 z0 50`, so every `sens` case it generated died
  instantly on **[1]** — `sens` was never actually exercised.
* Its oracle is crash-only — *"a clean error is a PASS, the findings are sanitizer
  reports, signals, and hangs"* — and a transient full of zeros trips none of
  those.

Only one example in the whole tree sequences `sens` with another analysis, and it
uses a deliberately nonexistent node.

## Two dead ends, recorded so they are not re-tried

* **`CKTnumStates`.** `cktsens.c` reassigns it to each device's state base and
  lets `DEVsetup` advance it, restoring nothing. That is real, and it was
  *implemented* as the fix — the symptom did not move. It is not the channel, and
  the change was reverted rather than shipped as an untestable extra.
* **`CKTmode` / `CKTstates[]` leaking out of `sens`.** Both looked promising and
  both are dead code: the `MODEINITSMSIG` assignment and every `CKTstates`
  save/restore block in `cktsens.c` sit inside `#ifdef notdef`, and `dctran`
  fully reassigns `CKTmode` at entry.

What settled it was instrumenting `VSRCload` and printing the function type:
`ftype=2` (SIN) before `sens`, `ftype=10` (PORT) after.

## Verification

`examples/sensstate_examples` — 17 checks.

```
   fixed:     17/17
   pre-fix:    7/17
```

The ten pre-fix failures are the defects, at least one per finding. The six accept
checks pass on **both** binaries, which is the point of having them: [2] changes
the parameter that makes a source a port and [4] changes port setup, so the RF
path is exactly what a careless fix would break. They pin the S-parameters of a
valid 2-port (bit-identical, `S11 = 0.90889370933`), a genuine port source keeping
its `pwr`/`freq`, `sens`'s own numbers against the analytic derivative
(`dv/dR1 = -2.5e-4`, `dv/dV1 = 0.5`), a plain transient, and the OSDI model's own
`DT` still taking effect.

`examples/touchstone_examples` and `examples/rfstab_examples` pass unchanged.

Regression 307/307 → 308/308.
