#!/bin/bash
# Fetch the IHP SG13G2 gnucap model library (branch dev) and the Verilog-A
# model sources it includes, plus the gnucap testbenches and reference outputs
# this run compares against, into ./work. Needs the GitHub CLI (`gh`).
set -e
cd "$(dirname "$0")"
W=work
R="repos/IHP-GmbH/IHP-Open-PDK/contents/ihp-sg13g2/libs.tech"
get() { gh api "$R/$1?ref=dev" --jq '.content' | base64 -d > "$2"; }
mkdir -p $W/va/r3_cmc $W/va/psp103 $W/va/cap_cmomi $W/va/cap_cmomf $W/tests $W/ref
for f in Makefile capacitor.va capacitor_module.va capacitor_paramset.va cornerCAP.va cornerMOShv.va cornerMOSlv.va cornerRES.va discipline.h idc.va resistor.va resistor_paramset.va sg13g2_moshv_module.va sg13g2_moshv_paramset.va sg13g2_moshv_rf_paramset.va sg13g2_moslv_module.va sg13g2_moslv_paramset.va sg13g2_moslv_rf_paramset.va; do
  get gnucap/models/$f $W/$f; done
for f in r3_cmc.va r3_cmc_macros.include; do get verilog-a/r3_cmc/$f $W/va/r3_cmc/$f; done
for f in Common103_macrodefs.include JUNCAP200_InitModel.include JUNCAP200_macrodefs.include JUNCAP200_parlist.include JUNCAP200_varlist.include PSP103_macrodefs.include PSP103_module.include PSP103_nqs_macrodefs.include PSP103_parlist.include PSP103_scaling.include juncap200.va psp103.va psp103_nqs.va psp103t.va; do
  get verilog-a/psp103/$f $W/va/psp103/$f; done
get verilog-a/cap_cmomi/cap_cmomi.va $W/va/cap_cmomi/cap_cmomi.va
get verilog-a/cap_cmomf/cap_cmomf.va $W/va/cap_cmomf/cap_cmomf.va
# reference outputs
for c in typ bcs wcs; do get gnucap/tests/gnucap/resistor/ref/tb_res_basic_$c.gc.out $W/ref/tb_res_basic_$c.gc.out; done
for f in tb_cap_cmomf_typ tb_cap_cmomi_typ tb_cap_cutoff_typ tb_cap_cutoff_bcs tb_cap_cutoff_wcs; do get gnucap/tests/gnucap/capacitor/ref/$f.gc.out $W/ref/$f.gc.out; done
for k in moslv moshv; do
  for c in tt ss ff sf fs; do for rf in "" _rf; do get gnucap/tests/gnucap/$k/ref/tb_${k}_inv_$c$rf.gc.out $W/ref/tb_${k}_inv_$c$rf.gc.out; done; done
  for d in nmos pmos; do for n in 1 2 3 4; do for rf in "" _rf; do
    get gnucap/tests/gnucap/$k/ref/tb_${k}_${d}_id_vd_ng$n$rf.gc.out $W/ref/tb_${k}_${d}_id_vd_ng$n$rf.gc.out; done; done; done
done
echo "fetched into $W"
