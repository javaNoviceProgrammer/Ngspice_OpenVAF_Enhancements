#!/bin/bash

# Copyright 2023 The ngspice team
# Authors: Holger Vogt, Dietmar Warning
# License: New BSD

mkdir -p ../admslibs

cd ./angelov/vacode
buildxyceplugin.sh angelov.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
buildxyceplugin.sh angelov_gan.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
#buildxyceplugin.sh ../ASMHEMT/vacode/asmhemt.va .
cd ./bsim4/vacode
buildxyceplugin.sh bsim4.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./bsim6/vacode
buildxyceplugin.sh BSIM6.1.1.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./bsimbulk/vacode
buildxyceplugin.sh bsimbulk.va .
#buildxyceplugin.sh bsimbulk107.va .
#buildxyceplugin.sh bsimbulk106.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./bsimcmg/vacode
buildxyceplugin.sh bsimcmg.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
#buildxyceplugin.sh bsimimg.va .
cd ./bsimsoi/vacode
buildxyceplugin.sh bsimsoi.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./diode_cmc/vacode
buildxyceplugin.sh diode_cmc.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./ekv/vacode
buildxyceplugin.sh ekv26.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./ekv3/vacode
buildxyceplugin.sh ekv3.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
#buildxyceplugin.sh ../EPFL-HEMT/vacode/epfl_hemt.va .
#buildxyceplugin.sh ../fbh_hbt/vacode/fbh_hbt-2_1.va .
#buildxyceplugin.sh ../fbh_hbt/vacode/fbh_hbt-2_3.va .
cd ./hicum0/vacode
buildxyceplugin.sh hicumL0_v2p0p0.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./hicum2/vacode
buildxyceplugin.sh hicumL2_v310.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
#buildxyceplugin.sh ../hisim2/vacode/hisim2.va .
#buildxyceplugin.sh ../hisimhv/vacode242/hisimhv.va .
#buildxyceplugin.sh ../hisimhv/vacode250/hisimhv.va .
#buildxyceplugin.sh ../hisimsoi/vacode/hisimsoi.va .
#buildxyceplugin.sh ../hisimsotb/vacode/hisimsotb.va .
cd ./IGBT/vacode
buildxyceplugin.sh igbt3.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./L-UTSOI/vacode
buildxyceplugin.sh L_UTSOI_102.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./mextram/vacode504p12p1
buildxyceplugin.sh bjt504.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
buildxyceplugin.sh bjt504t.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./mextram/vacode
buildxyceplugin.sh bjt505.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
buildxyceplugin.sh bjt505t.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./MOSVAR/vacode
buildxyceplugin.sh mosvar.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
#buildxyceplugin.sh ../mvsg/vacode/mvsg_cmc.va .
#buildxyceplugin.sh ../psp102/vacode/psp102.va .
cd ./psp103/vacode
buildxyceplugin.sh juncap200.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
buildxyceplugin.sh psp103.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
#buildxyceplugin.sh ../r2_cmc/vacode/r2_cmc.va .
#buildxyceplugin.sh ../r2_cmc/vacode/r2_et_cmc.va .
cd ./r3_cmc/vacode
buildxyceplugin.sh r3_cmc.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..
cd ./vbic/vacode
buildxyceplugin.sh vbic_1p3.va .
rm Makefile .*.adms *.C *.cmake *.log CMake*.txt N_DEV_*.h .*.xml
rm -rfd CMakeFiles/
mv *.so ../../../admslibs
cd ../..

echo done

