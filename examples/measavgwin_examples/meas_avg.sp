* Enhancement-316: .meas AVG must equal INTEG/(to-from) over the same window.
* This B-source (two sines + a ramp) sampled at 2.5e-7 places a sample within 100 ULPs
* of `to` -- the case where AVG previously dropped the final trapezoid and ended one
* timestep short of `to`, disagreeing with INTEG/(to-from) by ~1.6%. Line 1 is the title.
B1 x 0 V=2.748*sin(2*3.141592653589793*2000*time+5.289)+0.77*sin(2*3.141592653589793*2000*time+6.106)-0.71*time/0.001
Rx x 0 1meg
.tran 2.5e-7 1e-3 uic
.meas tran avg1 AVG   v(x) from=9.355e-05 to=0.00064624
.meas tran int1 INTEG v(x) from=9.355e-05 to=0.00064624
.end
