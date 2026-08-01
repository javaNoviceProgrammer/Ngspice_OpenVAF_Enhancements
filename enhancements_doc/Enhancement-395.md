# Enhancement-395 — a constant random number, three mis-scaled filters, and six things the compiler should have refused

Nine defects from a one-hour hunt aimed at **openvaf-r**. Two produce wrong
numbers from code that compiles clean, five are input the compiler should have
rejected and accepted instead, one is a crash, and one turned out to be a
deliberate design trade that was merely undocumented and silent. A tenth finding was withdrawn
during the fix, and the evidence for withdrawing it is recorded below because it
is the more useful result.

## 1. `$random` and the whole `$dist_*` family return a constant inside a loop

```verilog
for (i = 0; i < n; i = i + 1)
    s = s + $dist_normal(seed, 0, sigma);
```

draws **one** number and adds it `n` times. Every distribution is affected —
uniform, normal, exponential, poisson, chi_square, t, erlang — under both the
`$dist_` and `$rdist_` spellings. A Monte-Carlo model written the obvious way
has exactly one sample of variation in it, and nothing said so.

The LRM makes `seed` an **inout** and prescribes advancing it in place, so the
obvious fix is to write the advanced seed back. **That fix was written, and then
withdrawn, because it is wrong.**

[Enhancement-10](Enhancement-10.md) made these builtins pure functions of
`(seed, salt)` with no persistent state *deliberately*, and left a design note
saying exactly why at the top of `openvaf/osdi/stdlib.c`: the draws must be
stable across the nonlinear solver's Newton iterations, and "an in-place
advancing seed, as the LRM nominally prescribes, would change every evaluation
and break DC/tran convergence."

That is not a theoretical objection. With the seed advancing, a model that
carries its seed across evaluations —

```verilog
analog begin
    @(initial_step) seed = 91;
    x = $rdist_normal(seed, 1.0, 0.5);
    I(p,n) <+ V(p,n)*1e-3*x;
end
```

— fails **dynamic gmin stepping, true gmin stepping, source stepping and the
transient operating point**, in that order, and the run aborts. The seed had
advanced to −1.8×10⁸ by then, which is also the direct proof that the variable
persists across evaluations. A first pass with `sigma = 0.01` appeared to
converge; that was tolerance masking, not success. **Trading a wrong number for
a simulator that does not converge is not a fix.**

So the purity stays and the *silence* goes. An RNG builtin inside a runtime loop
now raises the **`rng_in_loop`** lint, which names the call, states that the draw
is constant within the loop, states why it cannot be otherwise, and suggests a
separate call site per sample. It reuses the `loop_depth` counter that
[Enhancement-330](Enhancement-330.md) added for `ddx`, so it counts every loop
form rather than only those with a non-constant bound.

It is a **warning, not an error** — the code is well formed, and a model that
genuinely does not care can keep it. `(* openvaf_allow="rng_in_loop" *)`
silences it, and `openvaf_deny` promotes it.

**The lesson is the same one this release learned twice** (see the withdrawn
finding below): the site carried a comment explaining the design, and reading it
was cheaper than the fix. The difference is that here the comment was not enough
on its own — the convergence failure had to be measured before the naive fix
could be ruled out with confidence.

## 2. Three of the four laplace filters used unnormalised roots

LRM 4.5.11 defines the root forms as products of `(1 - s/r_k)`, so a filter
given by its roots has DC gain 1. `laplace_np`, `laplace_zp` and `laplace_zd`
built products of `(s - r_k)` instead — the same polynomial multiplied by
`prod(-r_k)`, which is a silently wrong DC gain. `laplace_nd`, which takes
coefficients rather than roots, was right, so **the four spellings of one filter
disagreed with each other**.

On `H(s) = (1 + s/1e5) / (1 + s/1e4)`, whose true DC gain is 1:

| form | gave | should give |
| --- | --- | --- |
| `laplace_nd` | 1.000e-03 | 1.000e-03 |
| `laplace_np` | 1.000e-07 | 1.000e-03 |
| `laplace_zp` | 1.000e-02 | 1.000e-03 |
| `laplace_zd` | 9.999e+01 | 1.000e-03 |

Each error is exactly the root product of whichever vector was given as roots.
With two poles instead of one the `np` error is 1e8.

A root **at the origin** is the LRM's own stated exception — it contributes a
bare `s` rather than `(1 - s/0)`. That case is handled explicitly now instead of
dividing by zero, and is pinned against the same filter written in the `nd` form.

### This one changes existing models, and that is stated rather than buried

