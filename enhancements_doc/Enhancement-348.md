# Enhancement-348 — `.pss` no longer crashes on a short or degenerate argument list

`pss 1meg 1u out 1024` — a `.pss` card with four of its seven arguments —
segfaulted. `pss` with none of them hung forever. And the crash was not really
about the missing arguments at all: `pss 1meg 1u out 1024 0 50 5u`, a complete,
well-formed card, crashed the same way.

---

## How it was found: walking a valid command backwards

The existing fuzz campaigns each drive one surface — `cmdfuzz` mutates argument
*values*, `parserfuzz`/`snpfuzz`/`rawfuzz`/`osdifuzz` feed malformed *input
files*. Neither shape finds this one. A command that reads its fifth argument
after checking only that a first one exists is invisible to value mutation,
because every value it is handed is present.

So the sweep took a **known-good invocation of each command and ran every proper
prefix of its argument list** — 38 commands, each truncated one token at a time,
with the full-length call kept as a control so a wrong exemplar could not pass
for a clean row.

`pss` was the only offender in the whole set:

```
  pss         nargs=7   0:HANG  1:SIGSEGV  2:SIGSEGV  3:SIGSEGV  4:SIGSEGV
```

Every other command — including `qpss`, which takes eight arguments, and
`optimize`, which takes twelve — truncates cleanly.

## Where it actually crashes

The release binary is stripped, so the disassembly gave the shape but not the
place: a load from a null pointer followed immediately by a divide.

```
->  0x1003ab874 <+696>: ldr    d0, [x19]      ; x19 == 0
    0x1003ab87c <+704>: fdiv   d0, d0, d1
    0x1003ab880 <+708>: str    d0, [x26]
```

The UBSan build named it exactly:

```
src/spicelib/analysis/dcpss.c:4990:15: runtime error: load of null pointer of type 'double'
```

which is

```c
Mag [0] = Phase [0] / (double)ndata;
```

— load, divide, store, matching the three instructions above.

## The root cause is three failures stacked

**1. `dot_pss()` never checks for a missing argument.** It reads seven required
values in a row, and `INPgetValue()` has no way to say *"there was nothing left
to read"* — on an empty line it hands back `0`. A card that stopped early
therefore reached the analysis with `points`/`harmonics` quietly set to zero.

**2. `DCpss()` never validated what it was given.** `CKTharms` is the length of
every array the DFT writes into:

```c
double *pssfreqs   = TMALLOC (double, ckt->CKTharms);
double *pssmags    = TMALLOC (double, ckt->CKTharms);
double *pssphases  = TMALLOC (double, ckt->CKTharms);
```

At `CKTharms == 0` those are `tmalloc(0)`, which returns **NULL**.

**3. `DFT()` writes index 0 unconditionally.** Its clearing loops are bounded by
`numFreq` and so do nothing when it is zero — but `Mag[0]`, `Phase[0]`,
`nMag[0]`, `nPhase[0]` and `Freq[0]` are written *outside* any loop. With NULL
arrays that is the segfault.

This is why fixing the parser alone would not have been enough. **`harmonics`
can be written out as zero on a complete card**, and that path never goes near
the truncation guard. The crash had two independent entrances.

## The fix

Three layers, one per failure above.

**Parse.** A macro next to `dot_pss()` rejects a card that runs out of tokens,
naming the argument that is missing:

```c
#define PSS_NEED_ARG(what)                                              \
    do {                                                                \
        if (*line == '\0') {                                            \
            LITERR("Not enough arguments on .pss: missing " what "\n");  \
            return (0);                                                 \
        }                                                               \
    } while(0)
```

This follows the idiom `dot_dc()` already uses a few hundred lines earlier in
the same file (`if (*line == '\0') …`); `dot_pss()` simply never adopted it.

**Analysis.** `DCpss()` now validates before anything is sized from the
parameters — this is the layer that catches an explicit zero:

```c
if (ckt->CKTguessedFreq <= 0.0)  → ERROR: .pss fguess must be > 0
if (ckt->CKTpsspoints < 1)       → ERROR: .pss points must be >= 1
if (ckt->CKTharms < 1)           → ERROR: .pss harmonics must be >= 1
```

**DFT.** The unconditional index-0 stores are guarded at the top of the
function, so the bound no longer depends on the caller getting it right:

```c
if (ndata < 1 || numFreq < 1 ||
        !Freq || !Mag || !Phase || !nMag || !nPhase)
    return (E_PARMVAL);
```

## What was measured and deliberately *not* rejected

Every parameter was tested at zero and negative before deciding which ones the
validation covers. Only three misbehave:

| parameter | at 0 | at < 0 | rejected? |
|---|---|---|---|
| `fguess` | HANG | clean error | yes |
| `points` | clean | clean error | yes |
| `harmonics` | **SIGSEGV** | clean error | yes |
| `sc_iter` | clean (rc=0) | clean (rc=0) | **no** |
| `steady_coeff` | clean (rc=0) | clean (rc=0) | **no** |

`sc_iter` and `steady_coeff` are harmless at any value tested, so they are left
alone. Rejecting them would be tightening the accepted input on no evidence, and
could break a working deck.

## Verification

- **Truncation sweep: 0 crashing truncations** across all 38 commands, from 5.
- **Degenerate values**: `harmonics 0` and `fguess 0` now produce a named error
  and exit cleanly instead of crashing/hanging.
- **No valid answer moved.** 22 correct invocations — `op`, `dc`, `ac`, `tran`,
  `tf`, `pz`, `sens`, `noise`, `disto`, `four`, `pss` (plain and `uic`), `pac`,
  `pnoise`, `hb`, `sp` — were run on the shipped binary and the rebuilt one and
  every printed number compared **exactly**. All identical. (The one apparent
  difference was `Total analysis time`, i.e. the clock.)
- The full example suite passes.

Reproducers live in `examples/pssargs_examples/`.
