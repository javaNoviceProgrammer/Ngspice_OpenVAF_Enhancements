# Enhancement-529: the ngspice OSDI layer, audited

**Scope:** the loader and its guards — the conformance audit's last area.
Two bugs (the broken v0.3 acceptance path, a phantom parameter row), the
OpenMP `@(initial_step)` divergence, a negative-multiplicity guard, and the
layer's deliberate bounds documented. (The audit's `$limit` load-failure
deviation was already fixed by E-520 and is re-pinned here;
`analysis("nodeset")` landed in E-528.)

**Suite:** [`examples/lrmosdi_examples/`](../examples/lrmosdi_examples/) —
10 checks, both solvers, including a spec-conformant fake v0.3 object
compiled by the suite itself. The full 440-suite sweep is ALL OK.

## v0.3 objects loaded and were misread (ngspice)

The loader kept an "original OpenVAF, must be version 0.3" path: an object
without `OSDI_DESCRIPTOR_SIZE` was accepted and then interpreted with
`sizeof(OsdiDescriptor)` — the EXTENDED in-repo struct. Three divergences
made that a trap, measured on a minimal but functional 0.3 object written
strictly against the published spec: the `OsdiNode` stride grew from 48 to
56 bytes (E-45's nodeset field), so every node record past the first was
misread — devhelp listed a terminal current named `i_V`, the second node's
NAME read from the first's *units* field; `osdiacld.c`/`osditrnoise.c`
read `num_ac_stim_src`/`noise_source_type` and friends past the 0.3
descriptor's end unconditionally; and 0.3's five-argument `load_noise` was
called with four, expecting E-54's paired densities. DC produced subtly
wrong metadata; `.tran` died with SIGSEGV and zero diagnostics.

Such objects are now **rejected** with a recompile-with-openvaf-r message,
the same honesty the openvaf-reloaded version gate applies. `osdi.h` drops
its stale "matches the OSDI specification" claim and the v0.3 CURR
constants in favor of an explicit divergence note, and README_OSDI gained
a "version support and deliberate bounds" section recording the removal.

## The phantom IFparm row (ngspice)

`osdi_create_spicedev` reserved one extra instance-parameter slot for the
synthesized `m` alias whenever the model lacked its own `m` — but
`write_param_info` only fills that slot when a parameter literally named
`$mfactor` exists. For a foreign descriptor without one, the table's last
row stayed zeroed: keyword NULL, id 0 — a `(null)` row in devhelp, one
strcmp from a crash for anything iterating `instanceParms`. The count now
mirrors the writer's condition. Unreachable for openvaf-r output (which
always emits `$mfactor`); reachable for exactly the hand-written-object
class the old 0.3 path admitted.

## The OpenMP branch never fired @(initial_step) (ngspice)

Enhancement-7's `EVAL_FLAG_IS_INITIAL_STEP`/`has_evaluated` gating lived
only in the serial branch of `OSDIload`; the OpenMP task called `eval()`
with the shared `OsdiSimInfo` and never set either, so an ngspice built
with `--enable-openmp` would never execute a Verilog-A `@(initial_step)`
block in any OSDI device. The task now takes a task-local copy with the
per-instance flag (one task per instance, race-free), verified by
compilation under `-DUSE_OMP` — the committed binaries carry no OpenMP.

## A negative multiplicity was applied silently (ngspice)

The parser layer (E-447) warns on a deck-written negative `m`, but `alter
@n1[m]=-2` reaches `OSDIparam` directly and the value was APPLIED: the
device's contribution sign-inverted — the audit's 1k resistor model
*sourced* +4 mA — and the compiled noise factor is `sqrt(m)`, so `.noise`
printed `onoise_spectrum = nan` with no diagnostic on any channel. A
negative value is now warned and ignored on every route. **Zero stays
silent and applied**: E-426 established `m=0` as the disable-this-instance
idiom shared with the built-ins — the first cut of this guard refused it
and the `inputguard`/`instknobs` suites caught the over-reach immediately,
which is exactly what they are for.

## Documented

README_OSDI's new section records the v0.3 removal, the ⚠️ `$bound_step`
floor of (tstop−tstart)/1e6 steps per model (E-504's knowing relaxation of
9.17.2's shall-clause, warned once per instance), the multiplicity rules,
and the 9.17.3 `$limit` fallback; the compliance doc carries the
bound_step ⚠️ beside its smallest-wins entry, and handbook §3.1 points at
both.
