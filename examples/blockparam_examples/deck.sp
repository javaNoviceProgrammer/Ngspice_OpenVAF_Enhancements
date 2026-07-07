Enhancement-87 block-scoped parameter runtime
N1 a bmod
Rl1 a 0 1k
N2 b bmodo
Rl2 b 0 1k
Nn n nmod
Rl3 n 0 1k
.model bmod  blockparam
.model bmodo blockparam gain=3 offset=0.2
.model nmod  nested
.control
pre_osdi blockparam.osdi
pre_osdi nested.osdi
op
print v(a) v(b) v(n)
.endc
.end
