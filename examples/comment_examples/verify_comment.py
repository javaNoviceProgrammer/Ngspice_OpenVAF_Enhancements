#!/usr/bin/env python3
"""
verify_comment.py -- verifies Enhancement-35 comment handling, end-to-end through
the committed openvaf-r + ngspice.

Both comment forms already worked, BUT a `//` comment as the last line of a file
with NO trailing newline hung the compiler forever (the lexer's line-comment loop
only broke on '\\n'; at end of input the cursor returns the EOF sentinel forever
while bump() no-ops). E-35 adds the missing end-of-file break.

Checks:

  1. HANG REPRODUCER: a file whose final bytes are exactly `// eof comment` (no
     trailing newline) compiles within a watchdog timeout (it used to spin
     forever -- a regression here trips the 20 s timeout, not a CI hang);
  2. the comment-torture model (line/block/multi-line/mid-expression/trailing
     comments, code-like text inside comments) compiles and simulates with the
     exact expected current -- the commented-out 999 A/V contribution is ignored;
  3. an unterminated `/*` at EOF stays a clean "unexpected EOF" error;
  4. a lone backslash ending a `//` comment at EOF (escaped-newline lookahead
     touching end of input) also terminates.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF, NG as NGSPICE

WATCHDOG_S = 20

BASE = (
    '`include "disciplines.vams"\n'
    "module comment_eof(a,c); inout a,c; electrical a,c;\n"
    "  analog I(a,c) <+ 1e-3*V(a,c);\n"
    "endmodule\n"
)


def compile_va(src, dst):
    """Compile with a watchdog; returns (status, log) where status is
    'ok' | 'error' | 'timeout'."""
    try:
        r = subprocess.run([OPENVAF, src, "-o", os.path.join(HERE, dst)],
                           cwd=HERE, capture_output=True, text=True,
                           timeout=WATCHDOG_S)
    except subprocess.TimeoutExpired:
        return "timeout", ""
    out = r.stdout + r.stderr
    ok = r.returncode == 0 and os.path.isfile(os.path.join(HERE, dst))
    return ("ok" if ok else "error"), out


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] hang reproducer: `// comment` at EOF, NO trailing newline")
    with open(os.path.join(HERE, "_eof.va"), "wb") as fh:
        fh.write(BASE.encode() + b"// eof comment, no trailing newline")
    st, _ = compile_va("_eof.va", "_eof.osdi")
    check("compiles within watchdog (used to hang forever)", st == "ok",
          f"status = {st}")

    print("[2] comment-torture model compiles + simulates exactly")
    st, log = compile_va("comment_demo.va", "comment_demo.osdi")
    check("comment_demo.va compiles", st == "ok",
          "" if st == "ok" else (log.strip().splitlines() or [st])[0])
    if st == "ok":
        deck = ("* comments\nvin a 0 dc 2\nn1 a 0 dm\n.model dm comment_demo\n"
                ".control\npre_osdi comment_demo.osdi\ndc vin 2 2 1\n"
                "wrdata _o.txt i(vin)\n.endc\n.end\n")
        with open(os.path.join(HERE, "_o.cir"), "w") as fh:
            fh.write(deck)
        subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE,
                       capture_output=True, text=True, timeout=60)
        i = float(open(os.path.join(HERE, "_o.txt")).read().split()[1])
        check("I == -2e-3*V (commented-out 999 ignored)", abs(i + 4e-3) < 1e-12,
              f"i = {i:.6e}")

    print("[3] unterminated /* at EOF stays a clean error")
    with open(os.path.join(HERE, "_unterm.va"), "w") as fh:
        fh.write(BASE + "/* unterminated block comment...")
    st, log = compile_va("_unterm.va", "_unterm.osdi")
    check("clean 'unexpected EOF' error", st == "error" and "EOF" in log,
          f"status = {st}")

    print("[4] `//` comment ending in a lone backslash at EOF terminates")
    with open(os.path.join(HERE, "_bs.va"), "wb") as fh:
        fh.write(BASE.encode() + b"// ends with backslash \\")
    st, _ = compile_va("_bs.va", "_bs.osdi")
    check("compiles within watchdog", st == "ok", f"status = {st}")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
