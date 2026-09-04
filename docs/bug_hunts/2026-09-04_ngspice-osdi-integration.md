# Bug hunt — the ngspice/OSDI integration, one hour of probing

**Date:** 2026-09-04 · **Commit under test:** `c0f6e5c2` · **Binaries:** locally
built `OpenVAF-master-20260610/target/opt/openvaf-r` and
`ngspice-46/build/src/ngspice` (the tree's own `--disable-openmp --enable-klu`
configuration).

A timeboxed hunt over the *simulator side* of OSDI: analyses, parameters,
topology, temperature, state across analyses, and the device registry. The
method throughout was the one the previous hunts settled on — **never judge an
OSDI result on its own; build the built-in control and put the two on the same
netlist**. Every number below was measured against a built-in device, an
explicit hand-built equivalent, or an analytic value.

**Result: four findings, one unreproducible code defect, one design fragility,
and two non-OSDI simulator gaps.** None of them is a wrong number in
an analysis: the numerical integration between ngspice and OSDI came through
every probe exact. What broke was at the edges — the device registry, the
netlist parameter parser, and a diagnostic that names the wrong cause. F1 and
F2 were fixed the same day.

> **Reviewed 2026-09-04, after the fixes.** Every finding was re-run against
> the tree and its claims checked against the source. Four statements did not
> survive and are corrected in place, each marked *"Review:"* — F3 was
> overstated (an array parameter *can* be set from a card, per element; only
> the whole-array spelling is refused), F1's keyword list was incomplete, F4's
> `i_p` note claimed a current became unreachable that `show` still lists, and
> the long-label noise vectors are separate rows that share one name rather
> than merely "truncated for display". A second pass added a fifth: N2's
> "`.lib` is the special case" — `.include` on line 1 behaves identically, and
> the entry now records the actual rule and a no-fix verdict. The measurements
> in *What was measured and holds* reproduced as recorded.