It is the only change in this release that alters the meaning of source that
compiled before. A model written against the old behaviour supplied a numerator
pre-multiplied by the root product to cancel it, and that compensation is now a
double count. **This project's own examples did exactly that**, which is how the
size of the change is known:

- `complexpole_examples` asked for a resonant low-pass as
  `laplace_np(V(in), '{w02}, '{sig, wd, sig, -wd})`. Under the LRM the numerator
  is `'{1.0}`; the `'{w02}` was cancelling the un-normalised denominator. Its
  own oracle — *"|np − nd| < 1e-3 dB across the sweep"* — caught it immediately,
  failing by **272 dB, which is exactly w0²**, and now passes at **0.00 dB**.
- `laplace_examples` needed the same treatment in four models.

  **Left for the CI rebuild, stated rather than hidden:** that directory's
  committed `.txt` outputs are produced by `run_examples.sh`, which sources its
  binaries from the checked-in `bin/<os>/<arch>/` matrix — still the pre-E-395
  compiler until CI refreshes it. Regenerating them now would pair the new
  models with the old compiler and commit numbers from neither, so they are
  left untouched and will refresh on the next `bin/` update. (Its `_setup.sh`
  looked for `examples/bin` rather than the repo-root `bin/`, which had left the
  demo unrunnable; that one-line path is fixed here.)

The corpus is unaffected — no `VA_TEST` model uses a root form — but a user's
model may be, and the symptom is a DC gain off by the product of the roots. The
fix is to drop the compensating factor, exactly as the examples above show.

The alternative was to keep a known-wrong scaling because something depended on
it. The four spellings of one filter disagreeing with each other is not a
convention anyone can build on, and `laplace_nd` — the form with no roots to
normalise — was always the one telling the truth.

## 3. Runtime `$table_model` clamped where it should have extrapolated

With linear extrapolation requested (`"1L"` and friends), a query outside the
grid returned the end **value** rather than continuing the end **segment's**
slope — but only when the table came from runtime arrays.

A runtime table's arrays have a fixed declared size, so a model with fewer
distinct knots than slots leaves repeated abscissae, which
[Enhancement-391](Enhancement-391.md) compacts to the end of the array. The end
slope was taken from a segment chosen without regard to which knots were live,
so at the boundary it could land on one of those zero-width segments — and a
zero-width segment has slope 0, which is a clamp.

On `y = 2x` over `[0, 3]` held in a six-slot array with the top two slots
repeated:

| x | gave | should give |
| --- | --- | --- |
| 4.0 | 6.0 | 8.0 |
| 7.5 | 6.0 | 15.0 |
| −0.5 | 0.0 | −1.0 |
| −2.0 | 0.0 | −4.0 |

The end slopes now come from the first and last **non-degenerate** segments,
found by walking the segment list in the direction that makes the surviving
assignment the right one.

## 4. `$table_model` silently ignored five of the LRM's control codes

Tables 9-30 and 9-31 define interpolation codes `I`, `D`, `1`, `2`, `3` and
extrapolation codes `C`, `L`, `E`. Four of them — `2`, `D`, `I`, `E` — were
accepted and then quietly treated as something else, and a sub-string asking for
a **different extrapolation method at each end** (`"1CL"`) was accepted with only
one end honoured. A model asking for quadratic interpolation got linear and was
never told.

These are rejected now, each with a message naming what was asked for and what
to use instead, rather than being silently substituted. The implemented codes
keep working — whitespace inside a sub-string, the `;N` dependent-column suffix,
and per-dimension sub-strings such as `"1C,1L"` all still compile.

## 5. `$discontinuity;` with no argument crashed the compiler

The argument is optional in the LRM and defaults to degree 0. The lowering read
`args[0]` unconditionally.

## 6. An access function from a foreign discipline silently aliased the native one

`Zi(p,n)` on an `electrical` branch behaved **exactly** as `I(p,n)`, provided
the unrelated nature `ZCur` happened to declare `units = "A"`.

Access resolution asked `NatureTy::compatible`, and that function compares
**units strings and nothing else**. So it could tell a potential from a flow but
not which discipline the access function belonged to, and a genuine modelling
error compiled clean and simulated.

It asks `NatureTy::related` now — same base nature, which is the LRM's own rule
and was already implemented right next to `compatible`. That still admits every
legitimate use: a discipline's own access functions, and any nature *derived*
from them, since `nature MyPot : Voltage` keeps `Voltage` as its base.

This is the change in this release with the most reach, so it is the one the
corpus differential exists for — see Verification.

