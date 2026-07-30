#!/usr/bin/env python3
"""Enhancement-377: OSDI diagnostics were unreadable and had no severity.

Found by the correctness campaign over all 94 `$`-prefixed system functions, when
`$simparam$str("analysis")` -- a wrong name, my mistake -- reported:

    OSDI(debug) n1: unknown $simparam_stranalysisOSDI(debug) n1: unknown $simp...

Four separate defects in that one line.

1. NO SEPARATOR. `concat("unknown $simparam_str", name)` glued the function name to
   its argument, so `$simparam_str` + `analysis` read as `$simparam_stranalysis`
   and the reader cannot see where one ends and the other begins.

2. NO NEWLINE. `osdi_log` writes with `fprintf(dst, "%s", msg)` and no message
   carried a `\\n`, so consecutive reports concatenated into a single unreadable
   line. This also HID the repetition: the old output looked like two lines, the
   new one shows 373 -- the same 373 reports were always there.

3. WRONG SEVERITY, FOR EVERY MESSAGE IN THE OSDI LAYER. ngspice's `osdi.h` had
   `#define LOG_LVL_MASK 8`. The level occupies the low THREE bits (DEBUG 0 ..
   FATAL 5), so the mask must be 7; 8 selects bit 3, which no level ever sets, so
   `lvl & LOG_LVL_MASK` was 0 -- LOG_LVL_DEBUG -- for EVERY level. `$display`,
   `$info`, `$warning`, `$error` and every fatal diagnostic alike were labelled
   "OSDI(debug)" and written to stdout. OpenVAF's own copy of the header
   (`osdi/header/osdi_0_4.h`) has always said 7, so the two sides disagreed.

   This is the one with reach beyond `$simparam`: severity was invisible to the
   user and to any log scraping, and `$error`/`$warning` never reached stderr.

4. A LEAK. The message was `malloc`ed and never freed -- and `free` was not even
   declared in the runtime's `NO_STD` block. At 373 reports per failing operating
   point that is 373 leaked allocations, not one.

WHAT IS NOT FIXED, deliberately: the report still repeats 373 times. That is
ngspice retrying the failing operating point (gmin then source stepping), each
retry re-evaluating the device. Suppressing it is a convergence-path change, not a
diagnostic one, and is left alone here.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402

checks = passed = 0

BAD_SIMPARAM = """`include "disciplines.vams"
module spdiag(a, c);
  inout a, c; electrical a, c;
  (* desc="s" *) string s;
  analog begin
    // the result must be USED or the call is dead-code eliminated and the
    // diagnostic never fires -- that cost a confused half hour
    s = $simparam$str("no_such_name");
    I(a,c) <+ 1e-3*V(a,c);
  end
endmodule
"""

SEVERITIES = """`include "disciplines.vams"
module spsev(a, c);
  inout a, c; electrical a, c;
  analog begin
    @(initial_step) begin
      $display("SEV_DISPLAY");
      $info("SEV_INFO");
      $warning("SEV_WARN");
      $error("SEV_ERR");
    end
    I(a,c) <+ 1e-3*V(a,c);
  end
endmodule
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_sd_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, "m.va", "-o", "m.osdi"], cwd=d, env=env,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return os.path.join(d, "m.osdi") if r.returncode == 0 else None


def sim(osdi, model, tag):
    """Returns (stdout, stderr) SEPARATELY -- the routing is half the point."""
    p = os.path.join(HERE, "_sd_%s.cir" % tag)
    open(p, "w").write(
        "spdiag\nV1 a 0 dc 0.4\nN1 a 0 %s\n.model %s %s()\n"
        ".control\noption noacct\npre_osdi %s\nop\n.endc\n.end\n"
        % (model, model, model, osdi))
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout, r.stderr


def main():
    osdi = build(BAD_SIMPARAM, "sp")
    if not osdi:
        check("unknown-simparam model builds", False, "compile failed")
        return finish()
    out, err = sim(osdi, "spdiag", "sp")
    both = out + err

    # 1. separator + quoting: the argument must be quoted, not glued on
    check("the name is separated from the function and quoted",
          'unknown $simparam$str "no_such_name"' in both,
          "glued form 'unknown $simparam$strno_such_name' is the pre-fix signature")

    check("the glued pre-fix spelling is gone",
          "$simparam$strno_such_name" not in both and
          "$simparam_strno_such_name" not in both)

    # 2. the Verilog-A spelling is `$simparam$str`, not the internal `$simparam_str`
    check("reported as `$simparam$str`, the spelling the user wrote",
          "$simparam$str" in both and "unknown $simparam_str" not in both)

    # 3. severity: a fatal must say fatal, and must be on stderr
    check("the fatal diagnostic is labelled OSDI(fatal)",
          "OSDI(fatal)" in both and
          not re.search(r"OSDI\(debug\)[^\n]*unknown \$simparam", both),
          "was OSDI(debug)")
    check("the fatal diagnostic goes to stderr, not stdout",
          "unknown $simparam" in err and "unknown $simparam" not in out)

    # 4. newline-terminated: each report on its own line, so repeats are visible
    lines = [l for l in err.splitlines() if "unknown $simparam" in l]
    check("each report is newline-terminated (own line)", len(lines) >= 2,
          "%d separate lines; pre-fix they concatenated into one" % len(lines))
    check("no line carries two concatenated reports",
          all(l.count("unknown $simparam") == 1 for l in lines),
          "max per line %d" % max([l.count("unknown $simparam") for l in lines] or [0]))

    # ---- severity routing for the whole task family -------------------------
    osdi = build(SEVERITIES, "sev")
    if not osdi:
        for lbl in ("$display", "$info", "$warning", "$error"):
            check("%s severity routing" % lbl, False, "compile failed")
        return finish()
    out, err = sim(osdi, "spsev", "sev")
    # $display and $info are stdout; $warning and $error are stderr
    check("$display -> 'OSDI ' on stdout",
          re.search(r"OSDI n1: SEV_DISPLAY", out) is not None,
          "was OSDI(debug)")
    check("$info -> 'OSDI(info)' on stdout",
          "OSDI(info) n1: SEV_INFO" in out, "was OSDI(debug)")
    check("$warning -> 'OSDI(warn)' on stderr",
          "OSDI(warn) n1: SEV_WARN" in err, "was OSDI(debug) on stdout")
    check("$error -> 'OSDI(err)' on stderr",
          "OSDI(err) n1: SEV_ERR" in err, "was OSDI(debug) on stdout")
    check("no severity is still mislabelled debug",
          "OSDI(debug)" not in (out + err),
          "every level ANDed to 0 with the old mask of 8")

    return finish()


def finish():
    for j in os.listdir(HERE):
        q = os.path.join(HERE, j)
        if j.startswith("_sd_"):
            shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) else os.remove(q)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
