* Enhancement-90: multi-bit input bus port, per-bit read
.model bp busport
Va0 na0 0 1.0
Va1 na1 0 2.0
Va2 na2 0 3.0
* header terminal order: in[0] in[1] in[2] o0 o1 o2
N1 na0 na1 na2 o0 o1 o2 bp
.control
pre_osdi busport.osdi
op
print v(o0) v(o1) v(o2)
.endc
.end
