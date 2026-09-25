# array_examples — Verilog-A array literals / aggregates (Enhancement-14)

Demonstrates the three array-aggregate capabilities added in Enhancement-14,
using **version11's own** `openvaf-r` and `ngspice-46`:

| # | Capability | Syntax |
|---|---|---|
| A | Whole-array **aggregate assignment** and copy | `acc = '{a, b, c};`  ·  `b = a;` |
| B | Array-valued **parameters** (per-element default **and** override) | `parameter real [0:3] w = '{...};` |
| C | **Dynamic** (non-constant) indexing | `rev[i] = acc[3 - i];` in a `for` loop |

Both models are programmable-gain buffers: `V(out) = gain * V(in)`, where the
gain is computed through the array machinery, so measuring `V(out)` at `V(in)=1`
reads the gain back directly.

## Files

| File | Purpose |
|---|---|
| `array_demo.va` | 4-tap gain buffer exercising **A + B + C** together. Gain = `w[0]+w[1]+w[2]+w[3]`. |
| `array_copy.va` | Whole-array copy `b = a` and integer→real element promotion (`a = '{1,2,3}`). |
| `verify_array.py` | Compiles both, drives them through ngspice, asserts gains against closed forms. |

## Run

```
python3 verify_array.py
```

Expected:

```
array_demo default (w='{0.1,0.2,0.3,0.4})         1.000000     1.000000  PASS
array_demo override w[0..3]=0.3,0.4,0.5,0.6       1.800000     1.800000  PASS
array_demo override w[2]=0.9 only                 1.600000     1.600000  PASS
array_copy (b=a='{1,2,3}) gain                    0.600000     0.600000  PASS
ALL PASS
```

## Enhancement-715: an element in every constant context (correctness campaign F1)

`array_const.va` derives its gain from parameters that READ elements of the tap
array `w`: `parameter real gsum = w[1] + w[2];`, `localparam real gtwice = w[0] * 2.0;`,
`parameter real glim = 0.25 from [w[0]:w[3]];`, `parameter real [0:1] q = '{w[3], w[0]};`
and an integer default `n[0] + n[1]`. The E-714 compiler refused every one of them with
"'w' was not found in the current scope" — the type inference looked the array up only
for the module's own body, and a parameter's default or range is a body of its own —
while the analog block read `w[k]` all along
([E-715](../../enhancements_doc/Enhancement-715.md)). Seven checks, eleven in all:

- the defaults give 1.5 (0.5 + 0.2 + 0.25 + 0.4 + 0.1 + 0.05);
- `w[1]=0.7` on the card moves the derived `gsum` (2.0), and `gsum=0.9` given wins (1.9);
- `w[0]=0.05` moves the localparam, the array literal and the range at once (1.35);
- `glim=0.5` is refused at setup as outside `[w[0]:w[3]]` = [0.1:0.4], and accepted
  once `w[3]=0.6` moves the bound (1.95);
- `n[1]=7` moves the integer default (1.54).

A forward reference — `parameter real pb = pa[1];` declared before `pa` — is refused
as "definition of 'pb' references parameter 'pa[1]' defined afterwards", like a scalar's
(it crashed the compiler in the first cut of E-715, once the element resolved).

```
OPENVAF_BIN=/path/to/E-714/openvaf-r python3 verify_array.py   # 4/11, exit 1
```

## Notes

- **Array declaration syntax** is *range-before-name*: `real [0:3] w;` (as for
  vectored nets and Enhancement-4 array variables), not `real w[0:3];`.
- **Array parameters** expand into one scalar OSDI parameter per element, named
  `w[0]`, `w[1]`, … — ngspice overrides each individually in a `.model` card
  (`.model mm array_demo(w[2]=0.9)`); unset elements keep their literal default.
  Element order follows the declared range (`[msb:lsb]`), so `[2:0]` fills the
  literal from `w[2]` down to `w[0]`.
- **Dynamic indexing** applies to array *variables* (mutable state). Array
  *parameters* are constant tables and are read by a **constant** index; to index
  a parameter table dynamically, copy it into an array variable first (as
  `array_demo` does: `acc = '{w[0], w[1], w[2], w[3]}`, then `acc[i]`).
- A dynamic index lowers to a runtime select over the element variables, so its
  cost grows with the array length — fine for the small coefficient arrays these
  features target.
