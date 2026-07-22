# Enhancement-295 — openvaf-r: regression guards for the two correctness blind spots

A correctness campaign against openvaf-r found **no defects** (~150 oracle checks across
parameter storage, the multi-terminal Jacobian and capacitance matrices, the noise
subsystem, node collapsing, `$mfactor`, `$table_model` and temperature). This enhancement
folds in the two checks that were genuinely **new coverage**, each mutation-tested so it
cannot be vacuous. Verification-only: no compiler source changed.

## What was already covered, and therefore not added

Two of the four candidates turned out to be duplicates, and adding them would have been
noise:

* **flicker noise and the correlated-noise summation rule** — `noise_examples` already
  checks `flicker_noise` against the closed-form `1/f` law, and `noisecorr_examples`
  already asserts the exact amplitude-vs-power results (same-name `2e-6`, distinct-name
  `sqrt(2)*1e-6`, and factor-weighted amplitudes).
* **2-D `$table_model` interpolation** — `mdtable_examples` already checks the DC surface
  against a bilinear reference *and* both partials (`gm`, `gds`).

## [1] The full multi-terminal matrices — `vafautodiff_examples`

Everything in that suite biases a **2-terminal** device, and its `[cross]` check reads a
single off-diagonal entry. Neither exercises the entries openvaf does **not** obtain by
differentiating a contribution: on a 4-terminal device the source row follows from KCL
over the other contributions, and an untouched terminal must give an identically zero row
and column. A sign or index slip there is invisible to a 2-terminal test and wrong in
every real compact model.

The new `[matrix]` checks measure **all 16 entries** of both the conductance matrix
`dI/dV` and the capacitance matrix `dQ/dV` (a separate code path — the reactive residual),
on a device whose two contributions are polynomials in three distinct branch voltages, at
a bias where every branch voltage differs so no accidental symmetry can mask a wrong entry.

**Mutation test.** Dropping the second term of the product rule in
`mir_autodiff/src/builder.rs` (`d(uv) = u'v`):

| check | verdict under the mutation |
|---|---|
| `[matrix]` conductance | **FAIL** (worst reldiff 1.6e-01) |
| `[matrix]` capacitance | **FAIL** (worst reldiff 2.2e-01) |
| `[cross]` | pass — misses it |
| `[regression]` | pass — misses it |
| `[multipoint]` | pass — misses it |

So the new guard has *unique* detection power, not merely extra breadth.

## [2] Parameter slots, per instance — `vafcodegen_examples`

Enhancement-290 was a wrong struct-GEP: a field offset computed as a flat
`5*sizeof(double)` instead of `offsetof(instance, temperature)`. In a model with one or two
parameters such an error can land on the right bytes by luck — and every prior oracle test
used exactly such models.

`paramslots.va` interleaves 13 model and instance parameters of different types with
distinct non-round values, mirrors each through its own operating-point variable, and the
deck instantiates **three** instances across **two** model cards. The 39 readbacks cover
declaration defaults, model-card values, instance-line values, instance-overrides-model,
and the absence of any cross-instance bleed.

**Mutation test.** The slot index function is used by *both* the writer and the reader, so
permuting it is a self-consistent renaming and unobservable — only a **reader/writer
mismatch** shows, which is what E-290 was. Making `nth_opvar_ptr` read a different slot
than eval wrote produces `mp0 = 7.0` — its neighbour `ip0`'s value — and the guard fails.

### An honest limit, found by the mutation test

E-290 fixed **two** sites. The reachable one is `load_eval_output`, covered by this suite's
existing `ac_stim("ac", $temperature, 0)` check. The other, `nth_opvar_ptr`'s
`ParamKind::Temperature` arm, is **not reachable**: `ov = $temperature` lowers to a
computed eval-output slot instead. A reachability marker compiled into that arm and run
over all **326** corpus models was reached **zero** times. That arm therefore cannot be
covered by any runtime test; it is protected by the fix itself, and this suite does not
claim otherwise. Discovering that is what the mutation test was for — the first two
mutations I tried failed to trip the guard precisely because they hit unreachable or
symmetric code.

## Verification

`vafautodiff_examples` 16 → **18** checks; `vafcodegen_examples` 17 → **19** checks (both
solvers). Full dual-solver regression **237/237 OK**. No compiler source changed, so
`cargo test` and every `.osdi` are untouched.

## Scope

Two example suites (one new model, `paramslots.va`). No source, public interface, or OSDI
ABI change.
