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
