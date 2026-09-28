#!/usr/bin/env python3
"""Regression guard: the interactive `help` command must not crash.

ngspice prints each command's one-line help by passing the help string itself
as the *format* argument to out_printf/tvprintf:

    out_printf(ccc[i]->co_help, cp_program);   /* com_help.c */

so the help string is a printf format with exactly one available argument
(cp_program, meant for a single %s). A help string that contains any other '%'
(e.g. a literal "95% CI") is an invalid conversion specifier: tvprintf fails and
ngspice calls a fatal exit(-1). `help all` walks every command, so one bad
string takes down the whole command -- and `help <thatcommand>` too.

This actually shipped: the `montecarlo` command's help (Enhancement-151) read
"... a Wilson 95% CI ...", so `help all` and `help montecarlo` crashed with
"Error: tvprintf failed / fatal error in ngspice, exit(-1)". Fixed by escaping
the percent as %%.

Two checks:
  [1..3] RUNTIME -- drive an interactive ngspice on a pty and confirm `help`,
         `help all`, and `help montecarlo` each run to completion (no crash, no
         "tvprintf failed"), and that the montecarlo line renders the literal
         "95% CI".
  [4] STATIC class-guard -- scan commands.c and assert NO command help string
         carries a format hazard (a '%' that is not '%s' or '%%', or more than
         one '%s'), so a future unescaped '%' is caught even if that specific
         command is never exercised at runtime.

Enhancement-753 adds the listing itself (batch mode):
  [5] every line of the `help all` list has the form `name args : text.` -- no
      continuation line (setscale's second half printed as one), no blank line
      inside the list (deftype ended in a newline), the separator (remzerovec,
      sysinfo lacked it), a final period, one space after the name, no trailing
      space; the list is sorted
  [6] completeness: the listed names are exactly the names in commands.c's table
      that `help <name>` answers in this build. `help all` and `newhelp` counted
      the table to the first entry WITHOUT A HANDLER instead of to its
      terminator; the control keywords have none, so the 28 commands from
      `while` down (the keywords, settype, strcmp, fopen, linearize, cutout,
      devhelp, inventory, check_ifparm ...) were never listed
  [7] `help setscale` is one line; `help` alone and an unknown name answer as
      before; the manual links still follow the list
  [8] `newhelp` at the advanced level lists the keywords and what follows them

Not a circuit simulation, so the dual-solver harness does not apply.
"""
import os
import pty
import re
import select
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

