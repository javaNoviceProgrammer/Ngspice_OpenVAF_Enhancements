# Enhancement-539: the second LRM audit's findings, worked — and one of them withdrawn

**Scope:** the 2026-09-02 re-audit
([`docs/audits/`](../docs/audits/2026-09-02_LRM-audit-round2.html)) raised six
findings. **Five are fixed here**; the sixth is **withdrawn**, because it was
never a defect and the audit was wrong to call it one. Two of the five had been
documented as deliberate deferrals — the reasons they were deferred are dealt
with rather than ignored, which is what let them be fixed now.

**Suites:** [`examples/lrmio_examples/`](../examples/lrmio_examples/) is new
(**17 checks**, both solvers). Against the previously shipped binaries the same
suite scores **6/17**, so every check discriminates. Full sweep ALL OK.
**openvaf-r changes** (first compiler change since E-534).

## The withdrawal comes first

The audit's headline claim was that `$random`'s seed never advances, so a
sampling loop "silently returns one value N times" — and it listed the defect
among three that produce "wrong numbers **with no diagnostic on any channel**".

Both halves of that are wrong, and in a way worth recording:

* The behaviour is **deliberate and documented**. `hir_lower/src/expr.rs`
  marks it a "DELIBERATE DEVIATION from LRM 9.13.1's inout seed", because a
  seed that advances in place returns a different value on every Newton
  iteration and **destroys convergence**. Enhancement-10 §1 and
  `examples/rng_examples/README.md` say the same. The estimator the LRM
  describes assumes a procedural language; a seed read inside a residual
  evaluation that is re-run to convergence is a different problem.
* It is **already diagnosed**, loudly, by default. Compiling the audit's own
  repro deck emits lint **L019**:

  ```
  warning[L019]: `$rdist_uniform` inside a loop draws the same number every iteration
     |         x = $rdist_uniform(s, 0.0, 1.0);
     |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^ constant within the loop
     = the statistical builtins are pure functions of (seed, salt) ...
     = this is deliberate: a seed that advances in place ... would break DC/transient convergence
     = help: to vary a draw per iteration, use a separate call site per sample ...
  ```

The audit reproduced the *behaviour* against the simulator and never read the
compiler's own output, so it reported a diagnosed, intentional design as an
undiagnosed defect. Nothing is changed here; the audit page is corrected
instead. `%m`, the multichannel descriptor and `$fscanf`'s line read were also
pre-documented (E-417, E-516, E-11) and the audit presented all three as new —
those *were* genuine divergences, so they are fixed, but the write-up claiming
they were undiscovered was not accurate either.

## `%m` names the instance (LRM 9.4.4)

The clause exists for exactly one purpose — "when there are many instances of
the module ... `%m` **pinpoints the module instance** responsible" — and one
module instantiated four ways printed the same string every time, because
`%m` expanded at compile time to the *module* name.

Enhancement-417 recorded this as **"deliberately NOT fixed"**, and its reason
was real: the clean fix needs a callback slot the simulator fills in at load,
and "a model compiled by a new `openvaf-r` and run on an older ngspice would
therefore call NULL". That is the E-396 hazard, and it is a good reason not to
ship a naive fix.

It is not a reason to leave `%m` broken, because **the null check can live in
the model**. `osdi_inst_name(handle, fallback)` in `stdlib.c` tests the slot
before calling through it and returns the module name when it is unset — so a
new model on an old simulator gets precisely today's behaviour, and the
crash the deferral was protecting against cannot occur. Measured on the audit's
own four-instance deck:

| | before | after |
|---|---|---|
| `na` | `m=fmt` | `m=na` |
| `nb` | `m=fmt` | `m=nb` |
| `x1.nsub` | `m=fmt` | `m=n.x1.nsub` |
| `x2.nsub` | `m=fmt` | `m=n.x2.nsub` |

Hierarchical names come out hierarchical, which is what the clause asks for.

## Multichannel descriptors are one-hot bits (LRM 9.5.1)

The LRM defines two descriptor kinds and the difference is load-bearing:
`$fopen(name, mode)` yields a **file descriptor** "with the most significant
bit set", while `$fopen(name)` yields a **multichannel descriptor**, "a 32-bit
integer in which a single bit is set", whose bit 0 "**always** refers to the
standard output" and which may be combined "by **bitwise OR-ing**".

