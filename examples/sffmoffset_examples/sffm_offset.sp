* Enhancement-318: SFFM/AM sources must hold the DC offset VO before the delay (like SIN).
* Pre-fix, VSRC SFFM/AM returned 0 for time<=TD -- dropping VO at the operating point and over
* the whole pre-delay window, and injecting a spurious startup transient. SIN (same file) is the
* control: it correctly holds its quiescent value. Line 1 is the title.
Vsffm sf 0 SFFM(1.5 1 5000 4 500 0.2m)
Rsf sf 0 1k
Vam am 0 AM(2 1 0.5 200 5000 0.2m)
Ram am 0 1k
Vsin sn 0 SIN(1.5 1 5000 0.2m 0 0)
Rsn sn 0 1k
.tran 1u 0.5m
.meas tran m_sffm FIND v(sf) AT=0.1m
.meas tran m_am   FIND v(am) AT=0.1m
.meas tran m_sin  FIND v(sn) AT=0.1m
.end
