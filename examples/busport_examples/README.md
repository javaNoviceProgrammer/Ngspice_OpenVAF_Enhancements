# busport_examples — multi-bit input bus port bit reads (Enhancement-90)

A compiler fix for reading an individual bit of a multi-bit **input** bus port
declared in the non-ANSI (Verilog-2001) header style. When the bus was not the
last port in the header, its bits were placed out of order among the module's
nodes, so the OSDI terminals (mapped positionally by the simulator) were
mis-wired and `V(in[k])` read the wrong terminal — often 0.

`busport.va` mirrors each bit of a 3-bit input bus onto a scalar output; the
verify drives the three bus terminals with 1/2/3 V and checks each output reads
its own bit. It also exercises a bus in the *middle* of the header and confirms
the Enhancement-89 name-then-range spelling reads identically. Run:
`python3 verify_busport.py` (6 checks).
