# Enhancement-597: a parameter name without a value is refused, not applied as zero

**Scope:** `src/spicelib/parser/inpdpar.c` (`e597_value_refusal`, in both parameter
loops of `INPdevParse`), `src/spicelib/parser/inp2n.c` (the model-name refusal of the
`n` line), `src/frontend/inpcom.c` (the model-usage scan of the deck reader),
`examples/barevalue_examples/` (new, 21 checks per solver). **ngspice only; the parser
is shared by every device.** Finding F2 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)).

**Suites:** [`barevalue_examples`](../examples/barevalue_examples/) 21 of 21 per solver,
both solvers; full sweep 491 of 491.

## What was wrong

```
n1 a b am w=2 m
```

The `=3` lost from `m`. `INPdevParse` read the bare `m`, asked `INPgetValue` for its
value at the end of the line, got 0.0 from `INPevaluate`'s error path, and applied it:
`m = 0`, the device gone from every analysis, nothing said. The same road gave `temp`
alone 0 °C, a second bare `w` a `w = 0` refused deep in `setup_instance` with no value
in the message, and a built-in `r1 a 0 1k tc1` a `tc1 = 0` after a "can't find model
'tc1'" that named the wrong cause. A `.model` card's instance-parameter default had the
same hole — `.model im istr width` put 0 into every instance of the card — and an
integer that does not fit (`k=1e300`) was applied as 0 on an instance line, where the
model-card path has refused it since Enhancement-509. Enhancement-507 closed the
unparsable-value hole for **model** parameters on the card; instance parameters, on
the line and on the card, were left.

A bare word straight after the model name was a third shape: on an `n` line the model
is the last bare word, so `n1 a 0 im k` was reported as "Unable to find definition of
model k" — and the deck reader, having decided the same, commented the card `im` out
as unused, so nothing downstream could say what `k` was.

## What changed

- **`INPdevParse` refuses a scalar parameter whose value is missing or did not parse**,
  the way it refuses an unknown name: the line fails, and the message says which shape
  it was — "parameter 'm' has no value -- write m=<value>", "parameter 'm': 'x=1' is
  not a number", "parameter 'k': the value does not fit an integer". The same test runs
  on the card's instance defaults, with " on the .model im card" added. Real, integer
  and string parameters are judged; a flag such as a diode's `off` takes no value and
  is untouched, and a node, instance or vector value has its own reader. The
  end-of-line test runs on the raw text before the value is read, so `tag=""` — an
  empty string value, not a missing one — stays legal on the line and on the card.
- **The deck reader keeps the card a trailing word hides.** When the last bare word of
  an `n` line is not a model but the word before it is, that card is marked used and
  the "can't find model" warning is not printed, so `INP2N` can report the word itself:
  "'k' is not a model and not a name=value parameter; the model is 'im', so a parameter
  here needs a value -- write k=<value>", or for a bare number, "'3' is a value without
  a parameter name; the model is 'im' -- write <name>=3". An unknown model is still
  "Unable to find definition of model nosuch".
- `m=0` written out stays the silent disable idiom of Enhancement-426; only a name
  without a value changes.

## Verification

| line | before | now |
|---|---|---|
| `n1 a 0 im w=2 m` | m = 0, device gone, silent | refused: parameter 'm' has no value -- write m=<value> |
| `n1 a 0 im w=2 temp` | 0 °C, silent | refused |
| `n1 a 0 im w=2 w` | duplicate warning, then "1 errors occurred during initialization" | duplicate warning, then the value named as missing |
| `n1 a 0 im w=2 m x=1` | m = 0, then "unknown parameter (x)" | parameter 'm': 'x=1' is not a number |
| `.model im istr w` | w = 0 on every instance, refused in setup | parameter 'w' has no value on the .model im card |
| `.model im istr k=1e300`, `n1 ... k=1e300` | k = 0 on the line, refused on the card | both refused: the value does not fit an integer |
| `tag=""` on the line and on the card | legal | legal |
| `n1 a 0 im w=2 tag` | tag = "" | refused |
| `n1 a 0 im k` | "Unable to find definition of model k", card `im` commented out | 'k' is not a model and not a name=value parameter; the model is 'im' |
| `n1 a 0 im 3` | "Unable to find definition of model 3" | '3' is a value without a parameter name |
| `r1 a 0 1k tc1` | "can't find model 'tc1'", then tc1 = 0 | refused: parameter 'tc1' has no value |
| `d1 a 0 dm off`, `d1 a 0 dm off area` | legal; area = 0 | legal; refused |
| `n1 a 0 im w=2 m=3`, `n1 a 0 im m=0` | 6 mA; 0 A silent | unchanged |

Full sweep 491 of 491 on both solvers.
