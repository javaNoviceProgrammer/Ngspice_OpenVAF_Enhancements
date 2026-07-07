Enhancement-85 part-select connection check
N1 o1 o2 o3 o4 qmod
Rl1 o1 0 1k
Rl2 o2 0 1k
Rl3 o3 0 1k
Rl4 o4 0 1k
.model qmod quad
.control
pre_osdi bus_split.osdi
op
print v(o1) v(o2) v(o3) v(o4)
.endc
.end
