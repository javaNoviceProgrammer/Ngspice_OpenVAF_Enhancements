# Enhancement-361 — two sanitizer findings in `.disto`

Running the distortion suites under AddressSanitizer and UBSan turned up two
defects that every ordinary build tolerates silently: an out-of-bounds read I
introduced in [Enhancement-359](Enhancement-359.md), and a long-standing
NaN-to-`int` conversion in ngspice's own sweep setup.

---

## 1. Heap-buffer-overflow reading `CKTrhsOld` (mine, E-359)

```
ERROR: AddressSanitizer: heap-buffer-overflow
READ of size 8 at 0x6030000af2c0 ... 0 bytes after 32-byte region
    #0 numdisto_jac_at   osdidistonum.c:106
    #1 osdi_numdisto_build osdidistonum.c:214
    #2 OSDIdisto          osdidisto.c:249
```

The probe copies the solution vector before perturbing it:

```c
int n = ckt->CKTmaxEqNum;
for (i = 0; i <= n; i++)          /* <-- one past the end */
    scratch[i] = ckt->CKTrhsOld[i];
```

`CKTrhsOld` holds `CKTmaxEqNum` entries — ngspice's own code copies it as
`CKTmaxEqNum * sizeof(double)` — so the last valid index is `n-1`. The ASan
report matches exactly: a 32-byte region (4 doubles) faulting at index 4.

This fired on **every `.disto` run with a Verilog-A device**. It is a read, so
nothing was corrupted and the computed values are unchanged by the fix, but it
is undefined behaviour on the main path. The same off-by-one appeared in the
node-range guard (`gp > n` where the valid range is `gp < n`).

## 2. `(int)NaN` in the sweep point count (pre-existing ngspice)

```
distoan.c:86:37: runtime error: nan is outside the range of
representable values of type 'int'
```

Two independent triggers, both from ordinary user input and both reproducible
with **no OSDI device in the circuit at all**:

| input | what happens |
|---|---|
| `disto lin 1 1e6 1e6` | `start == stop` leaves `DfreqDelta = 0`, so the tolerance term is `0/0` |
| `disto dec 0 …`, `disto oct 0 …` | `exp(log(10)/0)` is `inf`, and the count then evaluates `0 * inf` |

Converting NaN to `int` is undefined: the resulting point count is whatever the
hardware happens to produce, so a nonsense request quietly ran with an arbitrary
number of points rather than being refused.

**Fix.** Zero-step decade and octave sweeps are rejected the way an unknown step
type already is. The linear division is guarded — where `DfreqDelta` is non-zero
the term is `floor(DfreqDelta * reltol / DfreqDelta)` = `floor(reltol)` = 0 for
any sane `reltol`, so zero is the value consistent with every other case, and
normal sweeps are bit-identical.

This one had been firing under my own test deck all along: check [4]'s mixer
sweeps `lin 1 1e6 1e6`, which is precisely the `start == stop` trigger. An
un-sanitized build tolerates it, so nothing ever failed.

## Verification

Both suites pass **8/8** and **7/7** under ASan + UBSan, and the distortion
values are unchanged by either fix. `examples/osdidisto_examples` gains check [8]
for the zero-step sweep — an ordinary build cannot observe the undefined
behaviour itself, but it can observe that a nonsense request now produces no
output instead of inventing some.

Regression 285/285.

## Note

Neither of these was reachable by the existing tests, and neither produced a
wrong number — one was an out-of-bounds *read*, the other an undefined
conversion that happened to yield a usable value on this hardware. That is
exactly the class of defect only a sanitizer finds, which is the argument for
running the suites under one after any change involving raw index arithmetic.