## 7. A genvar colliding with a declared name was not diagnosed

`genvar k` beside a `parameter k`, a `real k`, an `integer k` or an
`electrical k` was accepted, and which `k` the generate loop saw was not
something the source made visible.

## 8. Three instantiation validation holes left by Enhancement-392

[Enhancement-392](Enhancement-392.md) established that module instantiation was
unvalidated and closed the port-count, port-name and parameter-name gaps. Three
remained, each accepted in silence:

- a **duplicate named port** — `leaf i1(.a(p), .a(n));`
- a **duplicate named parameter** — `leaf #(.g(1e-3), .g(2e-3)) i1(...)`
- a connection list that **mixes positional and named form** — `leaf i1(p, .b(n));`

The mixed-form check discriminates on the presence of the dot, for the same
reason E-392 had to: `$mfactor` has no name child, so testing `name()` rather
than `dot_token()` misclassifies it.

## 9. A parameter and its `aliasparam` set to different values was silent

An OSDI parameter and each of its alias names are registered as separate
`IFparm` entries that all carry the **same `.id`**, so

```
N1 a 0 md w=1 width=4
```

writes one slot twice and one of the two spellings loses without a word. Setting
the same name twice does the same. Both are reported now, on the instance line
and on the model card.

The check lives in the deck parser (`INPdevParse` and `create_model`), so
`alter` — which legitimately re-sets a parameter after the deck is read — does
not come through it and stays silent. It is scoped to OSDI devices, because
`aliasparam` is a Verilog-A construct; no built-in device's parsing changes. An
instance line overriding a model-card default is a different thing and is
deliberately not reported.

### Why the model-card message does not name a winner

The instance-line message says the last value is used, because that is what
happens. The model-card message deliberately says only that one value takes
effect, because **the two channels on a card disagree**: a model parameter is
written straight through, so the last one on the card wins, while an
instance-parameter default is pushed onto `INPmodfast->defaults` with `wl_cons`
and therefore replayed in reverse, so the **first** one on the card wins.
Stating a rule there would have been wrong half the time.

## The finding that was withdrawn, and why that is the useful part

The tenth finding was that a parameter whose **default** lies outside its own
declared range is accepted without complaint —
`parameter real x = 0.0 from (0.0:1.0];` compiles.

That is deliberate, and [Enhancement-56](Enhancement-56.md) says so in a comment
at the site. Real compact models depend on it: `diode_cmc` declares

```verilog
parameter real CORECOVERY = 0.0 from (0.0:1.0];
```

and gates on `if (CORECOVERY > 0)`. The out-of-range default **is** the encoding
of "this feature is off". Range checking defaults would have rejected shipping
industry models to enforce a rule the LRM does not impose on defaults.

Checking the site's own comment before writing the fix was cheaper than the fix.

## Verification

`examples/langguard_examples` — **110/110 fixed, 66/109 against the shipped
binary**. Forty-four checks pin real defects; the count differs by one because
`$discontinuity;` crashes the shipped compiler outright, so its follow-on check
has nothing to run against.

Every check is paired. The reject half pins the defect; the accept half pins
that legitimate input still compiles **and still gives the same number** — the
laplace forms are compared against `laplace_nd` at every frequency in a sweep
rather than only at DC, the table is probed outside its grid in three different
knot layouts, and the aliasparam accept cases assert both silence and the value.

Two guards were added to the suite after they caught themselves: an AC check
whose deck had no `ac` stimulus made all four laplace forms read 0.0 and three
comparisons passed on `0 == 0`, so the checks now require a non-zero reference;
and the first table probe used a clean grid, which does not meet the defect's
condition and passed on both binaries, so it now probes the repeated-knot
layouts that actually reach the degenerate segment.

**Corpus differential.** Because (6) changes how every access function in every
model resolves, all 124 files of the `VA_TEST` industry corpus were compiled
with the shipped binary and with this one: **107 compiled by both, 0 return-code
differences, 0 byte differences**. Nothing that compiled before is rejected, and
the emitted `.osdi` is byte-identical for every model that does not use an
affected construct.

That result needed one correction to get. A first pass reported 107 byte
differences — because it gave the two binaries different `-o` paths, and an
`.osdi` embeds its own output path. Same path, or the differential is fake.

The same sweep also answers the question a new lint always raises: **no corpus
model trips `rng_in_loop`** (0 of 124), so the warning adds no noise to real
compact models.

Beyond the suite: `cargo test --workspace` **209/0**, full regression
**319/319**.
