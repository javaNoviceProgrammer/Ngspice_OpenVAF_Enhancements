#!/usr/bin/env python3
"""Enhancement-458: LRM function-and-form compliance.

Every Verilog-A function openvaf-r knows, in every argument form the LRM writes
for it, compiled AND run with a numeric or textual oracle -- 223 checks. The
oracles are the Verilog-AMS LRM 2023: Tables 4-14/4-15 and A.8.2
`analog_built_in_function_name` (the math functions, in BOTH the `$name` and bare
`name` spellings the LRM defines), Syntax 4-3 (analog operators), 4-4 (noise),
4.6.3 (`ac_stim`), 4.7.1 (`analysis`), 9-7 (severity tasks), 9-10 (environment),
9-12 (`$limit`), 9-16 (`$table_model`), 9.13 (RNG) and 9.5/9.9-9.12 (file I/O).

The audit that produced this suite found eight defects, seven of them fixed here:

  [1] `ln1p` and `expm1` DID NOT EXIST, in either spelling, though A.8.2 lists
      them beside `ln` and `exp`. They are their own MIR opcodes lowered to
      libm's `log1p`/`expm1` rather than `ln(1+x)`/`exp(x)-1`, because precision
      near zero is their entire reason to exist: at x = 1e-15 the naive spelling
      returns 1.11e-15 for a true value of 9.9999999999999949e-16 -- an 11%
      error, the first significant digit already wrong.

  [2] `$abs`, `$min` and `$max` were the only three math functions whose
      `$`-spelling was never registered. The other 23 worked, and the LRM
      explicitly encourages the spelling that failed.

  [3] AN ARRAY PARAMETER -- the form LRM Syntax 4-3 lists FIRST for a filter
      coefficient vector -- was rejected with "requires a bit-select [i]" by
      every Laplace and Z-transform filter. Only the assignment-pattern form
      worked, plus array variables for `laplace_*` (but not `zi_*`).

  [4] A TRAILING null filter argument (`laplace_np(x, n, )`, `laplace_zp(x, , )`)
      was rejected while the interior null (`laplace_zd(x, , d)`) worked.

  [5] `$simparam` required a string LITERAL; LRM 9-10 allows "a string literal,
      string parameter, or string variable".

  [6] `$fatal;` was rejected. Syntax 9-7 makes the whole parenthesised group
      optional, and `$error`/`$warning`/`$info` already accepted the bare form.

  [7] `noise_table` with a string PARAMETER file name PANICKED the compiler
      (exit 101, no diagnostic) on an `as_literal(..).unwrap()`, while its
      sibling `$table_model` rejected the same model cleanly.

Two audit findings were WITHDRAWN after re-reading the LRM, and are pinned here
so they are not "fixed" later by mistake:

  -- `$limit(probe, user_function, args)` is CORRECT as it stands. LRM 9.17 calls
     the user function with (value this iteration, internal state, then $limit's
     third and subsequent arguments), so its arity is always 2 + extra args. The
     audit's test functions took one argument too few; the reading that openvaf
     was "off by one" was the audit's error, not the compiler's.

  -- `noise_table`/`noise_table_log` with an ARRAY IDENTIFIER stays refused. LRM
     4.5.1 does allow it, but this table is materialised when the model is
     COMPILED, and a parameter or variable array only has values at run time.
     Accepting it would hand the builtin an empty table -- the silent
     no-noise-at-all failure Enhancement-399 fixed for `{...}`. It is refused
     with that reason spelled out instead of the old "requires a bit-select [i]".

The one form this suite originally recorded as a gap -- `parameter_identifier
[msb:lsb]`, the second filter-argument form in Syntax 4-3 -- was closed by
Enhancement-459; it is pinned here as accepted, and exercised in full by
`partselect_examples`.
"""
import math
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

HDR = '`include "disciplines.vams"\n'


