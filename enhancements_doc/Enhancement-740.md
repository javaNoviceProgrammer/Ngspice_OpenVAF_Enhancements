# Enhancement-740: what a compiled device's lines say when the deck speaks the built-in dialect — `ic=` and a bare `off` on the instance line are named as the built-in keywords with the route that exists, `m=` on a model that owns `m` says the multiplier is spelled `_mfactor=`, `level=` on a compiled model card is warned as ignored, a compiled model under another device letter is named with its module and the `n` prefix whether its card is live or was dropped as unused, and `.option bypass` is noted once as without effect on compiled devices

**Scope:** N1 of the
[options-and-convergence hunt](../docs/bug_hunts/2026-09-26_ngspice-osdi-options-and-convergence.md),
the notes block. Five files: `inpdpar.c` (the `ic=`, `off` and `m=` texts),
`inp2n.c` (the bare `off` refusal), `inpgmod.c` (the `level=` warning),
`inppas2.c` (the wrong-prefix hint, live and culled), `osdisetup.c` (the
bypass note). Messages only; nothing binds, parses or solves differently.
Two of the hunt's notes were wrong and are corrected on its page: the
"bare" errors carried a third line my filter had cut, and a constant-text
message is emitted from the compiled setup code once per setup by the
compiler's own hoisting, not suppressed by ngspice.

**Suites:** `hunt12diag` 26 of 26 under both solvers (20 of 26 on the E-739
binary: the six checks added here); `barevalue`, `guardspell`,
`paramsetguard` 41 of 41, `numguard`, `binstale`, `acgminhold`, `cmcsweep`,
`autobusopt` unchanged; the full sweep 532 of 532.

## What was wrong

A deck written for the built-in devices carries idioms a compiled device
does not have, and each of them was refused with the generic line or not at
all:

| line | before | after |
|---|---|---|
| `nm1 out in 0 0 mos_va w=1u l=100n ic=0.5,0.6,0` | *unknown parameter (ic)* | *`ic=` is the built-in devices' initial-condition list; a compiled device has no such keyword — use `.ic v(<node>)=<value>` on its terminals or internal nodes* |
| `nd1 a 0 dva off` (a model with no `off` parameter) | *'off' is not a model and not a name=value parameter; the model is 'dva', so a parameter here needs a value — write off=<value>* | *`off` is the built-in devices' start-off flag; a compiled device has no such keyword and model 'dva' declares no `off` parameter — remove it, or give the model one and write off=<value>* |
| `nd1 a 0 dva m=2` (the diode's grading coefficient is `m`) | *it is a model parameter of this device — set it on the .model card* | the same, then *; the instance MULTIPLIER of a compiled device is spelled `_mfactor=`* |
| `.model dva vadiode(level=1 is_=1e-14)` | nothing | *Warning: dva: `level=` on the .model card of a compiled model (module vadiode) has no meaning — the module is chosen by the model's type name — and is ignored.* |
| `q1 a 0 0 dva`, `d1 a 0 dva`, `m1 a 0 0 0 dva`, `p1 a 0 b 0 dva`, `y1 a 0 b 0 dva` | *incorrect model type* | the same, then *'dva' names a compiled (OSDI) model of module 'vadiode'; its instances are written with the prefix 'n', not 'q'* |
| `y1 a 0 dva`, `t1 a 0 b 0 dva` | *model name is not found* / *unknown parameter (dva)* | the same, then *'dva' names a .model card (type vadiode) that was dropped as unused: no line refers to it in the model position; vadiode is a compiled (OSDI) module, and its instances are written with the prefix 'n', not 'y'* |
| `.option bypass=1` with compiled devices | nothing | *Note: .option bypass has no effect on compiled (OSDI) devices such as vadiode; they are evaluated at every Newton iteration.* |

The wrong-prefix case has two halves because the unused-model cull runs
first: `inp_rem_unused_models` comments out a `.model` card that no line
refers to in its model position, and a line with the wrong letter refers to
it as a node or a parameter, so by pass 2 the card reads `*model dva ...`
and no lookup finds it. A `q` or `d` line keeps the card alive, since it
names the model in the model position, and fails on the type instead.

## What changed

- `inpdpar.c`: in the unknown-parameter branch, `ic` and `off` on a device
  with a registry entry get their own text; in the model-parameter branch,
  `m` on such a device gets the `_mfactor=` clause.
- `inp2n.c`: the bare-token refusal E-597 added names `off` as the built-in
  flag when the compiled model declares no `off` of its own. A model that
  does declare one keeps E-597's *parameter 'off' has no value* — the VA
  BSIM4 does, and that message is then right.
- `inpgmod.c`: where `level` and `m` are consumed for every card, a
  compiled model's `level` is warned, once per card. E-426 left `level`
  silent because the built-ins consume it in pass 1; a compiled model never
  reads it.
- `inppas2.c`: before a device line's parser runs, its tokens after the first
  are looked up for a live compiled model; if the line then fails, that token
  is named with its module and the `n` prefix. If no live model matched and
  the line failed, the deck's commented-out `*model` cards are scanned for the
  token, and the card's type is tested for a compiled module. Only failing
  lines pay for the second scan.
- `osdisetup.c`: `OSDIsetup` prints the bypass note once per circuit when
  `CKTbypass` is set.

## Verification

`hunt12diag` gains six checks, each reading the message and two also pinning
the number: the `ic=`, `off` and `m=` texts; `level=` warned with `v(a)`
equal to the card's without it (0.6294434 both); the prefix hint under `d`,
`q`, `y` and `t`, the last two through the culled card; the bypass note
exactly once across two operating points with `v(a)` equal to the run
without the option. All six fail on the E-739 binary.

## What this does not do

- A wrong prefix that happens to parse as a valid line of its own kind is
  not caught: `t1 a 0 dva` is a transmission line with `dva` as a node and
  fails later, at setup, on its impedance. A parse-time hint has nothing to
  attach to.
- The ngspice-wide items of the same notes block stay as they are, being
  the same for built-in devices: `meas` on a device vector needs a prior
  `save`; `stop when` re-fires at once on `resume`; `maxord` above 2 takes
  `.option dynorder`; `dc` sweeps only ngspice's own resistor.
- The repeated-message policy is unchanged: a message whose text is
  constant is hoisted into the compiled setup code and printed once per
  setup, five times then counted for a setup-time flood; the hunt's claim
  of suppression was wrong and its page says so now.
- `.option bypass` still does nothing for compiled devices; the note says
  so, which is the point. A bypass for compiled devices was prototyped and
  parked on 2026-09-26.
