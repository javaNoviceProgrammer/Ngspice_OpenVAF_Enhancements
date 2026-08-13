# Enhancement-450 — `savecurrents` could be requested but never declined

Whether `.options savecurrents` was in force was decided by a bare substring
search over the option line:

```c
for (; options; options = options->nextcard)
    if (strstr(options->line, "savecurrents"))
        break;
```

So **every option line merely containing the word switched it on, whatever the
line actually said.** The two spellings a user reaches for to turn it off both
turned it on instead:

```
.options savecurrents            ON     (correct)
.options savecurrents=0          ON     <- says off, does on
.options savecurrents=false      ON     <- same
.options nosavecurrents          ON     <- ngspice's own no<option> convention
.options mysavecurrentsxyz       ON     <- any identifier containing the word
```

`nosavecurrents` is the one that matters most, because it is not an invented
spelling: `noacct`, `noinit`, `nomod` and `nopage` are all real ngspice options,
so a `no` prefix is exactly what a user would reach for. It did the opposite.

Once on there was no way back — the feature could be requested but never
declined.

## Why it stayed hidden

Nothing goes wrong when it fires. A deck that quietly saves every terminal
current still simulates correctly; it simply carries vectors the user asked not
to have. On a large deck that is the difference between a small rawfile and a
very large one, and on an OSDI device it is one vector per terminal — the reason
this surfaced at all was a user noticing `i_<terminal>` vectors they had not
asked for.

It also cannot be reached from anywhere except an option **card**, which narrows
the search but makes the wrong answer stickier:

| source | switches it on? |
|---|---|
| `.options savecurrents` in the deck | yes |
| the same in an `.include`d file | yes |
| the same inside a `.lib` section | yes |
| `set savecurrents` in `.spiceinit` | no |
| `option savecurrents` inside `.control` | no |

`inp_savecurrents()` is a netlist pre-pass over the option cards, run before the
shell-variable machinery matters — the same "too late" ordering
[E-411](Enhancement-411.md) recorded for `set`, and the reason
[E-449](Enhancement-449.md) had to read its option from the option lists rather
than from `cp_getvar`.

## The fix

The line is read as **tokens** rather than searched as text. A token belongs to
the family when it is exactly `savecurrents` or begins `savecurrents_` — the
declared variants being `savecurrents_bsim3`, `savecurrents_bsim4` and
`savecurrents_mos1` — so an unrelated identifier that merely contains the word no
longer matches. A `no` prefix, or a value of `0`/`false`/`no`/`off`, turns it
off. The later card wins, matching how a repeated `.param` or `.options` value
already behaves.

**Which card is returned is deliberately unchanged.** The caller re-searches that
one line for `savecurrents_bsim3`/`_bsim4`/`_mos1` to choose the MOS current set,
so the *first enabling* card is returned exactly as the old first-match did.
Splitting the family across two cards behaves as it always has — that is a
separate wart, and widening the change to cover it would go past the evidence
([E-399](Enhancement-399.md)).

A `no` prefix combined with a value is left off rather than double-negated back
on: nobody writes `nosavecurrents=0` meaning "on".

## Verification

**`examples/savecuroff_examples` — 20/20, both solvers.** It is a separate
directory from [E-413](Enhancement-413.md)'s `savecur_examples`, which covers what
`savecurrents` PRODUCES once it is on; this one covers whether it is on at all.
E-413's suite is the sharpest control on this change and still passes 22/22. The oracle is the vector
list: with the option on, the two-terminal OSDI device contributes `@n1[i]`,
`@n1[i_p]` and `@n1[i_n]`; with it off, none of them exist.

Every fix is paired with a control that must not move:

* `.options savecurrents`, the singular `.option`, `savecurrents=1`, the word
  beside other options on one line, and the declared variant
  `savecurrents_mos1` all still switch it **on**
* no option at all, and an unrelated option, still give **none**
* `savecurrents=0`, `=false`, `=no`, `=off` and `nosavecurrents` now leave it
  **off** — each of these used to switch it on
* an identifier merely containing the word no longer matches
* on-then-off is off, off-then-on is on
* **the four MOS variants still select their own distinct current sets** —
  plain gives `id/ig/is/ib`, and the sets have sizes 4 / 6 / 3 / 11, byte-
  identical to the previous release
* the two terminal currents still sum to zero

A before/after differential over fifteen option spellings: **8/15 on the previous
binary, 15/15 on this one**, with every changed case moving in the intended
direction and no control moving at all.

**Full regression 363/363**, both solvers.
