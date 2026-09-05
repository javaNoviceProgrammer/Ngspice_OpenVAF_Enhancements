#!/usr/bin/env python3
"""Enhancement-553: raw strings and f-strings in the control language.

A deck is folded to lower case as it is read, and the fold reached the text a
control script hands to a command: `pyplot ... title "RC Low-Pass"` printed
`rc low-pass`, `set t="ABC"` stored `abc`. The fold is command-specific and
uneven (echo lines and gnuplot's title tokens were exempt, pyplot's were not),
and the same pass drops the spaces around an `=` inside a quoted string. There
was no way to say "this text, as written".

Now, after Python:
  r"..." / r'...'   a RAW string: copied through the deck reader as written --
                    its case and its spaces kept (also R, rf, fr)
  f"..." / f'...'   an F-STRING: every {expression} inside it is evaluated with
                    the control-language evaluator and replaced by its text,
                    with an optional printf-style format after ':' (`.3f`,
                    `.4g`, `e`, `d`); a scalar prints with %g, a vector as its
                    elements, a complex value as re,im; \\{ and \\} are literal
                    braces ({{ }} belongs to the netlist's .for construct); an
                    expression that resolves to nothing is an error naming the
                    string, and the command is not run
  rf"..." / fr"..." both
The prefix is a prefix only at a token start (`set t=r"..."` counts, a device
called r or a variable called f does not), and pyplot's title/xlabel/ylabel
tokens keep their case like plot's and gnuplot's did all along.

Checks (both solvers):
  [1]  r"..." and r'...' keep case in a deck; a plain "..." still folds (unchanged)
  [2]  set t=r"..." keeps case; the value reads back through $t
  [3]  pyplot's plain quoted title now keeps case like gnuplot's; a raw xlabel/ylabel too
  [4]  a raw string keeps the spaces around '=' that the deck reader strips elsewhere
  [5]  f"...": %g default, a format spec, an integer, a vector, a complex value
  [6]  rf"...": case kept and evaluated; \\{ \\} literal braces survive globbing
  [7]  an unresolved {expr} is an error naming the string; the command does not run
  [8]  a '{' without '}' is an error; a stray '}' is an error
  [9]  a colon inside brackets or parentheses is not a format spec
  [10] f-strings in a foreach list are evaluated
  [11] a bare r, f, rf word, a resistor r1 and `set r=...` are untouched
  [12] the interactive path takes all three prefixes
  [13] a .for loop with {{i}} in the netlist coexists with f-strings in the control block
  [14] an f-string title on a plot: formatted, case kept, spaces kept
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="rawfstring_")
CIRCUIT = """v1 in 0 dc 0 sin(0 1 1k) ac 1
r1 in out 1k
c1 out 0 159n"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(ctl, tag, netlist=CIRCUIT):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* Raw And F-String Probe {tag}\n{netlist}\n.control\ntran 10u 1m\n"
                f"echo START\n{ctl}\necho END\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=WORK, stdin=subprocess.DEVNULL)
    out = r.stdout
    body = out[out.find("START"):out.find("END")] if "START" in out and "END" in out else ""
    return body, r.stderr + out


def script(tag):
    p = os.path.join(WORK, tag + ".py")
    return open(p).read() if os.path.isfile(p) else ""


PNG = "set pyplot_terminal=png\nset pyplot_backend=Agg\n"

print("Enhancement-553: raw strings and f-strings\n")

# --------------------------------------------------------- [1]-[4] raw ---
body, all_ = run('''set a=r"ABC Def"
set b=R'Mixed Case'
set c="ABC Def"
echo a=$a b=$b c=$c
echo A r"B C" r'D E' plain''' + PNG + '''pyplot rw v(out) title "Plain Title Kept" xlabel r'My Time' ylabel R"Quoted Volts"
set d=r"A = B raw"
set e="A = B plain"
echo d=$d e=$e''', "raw")
check("[1] r\"...\" and r'...' keep their case in a deck; a plain \"...\" still folds",
      "b=Mixed Case" in body and "c=abc def" in body and "A B C D E plain" in body, body.strip()[-160:])
check("[2] set t=r\"...\" keeps case and reads back through $t", "a=ABC Def" in body)
py = script("rw")
check("[3] pyplot's plain quoted title keeps case like gnuplot's; a raw xlabel/ylabel too",
      "suptitle('Plain Title Kept')" in py and "set_xlabel('My Time')" in py and "set_ylabel('Quoted Volts')" in py,
      py[-200:])