| # | finding | severity |
|---|---|---|
| [F1](#f1--a-module-named-like-a-built-in-model-type-is-dropped-and-the-deck-may-simulate-the-built-in-instead) | a Verilog-A module whose name is a built-in model-type keyword is dropped; the deck either aborts with an unexplained error or **simulates ngspice's built-in device instead** | medium — wrong device, run completes. **Fixed** |
| [F2](#f2--two-modules-whose-names-differ-only-in-case-collapse-into-one-silently) | two modules in one `.osdi` whose names differ only in case collapse into one — **the second is unreachable and every deck asking for it silently gets the first**, with no diagnostic at all | medium — wrong device, nothing said. **Fixed** |
| [F3](#f3--an-array-parameter-cannot-be-set-from-a-netlist-card-and-the-card-says-it-does-not-exist) | the whole-array spelling `tab=[1 2 3]` — the one the card parser's own comment says OSDI cards use — is refused as "unrecognized parameter", and the card never names the per-element form that works (`tab[0]=1 tab[1]=2 ...`); the model card then runs on with defaults | low — **downgraded on review**: the parameter is settable per element on both card types |
| [F4](#f4--the-collapse-change-warning-blames-temperature-for-a-parameter-sweep) | the node-collapse-changed warning blames temperature and prescribes a temperature remedy when the trigger was a `.dc` parameter sweep | low — diagnostic quality |
| [F5](#f5--the-deferred-message-and-monitor-buffers-are-unsynchronised-under---enable-openmp) | the deferred `$strobe`/`$monitor` buffers are file-scope globals mutated from inside `#pragma omp task` | **unreproduced here** — code reading only; this tree builds `--disable-openmp` |
| [F6](#f6--monitor-change-detection-is-positional) | `$monitor` change detection keys on the *position* of the message in the flush, not on its instance and call site | observation — fragility, not a demonstrated defect |
| [N1](#n1-not-osdi--the-documented-temp-t1-t2-t3-list-form-is-not-implemented) | `.temp 50 100` rejects the whole card and runs at 27 °C | low, **not OSDI** — the built-in control behaves identically |
| [N2](#n2-not-osdi--a-title-line-beginning-with-lib-is-parsed-as-a-library-include) | a deck whose title line begins with `.lib` dies with `exit(1)` before anything runs — `.include` behaves identically; file directives are executed wherever they appear | low, **not OSDI**, **no fix** — stock reader behaviour, and the better rule for the common forgotten-title mistake |

---

## F1 — a module named like a built-in model type is dropped, and the deck may simulate the built-in instead

Compile a Verilog-A module called `diode` — a name a real model library would
plausibly use — and load it:

```verilog
module diode(a, c);
  inout a, c; electrical a, c;
  parameter real is = 1e-14;
  analog I(a, c) <+ is * (limexp(V(a,c)/$vt) - 1.0);
endmodule
```

```
.control
pre_osdi dio.osdi
.endc
v1 1 0 dc 0.6
r1 1 2 100
d1 2 0 md
.model md diode is=1e-20
```

What happens, in order:

```
Warning(osdi): device "diode" is already registered; keeping the existing device and ignoring this one
warning, model type mismatch in line
    d1 2 0 md
Warning: Model issue on line 8 :
  .model md diode is=1e-20 ...
unrecognized parameter (diode) - ignored

v(2) = 6.000000e-01     i(v1) = -1.19320e-10
 Diode models (Junction Diode model)          <- showmod md
```

**The analysis completes, and it is ngspice's built-in junction diode that
ran.** The Verilog-A model was discarded at load time; the `.model` card bound
to the built-in `diode` type; `is=1e-20` happened to be a parameter the
built-in also has, so it took it, and the deck produced a plausible,
completely different answer.

The "already registered" line is the same wording used when two `.osdi` files
define the same module — nothing says the collision is with a *built-in*
device, and nothing says the remedy is to rename the module.

Written the OSDI way (an `n`-prefixed instance line), the same collision
aborts instead:

```
n1 1 0 mm
.model mm diode
  -> incorrect model type! Expected OSDI or nport device
```

which is loud but never mentions the cause.

**Scope.** Two families of names collide, both measured one module at a time
with `.model mm <name>` on an `n` line:

* the **`.model` type keywords** `INPdomodel` matches — `c cpl csw d l ltra
  nhfet njf nmf nmos npn nsoi phfet pjf pmf pmos pnp psoi r res sw txl urc
  vdmos vdmosn vdmosp`, plus `ndev`, `numd`/`nbjt`/`numos` and `poly` in builds
  with NDEV, CIDER and XSPICE (read from `spicelib/parser/inpdomod.c`; *Review:*
  the hunt's first reading missed `txl cpl numd nbjt numos` — its pattern
  required a space after the comma that those five `strcmp` calls do not have);
* every built-in **device name** — measured shadowed: `diode`, `resistor`,
  `capacitor`, `inductor`, `bjt`, `jfet`, `switch`, `vsource`, `isource`,
  `asrc`, **`bsim4`, `hicum2`, `vbic`**.

`cap`, `ind`, `tra` and `mesfet` are free, so the set is neither obvious nor
guessable from the outside.

The compact-model reference sources sidestep this by convention — the
`integration_tests` copies are `bsim4va`, `hicumL2va`, `hisim2_va`, `diode_va`,
`resistor_va` — which is evidence that the collision is known somewhere, and
also why it bites hardest on a *user-written* module with a natural name.

The silent half needs the built-in's own device letter, and it is seamless: a
module named `res` plus `r1 1 0 mm 2k` runs a built-in linear resistor,
`showmod` reports *"Resistor models (Simple linear resistor)"*, and the model
card's `r=2000` is accepted **without any warning at all** — the built-in
resistor model happens to have an `r` parameter too (`res.c:85`), so the
substitution leaves no trace in the output at all.

A registry-time message naming the built-in and the remedy ("rename the
module") would close this; the information is available exactly where the
existing warning is printed.

**Resolved (2026-09-04, after the hunt) — with two corrections to this entry.**
First, the claim that *nothing* said to rename the module was wrong for the
device-name family: openvaf's lint **L018** (`reserved_module_name`) had warned
`module name 'diode' collides with ngspice's built-in 'Diode' device` at compile
time, with the rename advice in its help text. The hunt's compile step filtered
that line out. It was right for the keyword family (`res`, `d`, `sw`, `nmos`
...), which L018 did not cover, and for the case pair of F2. Second, a worse
route turned up while fixing: **`pre_osdi -f` on a built-in-colliding module
replaced ngspice's built-in for the session** — after `pre_osdi -f lcdiode.osdi`
a plain `.model md d(...)` card ran the Verilog-A module (`showmod` said
*"loaded with OSDI"*), because the forced-reload swap in `osdi_add_device` did
not ask whether the device it was replacing was a built-in.

The fix came in two stages. The first (`d3a21c79`) made the collision audible:
the loader refused such a module with a message naming the built-in and the
remedy, never swapped a built-in on `-f`, and remembered what it refused so
the `.model` card and the N line could explain themselves. That left the
module **unusable** under its name — "rename it" was the only way out.

**The second stage makes it usable.** An `n`-line instance can mean nothing
but an OSDI device, and ngspice materialises a model lazily (at the first
instance line that uses it, not at the card), so the ambiguity can be decided
where it is unambiguous:

* the loader (`spicelib/devices/dev.c`) now *registers* a colliding module
  under its own slot — it asks the parser through `INPbuiltinModelTypeKeyword`,
  which reads the same keyword table as `INPdomodel`, for the keyword family
  — and records it as **shadowed**: `Warning(osdi): Verilog-A module "res"
  ... has the same name as ngspice's built-in Resistor (a .model type
  keyword). A .model ... res card resolves to the built-in; only an n-line
  instance re-binds such a card to this module, any other device letter gets
  the built-in.` `INPtypelook` returns the first match, so every card still
  resolves to the built-in and nothing that worked before changes;
* `INPdomodel` keeps the card's type token on the model entry, and the N-line
  parser (`inp2n.c`) — before `INPgetMod` materialises the model — re-binds a
  card whose type resolved to a built-in to the shadowed module of that name:
  `Note(osdi): .model mm: type "res" is ngspice's built-in Resistor, but this
  n-line instance can only mean the Verilog-A module "res" from
  "coll_name.osdi" -- binding the card to it.` Measured: `.model mm res r=2000`
  on an `n` line now gives `-5.00000e-04`;
* a card used by a *built-in* device letter is materialised as the built-in,
  and `create_model` (`inpgmod.c`) says so at that moment — the one place it
  is certain: `Warning: .model md: created as ngspice's built-in Diode. The
  Verilog-A module "diode" ... is reached only from an n-line instance; this
  card is used by another device letter, so the built-in simulates.`
  (The first stage warned at `INPdomodel`, which runs before any instance line
  is seen and so could not have known; that warning is gone.);
* one card cannot serve both letters: `n` first then `d` fails on the `d` line
  ("incorrect model type"), `d` first then `n` fails on the `n` line with
  *"model "md" was already created as ngspice's built-in Diode by another
  instance line ... give this n line a .model card of its own, or rename the
  module"*;
* the deck-reading pre-pass in `inpcom.c` no longer pre-judges `n` lines at
  all: it runs before any `pre_osdi` has loaded a library, so it cannot know
  about shadowed modules, and INP2N reports every genuine n-line mismatch
  later with the cause;
* `pre_osdi -f` swaps the shadowed module's *own* slot and never the
  built-in's.

The compiler's L018 covers the keyword family with wording that now matches
the simulator: `.model <name> res` *resolves to* the built-in and ngspice
re-binds such a card only for an `n`-line instance. Pinned in
`examples/multimod_examples/` (24/24, both solvers): `vcvs` and `res` now
*run* from an `n` line ([7], [9]), the `d`-line card warns at
materialisation ([10]), `-f` keeps the built-in ([12]), and both mixed
orderings fail loudly on the second user ([13]); the L018 UI fixture pins two
keyword-named modules.

---

## F2 — two modules whose names differ only in case collapse into one, silently

Verilog-A is case-sensitive, so one `.va` file may legitimately define both:

```verilog
module Foo(p, n); ... analog I(p, n) <+ V(p, n) * 1e-3; endmodule   // 1 mA at 1 V
module foo(p, n); ... analog I(p, n) <+ V(p, n) * 7e-3; endmodule   // 7 mA at 1 V
```

The compiler accepts both into one `.osdi`. ngspice lowercases model type
names, so only the first survives — and the deck never learns:

```
n1 1 0 m1
.model m1 Foo      ->  i(v1) = -1.00000e-03      (correct)
n2 2 0 m2
.model m2 foo      ->  i(v1) = -1.00000e-03      (WRONG: `foo` is 7 mA)
```

`foo` compiled on its own gives `-7.00000e-03`, so the module is real and
distinct; in the combined library it is simply unreachable, and every request
for it is answered with `Foo`.

**Nothing is printed.** The registry's own duplicate guard — the
`Warning(osdi): device "X" is already registered; keeping the existing device
and ignoring this one` that fires when two `.osdi` *files* clash — does not fire
here. The hunt attributed that to a case-sensitive comparison; **the fix found
the real cause elsewhere**: the guard already compared case-insensitively, but
its scan stopped at `DEVNUM`, which is only advanced after the whole file has
been processed, so a module never saw the ones registered *earlier in the same
file*. Identical names cannot occur within one file (the compiler refuses
them), which is why only case variants slipped through.

The gap is the more striking because **the same collision one level down is
already diagnosed**. Two *parameters* of one module differing only in case get

```
Warning: pcase: model parameter 'rval' is declared more than once differing only in case;
         SPICE cannot tell the names apart, so only one of them can be set from a netlist.
```

and then behave exactly as the modules do — the first wins, the second keeps its
default (measured: `Rval` took the card's 250, `rval` stayed at 1000). Whoever
wrote that message had this class of problem in view; the module namespace was
not given the same treatment.

Nor is it the only sibling check that already works. Two `.model` **cards**
differing only in case draw `Warning: model "md" is already defined; keeping the
first definition and ignoring the later one`, and a module named `Diode` — a
case variant of the *built-in* — is caught by the registry. Within one file,
module-against-module was the one comparison the family did not make.

**Resolved (2026-09-04, after the hunt).** The scan now covers the devices
added earlier in the same load, and the collision is reported with both
spellings: `Warning(osdi): device "foo" is already registered as "Foo" by this
same library; the two names differ only in case, which a .model card cannot
tell apart, so "foo" is unreachable and every card of that type gets "Foo"`.
Pinned in `examples/multimod_examples/` (check [11], both spellings and the
1 mA both cards now audibly get).

---

## F3 — an array parameter cannot be set from a netlist card, and the card says it does not exist

```verilog
parameter real tab[0:2] = '{1.0, 2.0, 3.0};       // model-scope
(* type = "instance" *) parameter real itab[0:1] = '{1.0, 2.0};
```

| route | result |
|---|---|
| `.model mp pkinds tab=[1 2 3]` | `unrecognized parameter (tab) - ignored`, plus a second bogus `unrecognized parameter ([1)`; **the run continues with the defaults** |
| `n1 1 0 mi itab=[5 6]` | `unknown parameter (itab)` — hard error, deck aborts |
| `altermod mp tab=[7 8 9]` | `array parameter 'tab' is set per element: use @mp[tab[0]] = <value> (one element at a time)` |
| `altermod @mp[tab[0]] = 10` | **works** — the model's next evaluation sees 10 (`tsum` moved 11 → 20) |
| `echo $&@mp[tab[0]]` | **works** — reads back 10 |

**Review: this entry was overstated, and its stated cause was wrong.** The
parameter *is* reachable from both card types — in the per-element form that
`altermod`'s own message names:

| route | result |
|---|---|
| `.model mp pkinds r=1000 k=5 tab[0]=4 tab[1]=5 tab[2]=6` | **works** — `tsum` reads 20 |
| `n1 1 0 mi itab[0]=5 itab[1]=6` | **works** — `s` reads 11 |
| `showmod mp` | lists `tab[0]`, `tab[1]`, `tab[2]` with their values (the hunt's reading that it listed only `r k label` was a truncated capture) |

The mechanism is not what the hunt wrote either. The compiler does not export
one array parameter with `len = 3`: it **flattens** the array into three scalar
parameters named `tab[0]`, `tab[1]`, `tab[2]` (those are the strings in the
`.osdi`), and ngspice registers, sets, reads back and lists exactly those. No
OSDI parameter reaches ngspice with `len != 0`, so the `IF_VECTOR` entry in
`osdiinit.c` and the whole-array branch in the card parser — `inpgmod.c:229`,
whose comment says *"OSDI models receive array params in the syntax
`param_name=[...]`"* and strips the `[` — are dead code from an earlier
convention.

What remains of the finding is real but small: the whole-array spelling that
the parser's own comment documents, `tab=[1 2 3]`, is refused with
*"unrecognized parameter (tab)"* (plus a bogus *"([1)"* from the leftover
token), the model card then runs on with the defaults, and nothing on the card
route says *"set it per element"* — the hint `altermod` gives. The instance
line at least aborts. A card-side message of the same shape as `altermod`'s,
or accepting the documented `[...]` form by expanding it onto the element
parameters, would close it.

---

## F4 — the collapse-change warning blames temperature for a parameter sweep

A model whose node collapse depends on a parameter:

```verilog
if (rs == 0.0) V(a, di) <+ 0.0;          // collapsed
else           I(a, di) <+ V(a, di)/rs;  // internal node needed
```

`dc @n1[rs] 0 2000 500` prints, in this order:

```
Warning: n1: node collapse of model type 'rsdioi' changed at 300.1 K, but the matrix was built
         for the collapse decided at setup and cannot be rebuilt here.
         Results for this device are NOT trustworthy at this temperature. Run each temperature
         as its own analysis (.temp / set temp), which re-does the setup.
Warning: DC sweep 1: @n1[rs] = 500 changes this device's node collapse ... Use the `sweep`
         command, which rebuilds for each point
```

Nothing about this run has a temperature in it. The first message names a
temperature (300.1 K is simply the ambient at which `OSDItemp` re-ran the
instance setup), calls the results untrustworthy *at this temperature*, and
prescribes a remedy — one analysis per temperature — that does not apply. The
second message, from `cktdc.c`, is correct and gives the working remedy.

`osdisetup.c:1167` already suppresses this message for the sensitivity job and
while a setup reuse is live; the `.dc`-device-sweep case wants the same
treatment, or wording that does not assume temperature.

A smaller one of the same kind: a model that declares an opvar named `i_p` —
colliding with the terminal current ngspice synthesizes for terminal `p` —
draws *"instance parameter 'i_p' is declared more than once **differing only in
case**"*. The names are identical, not case variants; the guard is right to fire
but reports the wrong reason. (*Review:* the hunt added that the synthesized
current "becomes unreachable" — it does not. `show n1` lists both rows, `i_p
42` and `i_p 0.001`; only `@n1[i_p]` is ambiguous, and it answers with the
opvar's 42.)

The run is aborted immediately afterwards, so no wrong numbers reach the user
— and the recommended `sweep` command does work across the collapse change
(measured: `sweep @n1[rs] 0 2000 500 -analysis op` gives 0.271 A, 3.45e-4,
1.88e-4, 1.32e-4, 1.02e-4 across the five points).

---

## F5 — the deferred-message and `$monitor` buffers are unsynchronised under `--enable-openmp`

**Not reproduced here.** This tree configures `--disable-openmp` and the
machine has no `libomp`, so this is a code-reading finding; it is recorded
because the build option is a supported one.

`osdicallbacks.c` keeps the deferred-output machinery in file-scope state:

```c
static OsdiPendingMsg *pending;
static int pending_len, pending_cap;      /* appended by osdi_log_defer(), TREALLOC'd */
static char **monitor_prev;                /* $monitor change-detection history */
static int monitor_prev_cap;
static bool at_line_start[2];
```

`osdi_log_defer()` is reached from the model's log callback during `eval()`.
In `osdiload.c` the `USE_OMP` branch runs `eval()` inside

```c
#pragma omp task firstprivate(gen_inst, inst, extra_inst_data, model)
```

— one task per instance, with no `critical`/`atomic` around the append. Two
instances that `$strobe` (or `$display`/`$monitor`) during the same load
therefore append to the same buffer concurrently, and the `TREALLOC` growth can
move the array under another task's write. The consequences range from lost or
interleaved messages to heap corruption.

The surrounding code is otherwise careful about the parallel region — the
task-local `OsdiSimInfo` exists precisely to keep `EVAL_FLAG_IS_INITIAL_STEP`
race-free, and the stamping loop that follows is serial — which is what makes
the unguarded log buffer look like an oversight rather than a decision.

---

## F6 — `$monitor` change detection is positional

`osdi_display_flush()` compares *the k-th monitor message of this flush*
against the k-th of the previous flush:

```c
if (m->monitor) {
  int k = mon_seq++;
  if (k < monitor_prev_cap && monitor_prev[k] && strcmp(monitor_prev[k], m->text) == 0)
    continue;                      /* unchanged since the last accepted step */
```

The index is the message's position in the pending list, not the instance and
call site it came from. With a conditional `$monitor` — or an instance that
enters or leaves the emitting set — every later message shifts by one and is
compared against a *different* instance's history.

Probed with two instances, one of them conditional (`if (V(p,n) > thr)
$monitor(...)`), and the output was correct: the constant instance printed once,
the ramping instance printed on every change, because the conditional one
happened to enter the list at the tail. Recorded as fragility, not as a
demonstrated defect — the failure needs the shifted message's text to coincide
with the departed one's, which is reachable but was not constructed here.

---

## N1 (not OSDI) — the documented `.temp t1 t2 t3` list form is not implemented

```
.temp 50        ->  Doing analysis at TEMP = 50.000000     (correct)
.temp 50 100    ->  Warning: Could not set temperature to 50 100
                    Set to default 27 C instead.
                    Doing analysis at TEMP = 27.000000
.temp 0 50 100  ->  same
```

Both routes were measured with an OSDI device and a built-in resistor on the
same netlist (`tc1=0.01` on each): **they agree exactly at every temperature,
including the fallback**, so this is not an OSDI defect. It is the simulator's:
`frontend/inp.c:1855` runs `strtod` over the card and treats the second value as
trailing garbage, so the whole card is discarded and the temperature falls back
to 27 °C rather than to the first value — and `inp2dot.c:1604` marks the list
form *"not yet implemented - warn & ignore"* with its warning commented out.
The message a user gets reads like a parse failure, not like an unimplemented
feature. Recorded here because a temperature sweep written this way silently
becomes one room-temperature run.

---

## N2 (not OSDI) — a title line beginning with `.lib` is parsed as a library include

```
.lib my circuit title          <- line 1, the SPICE title
v1 1 0 dc 1
r1 1 0 1k
.control
op
print i(v1)
.endc
.end
```

```
Error: Could not find library file my
ERROR, library file my not found
ERROR: fatal error in ngspice, exit(1)
```

Found by accident (a hunt deck whose title happened to start with `.lib`), then
isolated: **no OSDI device is involved**. The failure is a hard `exit(1)` before
any analysis runs, which at least makes it loud.

*Review (2026-09-04, second pass):* the hunt called `.lib` "the special case
rather than dot cards in general". It is not. Putting each kind of dot-card on
line 1 of an otherwise valid deck:

| line 1 | what the reader does |
|---|---|
| `.include nosuch.cir` | executed — `Error: Could not find include file nosuch.cir`, `exit(1)` |
| `.lib nosuch.lib tt` | executed — `Error: Could not find library file nosuch.lib`, `exit(1)` |
| `.model md d(is=1e-14)` | taken as the title: `Circuit: .model md d(is=1e-14)` |
| `.param rr=2k` | taken as the title |
| `.temp 55` | taken as the title (the run stays at 27 °C) |

So the rule is: **file directives (`.include`, `.lib`) are executed wherever
they appear; every other dot-card on line 1 is the title.** That is stock
ngspice reader logic (`inpcom.c` carries no fork markers near it), and it is
the better rule to keep. The realistic mistake is the reverse of the hunt's
case — a deck with *no* title whose first line is `.include models.lib` or
`.lib corners.lib tt`, which is common — and under a strict "line 1 is always
the title" that include would be swallowed in silence, with the models missing
and the errors far from the cause. As it stands the file is loaded, or the run
stops and names the file. A title that genuinely *begins* with `.include` or
`.lib` is rare, and when it happens the failure is immediate and names the
token it took as a filename. Nothing computes a wrong number either way.

**Verdict: no fix.** At most a one-line note when a line-1 file directive is
executed ("line 1 of a deck is its title by convention -- this deck has none"),
which would serve the forgotten-title case as much as the odd-title one;
recorded as optional.

Real `.lib` use with OSDI model cards is fine: a two-section library selected as
`.lib models.lib tt` / `... ff` gives `is=1e-14` (`id = 8.53508e-05`) and
`is=1e-13` (`id = 3.30637e-04`) respectively.

---

## A candidate a control killed

Worth recording, because it is the trap this method exists to catch. Running a
collapse change and a temperature change in one session —

```
altermod md rs=1000     (Verilog-A)      set temp=100
altermod dbi rs=1000    (built-in diode)
```

— the two devices diverged by 4.4×: `-7.07272e-05` against `-3.13785e-04`,
having agreed exactly (`-1.88097e-04` each) at 27 °C. That reads like a
temperature-plus-collapse defect in the OSDI setup path.

It is not. **The control was invalid at any temperature but 27 °C**: ngspice's
built-in diode scales its saturation current with temperature (the SPICE
`is(T)` law with `xti`/`eg`), and the toy Verilog-A model has no temperature
dependence beyond `$vt`, which moves the current the *other* way. The devices
were never equivalent away from nominal.

The valid control is OSDI against OSDI: at 100 °C, an instance whose collapse
was changed by `alter @n1[rs] = 1000` gives `-7.07272e-05`, and an instance
*born* uncollapsed at `rs=1000` gives `-7.07272e-05` — identical to every digit.
The collapse-plus-temperature path is sound; only the comparison was wrong.

(The temperature channel itself is separately confirmed by a control that *is*
equivalent: the `tc1` resistor pair, which matches the built-in exactly at
−50, 0, 50, 100 and 150 °C.)

---

## What was measured and holds

Everything in this list was run OSDI-vs-control on one netlist and agreed to
the digits printed. This is the useful half of a hunt that found no numerical
defect — it is now on record that these paths were checked.

**Analyses.** `.op`, `.dc` (source and device-parameter sweeps), `.ac`, `.tran`,
`.noise`, `.tf`, `.pz`, `.disto`, `.sens`, `.meas`, `fourier`. Specifically:

* `.tf` — transfer function, output and input impedance: `7.518872e-01` vs the
  built-in diode's `7.518861e-01`.
* `.pz` (voltage mode) — an OSDI capacitor and a built-in capacitor in the same
  RC both report the pole at `-1.00000e+09` rad/s exactly.
* `.disto` — third-harmonic distortion `-1.67934e+00` vs the built-in diode's
  `-1.67932e+00`; **with `m=4`** the OSDI device, a built-in `d1 ... dbi 4`, and
  four explicit devices all agree.
* `.sens` — verified against a hand-derived finite difference, not merely
  against the built-in: `n1:is = -6.41742e+11` where the analytic value is
  `8.535e9 / -(0.01 + g) = -6.417e11`; `n1_temp = 4.889e-4` and
  `n1__mfactor = -6.417e-3` likewise check out. (ngspice reaches OSDI parameters
  numerically — the OSDI layer registers no `DEVsenSetup`/`DEVsenLoad`.)
* `.noise` at f = 0 is refused with a clear message; `.ac` at f = 0 gives the
  correct open-circuit result.

**Numerical integration.** `method=trap` and `method=gear`, `maxord` 2 and 4,
tight and loose tolerances (`reltol=1e-6` … `reltol=0.01 trtol=7`): the OSDI
capacitor and the built-in capacitor produce *identical* values at every probe
point and take the same steps, so OSDI charge participates in truncation-error
control exactly as a built-in does. `$bound_step` works (59 → 1005 → 108 points
for no bound / 1 µs / 10 µs over a 1 ms run). `$finish` stops the transient and
says so (`Note: $finish requested by a Verilog-A device at 4.056000e-04 s`).

**State and sequencing.** `ac` and `noise` after a `tran` re-linearise about the
DC operating point (identical to fresh runs); three transients interleaved with
operating points give identical results; `stop when time > 0.5m` followed by
`delete`/`resume` continues with OSDI state intact (`0.632119` / `0.864665`
against the analytic `0.632121` / `0.864665`); `reset` restores netlist values
after `alter`.

**Topology.** Per-instance node collapse under one model card (one collapsed,
one not — `n2#di` exists, `n1#di` does not, both match their built-in twins);
`altermod` moving a model in and out of collapse in both directions;
an unused internal node; a device with both terminals on one node; both
terminals grounded; `m=0` (disabled) and `m<0` (warned and ignored); a
260-character instance name.

**Parameters.** Range enforcement on model and instance parameters, naming the
parameter, the owner and the offending value (`Parameter r of 'mr' is out of
bounds (value -500)!`); an integer parameter given `2.7` is rounded *with a
warning*; a duplicate parameter on a model card warns and takes the last;
mixed-case module, model and parameter names resolve; string parameters
including one with an embedded space; `$param_given` flips when `alter` sets a
parameter; `@mp[r]` reads model parameters and `@n1[ir]` instance parameters,
matching the built-in convention exactly; built-in instance keywords that OSDI
does not have (`off`, `ic=`, `area=`) are refused rather than ignored.

**Multiplicity.** Netlist `m=4`, subcircuit `X ... m=4`, and four explicit
instances agree exactly in AC (`2.000000e-01`) and noise (`4.000000e-04`);
a switch branch with `m=4` matches four explicit copies in DC and AC, and its
short arm stays a short.

**Temperature.** `.temp`, `.options temp=`, `set temp=` and `option temp=` all
give the same answer as the built-in (`-5.78035e-04` at 100 °C with
`tc1=0.01`); a `.dc temp -50 150 50` sweep matches the built-in at all five
points.

**Topology, continued.** Noise through an *internal* node equals the same
network built on netlist nodes to every digit (`5.773503e-04` for a two-branch
device with an internal midpoint, and for two single-branch devices in series
carrying the same two noise powers). A Jacobian entry that is **zero at setup**
comes to life when `altermod` makes it nonzero (`g=0` → `g=1e-3` moves the
divider from 1 V to 0.5 V), and the same branch behaves at `g=1e15` and
`g=1e-15`. Nested subcircuit multipliers compose: an `m=2` subcircuit containing
an `m=3` subcircuit gives exactly the DC and the noise of a single `m=6`
instance (`1.428571e-01` V, `3.499271e-04`). A two-source `.dc` sweep produces
its nine points correctly.

**A hard DC sweep.** `dc v1 0 5 0.5` into 100 Ω and a diode — 42 mA at the top,
where limiting decides everything — converges at every point on both routes, and
the OSDI and built-in node voltages track to the solver's tolerance: `~1e-4` V
apart at the default `reltol`, collapsing to `~2.5e-7` V at `reltol=1e-10`. The
residual is tolerance, not a systematic difference (the two devices limit
differently: `limexp` against the built-in's `pnjlim`).

**Time and halting.** `$abstime` matches the simulator's own `time` vector under
a *delayed-start* transient (`tran 20u 1m 0.5m` → both read `5.028000e-04` at the
first stored point). `$stop` pauses with `Note: $stop requested by a Verilog-A
device at 4.056000e-04 s`, keeping the data up to that point; `$fatal` prints the
model's own message, then `Error: $fatal raised by a Verilog-A device ...
aborting the transient analysis`, and correctly drops the point it died on.

**Per-instance temperature.** `dtemp=25` under a global `.temp 100` gives
`-5.05051e-04` and `temp=40` gives `-8.84956e-04` — identical to a built-in
resistor carrying the same `tc1` and the same instance parameters.

**Simulator parameters.** With `.options gmin=1e-9 reltol=1e-4 abstol=1e-13
tnom=25 temp=85`, a model reading `$simparam` back through opvars sees exactly
those values — `gmin=1e-09 gdev=1e-09 srcfact=1 iter=3 tnom=25 temp=85
abstol=1e-13 reltol=0.0001`.

**GMIN is the model's job, and that shows.** Two diodes back to back with a
weakly-coupled midpoint settle at `4.982065` V with a Verilog-A diode and
`4.840851` V with the built-in — a 141 mV difference that is *not* a defect: the
built-in adds ngspice's GMIN across its junction and the Verilog-A model did not.
Adding `$simparam("gmin", 1e-12) * V(a,c)` to the same model brings it to
`4.840751` V, matching the built-in. Recorded because it is a porting trap: a
Verilog-A model compared against a built-in equivalent will differ wherever a
node is anchored by GMIN alone, and nothing says so.

**Hierarchy.** `@x1.n1[id]`, `@x1.n1[gd]` and `show x1.n1` reach an OSDI
instance inside a subcircuit (shown as device `n.x1.n1`, model `x1:md`).
Subcircuit-scoped `.model` cards parameterised through `params:` give each
instance its own model parameters — `x1` with `is={iss}=1e-14` matches a
built-in diode with `is=1e-14` and `x2` with `1e-13` matches one with `1e-13`,
in the same deck.

**Batch dot cards, `meas`, `fourier`, raw files.** A batch
`.print dc v(2) @n1[id] @n1[gd]` card prints opvars per sweep point with the
same values the control shell reports. `meas tran` with `MAX`, `AVG`, `WHEN`
and `FIND` all work over an opvar vector, and they are self-consistent:
`FIND v(2) WHEN @n1[gd]=4e-3` returns `5.96439e-01`, which is `$vt·ln(id/is)`
for the `id` that conductance implies. A `fourier 5k @n1[id]` command runs on
an opvar vector (THD 10.65 %). A `write`/`destroy`/`load` raw round trip
preserves an OSDI internal node exactly (`v(n1#di) = 6.119031e-01` before and
after).

**Noise reporting.** The per-source breakdown vectors are exact and compose:
two labelled sources of `1e-12` and `4e-12` A²/Hz across a 1 kΩ device report
`onoise_n1_aa = 9.999990e-04`, `onoise_n1_bb = 1.999998e-03`, and both the
device total `onoise_n1` and `onoise_spectrum` as `2.236066e-03` — the
quadrature sum to seven digits. `flicker_noise(1e-12, 1.0)` gives
`3.162274e-04` at 10 Hz and `9.999990e-05` at 100 Hz: the √10 slope and the
absolute level both exact. With `m=4` that flicker source reads `4.999999e-05`,
identical to four explicit instances of the same model.

**Names and buffers.** A 260-character instance name, a 92-character module
name, a module named `x1`, and a model card sharing its name with an instance
all work. Two `white_noise` sources whose labels share their first 260
characters stay *separate* vectors in the noise plot — their contributions are
not merged — but (*Review*) the 256-byte label buffer in `osdinoise.c:99` cuts
both labels at the same point, so the two vectors carry **one identical
265-character name** (read back from an ASCII raw file), and `print`ing that
name reaches only one of them. Reachable only with labels over 255 bytes; noted,
not pursued. All four fixed buffers in the layer (`osdicallbacks.c:74`,
`osdinoise.c:99`, `osdisetup.c:849`, `osdisetup.c:1727`) are written through a
bounded call.

**Bad libraries.** A missing file, a text file, 200 kB of random bytes, a
truncated `.osdi`, and a *valid* shared library that is not an OSDI model are
all rejected with a named error (`dlsym(...): symbol not found` for the last)
and no crash.

**Registry and I/O.** Two `.osdi` files defining the same module warn and keep
the first; opvars are recorded per point across a `.dc` sweep and per timestep
across a transient (`id`/`gd` consistent with `gd = id/$vt` at every point);
`savecurrents`, `@n1[i]`, `@n1[i_a]`, internal-node voltages (`n1#di`) and
`show`/`showmod` all read correctly; subcircuit parameter passing, including a
nested `rr={rr*2}`, reaches OSDI instance parameters; unconnected trailing
ports warn precisely and set `$port_connected` = 0; Verilog-A `white_noise` is
injected into a transient only when the deck has transient noise, and is
exactly zero otherwise.

## Coverage, honestly

One hour, ~70 probes, all foreground. What this hunt did **not** reach: an
OpenMP build (F5 is unverified), the quasi-periodic family (`qpac`/`qpnoise`/
`qpxf` — they have verify scripts inside `qpss_examples`, which is why they were
skipped), harmonic balance, `.pss` (its syntax needs an oscillator node and a
driven circuit is the wrong test), aging/`osdimc`/`autobus` (three prior hunts),
and any large real compact model under a full analysis chain.

The review that followed is its own lesson: of the hunt's four findings, one
(F3) rested on a mis-read mechanism and a `head`-truncated `showmod`, and three
smaller statements were wrong in ways a second run exposed in minutes. The
measured values all held; it was the *explanations* attached to them that
needed re-checking.
