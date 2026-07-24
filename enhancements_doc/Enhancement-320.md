# Enhancement-320 — `.param` fast-sweep (skip the per-point reset)

## The cost

Sweeping a netlist `.param` is slow because a `.param` has no live binding into
the built circuit. numparam resolves parameters **at parse time**, folding each
`{expr}` on a device line into a fixed numeric literal; once the circuit is
built the device holds a plain number with no back-pointer to the symbol. So the
only way the `sweep`/optimize machinery can change a `.param` is `alterparam`
(rewrite the deck text) followed by **`reset`** — a full teardown and re-source:
re-parse the deck, re-expand subcircuits, re-run `CKTsetup`, and **re-order the
sparse matrix** — at *every* sweep point, even though the topology never changes.

By contrast an *instance/model* parameter (`@R1[resistance]`) can be poked in the
live circuit with `alter`/`altermod` and the next analysis reuses the node table,
the matrix ordering, and the symbolic factorization. Enhancement-320 lets a
`.param` sweep take that same in-place road whenever it is safe to.

## The fast path

When every swept `.param` feeds **only addressable top-level device/model
values**, `com_sweep` now, per point:

1. overrides the swept symbol(s) in the retained numparam dictionary
   (`nupa_add_param`) and refreshes the derived-parameter closure
   (`nupa_recompute_params` replays the dependent `.param` lines);
2. re-evaluates each captured device value expression against that dictionary
   (`nupa_eval_expr` → the numparam `formula()` evaluator); and
3. pushes the fresh value into the live instance with a resolved direct set
   (`ft_sim->setInstanceParm`, i.e. `CKTparam` → `DEVparam`), then refreshes each
   touched device type's derived state once (`DEVtemperature`, mirroring the
   Enhancement-62 `.dc @inst[param]` path).

No reset — the matrix structure, ordering, and factorization pattern are all
preserved. The template is the existing `temper` machinery (a temperature-
dependent device value re-evaluated and `alter`-ed in place at every `.dc` step);
the difference is that a parse tree cannot re-read an arbitrary `.param` cell
(only `time`/`temper`/`hertz` bind to live circuit storage), so re-evaluation
goes through numparam rather than `IFeval`.

Two optimizations keep the per-point work minimal: each `@dev[param]` target is
resolved to its `(instance, param-id)` **once** at arm time (no per-point lexing
or device-list walk), and identical value expressions are grouped so each
**unique** expression is evaluated once per point (a swept param typically feeds
many identically valued devices).

## Correctness — conservative by construction

The path **arms only** when a scan of the original (pre-expansion) deck finds
every occurrence of every swept param to be a top-level device/model value slot
(a positional principal value, or a `key={expr}` named parameter). It **disarms
and falls back to the exact reset path** on any of:

- a swept param used inside a `.subckt` … `.ends` body (its expression is not
  retained past subckt flattening);
- a structural use — the param in a node position, an instance/model/subckt
  name, a subckt call (`X`) argument, `.if`/`.elseif`, `.temp`, an analysis card
  (`.tran`/`.dc`/`.ac`/`.step`/…), `.option`, `.ic`, `.nodeset`, or `.global`;
- a **derived** parameter (a non-swept `.param` whose definition references a
  swept one);
- any value slot it cannot classify with confidence.

Because a disarm reproduces today's behaviour exactly, the feature can only ever
*speed up* a sweep, never change its result.

## Measured speedup

A 2500-stage resistive ladder, 120-point `.param` sweep:

| Case | reset path | fast path | speedup |
|------|-----------:|----------:|--------:|
| param feeds ONE device in a large circuit (typical) | 2.91 s | 0.26 s | **11.1×** |
| param feeds ALL 5000 devices (worst case) | 3.42 s | 1.33 s | 2.6× |

The fast path matches the reset path to `~7e-9` (the only difference is
numparam's value-string formatting; the underlying doubles are identical), and
the subckt fallback is bit-for-bit identical.

## Scope

Implemented for the `sweep` command; instance values take the fast direct set,
model values use the textual `altermod` fallback. Subcircuit-internal param
expressions, and the optimizer/Monte-Carlo `.param` reset sites, remain on the
reset path (Monte-Carlo genuinely needs a re-draw; the others are future tiers).

## Files

- `ngspice-46/src/frontend/com_sweep.c` — classifier, capture, resolve, and the
  in-place apply; the fast-path branch in the point loop.
- `ngspice-46/src/frontend/numparam/{spicenum.c,xpressn.c,numparam.h,numpaif.h}`
  — `nupa_eval_expr` (evaluate a bare expression against the active dico) and
  `nupa_recompute_params` (replay the derived-`.param` closure).
- `examples/paramfastsweep_examples/` — arms + closed-form correctness + subckt
  fallback (`verify_paramfastsweep.py`, 3 checks).