check("[4] a raw string keeps the spaces around '=' that the deck reader strips from a plain one",
      "d=A = B raw" in body and "e=a=b plain" in body, body.strip()[-120:])

# ------------------------------------------------------- [5]-[10] f ---
body, all_ = run('''echo f"vmax {vecmax(v(out)):.3f} V default {vecmax(v(out))} int {length(v(out)):d} vec {vector(3)} pct {100*0.4963:.1f}%"
echo rf"Kept Case {2*3} and \\{literal\\} braces"
setplot tran1
ac dec 2 1 100
echo f"complex {v(out)[0]} mag {mag(v(out)[0]):.4f}"
setplot tran1
foreach x f"{1+1}" f"{2+2}"
  echo x=$x
end
echo f"colon {vecmax(v(out)[0])} paren {max(1,2)} name {v(out)[1]:.2e}"''', "fstr")
check("[5] f-string: %g default, a .3f spec, an integer :d, a vector, a complex value as re,im",
      re.search(r"vmax 0\.75\d V default 0\.75\d+ int \d+ vec 0 1 2 pct 49\.6%", body) is not None
      and re.search(r"complex 0\.99\d+,-0\.000\d+ mag 1\.0000", body) is not None, body.strip()[-260:])
check("[6] rf-string: case kept, evaluated, \\{ \\} literal braces survive globbing",
      "Kept Case 6 and {literal} braces" in body, body.strip()[-160:])
check("[10] f-strings in a foreach list are evaluated", 'x="2"' in body and 'x="4"' in body)
check("[9] a colon inside brackets or parentheses is not a format spec, and a real spec after one works",
      re.search(r"colon 0 paren 2 name \d\.\d\de[-+]\d\d", body) is not None, body.strip()[-120:])

body, all_ = run('''echo f"bad {v(nosuch)} here"
echo after-bad
echo f"open {2*3"
echo f"stray } here"
echo after-both''', "ferr")
check("[7] an unresolved {expr} is an error naming the string, and the command does not run",
      'Error: f-string f"bad {v(nosuch)} here": {v(nosuch)} does not evaluate' in all_
      and "bad {" not in body and " here" not in body and "after-bad" in body, all_.strip()[-200:])
check("[8] a '{' without '}' and a stray '}' are errors; the script goes on",
      "'{' without a closing '}'" in all_ and "a '}' without a '{'" in all_ and "after-both" in body
      and "open" not in body and "stray" not in body, all_.strip()[-200:])

# ------------------------------------------------- [11]-[14] boundaries ---
body, all_ = run('''let r = 3
let f = 4
set rf=plain
echo r=$&r f=$&f rf=$rf rr ff
print @r1[resistance]''', "words")
check("[11] a bare r, f, rf word, a resistor r1 and `set r=...` are untouched",
      "r=3 f=4 rf=plain rr ff" in body and "1.000000e+03" in body, body.strip()[-120:])

r = subprocess.run([NGSPICE, "-p"], input='echo r"ABC Def" f"{1+1}" rf"Kept {3*3}" \'Single Quoted\'\nquit\n',
                   capture_output=True, text=True, timeout=60, cwd=WORK)
check("[12] the interactive path takes all three prefixes",
      "ABC Def 2 Kept 9 Single Quoted" in r.stdout, r.stdout.strip()[-120:])

body, all_ = run('''echo f"loop devices {length(v(out))}"
print @rl1[resistance] @rl2[resistance]''', "forloop",
                 netlist=CIRCUIT + "\n.for i in range(1,3)\nrl{{i}} n{{i}} 0 {{i}}k\n.endfor")
check("[13] a .for loop with {{i}} in the netlist coexists with f-strings in the control block",
      "loop devices" in body and "1.000000e+03" in body and "2.000000e+03" in body, body.strip()[-160:])

body, all_ = run(PNG + '''pyplot ft v(out) title rf"RC low-pass, Vmax = {vecmax(v(out)):.3f} V"''', "ftitle")
py = script("ft")
check("[14] an f-string title on a plot: formatted, case kept, spaces kept",
      re.search(r"suptitle\('RC low-pass, Vmax = 0\.75\d V'\)", py) is not None, py[-160:])

print(f"\n{passed}/{checks} checks passed")
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(0 if passed == checks else 1)
