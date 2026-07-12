#!/usr/bin/env python3
"""Enhancement-169: interactive command-line syntax highlighting.

ngspice now colors the interactive command line: the command word is shown GREEN
when it is a recognized command (looked up in the real command table, exactly as
the interpreter does), RED when it cannot become one, and left neutral while it is
still a valid prefix being typed; numbers, quoted strings and -option flags get
their own colors. Live coloring is done by overriding GNU readline's redisplay;
the `synhl' command prints the colorized form of a line non-interactively, which
is what makes the coloring engine testable here.

This is a front-end (REPL) feature, independent of the linear solver, so it is not
run under the dual-solver harness.

Two layers are checked:
  [engine]  the `synhl' command classifies tokens correctly (green valid command,
            red impossible command, neutral valid-prefix, plus number/string/
            option colors) -- run in batch mode, so it works in any build.
  [live]    typing at a real (pseudo-)terminal colors the line as it is entered:
            a word turns green the moment it becomes a complete command and red
            when it cannot; NO_COLOR and a non-tty suppress all color. This needs
            a readline-enabled build (as the shipped binaries are); on a build
            without readline the live layer is reported as SKIP.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
passed = failed = skipped = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def synhl(line):
    """Return ngspice's colorized rendering of `line` (via the `synhl' command)."""
    import tempfile
    deck = f"* synhl\n.control\nsynhl {line}\n.endc\n.end\n"
    with tempfile.NamedTemporaryFile("w", suffix=".cir", delete=False) as f:
        f.write(deck)
        path = f.name
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True,
                           text=True, timeout=30)
    finally:
        os.unlink(path)
    # the synhl output is the single colorized line (the only one with an escape)
    for ln in (r.stdout + r.stderr).splitlines():
        if "\033[" in ln:
            return ln
    return ""


# ---- [engine] the synhl coloring engine --------------------------------------
print("--- engine (synhl command, batch) ---")
o = synhl("plot v(out) vs time")
check("valid command 'plot' is green", o.startswith(GREEN + "plot" + "\033[0m") or (GREEN + "plot") in o,
      f"({o!r})")

o = synhl("boguscmd 1 2")
check("unknown command 'boguscmd' is red", (RED + "boguscmd") in o, f"({o!r})")

o = synhl("plo")
check("valid prefix 'plo' is neutral (neither green nor red)",
      (GREEN + "plo") not in o and (RED + "plo") not in o, f"({o!r})")

o = synhl("tran 1n 100n")
check("command green + numbers yellow", (GREEN + "tran") in o and (YELLOW + "1n") in o, f"({o!r})")

o = synhl('echo "hello world" -foo 3.5')
check("string magenta, option cyan, number yellow",
      (MAGENTA + '"hello world"') in o and (CYAN + "-foo") in o and (YELLOW + "3.5") in o,
      f"({o!r})")

o = synhl("PLOT v(1)")
check("command match is case-insensitive (upper-case 'PLOT' recognized -> green)",
      o.startswith(GREEN + "plot"), f"({o!r})")


# ---- [live] as-you-type coloring at a pseudo-terminal ------------------------
def has_readline(binpath):
    for cmd in (["otool", "-L", binpath], ["ldd", binpath]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True).stdout
            if "readline" in out.lower():
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    return False


def type_live(keys, env_extra=None, settle=0.7):
    """Type `keys` char-by-char into an interactive ngspice on a pty; return the
    raw bytes the terminal received."""
    import pty, time, select
    pid, fd = pty.fork()
    if pid == 0:
        if env_extra:
            os.environ.update(env_extra)
        os.execv(NGSPICE, [NGSPICE])
    time.sleep(1.0)
    for ch in keys:
        os.write(fd, ch.encode())
        time.sleep(0.05)
    time.sleep(settle)
    buf = b""
    while True:
        r, _, _ = select.select([fd], [], [], 0.4)
        if not r:
            break
        try:
            d = os.read(fd, 4096)
        except OSError:
            break
        if not d:
            break
        buf += d
    try:
        os.write(fd, b"\x03quit\n")
        time.sleep(0.15)
        os.close(fd)
    except OSError:
        pass
    return buf


print("--- live (as-you-type, pseudo-terminal) ---")
if not has_readline(NGSPICE):
    skipped += 1
    print("  SKIP  live as-you-type coloring: this ngspice was built without GNU "
          "readline (the shipped binaries are built with it, --with-readline=yes)")
else:
    out = type_live("plot")
    check("typing a complete command 'plot' renders green live",
          (GREEN + "plot").encode() in out)
    out = type_live("xqz")
    check("typing an impossible command 'xqz' renders red live",
          (RED + "xqz").encode() in out)
    out = type_live("plo")
    check("typing a valid prefix 'plo' stays neutral live",
          (GREEN + "plo").encode() not in out and (RED + "plo").encode() not in out)
    out = type_live("plot", env_extra={"NO_COLOR": "1"})
    check("NO_COLOR suppresses live coloring", b"\033[32m" not in out)

    # pressing Enter must move to a fresh line before the command output -- the
    # custom redisplay bypasses readline's cursor tracking, so accept-line has to
    # emit the closing newline itself (else output runs onto the input line).
    def screen_lines(raw):
        import re as _re
        raw = _re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw.decode(errors="replace"))
        lines = []
        for pl in raw.split("\n"):
            cur = ""
            for seg in pl.split("\r"):
                cur = seg if len(seg) >= len(cur) else seg + cur[len(seg):]
            lines.append(cur.rstrip())
        return lines
    # Use a command whose output text is distinct from the command itself: if
    # accept-line failed to emit the closing newline, the error would be
    # concatenated onto the input line ("... print v(zqx)Error: ...").
    out = type_live("print v(zqx)\r", settle=1.0)   # \r submits the line
    sc = screen_lines(out)
    input_line = next((l for l in sc if "print v(zqx)" in l and "->" in l), "")
    check("Enter moves output to a new line (not concatenated onto the input)",
          input_line != "" and "not available" not in input_line
          and "Warning" not in input_line
          and b"not available" in out,           # the command did run (and warn)
          f"(input line={input_line!r})")
    # a non-tty (piped) session must never leak color codes into output
    r = subprocess.run([NGSPICE], input="plot\nboguscmd\nquit\n",
                       capture_output=True, text=True, timeout=30)
    check("piped (non-tty) session leaks no color codes",
          "\033[32m" not in r.stdout and "\033[31m" not in r.stdout)

    # ---- semantic layer (E-170): signal + expression validity, red errors ----
    import tempfile as _tf
    _rc = os.path.join(_tf.gettempdir(), "synhl_rc.cir")
    open(_rc, "w").write("* rc\nv1 a 0 dc 1\nr1 a b 1k\nr2 b 0 1k\n.op\n.end\n")

    def type_after_run(keys, env_extra=None, settle=0.7):
        """Type `keys' after sourcing + running a circuit, so its node signals
        (a, b, ...) exist in the current plot."""
        import pty, time, select
        pid, fd = pty.fork()
        if pid == 0:
            if env_extra:
                os.environ.update(env_extra)
            os.execv(NGSPICE, [NGSPICE])
        time.sleep(1.0)
        for s in ("source " + _rc + "\r", "run\r"):
            os.write(fd, s.encode()); time.sleep(0.6)
        while select.select([fd], [], [], 0.3)[0]:
            try:
                os.read(fd, 4096)
            except OSError:
                break
        for ch in keys:
            os.write(fd, ch.encode()); time.sleep(0.05)
        time.sleep(settle)
        buf = b""
        while select.select([fd], [], [], 0.3)[0]:
            try:
                d = os.read(fd, 4096)
            except OSError:
                break
            if not d:
                break
            buf += d
        try:
            os.write(fd, b"\x03quit\r"); time.sleep(0.15); os.close(fd)
        except OSError:
            pass
        return buf

    print("--- semantic layer (signal + expression validity, red errors) ---")
    out = type_after_run("print v(a)")
    check("[signal] a valid signal v(a) is not red (exists after run)",
          b"v(a)" in out and (RED + "v(a)").encode() not in out)
    out = type_after_run("print v(zzz)")
    check("[signal] an invalid signal v(zzz) is red",
          (RED + "v(zzz)").encode() in out)
    out = type_after_run("print v(a)+v(zzz)")
    check("[expr] invalid signal inside a valid expression: only the signal is red",
          (RED + "v(zzz)").encode() in out and (RED + "v(a)").encode() not in out)
    out = type_after_run("print v(a)*/v(b)")
    check("[parse] a settled malformed expression is red as a whole",
          (RED + "v(a)*/v(b)").encode() in out)
    out = type_after_run("print v(bP")
    check("[incomplete] a half-typed expression stays neutral, no parser-error spam",
          (RED + "v(bP").encode() not in out and b"syntax error" not in out)
    out = type_after_run("print v(zzz)\r", settle=1.0)
    check("[error] error/warning output is drawn in red",
          b"\033[31mWarning" in out)
    out = type_after_run("print v(zzz)\r", env_extra={"NO_COLOR": "1"}, settle=1.0)
    check("[error] NO_COLOR suppresses red error output",
          b"\033[31m" not in out and b"not available" in out)

print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
raise SystemExit(1 if failed else 0)