Both came from one namespace of consecutive small integers, so:

* `$fopen("a")`→1 and `$fopen("b")`→2 made `$fdisplay(mA|mB, …)` compute **3**
  — the descriptor of an unrelated *third* file, which silently received the
  text meant for both. E-516 recorded this as "documented-missing"; a write
  landing in the wrong file is worse than missing, which is why it is fixed
  rather than re-deferred.
* The first user file was handed descriptor **1**, the value the LRM reserves
  for stdout, so `$fdisplay(1, …)` before any `$fopen` produced nothing.

Now a file descriptor is its slot with `OSDI_FD_BIT` set (slots 0–2 being the
pre-opened standard streams), and a multichannel descriptor is a one-hot bit
indexing a separate table. The write path fans out over the mask, and
`$fclose` on a mask closes every channel in it. Measured: `mA`=2, `mB`=4,
`$fdisplay(mA|mB, "BOTH")` writes **BOTH** to both files, and `$fdisplay(1, …)`
reaches stdout.

## `$fscanf` leaves what it did not consume

`$fscanf` is lowered as "read a line, then scan it like `$sscanf`", so it
consumed the **whole line** however little the format matched, and the ordinary
"scan the numbers, take the trailing label" idiom lost everything after the
last conversion. On `10 1.5 alpha / 20 2.5 beta`, a `$fscanf(fd,"%d %g",…)`
returning `iv=10 rv=1.5` was followed by a `$fgets` yielding **`20 2.5 beta`** —
the *next* line, with ` alpha` gone.

The line read now records where the line began (a distinct `FgetsScan`
callback, because `$fgets` proper is specified to consume the whole line and
must **not** do this), and each field scanner leaves the descriptor at the
first byte the format did not take. That deliberately does not fire for a plain
`$fgets` followed by `$sscanf` on the returned string: the check verifies that
pair still reads the *next* line, since the `$fgets` legitimately consumed the
whole of the previous one.

## `$fclose` + `$fopen` rewinds (LRM 9.5.1)

Opening a file for reading starts at byte 0. Measured on a three-line file:
open, `$fgets` → line 1; `$fclose`; open again, `$fgets` → **line 2**. The
same-name dedup in `osdi_fopen` returned the live handle with its position
intact, and the branch that re-opened properly was gated on *unmanaged* I/O —
which is never the case under the simulator.

A reopen after a close now rewinds and cancels the deferred close, so the
stream is not shut under the reader that just opened it. The guard is narrower
than the first attempt: it applies only when the stream is **already
readable**, because reopening a write-mode stream for reading is a mode change
that needs a real `freopen` — seeking a `"w"` handle back to zero leaves it
just as unreadable as it was. The first version of this fix missed that and
broke the write-then-reopen-to-read round trip in `stringio_examples`, which
is why that distinction is now pinned by a check.

## A nature's `abstol` reaches the convergence test (LRM 3.6.1)

`abstol` is "the absolute tolerance ... used to determine convergence" for
signals of a nature. The compiler has always written each nature's declared
value into the `.osdi` nature tables — **and nothing in ngspice ever read
them**. Every node was judged by the circuit-wide `abstol`/`vntol` whatever its
nature declared, so a model asking for `1p` on a charge node got `1e-12`'s
worth of care only by coincidence: too loose converges early on a wrong answer,
too tight refuses to converge, and neither said anything.

No ABI change was needed — the data was already in the file. The loader now
reads `OSDI_NATURES` / `OSDI_DISCIPLINES` / `OSDI_ATTRIBUTES`, resolves each
node's unknown to its nature (directly, or through its discipline's
potential/flow, walking the parent chain so a **derived** nature inherits per
LRM 3.6.1.1), and stamps the value on the `CKTnode`. `niconv.c` prefers it over
the global tolerance. Measured on the audit's nature deck, under `ngdebug`:

```
OSDI: node 1 convergence abstol = 1e-06 (declared by its nature)
OSDI: node 3 convergence abstol = 1e-12 (declared by its nature)
```

— the `myvoltage` potential (`abstol = 1u`) and the `mycurrent` flow
(`abstol = 1p`), each resolved through its discipline.

Because the data was already in the file, this works for **models compiled
before this change**: the same `.osdi` built by the previously shipped
`openvaf-r` produces the identical two lines under the new ngspice. Nothing has
to be recompiled to get the tolerance a model always declared.

