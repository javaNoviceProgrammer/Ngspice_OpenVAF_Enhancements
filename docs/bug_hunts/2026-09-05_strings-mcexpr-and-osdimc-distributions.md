# Bug hunt — the string forms, `montecarlo -expr`, and the osdimc distributions just added

**Date:** 2026-09-05 · **Commit under test:** `7767042b` (Enhancement-554) ·
**Binaries:** locally built `ngspice-46/build/src/ngspice` and
`OpenVAF-master-20260610/target/opt/openvaf-r`; the prebuilt
`bin/macos/apple-silicon/{ngspice,openvaf-r}` for the cross-version probes.
**Duration:** 14:41–15:41, foreground only, nothing fixed; the document was
written alongside the probes from the first quarter-hour on and finished in
the last ten minutes.

Target: the code of the last two days — raw strings and f-strings (E-553),
`montecarlo -expr` (E-552), the lognormal and truncated distributions of
`.option osdimc` (E-554) — and, around them, the OSDI paths those features
lean on: the parameter setter the draws go through, the compiled range
check, the walk and weight code, pyplot's file handling. Method as before:
every probe has a twin or a closed-form answer; every number below comes
from a run of the binaries above.

**Result: two findings in the OSDI parameter path that predate this week's
work and that this week's work makes easy to hit, two that make the new
f-strings dead where they would be most useful, two pyplot file-handling
gaps, and a tail of small ones.** A draw written through the parameter
setter — and, it turns out, a `.dc` sweep's restore — turns a *defaulted*
parameter into a *given* one, so a model that picks defaults with
`$param_given` runs a different model from the second trial on, or after
any parameter sweep — and keeps running it after the option is turned off
(BSIM4: a 0.003 % sigma on `toxp` costs 32 % of the drain current). And the
compiled setup checks the range only of a parameter the deck gave: a
parameter left at its default is never judged against a bound that another
parameter moved, by `altermod` or by a draw. That second point corrects an
assessment given earlier today, which said dependent bounds were "handled
correctly for rejection".

