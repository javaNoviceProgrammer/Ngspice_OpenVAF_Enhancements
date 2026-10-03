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

Enhancement-788 gives `help optimize` the full description beneath its line:
  [10] it follows the one-line text after a blank line; every flag, alias and
       -method name the parser in com_optimize.c accepts appears in it, and
       every result the command publishes; it fits 79 columns with only its
       section headers in column 0; `help all` keeps optimize to one line; the
       three examples run as printed on the deck the description names

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

# ------------------------------------------------------------------- [9]
# The internals document (docs/internals/ngspice_internals/ngspice_commands.md)
# ends with a table of every command `help all` prints, generated from the
# binary by make_commands_table.py in the same folder. A command added to the
# table in commands.c without rerunning that script shows up here.
print("\n[9] the internals document lists every command `help all` prints")
DOC = os.path.join(HERE, "..", "..", "docs", "internals", "ngspice_internals", "ngspice_commands.md")
doc = open(DOC).read()
seg = doc[doc.find("<!-- helpall:begin -->"):doc.find("<!-- helpall:end -->")]
rows = re.findall(r"^\| `([a-z_0-9]+)` \| (.*?) \| (.*) \|$", seg, re.M)
names_doc = [r[0] for r in rows]
names_bin = [l.split(" ", 1)[0] for l in (lst or []) if re.match(r"^[a-z_0-9]+\s", l)]
check("[9] the document's table names exactly the commands `help all` lists, once each",
      names_doc and sorted(names_doc) == sorted(names_bin) and len(names_doc) == len(set(names_doc)),
      f"doc {len(names_doc)} / binary {len(names_bin)}; missing {sorted(set(names_bin) - set(names_doc))[:5]}, "
      f"extra {sorted(set(names_doc) - set(names_bin))[:5]}")


def norm(s):
    return s.replace("\\|", "|").replace("`", "").strip()


bin_desc = {}
for l in (lst or []):
    m = re.match(r"^([a-z_0-9]+)\s(.*?)\s*:\s(.*)$", l)
    if m:
        bin_desc[m.group(1)] = norm(m.group(3))
doc_desc = {r[0]: norm(r[2]) for r in rows}
bad = [n for n in names_doc if doc_desc.get(n) != bin_desc.get(n)]
check("[9] ...and each description is the one the command table carries (rerun make_commands_table.py otherwise)",
      not bad, f"differs for {bad[:5]}")

# ------------------------------------------------------------------- [10]
# Enhancement-788: `help optimize` prints the full description beneath the
# one-line text -- every option, the methods, the results and examples. The
# one line had stayed at E-145's options (two of the nine methods, nothing of
# -center, -constrain, -polish or -starts). The description lives beside the
# parser in com_optimize.c; these checks scrape the parser, so an option added
# there without being described fails here.
print("\n[10] help optimize")
osrc = open(os.path.join(REPO, "ngspice-46", "src", "frontend", "com_optimize.c")).read()
out5 = run_batch("help optimize\necho ====\nhelp all")
p5 = out5.split("====")
ho = p5[0].split("\n")
i_one = next((i for i, l in enumerate(ho) if l.startswith("optimize ")), None)
i_use = next((i for i, l in enumerate(ho) if l == "Usage:"), None)
i_end = next((i for i, l in enumerate(ho) if l.startswith("For further details")), None)
desc = ho[i_use:i_end - 1] if i_use is not None and i_end is not None else []
text = "\n".join(desc)
check("[10] `help optimize` prints its one-line text, a blank line, then the description",
      i_one is not None and i_use == i_one + 2 and ho[i_one + 1] == "" and len(desc) > 100,
      f"{len(desc)} lines")


def word_in(w, t):
    return re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", t) is not None


flags = sorted(set(re.findall(r'eq\(w, "(-[a-z]+)"\)', osrc)))
miss = [f for f in flags if not word_in(f, text)]
check(f"[10] every flag the parser accepts is described, aliases included ({len(flags)})",
      len(flags) > 30 and not miss, f"missing {miss[:6]}")
