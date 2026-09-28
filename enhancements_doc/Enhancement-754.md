# Enhancement-754: `.option autoadapt`'s name-order note is said under `set ngdebug` or `autoadapt=debug` only — E-729 printed it in every mode, and a generated deck whose buses all sit at the same port index on both devices got one line per shared node; the choice itself, the `.adapt b:n2` override and the debug reports are unchanged

**Scope:** a report that autoadapt "prints a lot of notices" after
[E-729](Enhancement-729.md). One file, `parser/inp2n.c`: the note's `fprintf`
gains a condition. The orientation rule, the split, the adapter injection and
every warning and error are untouched.

**Suites:** `autoadapt` 37 of 37 per solver (36 of 37 on the E-753 binary:
the silence check), `adaptlisted`, `adaptmsg`, `adaptquiet`, `autobus`,
`busmixed`, `autoopts`, `subbus`, `silentaccept`, `hunt12diag` and
`autocorner` unchanged; the full sweep 533 of 533.

## What was wrong

E-729 made the tie-break deterministic: when the shared bus node sits at the
same port index on both devices, the instance names decide which one takes
the adapter's forward side, and, because deck order used to decide in
silence, the choice was announced in every mode, the quiet default included:

```
Note: autoadapt: node 'b1' sits at port 0 on both n1 and n2, so the port rule cannot orient the adapter; n1 takes the forward side (b1_f, the adapter's first port) by name order, whatever the deck order -- `.adapt b1:n2` puts n2 there instead, or split the node by hand.
```

That is the ordinary shape of a generated deck: every channel is
`N1 b a model1` / `N2 b c model2`, so every shared node ties, and a deck of
six channels printed the line six times, one per node, each saying the same
thing. Measured on the E-753 binary with the deck below: six notes in the
quiet mode and six under `autoadapt=debug`, beside that mode's six split
reports.

```
N1 b1 a1 mymodel1
N2 b1 c1 mymodel2
N3 b2 a2 mymodel1
N4 b2 c2 mymodel2
...
.option autobus
.option autoadapt adapter=amod
```

## What changed

The note is printed when `set ngdebug` is on or the mode is
`autoadapt=debug`, and not otherwise. Everything else stands: the name-order
rule chooses the same device, `.adapt b:n2` names the other, the quiet mode
stays quiet as E-466 made it, and the debug mode reports the tie beside each
split. On the deck above the quiet mode now prints nothing, `autoadapt=debug`
prints the six notes and the six reports, and `set ngdebug` prints the six
notes.

`ngdebug` has to be set **before the deck is parsed**, because autoadapt acts
while the deck is read: a `set ngdebug` in a `.spiceinit`, or typed in an
interactive session before `source`, reaches it; a `set ngdebug` inside the
deck's own `.control` block runs after the parse and does not, which is the
rule the handbook already states for `autobus` and `autoadapt` themselves.

## Verification

`examples/autoadapt_examples/verify_autoadapt.py`, the E-729 section: the
quiet-mode check that asserted the note now asserts its absence with the same
answer as the hand-written `n1` orientation, and a new check writes a
`.spiceinit` with `set ngdebug` beside the deck for one run, asserts the note
and the same answer, and removes the file. The two `autoadapt=debug` checks
still assert the note. On the E-753 binary the silence check fails and the
rest pass.

## What this does not do

- It does not change which device takes the forward side, nor the
  `.adapt` override; only whether the choice is announced.
- It does not make the note reachable from the deck's `.control` block; that
  is the parse-time rule of the whole feature, not a limit of this change.
- The split reports of `autoadapt=debug` are as they were; `ngdebug` alone
  does not print them.
