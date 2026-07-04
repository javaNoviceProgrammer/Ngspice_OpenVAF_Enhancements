# comment_examples — `//` comment at EOF lexer hang (Enhancement-35)

Demonstrates comment handling — and the fixed **compiler infinite loop** on a
`//` comment at end-of-file — using **the committed** `openvaf-r` and
`ngspice-46`.

## What was broken

Both comment forms already worked (`//` line and `/* ... */` block comments, in
every position). But a `//` comment as the **last line of a file with no trailing
newline** hung the compiler forever at 100 % CPU — no diagnostic, stalls any
build/CI pipeline. Pre-existing bug, found while torture-testing comment support.

## The fix

The lexer's line-comment scan loop only broke on `'\n'`; at end of input the
cursor returns the `EOF_CHAR` sentinel forever while `bump()` no-ops. One added
arm — `_ if self.is_eof() => break` — ends the token at EOF. An audit confirmed
every other lexer scan loop was already EOF-safe (which is why an unterminated
`/*` was always a clean `unexpected EOF` error, never a hang).
See `../Enhancement-35.md`.

## Run

```
python3 verify_comment.py
```

Checks (ALL PASS): the hang reproducer (final bytes exactly `// eof comment`, no
newline) compiles within a watchdog timeout; the comment-torture model
(line/block/multi-line/mid-expression comments, code-like text inside comments)
simulates with the exact expected current; an unterminated `/*` stays a clean
error; a `//` comment ending in a lone backslash at EOF also terminates.
