# Enhancement-430 — what `.probe` says when it refuses a token

```
.probe @r1[i]
    Warning: Strange parameter in line *probe @r1[i], ingnored
    Warning: Strange parameter in line *probe @r1[i], ingnored
```

Three things wrong, none of them the refusal itself: the message names neither
what `.probe` *does* accept nor where `@device[param]` belongs, it prints twice
for one bad token, it echoes the card in its internal `*probe` form, and it
misspells "ignored".

## The refusal is correct and stays

This started as a suspected capability gap — `.probe` rejecting `@dev[param]`
while `.save` accepts it — and it is not one. The two are deliberately different
mechanisms, and the manual is explicit.

§11.7.1: *"Device currents … may be measured by the `.probe` command. **Voltage
sources for measurements are placed in series to the devices nodes specified by
the user.**"* `.probe` **modifies the circuit** — that is why its results appear
as `<inst>#branch`.

§11.7.3 draws the other half of the line: `.options savecurrents` is described as
generating `.save @r1[i]` lines, and its stated advantage is that *"no extra
nodes are required, because the data are retrieved [internally]"*.

So the manual documents three distinct routes to a device current, and
`@device[param]` belongs to the one `.probe` is not:

| | mechanism | result |
|---|---|---|
| `.probe` | inserts series voltage sources | `r1#branch` |
| a hand-written `Vmeas … dc 0` | the same, manually | `vmeas#branch` |
| `.options savecurrents` → `.save @r1[i]` | reads internal data, no new nodes | `@r1[i]` |

That also makes the `vipVIP` gate principled rather than arbitrary: `.probe`
needs something it can put a source *in series with*. Teaching it to accept
`@r1[i]` would have conflated a circuit-modifying command with a
vector-selection one.

## What changed

Only the diagnostic:

```
Warning: .probe accepts v(...), i(...), p(...) or alli -- ignoring ".probe @r1[i]"
    `@device[param]` is read from the device rather than measured with an added
    source, so it belongs to .save: use `.save @r1[i]`, or `.options savecurrents`
    for every device terminal current.
```

* **Names the accepted forms**, so the refusal is actionable rather than a dead end.
* **Points `@` tokens at the right tool.** Only `@` tokens — a plain
  `.probe nonsense` gets the first line and no irrelevant advice.
* **Once, not twice.** The type test warned and advanced past the token, then the
  `!nextnode` test warned again on the wreckage. A `rejected` flag suppresses the
  second.
* **Echoes the card as written.** The wordlist holds it as `*probe …` because the
  card is commented out once consumed; showing that to a user who typed `.probe`
  is just confusing.
* **`ingnored` → `ignored`** — 5 further occurrences across `inpcom.c` (twice),
  `spiceif.c`, `inp.c` and `optran.c`, none of them `.probe`'s.

## Verification

* **`examples/probeshort_examples` — 48/48** (was 36). The new checks pin the
  message content, the single firing, the card echo, the absence of the typo, and
  — in the other direction — that `.probe i(r1)`, `.probe alli` and `.probe v(b)`
  stay silent and still produce `r1#branch`.
* **Full regression 345/345**, both solvers.

## Found by

Checking a claim rather than hunting: *".probe rejects `@dev[param]` outright (even
valid ones) with a warning — a capability gap, though the message misspells
'ignored'."* Both observations were right; the diagnosis was not, and the manual
settled it. The correct fix was the message, not the behaviour — a case where
reading the documentation before writing code changed what got written.