| # | finding | severity |
|---|---|---|
| [F1](#f1--an-osdimc-draw-or-a-dc-sweep-turns-a-defaulted-parameter-into-a-given-one) | a defaulted `(* std *)` parameter reads `$param_given` = 1 from trial 2 on; a `$param_given`-gated default (reff 2000 → 1000) is abandoned; `unset osdimc` restores the value, not the flag. **A `.dc @mm[r]` sweep of a defaulted parameter does the same, with no Monte Carlo at all** | **high** — wrong model from trial 2, or after any parameter sweep (BSIM4: −32 % drain current from a 0.003 % sigma on `toxp`); `@mos_va[toxp]` reads the declared default, not the derived value the model runs at |
| [F2](#f2--a-parameter-left-at-its-default-is-never-judged-against-a-bound-that-moved) | `l = 1.2 from [lmin:inf)`: `altermod mm lmin=1.5` (or a draw of `lmin`) runs with `l < lmin`; the same with `l=1.2` on the card is refused | **high** — silent range violation |
| [F3](#f3--f-strings-are-dead-after-name) | `let z = f"{7}"`, `set t = f"{1+1}"`, `alter r1 = f"{3k}"` in a deck: braces globbed away, nothing evaluated (`let z=f"7"`); interactive `set t=f"…"` too | medium |
| [F4](#f4--an-f-strings-result-keeps-its-quotes) | the substituted text is `"7"`, which `let`, `alter`, `setplot` and `print` refuse as a string | medium — the feature cannot feed a value anywhere numeric |
| [F5](#f5--pyplot-keeps-the-quotes-of-a-quoted-output-name) | `pyplot -export "sp dir/s1"` → `"sp dir/s1".npy: No such file or directory`; nothing written | medium |
| [F6](#f6--pyplot_status-is-not-published-on-five-paths) | after `-export` (success), after every unopenable-file failure (quoted name, read-only file, missing directory), after the `xlog`/`xlimit 0` refusal: the variable does not exist | medium-low — `if $pyplot_status ne 0` dies |
| [F7](#f7--montecarlo--expr-name-may-shadow-the-plots-own-vectors) | `-expr sample=…`, `-expr montecarlo_n=…` create a second vector of that name; the scale shadows the record | low |
| [F8](#f8--pyplot_decimate10-5-silently-turn-decimation-off) | a bin count below 2 is accepted silently where `abc` warns | low |
| [F9](#f9--the-range-error-names-the-parameter-that-did-not-move) | `Parameter l of 'mm' is out of bounds (value 1.2)` — not the bound, not `lmin` | low — diagnostic |
| [F10](#f10--wrdata-keeps-the-quotes-of-a-quoted-file-name) | `wrdata "o3.txt"` writes a file literally named `"o3.txt"`; `wrdata f"o{1+1}.txt"` inherits it | low — pre-existing |
| [F11](#f11--save-refuses-a-model-card-parameter) | `.save @mm[s]`: *no such device*, while `print @mm[s]` works | low — pre-existing |
| [F12](#f12--small-f-string-edges) | `{1e20:d}` saturates to LONG_MAX silently; the `{{…}}` error names vector `{1` | cosmetic |
| [F13](#f13--a-loop-commands--seed-does-not-pin-the-model-declared-draws-across-invocations) | `montecarlo 3 -seed 1 …` twice: the netlist `agauss` values repeat exactly, the osdimc draws do not (the global trial counter is in the key); `highsigma -seed 3` twice gives 0.0594 and 0.0481; a `reset` between makes them repeat | medium-low — reproducibility |
| [F14](#f14--a-plot-on-a-notype-scale-gets-no-axis-labels) | `pyplot mcv rr` on a `montecarlo` plot: no `set_xlabel`/`set_ylabel` at all — the scale's name `sample` is not used | low |
| [F15](#f15--altermod-of-a-promoted-parameter-is-refused-as-no-parameter) | `parameter real l = 2.0*w` (E-546 promotes it to instance level): `altermod mm l=10` → *model 'mm' has no parameter l*, while `.model mm vidd l=10` sets every instance and `alter n1 l=10` works | medium-low — the card and the command disagree, and the message is wrong |
| [F16](#f16--the-run-after-a-forced-reload-keeps-the-previous-draw-unlabelled) | `pre_osdi -f vlg.osdi` while trials are running: the next `op` prints no trial line and runs at trial 3's draw (1205.06); draws resume with trial 4 after it | low |

Thirty-one things that behaved, and five observations that are design limits
rather than defects, follow the findings.

---

## F1 — an osdimc draw, or a `.dc` sweep, turns a defaulted parameter into a given one

E-530 writes every draw "through the ordinary parameter setter — the
`alter` path". The setter does what `alter` does: it stores the value *and
sets the parameter's given flag*. For a parameter the deck never set that
is a change of model, because CMC models pick defaults with
`$param_given` — `if (!$param_given(x)) x = f(y);` is everywhere in BSIM4,
PSP and HiCUM.

```verilog
(* std=25.0 *) parameter real r = 1000.0 from (0:inf);
(* desc="param_given(r)" *) real pg;
(* desc="effective r" *)    real reff;
analog begin
  pg   = $param_given(r) ? 1.0 : 0.0;
  reff = $param_given(r) ? r : 2000.0;     // the model's real default
  I(a,b) <+ V(a,b)/reff;
end
```

```
V1 a 0 1
N1 a 0 mm
.model mm vpg                  $ r never given
set osdimc / set mcseed=5
repeat 4: op; print @mm[r] @n1[pg] @n1[reff]
unset osdimc; op; print …
```

| run | `@mm[r]` | `@n1[pg]` | `@n1[reff]` |
|---|---|---|---|
| trial 1 (nominal baseline) | 1000 | 0 | **2000** |
| trial 2 | 1012.39 | **1** | 1012.39 |
| trial 3 | 1023.32 | 1 | 1023.32 |
| trial 4 | 1012.09 | 1 | 1012.09 |
| after `unset osdimc` | 1000 | **1** | **1000** |
| after `reset` | 1000 | 0 | 2000 |

So the ensemble is centred on `r`'s own default (1000 ± 25) while the
design point the model computes when `r` is not given is 2000: the draws
do not vary the nominal design, they replace it. The same flag flip
happens under `montecarlo` (three samples: `pg` = 1, 1, 1) and it survives
the option being turned off — "turning the option off restores every
drawn parameter to its nominal" restores the *value* through the same
setter, so the flag stays set until `reset` or a re-`source`.

And it is not the draw as such, it is the setter: a plain
`dc @mm[r] 900 1100 100` on the same deck, no `osdimc`, leaves `pg` = 1 and `reff` = 1000
on the next `op` — E-534's sweep restores the *value* through the same
setter and the model runs its "given" branch from then on. The `sweep`
command (`sweep @mm[r] 900 1100 100 -analysis op`) leaves `pg` = 1 as well,
and so does a `dc @n1[r]` sweep of an instance-typed parameter. `sens`,
which perturbs and restores the same parameter, does not flip it (`pg` = 0
after `sens i(v1)`), so the restore path of the sweeps is the one to look
at.

The same per instance, with `(* type="instance", std=25.0 *)` on `r`:
`N1 a 0 mm` (defaulted) reads `pg` 0 → 1 → 1 and `reff` 2000 → 1034.6 →
979.8 over three runs, while `N2 a 0 mm r=500` (given) reads 1 throughout
and `reff` 500 → 494.8 → 500.1.

The osdimc suite never sees this because its models use the parameter
directly. A real model does not. BSIM4 reads `toxp` only when it is given
and derives it as `toxe − dtox` otherwise (bsim4.va line 3466), so with
`(* std=1e-13 *)` on `toxp` — a sigma of 0.003 % — and `toxe=2e-9` on the
card:

| `.model mos_va bsim4va(…)` | trial 1: `@mos_va[toxp]`, `i(vdd)` | trial 2 | trial 3 |
|---|---|---|---|
| `toxe=2e-9` (toxp derived) | 3e-9 in storage, model uses 2e-9: **−112.39 µA** | 3.00001e-9, **−76.30 µA** | 2.99993e-9, −76.31 µA |
| `toxe=2e-9 toxp=2e-9` (control) | 2e-9, −112.39 µA | 2.00001e-9, −112.39 µA | 1.99993e-9, −112.39 µA |

A 32 % drop in drain current from a draw that moved the oxide by one part
in thirty thousand: the second trial is a different transistor, at the
parameter's declared default instead of the value the model author derived
for it. `montecarlo 5 -seed 1 -analysis op -expr id=i(vdd)` on that deck
records −76.30, −76.30, −76.31, −76.30, −76.31 µA around a nominal of
−112.39 µA — an ensemble whose every member is 32 % from the design point.
And no Monte Carlo is needed: `dc @mos_va[toxp] 2.5e-9 3.5e-9 0.5e-9` on the
same card, with the option off, leaves the next `op` at −76.30 µA instead
of the −112.39 µA it read before the sweep. The built-in BSIM4
(`level=14 version=4.8 toxe=2e-9`) under the identical `dc @mos_bi[toxp]`
sweep reads
−108.96 µA before and after: the built-in restore puts the parameter back
as it was, given flag included, and the OSDI restore does not. For a
parameter the card *gives*, the OSDI restore is right: `dc @mos_va[toxe]`
over the same range puts `toxe` back to 2e-9 and the current back to
−112.39 µA.

The mechanism, and a readback defect of its own: the compiled model derives
`toxp` into a local and never writes it back to the parameter storage, so
`print @mos_va[toxp]` reports the *declared default*, 3e-9, while the device
is running at 2e-9 — the built-in reads back the derived 2e-9. A draw or a
sweep's restore then writes that stale 3e-9 through the setter, which marks
the parameter given, and from then on the model believes the 3e-9. `toxm` behaves the same (built-in 2e-9, OSDI 3e-9). Exposure in the
bundled corpus: bsim4.va gates 209 defaults on `$param_given`, BSIMBULK
36, r3_cmc 6, ASM-HEMT 2; PSP, HiCUM, MEXTRAM, EKV3 and diode_cmc none.
The count alone overstates it, though — what matters is the *declared*
default. BSIMBULK gates `TOXP` the same way (`BSIMBULKTOXP = TOXE·EPSROX/3.9
− DTOX` when not given) but declares it as `` `MPRoo(TOXP, TOXE, …) `` — a
default that *reads* `TOXE` — so the storage resolves to 2e-9, `@nb[toxp]`
reads 2e-9, and the same `dc @nb[toxp]` sweep leaves the current at
−0.294 µA before and after. BSIM4 declares `toxp` as the constant 3.0e-9.
The exposed shape is a `$param_given`-gated parameter whose declared
default is a constant that differs from what the model derives.

Where to look: the compiled `access()` sets the given flag on every write
with `ACCESS_FLAG_SET` (`openvaf/osdi/src/access.rs`, "set the param_given
flag if write flag is given", lines 115–135 and 184–198); `osdimc_write` in
`osdisetup.c` and the `.dc` restore of E-534 (`dctrcurv.c`/`dctsetp.c`) both
go through it. A write that must not change givenness needs either a flag
the compiled setter honours, or a save-and-restore of the given bit around
the write on the simulator side.
The defect is specific to the CMC idiom — gate on `$param_given`, derive
into a local — not to a Verilog-A default *expression*: `parameter real l =
2.0*w` with an instance `w` (E-546's promotion) resolves into the storage,
`@n1[l]` reads 6 for `w=3`, and a `(* std *)` on it draws around 6 with the
model in agreement. Three things follow: `@model[param]` cannot be trusted
for a derived parameter;
the nominal `osdimc` captures for such a parameter is the wrong number;
and any write-back path (draw, sweep restore) must either preserve the
given flag or write the value the model actually derived. And F1
interlocks with F2: the flag flip
is what makes a drawn value's *own* range get checked at all (osdimc check
27, a draw below `[0:inf)`, passes because the draw marks `r` given). A fix
that stops the flip must keep the range check on drawn values. The prebuilt
`bin/macos/apple-silicon/ngspice` (pre-E-554) behaves the same on the `vpg`
deck, so this dates from E-530, not from this week. Until then
the workaround is to give every statistical parameter on the card:
`.model mm vpg r=1000` reads `pg` = 1 and `reff` = `r` from trial 1 on,
a consistent ensemble — and on BSIM4, `altermod mos_va toxp=2e-9` before
the `montecarlo` (the value the model would have derived) records
−112.38 … −112.39 µA around the −112.39 µA nominal. Two possible shapes for a fix, neither
attempted here: capture and restore the given flag around a draw (the
setter's flag write is in `osdimc_write`'s `access()` path), or refuse to
draw a parameter the deck never gave and say so once.

## F2 — a parameter left at its default is never judged against a bound that moved

The compiled `setup_model`/`setup_instance` evaluate a parameter's `from`
bounds with the current values of everything they read — but only for a
parameter that was *given*. A default is presumed to satisfy its range,
which is true when the range is constant and false the moment the range
reads another parameter that has since moved.

```verilog
(* std=0.6 *) parameter real lmin = 1.0 from (0:inf);
parameter real l = 1.2 from [lmin:inf);
analog I(a,b) <+ V(a,b)*l/1000.0;
```

| deck | `altermod mm lmin=1.5` then `op` |
|---|---|
| `.model mm vdep` (l defaulted) | runs; `@mm[lmin]` = 1.5, `@mm[l]` = 1.2 — **l below its lower bound, no message** |
| `.model mm vdep l=1.2` (l given) | `Parameter l of 'mm' is out of bounds (value 1.2)!` |

No `osdimc` is involved in that table, and neither is `altermod` needed:
`dc @mm[lmin] 0.5 2.0 0.5` with `l` defaulted runs all four points, the
last two with `lmin` above `l`, and reports −1.2 mA at every one. With
`osdimc`, the draws of `lmin`
(0.87, 0.89, 1.17, **1.24**, 0.63, **1.33**, **1.27** over seven trials,
seed 11) push the defaulted `l` out of range on three of seven trials and
every one of them runs. The assessment given earlier today — that a bound
depending on other parameters is "handled correctly for rejection, because
the check does not live in the simulator" — is therefore wrong for the
common case of a parameter the deck leaves alone; it holds only for
parameters the deck sets.

Where the presumption comes from: E-546 made the model setup "skip its
given-value check" for a range that reads an instance parameter and judge
it in the instance setup; the given-only rule itself is older and applies
to every bound, E-546's new path included — `parameter real l = 2.0 from
(0:w]` with an instance `w=1` runs when `l` is defaulted and is refused
(*Parameter l of 'n1' is out of bounds (value 2)*) when the card says
`l=2.0`. A fix would re-check, in the setup, the range of every
parameter whose bound expression reads a parameter that is given or drawn —
the compiler already knows which bounds read what (`bound_exprs`). In the
bundled corpus the shape is rare but stock: E-546 counted twelve CMC
parameters whose range reads another parameter (BSIM6/BSIMBULK/BSIMIMG
`XGL`, HiSIM2 `LP`, HiSIMHV `RDRDL1/2`, HiSIMSOTB `PARL1/2`), every one of
them a defaulted parameter in the usual deck — though their shape,
`XGL from (-inf : L*LMLT+XL)` with a default of 0, cannot be violated by a
sane instance, so the practical exposure is a user model with a range like
`from [lmin:inf)`, which is exactly the shape the earlier assessment was
asked about.

## F3 — f-strings are dead after `name=`

E-553 recognises the prefix in two places with two rules. The lexer
accepts `r"`/`f"` at a word start *or after `=`, `(`, `,`*
(`cp_string_prefix_tail`), so `set title=r"Mixed Case"` keeps its case.
The glob skip (`cp_doglob`) and the evaluator (`cp_fstringsubst`) look only
at the *word start*. And the deck reader collapses `z = f"{7}"` into
`z=f"{7}"` (its whitespace pass strips the spaces around `=`), so in a deck
the after-`=` form is the one every `let`, `set` and `alter` produces:

| deck line | what runs | result |
|---|---|---|
| `let z = f"{7}"` | `let z=f"{7}"` → glob eats the braces → `let z=f"7"` | `Error: RHS "f"7"" invalid` |
| `set t = f"{1+1}"` | `set t=f"1+1"` | `t=1+1` |
| `set t=f"{7}"` | `set t=f"7"` | `t=7` — right by accident, the glob left `7` |
| `alter r1 = f"{3*1000}"` | `alter r1=f"3*1000"` | `Error: no such vector f"3` |
| `set v=r"{1+1}"` | the raw string's braces are globbed too | `v=1+1` |
| interactive `set u = f"{1+1}"` | word start, no reader | `u=2` ✓ |
| interactive `set t=f"{1+1}"` | after `=` | `t=1+1` ✗ |

`echo`, `foreach`, `shell`, `pyplot … title f"…"` and `wrdata` take the
whole-word form and work. Backquotes are not a way round it either:
`set t=\`echo f"{1+1}"\`` stores `f1+1`, the inner command having lost its
quotes and braces before it ran. In a deck there is therefore no way to
put an f-string's value into a variable at all. The fix is one rule in
three places: let the glob skip and the evaluator recognise the prefix
wherever the lexer does.

## F4 — an f-string's result keeps its quotes

The substituted word is `"7"`, quotes included, exactly like a literal
`"7"` — and ngspice's numeric commands do not take a quoted string:

```
let z = f"{7}"        Error: RHS " "7"" invalid          (interactive; F3 aside)
setplot f"op{1}"      Error: no such plot named "op1"
print f"{w}"          Warning from checkvalid: vector 7 is not available
if f"{1+1}" = 2       false   (as is  if "2" = 2 )
if f"{1+1}" eq "2"    false   (and  eq 2  too)
montecarlo … -max f"{1000+40}"     montecarlo: -max '"1040"' is not a number
```

That is pre-existing quoting: `let z = "7"` fails the same way, and so
does `if "2" eq "2"` (false, as is `set s="2"` then `if $s eq "2"`) — the
`eq` operator does not see through quotes either. But it means
an f-string can carry a formatted number into a *string* (a title, an echo,
a file name) and never into a *value*. Since the whole point of
`{expr:.3f}` is a number, the evaluator should probably drop the quotes when
the result is a single number, or the numeric commands should unquote — a
decision for the fix, not the hunt.

## F5 — pyplot keeps the quotes of a quoted output name

E-547 shell-quoted the *launch*. The *name* argument is still used verbatim,
quotes and all, so the one spelling that can name a directory with a space
is the one that cannot work:

```
pyplot -export "sp dir/s1" v(out) v(in)     "sp dir/s1".npy: No such file or directory
set pyplot_export=ascii
pyplot -export "sp dir/s2" v(out) v(in)     "sp dir/s2".data: No such file or directory
pyplot "sp dir/p1" v(out) title "in a dir"  "sp dir/p1".data: No such file or directory
```

Nothing is written (the directory stays empty) and — F6 — no status is
published. The most natural use of the new f-strings hits the same wall:
`foreach i 1 2 / pyplot -export f"run{$i}" v(out) / end` reports
`exported "run1".npy` and writes files named `"run1".npy`, `"run2".npy`,
quotes included. An unquoted name with a space cannot be given at all; `cp_unquote`
on the name would settle it. The one route that works today is a variable:
`set n="sp dir/s3"` then `pyplot -export $n v(out)` writes `sp dir/s3.npy`,
because variable substitution strips the quotes that the name argument
does not.

## F6 — `pyplot_status` is not published on five paths

E-547: "every pyplot publishes `pyplot_status` as `shell` publishes
`shellstatus`". Five paths do not — every failure to open the table file,
and the successful `-export`:

| path | `echo st=$pyplot_status` |
|---|---|
| `pyplot -export fam vo` (success, `exported fam.npy (62 rows, 8 columns)`) | `Error: pyplot_status: no such variable.` |
| the unopenable-file failure of F5 | same |
| `pyplot lx v(out) xlog xlimit 0 1m` → `Error: X values must be > 0 for log scale` | same |
| `pyplot -export ro v(out)` onto a read-only file → `ro.npy: Permission denied` | same |
| `pyplot -export nodir/x v(out)`, `pyplot nodir/y v(out)` (missing directory) → `No such file or directory` | same |

A deck written to the reference's own advice, `if $pyplot_status ne 0 …
quit 1`, aborts with *no such variable* on exactly the failures it was
written to catch. The missing-interpreter path is fine: `st=127`.

## F7 — `montecarlo -expr name=` may shadow the plot's own vectors

```
montecarlo 4 -seed 1 -analysis op -expr v(out) -expr sample=@r1[resistance] -expr 5
display
    expr1 … 4 long
    montecarlo_n … 1 long
    sample : notype, real, 4 long
    sample : notype, real, 4 long [default scale]
print sample              →  1 2 3 4   (the scale; the record is unreachable)
```

`-expr montecarlo_n=@r1[resistance]` does the same beside the 1-long
`montecarlo_n` result. Two `-expr` of the same name *are* refused
(*montecarlo: two -expr named 'a'*), so the check exists and only needs the
plot's own names added to it.

## F8 — `pyplot_decimate=1|0|-5` silently turn decimation off

On a 200 000-point trace `auto` emits the envelope (`_envelope`/`_dec` in
the script); `set pyplot_decimate=1`, `=0` and `=-5` emit none and say
nothing, while `=abc` warns *is not off, auto or a bin count; decimating
automatically*. A bin count below 2 is not a bin count and should get the
same warning.

## F9 — the range error names the parameter that did not move

`Parameter l of 'mm' is out of bounds (value 1.2)!` after
`altermod mm lmin=1.5`: the value shown is the one the user never touched,
and the bound that moved (`lmin`, now 1.5) is not named. When a range reads
another parameter, the message should say the bound's current value and,
if it can, which parameter set it.

## F10 — `wrdata` keeps the quotes of a quoted file name

`wrdata "o3.txt" v(out)` writes a file literally named `"o3.txt"` (quotes in
the name; `ls o*.txt` finds nothing), and `write "w2.raw" v(out)` writes
`"w2.raw"`. Pre-existing; the new forms inherit it: `wrdata f"o{1+1}.txt"`
writes `"o2.txt"`, `write f"w{1}.raw"` writes `"w1.raw"`, and
`source f"sub{1}.cir"` fails with *`"sub1.cir": Inappropriate ioctl for
device`* — the wrong file, and an errno text that has nothing to do with a
missing file. `cd "sp dir"` and `cd r"sp dir"` both work, so `cd` unquotes
and the others do not. As for F5, a variable is the route that works:
`set n="sp dir/w.txt"` then `wrdata $n v(out)`, `write $m v(out)` and
`source $q` all open the right file.

## F11 — `.save` refuses a model-card parameter

`.save @mm[s]` → *Warning: save `'@mm[s]'`: no such device, so this vector will
stay empty* — while `print @mm[s]` and `-expr @mm[s]` read it. `.save @n1[r]` (instance) works and, checked, holds the drawn value
(`tran2.@n1[r][0]` = 659.276 = the trial's draw).

## F12 — small f-string edges

`{1e20:d}` prints 9223372036854775807 with no note (LONG_MAX saturation);
`{{1+1}}` fails as it should but the text names *vector `{1`*; `{ }` is
reported as *`{ }` does not evaluate*, fine; `{1+1:.3}` (precision without a
conversion) is rightly not a spec and fails as an expression, but the
message could say a format needs a conversion letter. An unterminated
prefixed string passes through as text, harmlessly, but a single-quoted one
comes out re-quoted: `echo r'abc` prints `r"abc`.

## F13 — a loop command's `-seed` does not pin the model-declared draws across invocations

```
.param rr=agauss(1000,100,3)      R1 a b {rr}      N1 b 0 mm  (vlg: lognormal r)
montecarlo 3 -seed 1 -analysis op -expr rn=@r1[resistance] -expr ro=@mm[r]
montecarlo 3 -seed 1 -analysis op -expr rn=@r1[resistance] -expr ro=@mm[r]
```

| sample | `rn` (netlist agauss), run 1 / run 2 | `ro` (osdimc), run 1 / run 2 |
|---|---|---|
| 0 | 1022.03 / 1022.03 | 1020.17 / **1213.59** |
| 1 | 1011.23 / 1011.23 | 815.62 / **1198.65** |
| 2 | 1031.47 / 1031.47 | 719.15 / **1133.03** |

E-537 mixed the command's `-seed` into the osdimc draw key, but the key
also carries the global trial counter, which keeps advancing across
invocations — so `-seed` reproduces the netlist half of a deck and not the
model-declared half, and the published `montecarlo_seed` cannot regenerate
the ensemble. A second `montecarlo` with the same seed should either
restart the trial count for its own samples or say that it does not.
`highsigma` has it too: two `highsigma 1000 -scale 2 -seed 3 …` runs on the
same lognormal report 0.0594 and 0.0481, different samples under one seed
(both within their error of the 0.0548 exact). A `reset` between the two
invocations makes the draws repeat exactly (1020.17, 815.62, 719.15 twice),
so `reset` is the workaround — but only when the commands before the run
are the same too: a `highsigma 800 -seed 3` that followed two `wcd` runs
gave 0.0874, and the same command after `reset` and one `op` gave 0.0968,
because the position in the trial sequence, not the seed, decides: with
`osdimc_verbose` on, an `op` is trial 2, a `wcd` holds trial 3, the next
`op` is trial 4, a `highsigma 5` takes trials 5–9, and the `op` after it is
trial 10.
Toggling the option has the opposite behaviour: `unset osdimc`, an `op`,
`set osdimc` — the next run is *trial 2* again with the same draw (1104.18),
so a script that switches the option off and on repeats its ensemble.

## F14 — a plot on a notype scale gets no axis labels

`pyplot mcv rr` on a `montecarlo` plot (scale `sample`, type notype) writes
a script with no `set_xlabel` and no `set_ylabel` at all: E-551 labels an
axis by its vector *type* and a notype vector gets nothing, not even its
name. The scale's name is the obvious label.

## F15 — `altermod` of a promoted parameter is refused as "no parameter"

E-546 promotes a parameter whose default reads an instance parameter to
instance level and says it "stays settable on the .model card as the
card's default". The card form works; the runtime form is refused, with a
message that is not true:

```verilog
(* type="instance" *) parameter real w = 1.0 from (0:inf);
(* std=0.01 *)        parameter real l = 2.0*w from (0:inf);   // promoted (L028)
```

| deck (`N1 … w=3`, `N2 … w=1`) | `@n1[l]` | `@n2[l]` | `i(v1)` |
|---|---|---|---|
| `.model mm vidd`, then `altermod mm l=10`, `op` | **6** | **2** | −1.0 mA — *Error: model 'mm' has no parameter l.* |
| `.model mm vidd l=10` | 10 | 10 | −0.4 mA |
| `alter n1 l=10` | 10 | 2 | −0.8 mA |

The model does have `l`; the card proves it. The promotion moved `l` out
of the model-parameter table the runtime setter consults, so `altermod`
no longer finds it there (`dc @mm[l] 4 8 2` says *names a model that
exists, but not a sweepable parameter of it*, and `print @mm[l]` *no such
parameter l*), while the card path still resolves it. Under `osdimc` the E-530 recentring rule is
therefore unavailable for a promoted parameter through the model card at
run time; the instance route works (`alter n1 l=10` recentres `n1`'s draws
on 10, 9.9968 and 10.0151, and leaves `n2` at 2). Either the model-level
write should re-resolve every instance that did not give the parameter, as
the card does, or the message should say that `l` is instance-level since
its default reads `w` and point at `alter`.

## F16 — the run after a forced reload keeps the previous draw, unlabelled

`pre_osdi vlg.osdi`, `set osdimc`, two `op` (trials 2 and 3, verbose lines
printed), then `pre_osdi -f vlg.osdi` and an `op`: the reload says *reloaded
"vlg.osdi" (1 device)*, the `op` prints no trial line, and `@mm[r]` reads
1205.06 — trial 3's draw, still in the parameter. The `op` after that is trial 4 (1101.57, the same
value the uninterrupted sequence gives), so the table survived and the
counter did not move; one run simply went unlabelled at a stale draw. The
reload note should say that the running circuit keeps its old object and
its current draw, or the next run should count as a trial.

---

## What behaved

* **Cross-version objects.** A new object with `OSDI_STAT_PARAM_TRUNCS` in the
  prebuilt (pre-E-554) ngspice draws untruncated, identical numbers to an
  untruncated model; an old object in the new ngspice draws exactly what it
  drew before (1012.39, 1023.32, 1012.09 …). The prebuilt compiler ignores
  an unknown `trunc` attribute silently — its behaviour, not this tree's.
* **Lognormal corners.** A negative nominal keeps its sign (−1104, −1205 …);
  a zero nominal never moves; `std_rel=50` gives 4.8e-29 … 7e-9 without
  overflow; `trunc=1e-6` clamps to the nominal in 0.24 s (no hang).
* **The loop commands with a lognormal.** `montecarlo -expr @mm[r]` records
  varying values under osdimc; `wcd` on `r > 1000·e^0.2` reports
  β = 1.0000 exactly; `highsigma -scale 2` on `r > 1000·e^0.32` reports
  0.0520 ± 0.0027 against 0.0548 exact.
* **`.option osdimc mcseed=42` on the options card** works (unlike F6 of the
  2026-09-04 hunt for `osdilim_verbose`).
* **`noise` and `ac` are trials** (each draws); `montecarlo 1` and
  `montecarlo 0` are refused cleanly (*sample count must be in [2, 100000]*).
* **A `.dc @n1[r]` sweep of a lognormal instance parameter** is a machine
  write: the parameter is pinned during the sweep and the next `op` draws
  again (676.05 after the sweep); `reset` restarts the trial sequence and
  forgets an `altermod`, as documented.
* **pyplot quoting of a title** with an apostrophe, a backslash and a double
  quote (`'Vout\'s plot'`, `'a\\b'`, `'x"y'`) parses as Python.
* **A missing interpreter** gives `st=127` and names the script.
* **A recorded N × L family** exports as `time, vo[0], time_2, vo[1] …`,
  plots as N curves, and `wrdata` writes it.
* **Raw and f-strings on `+` continuation lines** of a control block keep
  their case and evaluate (`suptitle('Continued Title 0.76 V')`).
* **An f-string after a `$` end-of-line comment** is stripped with the
  comment by the deck reader, never evaluated; an unterminated `f"abc`
  neither hangs nor kills the block (a 200 000-element `{v(out)}` expands in
  0.35 s).
* **`echo f"{1+1}" > fout.txt`** redirects like a plain echo.
* **Raw braces** survive everywhere the prefix is at the word start:
  `title r"Braces {kept} here"` is the suptitle verbatim, `echo r"{x} and
  {a,b}"` prints them, and `f"lit \{{1+1}\}"` prints `{2}`.
* **The handbook's own example**, `set title=r"RC Low-Pass, Corner Case"`
  then `pyplot hb v(out) title $title` (or `"$title"`), gives
  `suptitle('RC Low-Pass, Corner Case')`.
* **A hardcopy through a variable path** (`set n="sp dir/p2"`, `pyplot $n
  …`) writes `sp dir/p2.png` and publishes `pyplot_status` = 0.
* **A device parameter inside an f-string** — `f"r={@mm[r]:.1f} pg={@n1[pg]:d}"` — evaluates.
* **`highsigma -inflate @mm[r]`** scoped to a lognormal gives 0.0524 against
  0.0548 exact; a spec that matches nothing says so and falls back to plain
  sampling.
* **`wcd` with a netlist Gaussian beside a truncated model parameter**
  (σ 50 and σ 25, boundary +100): β = 1.7889 at u = (1.6, 0.8), the exact
  MPFP, the truncated dimension used but not clamped.
* **`wcd` on a lognormal with `trunc=2`** and a boundary at z = 2.5 reports
  the truncation message (the walk held at the window, no distance), and
  at z = 1 reports β = 1.0000.
* **Statistics on an instance-dependent default** (`l = 2.0*w`, E-546's
  promotion): each instance draws around its own resolved default, 6 for
  `w=3` and 2 for `w=1`, and the value the model uses equals the readback.
* **`wcd … -seed 3` twice** on a two-dimension deck reports the same
  β = 1.2880 both times: the walk is deterministic under its seed.
* **`pre_osdi` of the same object twice** is skipped with a note that names
  `pre_osdi -f`; the statistics table is untouched.
* **Devices inside subcircuits** draw per flattened instance (`n.x1.n1:r`
  1045.6, `n.x2.n1:r` 1130.1) and read back as `@n.x1.n1[r]`.
* **`highsigma -scale 2` on a lognormal with `trunc=2`** (the two new
  shapes together): 0.0321 ± 0.0018 against 0.0336 exact.
* **`highsigma -scale 4` on a 1-sigma-truncated gauss** (the proposal
  confined to a quarter sigma, heavy weights): 0.2805 ± 0.0068 against
  0.2723 exact.
* **f-strings in `repeat` and `while` bodies** are re-evaluated every
  iteration (`iter 1`, `iter 2`, `iter 3`).
* **A `montecarlo` whose analysis is `dc @mm[r] …` over the drawn parameter**
  records the draws in `-expr r=@mm[r]` and a metric that the sweep, not the
  draw, decides; the *SAME value in every sample* note says so.
* **`montecarlo -expr` over a `noise` and over a `sens` analysis** records
  `onoise_total` (6.50e-8, 5.78e-8, 5.37e-8 V²/Hz) and the sensitivity
  `r1` (−2.43e-4, −2.45e-4, −2.42e-4) per sample, the osdimc draws varying
  underneath both.
* **`source` of a second deck** after trials restarts the sequence (trials
  2–4 repeat their values exactly) and the record plots keep counting
  (`montecarlo2`).
* **`alterparam rr=2000` + `reset`** takes the new netlist value and
  restarts the trial sequence (trial 2 again, same draw).
* **`set temp=100` beside draws**: the model sees 373.15 K and the draws go
  on (1012.39, 1023.32).
* **`showmod mm : r`** reports the drawn 1104.18 while a trial is applied and
  1000 after the option is off and a run has restored it.
* **`altermod mm r=1200`** before a `montecarlo` recentres the lognormal
  (1328, 1242, 1440, 911).

## Observations that are design limits rather than defects

* `ylimit` on a two-scale plot (E-548) is applied to the left axis only;
  there is no way to limit the twin.
* `pyplot -export out v(in)`: the existing vector `out` wins over the file
  name and the table is `export.npy` — the documented rule, but a node named
  like a file will surprise someone.
* `pyplot -hist` of an N × L family histograms all N·L points, silently
  flattened.
* Attribute strings are case-sensitive and say so (`dist="LOGNORMAL"`,
  `type="Instance"` warn and fall back); attribute *names* are
  case-sensitive and do not (`Dist="uniform"` is simply not `dist`, and the
  parameter is a plain gauss with no word) — correct by the language, easy
  to miss.
* `altermod mm r=0` on a lognormal `from (0:inf)` is stored as the new
  nominal, so every following trial draws 0 and fails with the range error —
  the same loop an illegal `altermod` produced before E-530, only now the
  draws around the illegal nominal are printed too.
