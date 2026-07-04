MEXTRAM Output Test Ic=f(Vc,Ib)

.model KSC1845F_km bjt504tva level=504 is=1.075431e-013 bf=362.1
+ bri=1.3565 vef=267 ver=20.6691 ik=0.25 ibf=1e-012 ibr=1e-012 mlf=2 rbv=144.908
+ rbc=12.092 re=1.5 rcc=1 rcv=150 scrcv=225 ihc=1.5m axi=.1 cje=7p
+ cjc=4.525739e-012 pe=0.36 pc=0.3659045 vde=0.6 vdc=0.5 taue=250p taub=2.1e-011 af=1 kf=0 vgb=1.1809
+ vgc=1.1809 vgs=1.1809 vgj=1.1809 exavl=0 wavl=1k Xcje=0.25 Cbeo=2p
+ Rth=100 Cth=100n

IB 0 B 1u
VC C 0 2.0
VS S 0 0.0
NQ1 C B 0 S dt KSC1845F_km

.control
pre_osdi ../../../osdilibs/bjt504t.osdi
dc vc 0 12.0 0.05 ib 10u 50u 5u
plot abs(i(vc)) xlabel Vce title Output-Characteristic
settype temperature v(dt)
plot v(dt)
.endc

.end
