# Enhancement-432 — `sweep -output` is variadic, and its failure tally was uninitialized

```
sweep @rs[resistance] 1k 3k 1k -output v(d) i(v1)
    ->  sweep: unrecognized token 'i(v1)'      the sweep runs, with one output
```

The usage line has always advertised `-output <expr> ...`, but only the first
token after the flag was ever read. Everything after it fell through to the
`unrecognized token` branch, and the sweep carried on with a silently shorter
output list.

## Where the list ends

The obvious rule — stop at the next token beginning with `-` — is wrong here.
`-v(d)` is a legitimate output expression, a negated one, and the old
single-token form accepted it because it took the next token unconditionally.
A rule based on the leading `-` would quietly break that.

So the list is ended by the flags `sweep` actually knows (`-vs`/`-family`,
`-analysis`/`-a`, `-overlay`/`-ov`, `-output`/`-o`), and by nothing else. A
mistyped flag is therefore read as an expression — which is the right outcome,
because Enhancement-431 names it in full when it fails to resolve:

```
sweep ... -output v(d) -ouptut i(v1)
    Error: sweep -output -ouptut never resolved -- no such vector; ...
```

One case genuinely improves rather than merely being preserved: a flag directly
after `-output` is now a missing expression rather than an output *named* `-vs`,
so the outer knob that follows is honoured instead of being consumed.

Each element goes through the same path as before, so `name=expr` and
Enhancement-267's `base[lo:hi]` bus expansion work from any position in the list,
not just the first.

## The second half: a tally that was never zeroed

Checking this turned up a defect in Enhancement-431 itself, and a worse one than
the parsing gap.

E-431 gives each output a count of the points at which it failed to resolve, and
zeroes it before the sweep runs:

```c
for (k = 0; k < nout; k++)
    outbad[k] = 0;
```

With no `-output` at all, the outputs are auto-collected from the first
analysis's plot — **inside** the point loop, below this line. So `nout` is still
0 here, every auto-collected output inherits whatever was on the stack, and E-431
reads that garbage as a resolve failure. On a 25-node deck:

```
sweep @r1[resistance] 1k 2k 1k -analysis op        (no -output at all)

    Error: sweep -output n18 never resolved -- no such vector; that curve is not recorded.
    Error: sweep -output n10 never resolved -- no such vector; that curve is not recorded.
    Warning: sweep -output n13 did not resolve at 1 of 2 points; ...
```

Six of the twenty-five nodes were **deleted**, and the others falsely warned
about. This is the default invocation of the command — no flags, nothing unusual
— and E-431 shipped it. The fix is to zero the whole array rather than the
`nout` entries known at that point.

The heap arrays sized per output (`data`, `ovy`) were checked and are fine: they
are allocated *after* the auto-collect, not before it.

## Verification

* **`examples/sweepguard_examples` — 23/23** (was 9). Fourteen new checks: the
  variadic list agrees value-for-value with the one-flag-each form it replaces;
  each terminator (`-vs`, `-analysis`, `-overlay`) ends it; a negated expression
  survives; an empty `-output` is diagnosed without swallowing the flag after it;
  a bus range expands from a non-first position.
* Both regression checks were **positive-controlled** — with the `outbad` fix
  reverted they fail, naming the six nodes that disappear.
* **Full regression 345/345**, both solvers.

## Found by

Enhancement-431 recorded the single-token limitation as *"noted, not fixed …
it wants its own decision about which of the two is right"*, and the decision was
to make the code match the documented usage.

The uninitialized tally was not part of that request. It surfaced because the new
parsing tests were run against a deck with no `-output` flag at all, and the
diagnostics that appeared could not be explained by anything in the change. The
tell was that the shipped binary — which predates E-431 — did not produce them,
which located the defect in E-431 rather than in the new code.
