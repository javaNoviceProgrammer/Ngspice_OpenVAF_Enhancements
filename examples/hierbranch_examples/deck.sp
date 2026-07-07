Enhancement-86 hierarchical branch probe check
V1 a 0 5
N1 a o1 ovb ovub oip tmod
Rl1 o1 0 1k
Rl2 ovb 0 1k
Rl3 ovub 0 1k
Rl4 oip 0 1k
.model tmod top
.control
pre_osdi hier_probe.osdi
op
print v(ovb) v(ovub) v(oip) i(V1)
.endc
.end
