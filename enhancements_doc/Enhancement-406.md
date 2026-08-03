# Enhancement-406 — the flow probe that shorted the branch it measured

Two 1 kΩ sections in series draw 0.5 mA. Adding one line that only *reads* a
current made them draw **1.0 mA**, with `rc=0` and no diagnostic:

```verilog
branch (a,mid) br;
analog begin
    I(a,mid) <+ 1e-3 * V(a,mid);
    I(mid,c) <+ 1e-3 * V(mid,c);
    iprobe = I(br);          // <-- doubles the terminal current
end
```

| probe spelling | `i(v1)` |
| --- | --- |
| `I(a,mid)` — the same spelling used to contribute | −5.0e−4 |
| `I(br)` — a declared branch over the same nodes | **−1.0e−3** |

A probe changed the circuit. That is the whole defect.

## Why, and why the semantics are *not* wrong

A declared `branch (a,mid) br` and the node pair `(a,mid)` are **different
branches**. Probing the flow of a branch nothing contributes to turns it into an
**ideal ammeter** — a 0 V source — which is a real feature (Enhancement-36) and
documented in the LRM compliance notes: *"probing a branch that is never
contributed to reads its true flow (an ideal ammeter) instead of the
0-and-open-circuit a naive topology gives."*

Put those together and the trap follows: contribute through one spelling, probe
through the other, and the ammeter lands **in parallel with** the real branch and
shorts it.

Three independent checks say the separation is deliberate and consistent, not a
bug to be merged away:

* the DAE keys `BranchWrite::Named(..)` and `Unnamed { hi, lo }` as distinct
  unknowns;
* the E-400 contribution map's `same_branch` returns false across the two, and
  measurement agrees — `V(br) <+ 0.4` alongside `I(a,mid) <+ 1e-3` yields 0.4, a
  voltage source in parallel with a current source, and raises **no** discarded
  contribution lint. Same-spelling pairs *do* raise it;
* the compliance notes document the ammeter as intended behaviour.

**So this release adds a diagnostic and changes no semantics.** Merging the two
branch kinds would break a documented feature; silently keeping the trap was the
actual defect.

## The lint

`probe_only_branch_short` (**L023**, warn by default) fires when a branch's flow
is probed, the branch has **no contribution of its own**, and **another branch
spanning the same node pair is contributed to**.

```
warning[L023]: in module `m`: branch `br` is probe-only and shorts `(a,mid)`
   |
10 |         I(a,mid) <+ 1e-3*V(a,mid);
   |         -------------------------- `(a,mid)` spans the same nodes and is driven here
12 |         iprobe = I(br);
   |                  ^^^^^ `br` is probed here, but never contributed to
   |
   = probing the flow of a branch nothing contributes to makes it an ideal ammeter
     -- a 0 V source -- so `br` is a SHORT across (a,mid), in parallel with `(a,mid)`
   = a declared branch and the node pair it spans are DIFFERENT branches, so `br`
     and `(a,mid)` do not refer to the same thing
   = help: probe the branch that is driven -- write the flow probe with the same
     spelling used to contribute -- or contribute to `br` as well if the short is intended
```

**That third clause is the reason the naive rule is wrong.** "Warn on any
probe-only branch" would flag the deliberate sense-ammeter idiom, where nothing
else drives the pair and the short *is* the intended circuit — **six** branches
across the shipped corpus rely on it. Requiring a driven branch over the same
nodes separates the mistake from the idiom exactly.

Node order is normalised, so `branch (mid,a) br` against `I(a,mid) <+ ..` is
caught too, and both directions of the mistake are (probe named / contribute
pair, and the reverse).

## No MIR needed

The check lives in `sim_back::module_info`, beside module collection, and never
touches the DAE. Both facts are already in the HIR: E-400 collects contributions,
and a new `Module::flow_probe_sites` collects flow probes, mirroring the branch
resolution `hir_lower` performs for `BuiltIn::flow` so a probe is attributed to
exactly the branch the backend will key its unknown on. A branch present among
the probes and absent from the contribution map **is** the probe-only case the
DAE would later hand an ammeter.

Doing it there rather than in the DAE buys the label that matters: the report
points at the **probe**, not at the correct code around it. Two details were
needed to make that work — lint attributes attach to statements rather than
expressions, so each probe is anchored on its innermost enclosing statement (so
`(* openvaf_allow="probe_only_branch_short" *)` works on the probing statement
and every enclosing scope); and a named branch declared over a **port**
(`branch (<p>) name;`) is skipped, because lowering routes it to the port's own
flow and it can never be probe-only.

## Verification

* **Fires** on both directions of the mistake and on reversed node order.
* **Silent** on: the same spelling used for both, the deliberate sense ammeter, a
  declared-but-never-probed branch, a potential-only probe (`V(br)` cannot short
  anything), a port-flow probe, and a module with no branches at all.
* **Zero false positives** over every `.va` file this repository ships — 640
  files, 552 compiling — so any future firing is signal.
* Lint controls all work: `--allow` silences, `--deny` gives `rc=65`,
  `(* openvaf_allow=".." *)` on the statement silences, `--lints` lists it.
* **Full regression 322/322**, **`cargo test --workspace` 210/0**, **corpus
  differential 107 compiled by both, 0 return-code and 0 byte differences** — this
  release changes what the compiler says, never what it emits.

## Found by

Digging into the tenth finding of the Enhancement-405 hunt, which recorded it as
*"probing `I(br)` … inserts an ammeter that shorts it — the DC solve fails"*.
**That description was wrong in the direction that matters.** The failed solve was
an artifact of the probe circuit used at the time, which put a voltage source
directly across the shorted branch. In an ordinary topology nothing fails — the
answer is simply wrong, which is strictly worse and is why this got a lint rather
than a footnote. The E-405 write-up is corrected accordingly.

Also observed while measuring, and **not** addressed here: the deliberate
sense-ammeter case draws `trivial_probe` (**L017**, *"Current probe always returns
zero"*), whose message predates E-36 giving such a probe its true flow. The
wording looks stale, but it is a separate question with its own history and is
left alone rather than changed in passing.
