# Enhancement-445 — nine silent failures made loud

A round of adversarial probing produced one crash and a set of paths that gave a
wrong answer, or refused a correct deck, without saying anything. They are
unrelated in mechanism but identical in shape: in every case the simulator
completed, returned 0, and printed nothing, so *"it ran"* was exactly the
problem.

Each fix below is paired with the sibling that was always handled correctly.
That pairing is the argument: it shows the guard already existed somewhere
nearby and only one path was missing it.

## A bare `.four` card crashed

```
.tran 1u 5m
.four
```

segfaulted — a NULL dereference in `fourier()`, reached from `ft_cktcoms`.

`dotcards.c` handles `.four` by skipping two tokens and, when nothing is left,
printing `Warning: no nodes given` and declining to save anything. What it does
not do is *drop the card*, so the empty command still arrives at `fourier()`,
which reads the fundamental frequency straight off the wordlist.

`.four` was the only one of 25 zero-argument dot-cards that died. `.print` and
`.plot` are handled a few lines above it, print the identical message, and were
always safe. The crash needed transient results to exist (with only `.op` or
`.ac` present the card is never evaluated) and it survived subcircuit
flattening.

## An overflowing `.four` fundamental frequency was accepted

`.four 1e400 v(nb)` overflows to `+INF`. The card was accepted and produced a
complete, authoritative-looking report:

```
  No. Harmonics: 10, THD: 201.971 %, ...
 1       inf         5.09663e-17 ...
```

against `THD: 1.91095e-11 %` for the valid case. A headline 202 % THD is a
number someone would act on, and the magnitudes behind it are numerical noise.

The validation around it was already thorough — `0`, `-1000`, `abc`, a literal
`inf`, a literal `nan`, and even `1e-400` (which *underflows* to 0.0 and is
caught by the `<= 0.0` test) were all refused. Overflow was the one hole, and
`!isfinite()` closes it.

## A comma in a device value silently changed it

```
R1 in nb 1,5k        ->  5000 ohm
```

not 1500 as a European decimal comma intends, and not 1000 either. `,` is a
token separator in SPICE, so the line parses as the value `1` followed by a
stray unlabeled `5k` — and an unlabeled trailing number *overwrote* the value
that had already been read.

That overwrite exists for a good reason: `R1 a b rmod 2k` gives its value that
way, after a model name. But there the value position held a name, so nothing
had been read yet. When a value *has* already been read, a second one is a
contradiction rather than an override.

The decisive evidence is that every other separator follows ngspice's documented
"parse the leading number, ignore trailing text" rule:

```
1;5  -> 1        1:5  -> 1        1_000 -> 1        1.2.3 -> 1.2
1,5k -> 5000                                        <- only the comma
```

Now the value written in the value position is kept and the contradiction is
reported. Applied to resistors, capacitors and inductors.

## An over-wide array instance collapsed to one device

Enhancement-441's array instances are capped at 8192 elements. Past the cap the
range failed to parse, and the line was then emitted unchanged — as a single
device literally named `r[0:8192]`:

```
R[0:8191]   -> 8192 devices,  v(a)=1.22055e-04   correct
R[0:8192]   -> 1 device,      v(a)=0.999001      9x wrong
R[0:19999]  -> 1 device,      v(a)=0.999001      21x wrong
```

all silent, all `rc=0`. The identical over-wide range in a *node* field already
produced Enhancement-443's warning; only the instance-name position was quiet,
because E-441 made `inp_expand_buses` skip an element line's first token, so the
malformed-token check never saw it.

The check is deliberately tight, and a lone `R[2]` is still an ordinary instance
name — a scalar bit is not a list, which is E-443's compatibility rule.

## `.option autobus` indexed tokens that cannot carry an index

The expansion appended the model's own bracket text to whatever token was
written, without asking whether that token could take one:

```
N1 0    b bd   ->  0[0] .. 0[4]        five ordinary FLOATING nodes, not ground
N1 a[0] b bd   ->  a[0][0] .. a[0][4]
```

Ground is the case that matters: tying a bus off is routine, and `0[i]` can
never be ground however it is spelled. With `b` driven at 1 V the correct
current is −1.9375 mA; the shorthand gave 5.4e−20 — the device contributing
nothing at all, with no diagnostic. The same line with the option **off** is
reported by Enhancement-402's under-connected warning, so switching the feature
on removed a diagnostic that the feature-off path already had.

Both are refused now, naming the real cause. Only *bus* ports are checked: a
scalar port is never indexed, so `0` or `a[0]` on one of those stays legal, and
an ordinary expansion is bit-for-bit unchanged.

## A failed `sweep` point published the previous solution

Enhancement-438 counted points whose analysis never solved and said so at the
end. But the *value* recorded for such a point was whatever the read-back
returned — and a failed run leaves the earlier plot in place, so that value is
the **previous solution**:

```
Rs=1k    pre-sweep v(nb)=0.5   failed rows = 0.5, 0.5, 0.5
Rs=250   pre-sweep v(nb)=0.8   failed rows = 0.8, 0.8, 0.8
Rs=4k    pre-sweep v(nb)=0.2   failed rows = 0.2, 0.2, 0.2
```