Two properties are deliberate. A node where several models meet keeps the
**tightest** declared value, because a shared node must satisfy the strictest
claim made about it. And a node no model makes a claim about is left at zero,
so the circuit-wide tolerance applies to it exactly as before — though as the
next section explains, that is rarer than it sounds.

### An explicit `.option` still wins, and that is not a detail

The trap here is that **`disciplines.vams` declares `abstol` on the standard
natures too** — `Voltage` is `1u` and `Current` is `1p` — so this does not
apply only to exotic models: it applies to every OSDI node in every deck.
Those two values happen to equal ngspice's own `vntol`/`abstol` defaults, so by
themselves they change nothing.

They stop being harmless the moment a user *loosens* a tolerance. Setting
`.option vntol=1e-4` to get a stubborn circuit to converge is ordinary
practice, and a first version of this change silently pulled every OSDI node
back to the discipline's `1u` — defeating the option, from a declaration the
user never wrote and probably never read. So the nature's value is used **only
where the user has not set that option**; an explicit `vntol`/`abstol` wins.
Measured, on a nature declaring `1e-9`:

| deck | effective tolerance at the node |
|---|---|
| no option given | `reltol·\|v\| + 1e-9` — the nature governs |
| `.option vntol=1e-4` | `reltol·\|v\| + 1e-4` — the user governs |

Carrying that fact required one repair on the way. ngspice already records
which tolerance options the user set (`TSKtolGiven`, from E-110), but the
analysis task **inherited every tolerance value from the default task and then
cleared the flags saying which of them were the user's** — so a `vntol` given
in the deck arrived at the solver with the right *value* and no memory of who
chose it. The flags now travel with the values they describe.

E-110's own preset rule is not affected either way: a preset and the explicit
options are applied to the same task, so an explicit `.option` already won
there, and no deck was found where the cleared flags changed a result. The
change is what makes the record usable downstream, which is what the tolerance
lookup above needs.

## Two existing checks asserted the old behaviour

Both were updated with the reason rather than worked around, because in each
case the *test* was encoding the defect:

* `display_examples` pinned `"%m prints the module path"` against
  `mod=dispkinds`. It now requires the **instance** path and that the module
  name does **not** appear.
* `lrmfuncs_examples` pinned `FTELL 19` after a `$fscanf` of `"42 3.5\n"` —
  the position reached by consuming the whole line. It is now **18**, the
  trailing newline left unread, which is exactly where C's own `fscanf` stops.

## One repair to the changelog build, found by folding this

Adding a row to the ngspice change report made its PDF build fail with *"2
index row(s) are CLIPPED"* — and the guard was right. The report's index table
**restarts twice**: once after a prose paragraph with no blank line between
them, and once after a blank line with no header row. Neither restart is a
table to pandoc, so every row from E-296 onward — two thirds of the index —
was swallowed into a paragraph, and `INDEX_LUA`, which exists precisely to
turn that index into a page-breakable definition list, never fired on any of
them. E-537's closing sentence was genuinely absent from the shipped PDF.

Both restarts now carry a header and delimiter, so the whole index is a table
again. The build verifies **356** ngspice and **193** openvaf index rows render
in full, where it previously checked a fraction of that and passed rows it was
not really seeing.

The verifier itself needed one fix to be trusted: it strips a page-number line
from the end of each page, because concatenating pages otherwise splices the
number into a sentence that straddles the break — but pymupdf does not always
return that number last, and a page whose body began mid-sentence returned it
*first*. Both ends are stripped now. A guard that cries wolf is worse than no
guard: it teaches the next person to reach for `SKIP_PDF_VERIFY`.

## Compatibility

The descriptor encoding changes, which is visible to a model that *prints* a
descriptor. Nothing in the suites does, and the failure-test idiom is
unaffected: `$fopen` still returns **0** on failure and every success is
non-zero. A model testing `fd > 0` would be affected, since a file descriptor
is now negative as a signed integer — no such idiom exists in the tree, and it
was never portable, the IEEE 1364 encoding this now follows having always had
the high bit set.

On the ngspice side both additions are optional-symbol lookups: an `.osdi`
built by an older compiler exports neither the `%m` callback slot nor, in
general, the nature tables, and is handled exactly as before.
