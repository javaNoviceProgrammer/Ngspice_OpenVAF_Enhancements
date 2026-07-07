Enhancement-89 Annex E primitives runtime
Vin in 0 2.0
* --- RC lowpass: DC out=in; tran settles to 2.0 ---
N1 in outrc rcmod
.model rcmod rc_lowpass r=1k c=1u
* --- CMOS inverter: drive in, supply 5V ---
Vdd vdd 0 5
Vlo lo 0 0
Vhi hi 0 5
Ninvl lo outl vdd 0 invmod
Ninvh hi outh vdd 0 invmod
.model invmod cmos_inv
Rl1 outl 0 1meg
Rl2 outh 0 1meg
.control
pre_osdi rc_lowpass.osdi
pre_osdi cmos_inv.osdi
op
print v(outrc) v(outl) v(outh)
.endc
.end