REPO = os.path.dirname(os.path.dirname(HERE))
COMMANDS_C = os.path.join(REPO, "ngspice-46", "src", "frontend", "commands.c")

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run_help(arg):
    """Type `help <arg>` into an interactive ngspice on a pty. Return
    (status, text) where status is 'ok' / 'crash' / 'exit<N>'."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(NGSPICE, [NGSPICE])
        os._exit(1)
    time.sleep(0.8)
    os.write(fd, (f"help {arg}\r" if arg else "help\r").encode())
    time.sleep(1.6)
    buf = b""
    try:
        while select.select([fd], [], [], 0.4)[0]:
            d = os.read(fd, 4096)
            if not d:
                break
            buf += d
    except OSError:
        pass
    status = "ok"
    try:
        wpid, st = os.waitpid(pid, os.WNOHANG)
        if wpid and os.WIFSIGNALED(st):
            status = f"crash(sig{os.WTERMSIG(st)})"
        elif wpid:
            status = f"exit{os.WEXITSTATUS(st)}"
    except ChildProcessError:
        status = "gone"
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    txt = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", buf.decode(errors="replace"))
    return status, txt


def alive_and_clean(status, txt):
    return status == "ok" and "tvprintf failed" not in txt and "fatal error" not in txt


# [1] plain `help` (the short blurb)
st, txt = run_help("")
check("[1] `help` runs without crash", alive_and_clean(st, txt), f"({st})")

# [2] `help all` -- walks every command's help string through the printf path
st, txt = run_help("all")
check("[2] `help all` runs without crash (was: tvprintf fatal at montecarlo)",
      alive_and_clean(st, txt), f"({st})")

# [3] `help montecarlo` -- the specific regressor; the % must render literally
st, txt = run_help("montecarlo")
line = next((l for l in txt.splitlines() if "Wilson" in l), "")
check("[3] `help montecarlo` runs and renders a literal '95% CI'",
      alive_and_clean(st, txt) and "95% CI" in line,
      f"({st}; line={line.strip()[:60]!r})")

# [4] STATIC class-guard over commands.c help strings
hazards = []
if os.path.isfile(COMMANDS_C):
    src = open(COMMANDS_C, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', src):
        s = m.group(1)
        if "%" not in s:
            continue
        toks = re.findall(r"%.", s)
        bad = [t for t in toks if t not in ("%s", "%%")]
        # a trailing bare '%' at end-of-literal also can't be caught by %. above
        trailing = s.endswith("%") and not s.endswith("%%")
        if bad or trailing or s.count("%s") > 1:
            ln = src[:m.start()].count("\n") + 1
            hazards.append((ln, toks, s[:70]))
    check("[4] no command help string has a printf-format hazard "
          "(bare % / multiple %s)",
          not hazards,
          "" if not hazards else f"({len(hazards)} found: {hazards[:2]})")
else:
    # source not present (running against a packaged binary only) -- skip, don't fail
    check("[4] static help-string scan (source not present -- skipped)", True,
          "(commands.c not found)")

# ---------------------------------------------------------------- E-753
MISSING_BEFORE = ["while", "repeat", "dowhile", "foreach", "if", "else", "end", "break",
                  "continue", "label", "goto", "cdump", "mdump", "mrdump", "settype", "strcmp",
                  "strstr", "strslice", "fopen", "fread", "fclose", "linearize", "cutout",
                  "devhelp", "inventory", "optran", "wrnodev", "check_ifparm"]


def run_batch(control):
    p = os.path.join(HERE, "_h.cir")
    open(p, "w").write("* helpcmd\n.control\n" + control + "\nquit\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", "_h.cir"], cwd=HERE, capture_output=True, text=True,
                       timeout=120, errors="replace")
    os.remove(p)
    return r.stdout


def the_list(out):
    """The command list: from the first `name ...` line after the circuit banner
    to the blank line before the manual links."""
    L = out.split("\n")
    try:
        i1 = next(i for i, l in enumerate(L) if l.startswith("For further details"))
    except StopIteration:
        return None, L
    i0 = next(i for i, l in enumerate(L) if l.startswith("Circuit:")) + 2
    return L[i0:i1 - 1], L



# ------------------------------------------------------------------- [5]
print("\n[5] the form of every line")
out = run_batch("help all")
lst, L = the_list(out)
if lst is None:
    check("[5] `help all` prints a list followed by the manual links", False, out[-200:])
    lst = []
else:
    cont = [l for l in lst if l[:1] in (" ", "\t")]
    blank = [i for i, l in enumerate(lst) if l == ""]
    nosep = [l for l in lst if l and l[0] not in " \t" and not re.match(r"^\S+ (.* )?:( |$)", l)]
    noper = [l for l in lst if l and l[0] not in " \t" and not l.endswith(".")]
    dbl = [l for l in lst if re.match(r"^\S+  ", l)]
    trail = [l for l in lst if l != l.rstrip()]
    check("[5] no continuation line (setscale's second half printed as one)", not cont, f"{cont[:2]}")
    check("[5] no blank line inside the list (deftype's text ended in a newline)", not blank,
          f"after {[lst[i - 1][:30] for i in blank][:3]}")
    check("[5] every line has the `name args : text` separator (remzerovec, sysinfo lacked it)", not nosep, f"{nosep[:3]}")
    check("[5] every line ends with a period (where, inventory, fopen, fread, strslice ... did not)", not noper, f"{[l[-40:] for l in noper[:3]]}")
    check("[5] one space after the name, no trailing space (linearize, cutout, optran, wrnodev)", not dbl and not trail, f"{dbl[:2]} {trail[:2]}")
    names = [l.split(" ", 1)[0] for l in lst if l and l[0] not in " \t"]
    check("[5] the list is sorted by name", names == sorted(names), "")

# ------------------------------------------------------------------- [6]
print("\n[6] completeness against the command table")
src = open(os.path.join(REPO, "ngspice-46", "src", "frontend", "commands.c")).read()
table = src[src.index("struct comm spcp_coms[]"):src.index("struct comm nutcp_coms[]")]
tnames = sorted(set(re.findall(r'\{\s*"([^"]+)",\s*\w+,\s*(?:TRUE|FALSE),', table)))
out2 = run_batch("help " + " ".join(tnames))
answered = set()
for l in out2.split("\n"):
    m = re.match(r"^(\S+) ", l)
    if m and m.group(1) in tnames and not l.startswith("Sorry"):
        answered.add(m.group(1))
listed = set(l.split(" ", 1)[0] for l in lst if l)
check(f"[6] the listed names are exactly the table's names that `help <name>` answers in this build ({len(answered)})",
      listed == answered and len(listed) > 150,
      f"listed-not-answered {sorted(listed - answered)[:5]} answered-not-listed {sorted(answered - listed)[:5]}")
miss = [n for n in MISSING_BEFORE if n not in listed]
check(f"[6] the {len(MISSING_BEFORE)} commands below `while` in the table are listed (the control keywords and settype ... wrnodev)",
      not miss, f"missing {miss[:6]}")
ctrl = ["while", "repeat", "dowhile", "foreach", "if", "else", "end", "break", "continue", "label", "goto"]
check("[6] the eleven control keywords each have their line", all(any(l.startswith(k + " ") for l in lst) for k in ctrl))

# ------------------------------------------------------------------- [7]
print("\n[7] the single-command forms")
out3 = run_batch("help setscale\necho ====\nhelp\necho ====\nhelp nosuchcmd")
parts = out3.split("====")
first = [l for l in parts[0].split("\n") if l.strip() and not l.startswith(("Circuit", "Warning"))]
one_line = (len(first) >= 1
            and first[0].startswith("setscale [vecname [vecname]] : Change default scale of current working plot, or set/clear")
            and (len(first) == 1 or not first[1].startswith(" ")))
check("[7] `help setscale` is one line", one_line, f"{first[:2]}")
check("[7] `help` alone still prints the short pointer to `help all`",
      len(parts) > 1 and 'For a list of all commands type "help all"' in parts[1])
check("[7] an unknown name still answers `Sorry, no help for nosuchcmd.`",
      len(parts) > 2 and "Sorry, no help for nosuchcmd." in parts[2])
check("[7] the manual links still follow the list (their indented URLs are deliberate)",
      "  https://ngspice.sourceforge.io/docs/ngspice-manual.pdf" in out)

# ------------------------------------------------------------------- [8]
print("\n[8] newhelp")
out4 = run_batch("set level=a\nnewhelp")
seen = [k for k in ("while", "if", "goto", "settype", "fopen", "linearize", "devhelp") if re.search(r"^" + k + " ", out4, re.M)]
check("[8] `newhelp` at the advanced level lists the control keywords and the commands below them (it cut the table the same way)",
      len(seen) == 7, f"{seen}")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
