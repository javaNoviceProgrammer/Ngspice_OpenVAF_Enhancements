# OSDI implementation for NGSPICE

OSDI (Open Source Device Interface) is a simulator independent device interface, that is used by the OpenVAF compiler.
Implementing this interface in NGSPICE allows loading Verilog-A models compiled by OpenVAF.
The interface is fixed and does not require the compiler to know about NGSPICE during compilation.
NGSPICE also doesn't need to know anything about the compiled models at compilation.
Therefore, these models can be loaded dynamically at runtime.

To that end the `osdi` command is provided.
It allows loading a dynamic library conforming to OSDI.
Example usage: `osdi diode.osdi`.

If used within a netlist the command requires the `pre_` prefix.
This ensures that the devices are loaded before the netlist is parsed.

Example usage: `pre_osdi diode.osdi`

If a relative path is provided to the `osdi` command in a netlist, it will resolve that path **relative to the netlist**, not relative to current working directory.
This ensures that netlists can be simulated from any directory

## Build Instructions

To compile NGSPICE with OSDI support ensure that the `--enable-predictor` and `--enable-osdi` flags are used.
The `compile_linux.sh` file enables these flags by default.




## Version support and deliberate bounds (OSDI-layer audit)

* **Only openvaf-reloaded objects load** (`OSDI_DESCRIPTOR_SIZE` present,
  version >= 0.7). Original-OpenVAF **v0.3 objects are rejected** with a
  recompile message: the in-repo ABI diverged deliberately (node records
  carry a nodeset field, the descriptor grew ac_stim/absdelay tails,
  `load_noise` fills paired densities), and the old acceptance path read a
  spec-conformant 0.3 object through the new layout — wrong metadata in DC
  and a transient segfault with no diagnostics.
* **`$bound_step` is floored to (tstop−tstart)/1e6 per model** (E-504): a
  bound that would demand more than a million steps of the analysis window
  is overridden after a named warning, so a device cannot demand an
  unbounded step count. This is a knowing relaxation of LRM 9.17.2's
  smallest-active-bound rule, which otherwise holds (including
  several-bounds-take-the-minimum semantics).
* **A negative multiplicity `m`/`_mfactor` is warned and ignored** on every
  route, `alter` included (it used to be applied there — a negative m made
  the device source current and turned `.noise` spectra into silent NaN via
  the compiled `sqrt(m)` noise factor). `m=0` stays silent and disables the
  instance, the established idiom shared with the built-ins (E-426/E-447).
* An unknown `$limit` function name falls back to **no limiting** with a
  warning, per LRM 9.17.3 (E-520).
* **A collapse chain that shorts two terminals becomes a real 0 V source**
  (E-532): ngspice cannot merge terminal nodes, so `V(a,m)<+0; V(m,b)<+0`
  (m internal) used to lose the second merge silently — the device fell
  open where the direct `V(a,b)<+0` spelling shorted correctly. Every
  refused terminal-terminal or terminal-ground merge is now stamped as a
  synthetic ideal 0 V source (all analyses, both solvers, `sens`'s
  double-setup included), and the same rewrite fixed two latent merge
  bugs: a re-merged ground group is no longer un-grounded, and a redundant
  hint inside one collapse group no longer corrupts the node count.

## Automatic Monte-Carlo: `.option osdimc`

A Verilog-A parameter compiled with statistics attributes —
`(* std=<sigma> *)` (absolute), `(* std_rel=<fraction> *)` (relative to the
nominal), optionally `(* dist="gauss"|"uniform"|"lognormal"|"tgauss" *)`
(gauss default; for uniform the value is the half-width; a lognormal, alias
`lnorm`, draws `nominal·exp(s·z)` with `std_rel` the sigma of the logarithm
and an absolute `std` converted at the nominal; `tgauss` is gauss with
`trunc=3`) and `(* trunc=<sigmas> *)` (the Gaussian coordinate confined to
±trunc by deterministic rejection; no effect on a uniform) — carries its
variability in the `.osdi` object itself, through the
`OSDI_STAT_PARAM_{COUNTS,INFOS}` side-table and, for a truncation, the
optional `OSDI_STAT_PARAM_TRUNCS` array beside it (the same mechanism as the
absdelay tables, so the descriptor ABI is unchanged and objects without
statistics simply lack the symbols; an object without a truncation lacks
the TRUNCS symbol and a simulator that does not know it draws untruncated).

With `.option osdimc` (alias `automc`) set, every run-class command starts
a fresh trial: each statistical parameter is written nominal + draw through
the ordinary parameter setter — **no `reset`, no netlist re-expansion, no
`gauss()` expressions in the deck**. Semantics:

* the **first run after sourcing is the nominal baseline** (defaults of
  parameters the deck never set are only knowable after one setup pass);
  draws begin with the second run;
* a **model parameter** is drawn once per model card per trial (process:
  instances sharing the card move in lockstep, distinct cards draw
  independently); an **instance parameter** (`(* type="instance" *)`)
  draws independently per instance (mismatch);
* draws are **pure functions of (mcseed, trial, owner name, param id)** —
  `.option mcseed=42` makes whole ensembles bit-reproducible, with no
  hidden RNG state; `resume` never redraws;
* `alter`/`altermod` of a statistical parameter **recenters its nominal**
  (machine writes -- `.dc` parameter sweeps, `sweep` points/restores,
  sensitivity perturbations -- deliberately do not, so a sweep can never
  shift the distribution); turning the option off restores every drawn
  parameter to nominal on the next run; a non-finite draw (sigma too large)
  is refused with a named warning; a failed trial is flagged in-band and
  its range error names the model, the value and (E-558) the declared
  range with the current value of every parameter it reads —
  `Parameter l of 'mm' is out of bounds (value 1.2; range from [lmin:inf),
  lmin = 1.5)`; `.option osdimc_verbose` prints every draw;
* a draw violating the parameter's Verilog-A `from` range fails that run
  with the device's own range error, exactly as the same `alter` would —
  the descriptor does not export ranges, so size sigmas accordingly;
* (Enhancement-555) a parameter the model tests with `$param_given` is drawn
  **only when the deck gives it**: a draw is a write, a write marks the
  parameter given, and a model that derives an ungiven parameter (BSIM4's
  `toxp = toxe - dtox`) would switch to its "given" branch instead of
  varying. The compiler flags such parameters in the side-table
  (`OSDI_DIST_GATED`); the simulator skips them and says so once. The same
  enhancement exports a per-descriptor given-flag entry point
  (`OSDI_PARAM_GIVEN_FNS`, read/set/clear; the descriptor ABI is unchanged,
  an older object simply has none), through which a `.dc` sweep, the `sweep`
  command and `unset osdimc` put the flag back as they found it.

Verified end to end by `examples/osdimc_examples/` (measured gauss
mean/sigma, uniform bounds, relative sigma, mismatch independence,
determinism, recentering, restore-on-disable).