methods = sorted(set(re.findall(r'eq\(mm, "([a-z-]+)"\)', osrc)))
miss = [m for m in methods if not word_in(m, text)]
check(f"[10] every -method name the parser accepts is described ({len(methods)})",
      len(methods) > 25 and not miss, f"missing {miss[:6]}")
results = sorted(set(re.findall(r'(?:dc_set_result|cp_vset)\("([a-z_]+)"', osrc)))
miss = [r for r in results if not word_in(r, text)]
check(f"[10] every result the command publishes is described ({len(results)}), "
      "with optimize_<name> and pareto1 ... paretoM",
      len(results) >= 8 and not miss and "optimize_<name>" in text and "paretoM" in text,
      f"missing {miss[:6]}")
long_ = [l for l in desc if len(l) > 79 or "\t" in l or l != l.rstrip()]
col0 = [l for l in desc if l and l[0] != " " and not l.endswith(":")]
check("[10] the description fits 79 columns, and only its section headers start in column 0 "
      "(so [6] cannot read a line as a command's)", desc and not long_ and not col0,
      f"{long_[:2]} {col0[:2]}")
lst5 = p5[1].split("\n") if len(p5) > 1 else []
oline = [l for l in lst5 if l.startswith("optimize ")]
check("[10] `help all` keeps optimize to one line naming the nine methods, without the description",
      len(oline) == 1 and "nm|lm|tr|pso|de|sa|cmaes|bayes|nsga2" in oline[0]
      and "Usage:" not in p5[1] and oline[0].endswith("."), f"{oline[:1]}")

# the examples, run as printed on the deck the description names
ex = desc[desc.index("Examples:") + 1:] if "Examples:" in desc else []
deck_txt, cmds = "", []
for l in ex:
    if l.startswith("    optimize "):
        cmds.append(l.strip())
    elif l.startswith("             ") and cmds:
        cmds[-1] += " " + l.strip()
    elif not cmds and l.startswith("  "):
        deck_txt += " " + l.strip()
m = re.search(r"On a deck with (.*):$", deck_txt.strip())
deck = re.split(r",\s*|\s+and\s+", m.group(1)) if m else []
res = []
if deck and len(cmds) == 3:
    ctl = "\n".join(c + "\necho status=$optimize_status" for c in cmds)
    p = os.path.join(HERE, "_hx.cir")
    open(p, "w").write("* help optimize examples\n" + "\n".join(deck) + "\n.control\n" + ctl +
                       "\necho feasible=$optimize_feasible\nquit\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", "_hx.cir"], cwd=HERE, capture_output=True, text=True,
                       timeout=300, errors="replace")
    os.remove(p)
    res = r.stdout.split("status=")


def knob(chunk, name):
    m = re.search(r"^\s+" + re.escape(name) + r" = (\S+)", chunk, re.M)
    return float(m.group(1)) if m else None


ok1 = len(res) == 4 and res[1].startswith("converged") and abs((knob(res[0], "r2") or 0) - 1000) < 1
AT = "@"     # split from the model name: check_mentions reads this file
is_, n_ = (knob(res[1], AT + "dmod[is]"), knob(res[1], AT + "dmod[n]")) if len(res) == 4 else (None, None)
ok2 = (len(res) == 4 and res[2].startswith("converged") and is_ and n_
       and 0.9e-13 < is_ < 1.4e-13 and 1.15 < n_ < 1.25)
ok3 = (len(res) == 4 and res[3].startswith("converged") and "feasible=1" in res[3]
       and abs((knob(res[2], "r2") or 0) - 1500) < 2)
check("[10] the three examples run as printed on the deck the description names: R2 = 1k; "
      "is ~ 1.1e-13 and n ~ 1.2 fitted; R2 = 1.5k with v(out) <= 0.6 met",
      bool(ok1 and ok2 and ok3), f"deck {len(deck)} lines, {len(cmds)} examples, is {is_} n {n_}")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