Three different priors, three different "results" — so this was the old solution
being republished, not a constant. On a plot it is a flat shelf that looks
physical, and `wrdata` wrote those rows with no marker at all, so a downstream
reader could not tell them from measurements.

They are now `NaN`. That keeps the array shape — every output stays aligned
against the sweep scale, which is precisely why E-438 declined to drop the
points — while plotting as a gap and writing as `nan`.

`montecarlo` was the guarded sibling all along: same cause, same binary, and it
already excluded failed samples and reported the exclusion.

## A legal 20-deep hierarchy was refused as "infinite subckt recursion"

`MAXNEST` bounded subcircuit nesting at 21 levels, and exhausting it reported
*infinite subckt recursion* — which a finite, strictly non-recursive chain does
not have. Confirmed a depth cap rather than a name-length one: the first failure
was at depth 20 for short and long names alike.

Real hierarchical designs reach that depth, so the limit is now 256. A finite
hierarchy costs exactly its own depth in passes — the loop stops as soon as a
pass expands nothing — so the headroom is only ever paid for by a pathological
deck, and genuine runaway recursion is still bounded by the existing
million-instantiation cap, which names recursion explicitly. The message no
longer asserts a cause it cannot distinguish.

## An iteration limit below the solver floor was silently discarded

`NIiter` raises any iteration limit below 100 to 100 — *"some convergence issues
that get resolved by increasing max iter"*. Enhancement-426 found that floor,
judged it deliberate and upstream, and left it alone. That judgement stands.

What was missing is that nobody was told. The value is stored, the `option`
command echoes it back verbatim, and the run ignores it: a circuit needing 13
Newton iterations still took 13 under `itl1=3`, with both convergence fallbacks
disabled. Raising a limit is the standard first move against a stubborn
operating point and lowering one is how a runtime budget is imposed — both did
nothing, quietly.

The floor stays; setting a limit below it now says so. It fires only for a limit
given explicitly, never for the shipped defaults (`itl2=50` and `itl4=10` are
themselves below the floor).

## Four working `.four` options were reported as unknown

`.option fourgridsize=10` moves the reported grid from 200 to 10 — and also
printed `Warning: unknown option 'fourgridsize'`. A warning that fires on a
setting the run then honours is worse than no warning: it teaches the reader to
ignore the check Enhancement-438 added.

`nfreqs`, `nperiods`, `polydegree` and `fourgridsize` are now registered.

The scope is deliberately just those four. Of the 179 names read through
`cp_getvar` in the sources, 176 are flagged this way, but most are shell
variables whose documented home is `set` in `.control` (`editor`, `helppath`,
the `pyplot_*` family); warning about those on a `.options` line is defensible.
These four control an analysis, belong with the deck, and are documented
alongside `.four`.

## One reported defect that was not one

An OSDI integer model parameter declared `from [1:inf)` accepts `n=0.5` as 1
while refusing `n=0.4`, which looks like a range check running after rounding.
It is not a defect. Enhancement-399 established that a netlist value assigned to
an integer parameter must round half away from zero, because that is what
Verilog-A does for the same conversion *inside* a model — before E-399 the two
disagreed at every negative half-boundary. `0.5` therefore becomes `1`, and `1`
is legitimately inside the declared range. Rejecting it would contradict E-399
and refuse LRM-conformant decks, so nothing was changed.

## Verification

**`examples/guardgaps_examples` — 59/59, both solvers.** Every fix is checked
together with the sibling that must not move:

* the crash is gone in all five shapes that triggered it, including inside a
  `.subckt`, and a valid `.four` still produces its analysis
* `1e400` and `1e309` refused; `0`, `-1000`, `inf`, `nan`, `1e-400` still
  refused; `1e30` still accepted
* `1,5k`, `9,1k`, `1k,9` keep the value position and warn — while `R1 a b rmod
  2k` still takes its trailing value, and `1k`, `1;5`, `1:5`, `1_000` are
  untouched and unwarned
* `R[0:8192]` and `R[0:19999]` refused; `R[0:3]` and the widest legal
  `R[0:8191]` still expand; a lone `R[2]` is still one instance
* hierarchies 20, 25, 60 and 200 deep accepted; a self-recursive subcircuit
  still refused and still terminating
* the three forbidden sweep points are `NaN` in both `print` and the `wrdata`
  file while the two legal points keep real values — and a *different* prior
  operating point yields the same NaNs, which is what proves the stale value is
  gone
* autobus refuses ground and an already-indexed token, while a normal expansion
  still matches its analytic value to ten digits and a scalar port tied to
  ground is untouched
* `itl1=3`, `itl2=5`, `itl4=1` announced; `itl1=100` and `itl1=200` silent
* the four `.four` options are not flagged, `fourgridsize` demonstrably still
  changes the analysis, and a genuinely unknown name is still flagged

**Full regression 357/357**, both solvers. Enhancement-438's suite asserted the
old wording — that a failed sweep point "reads back as 0" — and now asserts the
NaN behaviour instead.
