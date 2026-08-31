# lrmsysio — display & file-I/O system tasks vs. the LRM (Enhancement-516)

An LRM-2023 conformance audit of clauses **9.4** (display tasks) and **9.5**
(file I/O) found five bugs — the headline being that *every* display task and
file write fired on *every Newton iteration*, against 9.4.6's "shall not
display output unless an iteration has been accepted" and 9.5.9's file-side
twin. This suite pins the fixes end-to-end:

- **Accepted-iteration deferral** (9.4.6/9.5.9): a `.op` prints one `$strobe`
  and one `$display` (it printed ~15 of each); `$debug` keeps its exemption;
  `@(initial_step)` output still prints exactly once; an un-gated `$fdisplay`
  writes one line holding the **converged** value.
- **`$monitor` change detection** (9.4.1): one line per change of its
  arguments across a whole transient.
- **`%r`/`%R` engineering notation** (9.4.3): `1e3 → 1.000000k`,
  `1e-9 → 1.000000n`, `0.036 → 36.000000m` (it printed garbage for every
  input).
- **Null display arguments** (9.4.1): `$strobe("a",,"b")` prints `a b`.
- **Append across analyses** (9.5.1.1): two `op` runs leave two `RUN` lines.
- **Open-write-close lifecycle**: the idiom writes its line now (the
  descriptor used to be closed before eval's first write), and a re-run of the
  instance initialization reproduces `$rewind`/`$fseek` files byte-exactly.
- **Pre-opened descriptors** (9.5.1): `32'h8000_0001` reaches stdout.

Run `python3 verify_lrmsysio.py` — 19 checks, both solvers.
