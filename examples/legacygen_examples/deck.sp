Enhancement-88 legacy generate flash-ADC runtime
Vin in 0 0.7
* bus out[0:3] maps terminals in order: o0=out[0] .. o3=out[3]
N1 in o0 o1 o2 o3 adc
Rl0 o0 0 1k
Rl1 o1 0 1k
Rl2 o2 0 1k
Rl3 o3 0 1k
.model adc flashadc
.control
pre_osdi flashadc.osdi
op
print v(o0) v(o1) v(o2) v(o3)
.endc
.end