def build(src, tag, extra=None):
    d = os.path.join(HERE, "_w_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    for n, c in (extra or {}).items():
        open(os.path.join(d, n), "w").write(c)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900,
                       stdin=subprocess.DEVNULL)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def run(d, deck_txt, guard=60):
    open(os.path.join(d, "q.cir"), "w").write(deck_txt)
    r = subprocess.run(["perl", "-e", f"alarm {guard}; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def deck(net="N1 a 0 mm", card="dut()", body="op", src="V1 a 0 dc 1", extra="", pr=""):
    return ("p\n.control\npre_osdi m.osdi\n.endc\n" + src + "\n" + net + "\n.model mm " + card
            + "\n" + extra + "\n.control\noption noacct\nset numdgt=15\n" + body + "\n" + pr
            + "\n.endc\n.end\n")


def opv(out, name):
    m = re.search(rf"@\S*n1\[{re.escape(name)}\]\s*=\s*(\S+)", out)
    return float(m.group(1)) if m else None


def crashy(rc):
    return rc == 101 or rc < 0 or rc == 139 or rc == 134


N=[0];OK=[0];FAIL=[]
def chk(sec,lbl,cond,detail=""):
    N[0]+=1
    if cond: OK[0]+=1
    else: FAIL.append((sec,lbl,detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {lbl:44s} {detail[:40]}")
def mod(body,decl="",ports="p,n",dc=True):
    # `dc=False` for anything whose OWN contribution is being measured: appending a
    # resistor would parallel-load a noise/ac test and add V*1e-3 to an operator read.
    tail=" I(p,n) <+ V(p,n)*1e-3;" if dc else ""
    return (HDR+f"module dut({ports}); inout {ports}; electrical {ports};\n"+decl+
            f" analog begin {body}{tail} end\nendmodule\n")
def opval(src,tag,card="dut()",extra=None):
    d,rc,o=build(src,tag,extra)
    if rc!=0:
        e=[l for l in o.splitlines() if 'error' in l.lower()]
        return None,("CRASH" if crashy(rc) else "rejected"),(e[0][7:60] if e else "")
    out=run(d,deck(card=card,body="op",pr="print @n1[y]"))[1]
    return opv(out,"y"),"ok",""
Y=' (*desc="y"*) real y;\n'

print("\n=== LRM Table 4-14/4-15 + A.8.2: math functions, BOTH spellings ===")
M=[("ln","$ln",math.log,[2.0]),("ln1p","$ln1p",math.log1p,[0.5]),("log","$log10",math.log10,[100.0]),
   ("exp","$exp",math.exp,[1.0]),("expm1","$expm1",math.expm1,[0.5]),("sqrt","$sqrt",math.sqrt,[2.0]),
   ("abs","$abs",abs,[-2.5]),("floor","$floor",math.floor,[2.7]),("ceil","$ceil",math.ceil,[2.2]),
   ("sin","$sin",math.sin,[0.7]),("cos","$cos",math.cos,[0.7]),("tan","$tan",math.tan,[0.7]),
   ("asin","$asin",math.asin,[0.4]),("acos","$acos",math.acos,[0.4]),("atan","$atan",math.atan,[0.4]),
   ("sinh","$sinh",math.sinh,[0.7]),("cosh","$cosh",math.cosh,[0.7]),("tanh","$tanh",math.tanh,[0.7]),
   ("asinh","$asinh",math.asinh,[0.7]),("acosh","$acosh",math.acosh,[1.7]),("atanh","$atanh",math.atanh,[0.4]),
   ("min","$min",min,[(2.0,3.0)]),("max","$max",max,[(2.0,3.0)]),("pow","$pow",math.pow,[(2.0,3.0)]),
   ("atan2","$atan2",math.atan2,[(1.0,2.0)]),("hypot","$hypot",math.hypot,[(3.0,4.0)])]
for i,(trad,dol,ref,pts) in enumerate(M):
    for j,sp in enumerate((trad,dol)):
        pt=pts[0]; a=pt if isinstance(pt,tuple) else (pt,)
        want=ref(*a); args=", ".join("%.17g"%v for v in a)
        g,st,msg=opval(mod(f"y = {sp}({args});",Y),"M%d_%d"%(i,j))
        chk("math",f"{sp}({args})",st=="ok" and g is not None and abs(g-want)<=1e-12*max(1,abs(want)),
            msg or f"{g} want {want:.10g}")

print("\n=== LRM Syntax 4-3: analog operators, every optional-argument form ===")
RAMP="V1 a 0 PWL(0 0 10u 10)"; STEP="V1 a 0 PWL(0 0 0.999u 0 1.001u 2 10u 2)"
def tran(body,tag,src=RAMP,at="5u",decl=""):
    d,rc,o=build(mod(body,decl,dc=False),tag)
    if rc!=0:
        e=[l for l in o.splitlines() if 'error' in l.lower()]
        return None,("CRASH" if crashy(rc) else "rejected"),(e[0][7:60] if e else "")
    out=run(d,deck(src=src,body="tran 0.02u 10u",pr=f"meas tran yy FIND i(v1) AT={at}"))[1]
    m=re.search(r"^\s*yy\s*=\s*(\S+)",out,re.M)
    return (-float(m.group(1)),"ok","") if m else (None,"NOVALUE","")
OPS=[("ddt(x)","ddt(V(p,n))",1e6),("ddt(x,abstol)","ddt(V(p,n),1e-6)",1e6),("ddt(x,nature)","ddt(V(p,n),Voltage)",1e6),
 ("idt(x)","idt(V(p,n))",1.25e-5),("idt(x,ic)","idt(V(p,n),3.0)",3.0+1.25e-5),
 ("idt(x,ic,assert)","idt(V(p,n),3.0,0)",3.0+1.25e-5),("idt(x,ic,assert,tol)","idt(V(p,n),3.0,0,1e-6)",3.0+1.25e-5),
 ("idt(x,ic,assert,nature)","idt(V(p,n),3.0,0,Voltage)",3.0+1.25e-5),
 ("idtmod(x)","idtmod(V(p,n))",1.25e-5),("idtmod(x,ic)","idtmod(V(p,n),3.0)",3.0+1.25e-5),
 ("idtmod(x,ic,mod)","idtmod(V(p,n),0.0,1.0)",1.25e-5),("idtmod(x,ic,mod,off)","idtmod(V(p,n),0.0,1.0,0.0)",1.25e-5),
 ("idtmod(x,ic,mod,off,tol)","idtmod(V(p,n),0.0,1.0,0.0,1e-6)",1.25e-5),
 ("absdelay(x,td)","absdelay(V(p,n),1e-6)",4.0),("absdelay(x,td,maxdelay)","absdelay(V(p,n),1e-6,2e-6)",4.0),
 ("limexp(x)","limexp(V(p,n)*0.2)",math.exp(1.0)),("ddx(f,V(p))","ddx(V(p,n)*V(p,n),V(p))",10.0),
 ("laplace_nd(x,n,d)","laplace_nd(V(p,n),{1},{1})",5.0),("laplace_nd(x,n,d,tol)","laplace_nd(V(p,n),{1},{1},1e-9)",5.0),
 ("laplace_zd(x,<null>,d)","laplace_zd(V(p,n), , {1})",5.0),("laplace_zd(x,'{},d)","laplace_zd(V(p,n),'{},{1})",5.0),
 ("laplace_np(x,n,<null>)","laplace_np(V(p,n),{1}, )",5.0),("laplace_zp(x,<null>,<null>)","laplace_zp(V(p,n), , )",5.0),
 ("zi_nd(x,n,d,T)","zi_nd(V(p,n),{1},{1},1e-7)",5.0),("zi_nd(x,n,d,T,t0)","zi_nd(V(p,n),{1},{1},1e-7,0.0)",5.0),
 ("zi_nd(x,n,d,T,t0,tol)","zi_nd(V(p,n),{1},{1},1e-7,0.0,1e-9)",5.0),
 ("zi_zd(x,<null>,d,T)","zi_zd(V(p,n), , {1},1e-7)",5.0),("zi_np(x,n,<null>,T)","zi_np(V(p,n),{1}, ,1e-7)",5.0),
 ("zi_zp(x,<null>,<null>,T)","zi_zp(V(p,n), , ,1e-7)",5.0)]
for i,(lbl,ex,want) in enumerate(OPS):
    g,st,msg=tran(f"I(p,n) <+ {ex};","O%02d"%i)
    chk("ops",lbl,st=="ok" and g is not None and abs(g-want)<=2e-3*max(1,abs(want)),msg or f"{g} want {want:.6g}")
for i,(lbl,ex) in enumerate([("transition(x)","transition(V(p,n))"),("transition(x,td)","transition(V(p,n),1e-7)"),
   ("transition(x,td,rise)","transition(V(p,n),1e-7,1e-7)"),("transition(x,td,rise,fall)","transition(V(p,n),1e-7,1e-7,1e-7)"),
   ("transition(x,td,rise,fall,tol)","transition(V(p,n),1e-7,1e-7,1e-7,1e-9)"),("slew(x)","slew(V(p,n))"),
   ("slew(x,pos)","slew(V(p,n),1e7)"),("slew(x,pos,neg)","slew(V(p,n),1e7,-1e7)")]):
    g,st,msg=tran(f"I(p,n) <+ {ex};","S%02d"%i,src=STEP,at="8u")
    chk("ops",lbl,st=="ok" and g is not None and abs(g-2.0)<=2e-3*2,msg or f"{g} want 2.0")
for i,(lbl,ex,want) in enumerate([("last_crossing(x)","last_crossing(V(p,n)-5.0)*1e6",5.0),
   ("last_crossing(x,+1)","last_crossing(V(p,n)-5.0,+1)*1e6",5.0),
   ("last_crossing(x,0)","last_crossing(V(p,n)-5.0,0)*1e6",5.0)]):
    g,st,msg=tran(f"I(p,n) <+ {ex};","L%02d"%i,at="8u")
    chk("ops",lbl,st=="ok" and g is not None and abs(g-want)<=2e-3*want,msg or f"{g} want {want}")
# LRM 4.5.1: an array argument may be an array IDENTIFIER (parameter or variable)
AP=" parameter real cf[0:1] = '{1.0, 0.0};\n"; AV=" real vf[0:1];\n"
for i,(lbl,ex,dc) in enumerate([("laplace_nd(x, param_id, param_id)","laplace_nd(V(p,n),cf,cf)",AP),
   ("laplace_nd(x, var_id, var_id)","laplace_nd(V(p,n),vf,vf)",AV),
   ("zi_nd(x, param_id, param_id, T)","zi_nd(V(p,n),cf,cf,1e-7)",AP)]):
    d,rc,o=build(mod(f"I(p,n) <+ {ex};",dc,dc=False),"A%02d"%i)
    e=[l for l in o.splitlines() if 'error' in l.lower()]
    chk("ops",lbl,rc==0,(e[0][7:52] if e else ""))

print("\n=== LRM Syntax 4-4: noise functions (verified against 4kT/R) ===")
K=1.3806488e-23;T=300.15;R=1e3;SI=4*K*T/R;VN=math.sqrt(SI)*R
def nz(ex,tag,extra=None,decl=""):
    d,rc,o=build(mod("I(p,n) <+ V(p,n)/1e3;\n  I(p,n) <+ "+ex+";",decl,dc=False),tag,extra)
    if rc!=0:
        e=[l for l in o.splitlines() if 'error' in l.lower()]
        return None,("CRASH" if crashy(rc) else "rejected"),(e[0][7:52] if e else "")
    dk=("p\n.control\npre_osdi m.osdi\n.endc\nV1 in 0 dc 0 ac 1\nRs in a 1meg\nN1 a 0 mm\n.model mm dut()\n"
        ".control\noption noacct\nset numdgt=12\nnoise v(a) v1 lin 3 1meg 3meg\nsetplot noise1\n"
        "print onoise_spectrum\n.endc\n.end\n")
    out=run(d,dk)[1]; v=re.findall(r"^\d+\s+\S+\s+(\S+)",out,re.M)
    return (float(v[0]),"ok","") if v else (None,"NOVALUE","")
A=f"'{{1.0, {SI:.17g}, 1e12, {SI:.17g}}}"; F={"nt.tbl":f"1.0 {SI:.17g}\n1e12 {SI:.17g}\n"}
NZ=[("white_noise(pwr)",f"white_noise({SI:.17g})",None,""),
    ('white_noise(pwr,"name")',f'white_noise({SI:.17g},"th")',None,""),
    ("flicker_noise(pwr,exp)",f"flicker_noise({SI*1e6:.17g},1.0)",None,""),
    ('flicker_noise(pwr,exp,"name")',f'flicker_noise({SI*1e6:.17g},1.0,"fl")',None,""),
    ("noise_table('{...})",f"noise_table({A})",None,""),
    ('noise_table(\'{...},"name")',f'noise_table({A},"tb")',None,""),
    ('noise_table("file")','noise_table("nt.tbl")',F,""),
    ('noise_table("file","name")','noise_table("nt.tbl","tb")',F,""),
    ("noise_table_log('{...})",f"noise_table_log({A})",None,""),
    ('noise_table_log(\'{..},"name")',f'noise_table_log({A},"tb")',None,""),
    ('noise_table_log("file")','noise_table_log("nt.tbl")',F,""),
    ('noise_table_log("file","name")','noise_table_log("nt.tbl","t")',F,""),
    ]
for i,(lbl,ex,extra,dc) in enumerate(NZ):
    g,st,msg=nz(ex,"Z%02d"%i,extra,dc)
    chk("noise",lbl,st=="ok" and g is not None and abs(g-VN)<=0.02*VN,msg or f"{g}")

print("\n=== LRM 4.6.3 ac_stim / 4.7.1 analysis ===")
def ac(ex,tag):
    d,rc,o=build(mod(f"I(p,n) <+ {ex};",dc=False),tag)
    if rc!=0: return None,"rejected",""
    dk=("p\n.control\npre_osdi m.osdi\n.endc\nV1 in 0 dc 0 ac 1\nR1 a 0 1k\nN1 a 0 mm\n.model mm dut()\n"
        ".control\noption noacct\nset numdgt=12\nac lin 1 1meg 1meg\nprint mag(v(a))\n.endc\n.end\n")
    out=run(d,dk)[1]; m=re.search(r"mag\(v\(a\)\)\s*=\s*(\S+)",out)
    return (float(m.group(1)),"ok","") if m else (None,"NOVALUE","")
for i,(lbl,ex,want) in enumerate([("ac_stim()","ac_stim()",1000.0),('ac_stim("ac")','ac_stim("ac")',1000.0),
  ('ac_stim("ac",mag)','ac_stim("ac",2.0)',2000.0),('ac_stim("ac",mag,phase)','ac_stim("ac",2.0,0.5)',2000.0),
  ('ac_stim(other analysis)->0','ac_stim("noise",2.0)',0.0)]):
    g,st,msg=ac(ex,"C%02d"%i)
    chk("ac",lbl,st=="ok" and g is not None and abs(g-want)<=1e-6*max(1,want),f"{g} want {want}")
def strobe(ex,tag):
    d,rc,o=build(HDR+"module dut(p,n); inout p,n; electrical p,n;\n"
        ' analog begin @(timer(3e-6)) $strobe("TK %.12g", '+ex+');\n  I(p,n) <+ V(p,n)*1e-3; end\nendmodule\n',tag)
    if rc!=0: return None,"rejected",""
    out=run(d,deck(src="V1 a 0 PWL(0 0 6u 6)",body="tran 0.05u 6u"))[1]
    v=re.findall(r"TK (\S+)",out); return (float(v[0]),"ok","") if v else (None,"NOVALUE","")
for i,(lbl,ex,want) in enumerate([('analysis("tran") in tran','analysis("tran")',1.0),
   ('analysis("static") in tran','analysis("static")',0.0),('analysis("ic") in tran','analysis("ic")',0.0),
   ("$abstime at t=3us","$abstime",3e-6),("$realtime at t=3us","$realtime",3e-6)]):
    g,st,msg=strobe(ex,"T%02d"%i)
    chk("ac",lbl,st=="ok" and g is not None and abs(g-want)<=1e-3*max(1e-6,abs(want)),f"{g} want {want}")
for i,(lbl,ex,want) in enumerate([('analysis("static") in op','analysis("static")',1.0),
   ('analysis("ac","dc") 2 names','analysis("ac","dc")',None),
   ('analysis 4 names','analysis("ac","dc","tran","noise")',None)]):
    g,st,msg=opval(mod(f"y = {ex};",Y),"N%02d"%i)
    chk("ac",lbl,st=="ok" and g is not None and (want is None or abs(g-want)<1e-9),msg or f"{g}")

print("\n=== LRM Syntax 9-10: environment functions ===")
for i,(lbl,ex,want,dc,card) in enumerate([("$temperature","$temperature",300.15,"","dut()"),
   ("$vt","$vt",K*300.15/1.602176565e-19,"","dut()"),("$vt(T)","$vt(400.0)",K*400/1.602176565e-19,"","dut()"),
   ('$simparam("gmin")','$simparam("gmin")',None,"","dut()"),
   ('$simparam("x", default)','$simparam("nope",42.0)',42.0,"","dut()"),
   ('$simparam(string PARAMETER)','$simparam(sp)',None,' parameter string sp = "gmin";\n',"dut()"),
   ("$param_given(p) given","$param_given(pp)",1.0," parameter real pp = 1.0;\n","dut() pp=2"),
   ("$param_given(p) not given","$param_given(pp)",0.0," parameter real pp = 1.0;\n","dut()"),
   ("$port_connected(p)","$port_connected(p)",1.0,"","dut()"),("$mfactor","$mfactor",1.0,"","dut()"),
   ("$xposition","$xposition",None,"","dut()"),("$yposition","$yposition",None,"","dut()"),
   ("$angle","$angle",None,"","dut()"),("$hflip","$hflip",None,"","dut()"),("$vflip","$vflip",None,"","dut()"),
   ("$rtoi(2.7)","$rtoi(2.7)",2.0,"","dut()"),("$itor(3)","$itor(3)",3.0,"","dut()"),
   ("$clog2(9)","$clog2(9)",4.0,"","dut()")]):
    g,st,msg=opval(mod(f"y = {ex};",Y+dc),"E%02d"%i,card=card)
    chk("env",lbl,st=="ok" and g is not None and (want is None or abs(g-want)<=1e-4*max(1,abs(want))),msg or f"{g}")

print("\n=== LRM 9.13: $random / $arandom / $dist_* / $rdist_* ===")
S=" integer sd;\n"; SP=" parameter integer sp2 = 7;\n"
RNG=[("$random","sd=1; y = $random;",S,None),("$random(seed)","sd=5; y = $random(sd);",S,None),
     ("$arandom","sd=1; y = $arandom;",S,None),("$arandom(seed)","sd=5; y = $arandom(sd);",S,None),
     ('$arandom(seed,"global")','sd=5; y = $arandom(sd,"global");',S,None),
     ("$arandom(param seed)","y = $arandom(sp2);",SP,None)]
for f in ("uniform","normal","erlang"):
    RNG.append((f"$dist_{f}(seed,a,b)",f"sd=5; y = $dist_{f}(sd, 2, 5);",S,"int"))
    RNG.append((f"$rdist_{f}(seed,a,b)",f"sd=5; y = $rdist_{f}(sd, 2, 5);",S,None))
for f in ("exponential","poisson","chi_square","t"):
    RNG.append((f"$dist_{f}(seed,a)",f"sd=5; y = $dist_{f}(sd, 5);",S,"int"))
    RNG.append((f"$rdist_{f}(seed,a)",f"sd=5; y = $rdist_{f}(sd, 5);",S,None))
RNG += [('$dist_uniform(...,"name")','sd=5; y = $dist_uniform(sd,0,10,"n");',S,"int"),
        ('$rdist_uniform(...,"name")','sd=5; y = $rdist_uniform(sd,0,10,"n");',S,None),
        ("$dist_uniform(param seed,..)","y = $dist_uniform(sp2,0,10);",SP,"int"),
        ("$rdist_uniform(param seed,..)","y = $rdist_uniform(sp2,0,10);",SP,None)]
for i,(lbl,b,dc,kind) in enumerate(RNG):
    g,st,msg=opval(mod(b,Y+dc),"R%02d"%i)
    good=st=="ok" and g is not None and (kind!="int" or float(g)==int(float(g)))
    chk("rng",lbl,good,msg or f"{g}")

print("\n=== LRM Syntax 9-7 severity + 9.7 display + 9.5/9.9-9.12 file I/O ===")
def textsim(body,decl,tag,extra=None):
    d,rc,o=build(mod(body,decl),tag,extra)
    if rc!=0:
        e=[l for l in o.splitlines() if 'error' in l.lower()]
        return d,None,(e[0][7:56] if e else "rejected")
    return d,run(d,deck(body="op"))[1],""
for t_ in ("display","strobe","write","monitor","debug"):
    d,out,msg=textsim(f'@(initial_step) ${t_}("MK{t_.upper()} %g", 42.0);',"","D_"+t_)
    chk("io",f"${t_}(fmt, args)",out is not None and f"MK{t_.upper()} 42" in out,msg)
for t_ in ("info","warning","error"):
    d,out,msg=textsim(f'@(initial_step) ${t_}("SV{t_.upper()}");',"","V_"+t_)
    chk("io",f"${t_}(message)",out is not None and f"SV{t_.upper()}" in out,msg)
    d,out,msg=textsim(f'@(initial_step) ${t_};',"","V0_"+t_)
    chk("io",f"${t_}  (no parens, LRM 9-7)",out is not None,msg)
d,out,msg=textsim('@(initial_step) $fatal(0, "SVFATAL");',"","V_fat")
chk("io","$fatal(finish_number, message)",out is not None and "SVFATAL" in out,msg)
d,out,msg=textsim('@(initial_step) $fatal;',"","V_fat0")
chk("io","$fatal  (no parens, LRM 9-7)",out is not None,msg)
for i,(lbl,b) in enumerate([("$finish","$finish;"),("$finish(n)","$finish(1);"),("$stop","$stop;"),("$stop(n)","$stop(1);")]):
    d,out,msg=textsim("@(initial_step) "+b,"","F%02d"%i); chk("io",lbl,out is not None,msg)
D=" integer f, r, iv; real rv; string s, es;\n"
d,out,msg=textsim('@(initial_step) begin f = $fopen("o.txt"); $fdisplay(f,"L1 %g",7.0); $fwrite(f,"AA");'
                  ' $fstrobe(f,"BB"); $fmonitor(f,"CC"); $fdebug(f,"DD"); r=$fflush(f); $fclose(f); end',D,"IO1")
txt=open(os.path.join(d,"o.txt")).read() if out is not None and os.path.exists(os.path.join(d,"o.txt")) else ""
for probe,nm in [("L1 7","$fopen(name)+$fdisplay"),("AA","$fwrite(fd,...)"),("BB","$fstrobe(fd,...)"),
                 ("CC","$fmonitor(fd,...)"),("DD","$fdebug(fd,...)")]:
    chk("io",nm,probe in txt,msg or repr(txt[:26]))
d,out,msg=textsim('@(initial_step) begin f=$fopen("o2.txt","w"); $fdisplay(f,"MW"); $fclose(f); end',D,"IO2")
t2=open(os.path.join(d,"o2.txt")).read() if out is not None and os.path.exists(os.path.join(d,"o2.txt")) else ""
chk("io",'$fopen(name, mode)  2-arg',"MW" in t2,msg or repr(t2[:20]))
d,out,msg=textsim('@(initial_step) begin f=$fopen("in.txt","r"); r=$fgetc(f); $display("FGETC %d",r);'
   ' r=$ungetc(r,f); r=$fgets(s,f); $display("FGETS %s",s); r=$fscanf(f,"%d %f",iv,rv);'
   ' $display("FSCANF %d %d %g",r,iv,rv); $display("FTELL %d",$ftell(f)); $rewind(f);'
   ' $display("REW %d",$ftell(f)); r=$fseek(f,6,0); $display("SEEK %d",$ftell(f));'
   ' $display("FEOF %d",$feof(f)); r=$ferror(f,es); $display("FERR %d",r); r=$fflush(); $fclose(f); end',
   D,"IO3",{"in.txt":"hello world\n42 3.5\n"})
for want,nm in [("FGETC 104","$fgetc(fd)"),("FGETS hello","$ungetc + $fgets(str,fd)"),
                ("FSCANF 2 42 3.5","$fscanf(fd,fmt,targets)"),("FTELL 19","$ftell(fd)"),
                ("REW 0","$rewind(fd)"),("SEEK 6","$fseek(fd,off,whence)"),("FEOF 0","$feof(fd)"),
                ("FERR 0","$ferror(fd,str)")]:
    chk("io",nm,out is not None and want in out,msg)
d,out,msg=textsim('@(initial_step) begin $swrite(s,"SW %g",5.0); $display("G1 %s",s);'
   ' $sformat(s2,"SF %g",6.0); $display("G2 %s",s2); r=$sscanf("77","%d",iv); $display("G3 %d %d",r,iv); end',
   " string s, s2; integer r, iv;\n","IO4")
for want,nm in [("G1 SW 5","$swrite(str,fmt,...)"),("G2 SF 6","$sformat(str,fmt,...)"),("G3 1 77","$sscanf(str,fmt,...)")]:
    chk("io",nm,out is not None and want in out,msg)

print("\n=== LRM 9-12 $limit / 9-16 $table_model / analog control tasks ===")
for i,(lbl,b) in enumerate([("$discontinuity","$discontinuity;"),("$discontinuity()","$discontinuity();"),
   ("$discontinuity(degree)","$discontinuity(1);"),("$bound_step(t)","$bound_step(1e-7);")]):
    d,rc,o=build(mod(b,dc=True),"B%02d"%i)
    e=[l for l in o.splitlines() if 'error' in l.lower()]
    chk("misc",lbl,rc==0,(e[0][7:52] if e else ""))
# LRM 9.17: the user function is called with (value_this_iteration, internal_state,
# then $limit's own third and subsequent arguments) -- so its arity is ALWAYS
# 2 + (number of extra $limit args), never 1.
F2=" analog function real f2; input a,b; real a,b; begin f2 = a; end endfunction\n"
F3=" analog function real f3; input a,b,c; real a,b,c; begin f3 = a; end endfunction\n"
F4=" analog function real f4; input a,b,c,d; real a,b,c,d; begin f4 = a; end endfunction\n"
for i,(lbl,b,dc,want) in enumerate([("$limit(probe)","y = $limit(V(p,n));",Y,1.0),
   ('$limit(probe,"pnjlim",args)','y = $limit(V(p,n),"pnjlim",0.026,1.0);',Y,1.0),
   ('$limit(probe,"fetlim",arg)','y = $limit(V(p,n),"fetlim",1.0);',Y,1.0),
   ("$limit(probe, f2)      f2(v,state)","y = $limit(V(p,n), f2);",Y+F2,1.0),
   ("$limit(probe, f3, x)   f3(v,state,x)","y = $limit(V(p,n), f3, 2.0);",Y+F3,1.0),
   ("$limit(probe, f4, x,y) f4(v,state,x,y)","y = $limit(V(p,n), f4, 2.0, 3.0);",Y+F4,1.0)]):
    g,st,msg=opval(mod(b,dc),"J%02d"%i)
    chk("misc",lbl,st=="ok" and g is not None and abs(g-want)<1e-9,msg or f"{g} want {want}")
T2={"g2.tbl":"2\n2 2\n0 1\n0 1\n0 1\n1 2\n"};T3={"g3.tbl":"3\n2 2 2\n0 1\n0 1\n0 1\n0 1 1 2 1 2 2 3\n"}
T1={"t1.tbl":"0 0\n1 2\n2 4\n"}
for i,(lbl,b,ex,want) in enumerate([("$table_model(x,'{data})","y = $table_model(V(p,n),'{0,0, 1,2, 2,4});",None,2.0),
   ('$table_model(x,\'{data},"ctrl")','y = $table_model(V(p,n),\'{0,0, 1,2, 2,4},"1L");',None,2.0),
   ('$table_model(x,"file")','y = $table_model(V(p,n),"t1.tbl");',T1,2.0),
   ('$table_model(x,"file","ctrl")','y = $table_model(V(p,n),"t1.tbl","1L");',T1,2.0),
   ('$table_model(x,y,"file")  2-D','y = $table_model(V(p,n),0.5,"g2.tbl");',T2,1.5),
   ('$table_model(x,y,"file","c") 2-D','y = $table_model(V(p,n),0.5,"g2.tbl","1L,1L");',T2,1.5),
   ('$table_model(x,y,z,"file") 3-D','y = $table_model(V(p,n),0.5,0.5,"g3.tbl");',T3,2.0)]):
    g,st,msg=opval(mod(b,Y),"K%02d"%i,extra=ex)
    chk("misc",lbl,st=="ok" and g is not None and abs(g-want)<1e-9,msg or f"{g} want {want}")
for i,(lbl,b,dc) in enumerate([('$simprobe(dev,param)','y = $simprobe("v1","dc");',Y),
   ('$simprobe(dev,param,default)','y = $simprobe("no","x",3.5);',Y),
   ('$analog_node_alias(node,"n")','r = $analog_node_alias(p,"vp");'," integer r;\n"),
   ('$analog_port_alias(node,"n")','r = $analog_port_alias(p,"ip");'," integer r;\n"),
   ('$test$plusargs("flag")','r = $test$plusargs("f");'," integer r;\n"),
   ('$value$plusargs("f=%d",int)','r = $value$plusargs("f=%d",iv);'," integer r, iv;\n"),
   ('$value$plusargs("f=%f",real)','r = $value$plusargs("f=%f",rv);'," integer r; real rv;\n"),
   ('$value$plusargs("f=%s",str)','r = $value$plusargs("f=%s",sv);'," integer r; string sv;\n"),
   ('$simparam$str(name)','s = $simparam$str("analysis_name");'," string s;\n")]):
    d,rc,o=build(mod(b,dc),"P%02d"%i)
    e=[l for l in o.splitlines() if 'error' in l.lower()]
    chk("misc",lbl,rc==0,(e[0][7:52] if e else ""))

# ---- the LRM forms that are deliberately REFUSED (see the header) ----
print("\n=== refused by design, each with the reason ===")
for lbl, decl in [("noise_table(array PARAMETER)", " parameter real tb[0:3] = '{1.0,2.0,3.0,4.0};\n"),
                  ("noise_table(array VARIABLE)", " real tb[0:3];\n"),
                  ("noise_table_log(array PARAM)", " parameter real tb[0:3] = '{1.0,2.0,3.0,4.0};\n")]:
    fn = "noise_table_log" if "log" in lbl else "noise_table"
    d, rc, o = build(mod(f"I(p,n) <+ V(p,n)/1e3; I(p,n) <+ {fn}(tb);", decl, dc=False),
                     "R%d" % (abs(hash(lbl)) % 97))
    txt = " ".join(l for l in o.splitlines() if l.startswith("error"))
    chk("refused", lbl, rc != 0 and not crashy(rc) and "run time" in txt, txt[:44])
d, rc, o = build(mod('I(p,n) <+ V(p,n)/1e3; I(p,n) <+ noise_table(fn);',
                     ' parameter string fn = "n.tbl";\n', dc=False), "Rstr")
chk("refused", "noise_table(string PARAMETER) [was a PANIC]", rc != 0 and not crashy(rc),
    "rc=%d" % rc)
# Enhancement-459 closed the last gap this suite recorded: `param[msb:lsb]`, the
# second `analog_filter_function_arg` form in Syntax 4-3, is now accepted. The
# form-coverage claim above is what is pinned here; the values, the slice ORDER
# and the range checks live in `partselect_examples`.
P4 = " parameter real cf[0:3] = '{1.0, 0.0, 0.0, 0.0};\n"
d, rc, o = build(mod("I(p,n) <+ laplace_nd(V(p,n), cf[0:1], cf);", P4, dc=False), "Rslice")
chk("ops", "laplace_nd(x, param[msb:lsb], d)  [LRM Syntax 4-3 form 2]", rc == 0, "rc=%d" % rc)
d, rc, o = build(mod("r = max(1.0, 2.0,);", ' (*desc="r"*) real r;\n'), "Rtc")
chk("refused", "max(1.0, 2.0,) trailing comma still refused", rc != 0 and not crashy(rc),
    "rc=%d" % rc)

for j in os.listdir(HERE):
    if j.startswith("_w_"):
        shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
print(f"\n{'ALL PASS' if not FAIL else 'FAILURES'}: {OK[0]}/{N[0]} passed")
sys.exit(0 if not FAIL else 1)
