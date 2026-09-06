# Enhancement-560: `pyplot` labels an untyped axis by name, a promoted parameter is named instance-level through its model, and a circuit built against a reloaded object is refused until rebuilt

**Scope:** F14, F15 and F16 of the
[bug hunt of 2026-09-05](../docs/bug_hunts/2026-09-05_strings-mcexpr-and-osdimc-distributions.md):
the pyplot script writer (`src/frontend/plotting/pyplot.c`), the parameter
lookups behind `altermod`, `print` and the `dc` knob
(`src/frontend/{spiceif,device}.c`, `src/spicelib/analysis/dctrcurv.c`), and
the forced reload (`src/spicelib/devices/dev.c`, `src/osdi/osdisetup.c`,
`src/frontend/{spiceif,inp}.c`, `src/include/ngspice/{ftedefs,osdiitf}.h`).
**ngspice only; the compiler is unchanged.**

**Suites:** [`pyplot_examples`](../examples/pyplot_examples/) 53 → 54,
[`instdep_examples`](../examples/instdep_examples/) 20 → 23,
[`osdireload_examples`](../examples/osdireload_examples/) 5 → 6, both solvers;
the thirteen suites that pin a parameter-lookup message pass; full sweep 459
of 459. The [pyplot reference](../docs/internals/ngspice_internals/ngspice_pyplot.md)
§5.2, handbook [§3.3](../docs/handbook/03-ngspice-workflows.md), the
[command reference](../docs/internals/ngspice_internals/ngspice_commands.md)
§8, the [E-229 write-up](Enhancement-229.md), the two suite READMEs.

## What was wrong

**F14.** `pyplot mcv rr` on a `montecarlo` plot (scale `sample`, value `rr`,
both untyped) wrote a script with neither `set_xlabel` nor `set_ylabel`.
E-551 labels an axis by its vector *type*, and plotit hands the writer a NULL
abbreviation for an untyped one — so the plot said nothing, not even the
names it had.

**F15.** `parameter real l = 2.0*w` with an instance `w` is resolved per
instance since E-546 (lint L028 says so at compile time), and the card form
`.model mm vidd l=10` sets every instance's default. The runtime form
`altermod mm l=10` was refused with *model 'mm' has no parameter l* — after
a stray *no such parameter w* / *Can't access width instance parameter* pair,
because the MOS bin probe fires for any name starting with `m` and a `w`/`l`
parameter, model names included. `print @mm[l]` said *no such parameter l*
and `dc @mm[l] …` *not a sweepable parameter of it*. The card had just
proved the parameter exists; the messages denied it.

**F16.** The hunt reported that the run after `pre_osdi -f` printed no trial
line and kept the previous draw. A trace of the applier shows every run
labelled and counted: the unlabelled run was the *first* `op`'s nominal
baseline, which the hunt had miscounted. What the probe did expose is the
reload itself: `pre_osdi` in a control block is hoisted before the deck is
parsed, so that deck is built against the new object — but `osdi -f` at the
prompt reloads mid-session, the registered device type is swapped in place
(E-229), and a circuit loaded earlier resolves its type through that table:
its next run executes the *new* object's code on data blocks laid out by the
*old* one. Harmless while the two layouts agree (the same file reloaded),
memory corruption the moment the recompiled model adds a parameter, a node
or an opvar — which is what a recompile is for. E-229 documented this as a
caveat and nothing enforced it.

## What changed

* **An untyped axis is labelled by name.** The scale's name on x, a single
  untyped signal's own name on y (several are told apart by the legend, as
  before), and `-hist` of an untyped value labels its x-axis with the name. A
  label the user gives still wins.
* **The three refusals say instance-level.** `altermod mm l=10`: *'l' is an
  INSTANCE parameter of model 'mm' (declared (\* type="instance" \*), or
  resolved per instance because its default reads an instance parameter, lint
  L028); `altermod` sets model parameters. Use `alter @<instance>[l]=...` on
  each instance, or write l=... on the .model card, where it is the instances'
  default.* `print @mm[l]` says the same and *Read it from an instance:
  @<instance>[l]*; the `dc` knob says *sweep @<instance>[l] instead*. The MOS
  bin probe runs for instance writes only. The command stays per-instance: a
  card's instance parameters are replayed onto each instance as it is parsed,
  so a runtime write cannot tell an instance that took the default from one
  that gave its own.
* **A circuit built against a reloaded object is refused until rebuilt.** The
  reload names every loaded circuit that has models of the swapped type —
  *circuit "…" was built against the previous "vlg.osdi" and keeps its data;
  `reset` (or re-`source`) it before its next run, which is refused until
  then* — and `if_run` refuses that circuit with the same remedy; a `reset`
  or re-`source` rebuilds it against the new object and clears the mark. The
  deck whose control block carried the hoisted `pre_osdi -f` is unaffected.

## Verification

| check | result |
|---|---|
| `pyplot nt y` with an untyped scale `s` and value `y` | `set_xlabel('s')`, `set_ylabel('y')`; `xlabel "my s"` kept; `-hist y` labels x `y` |
| `altermod mm l=4e-6` on the promoted `l` | the instance-level message, no width probe; `alter @n1[l]=4e-6` moves `n1` only (4e-6 / 2e-6) |
| `print @mm[l]`, `dc @mm[l] 4e-6 8e-6 2e-6` | *Read it from an instance: @<instance>[l]*; *sweep @<instance>[l] instead* |
| pipe mode: `op`, `osdi -f m.osdi` (recompiled 1 kΩ → 2 kΩ), `op`, `reset`, `op` | the reload names the circuit; the `op` is refused; after `reset` i(v1) = −0.5 mA |
| batch: `pre_osdi -f vlg.osdi` in the control block | hoisted: the deck runs against the new object, trials 2, 3, 4 all labelled |
| `pyplot_examples`, `instdep_examples`, `osdireload_examples`; full sweep | 54 / 54, 23 / 23, 6 / 6; 459 of 459 |
