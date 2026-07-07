Enhancement-89 name-then-range output bus runtime
Vin in 0 2.0
N1 in o0 o1 o2 o3 tmod
Ro0 o0 0 1k
Ro1 o1 0 1k
Ro2 o2 0 1k
Ro3 o3 0 1k
.model tmod tapbuf gain=1.0
.control
pre_osdi arrayport.osdi
op
print v(o0) v(o1) v(o2) v(o3)
.endc
.end
