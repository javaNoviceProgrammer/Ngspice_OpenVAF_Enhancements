#!/usr/bin/env python3
"""Draw circuit schematics for the RF-suite document (docs/internals/ngspice_internals/
ngspice_rf_suite.md). One PNG per example netlist, saved under rf_figs/.

Requires `schemdraw` (pip install schemdraw). Regenerate with:
    python3 make_rf_schematics.py
"""
import os
import schemdraw
import schemdraw.elements as elm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "rf_figs")
os.makedirs(OUT, exist_ok=True)
schemdraw.config(fontsize=11)


def save(d, name):
    d.save(os.path.join(OUT, name + ".png"), dpi=130)
    print("wrote", name + ".png")


def rc_lowpass_2port():
    with schemdraw.Drawing(show=False) as d:
        d += elm.SourceSin().up().label("V1\nport 1\nz0=50Ω")
        d += elm.Line().right().length(1)
        d += elm.Dot().label("in", "top")
        d += elm.Resistor().right().label("R1  100Ω")
        d += elm.Dot().label("out", "top")
        d.push()
        d += elm.Capacitor().down().label("C1\n1nF")
        d += elm.Ground()
        d.pop()
        d += elm.Line().right().length(1)
        d += elm.SourceSin().down().label("V2\nport 2\nz0=50Ω")
        d += elm.Ground()
    save(d, "sch_rc_2port")


def diode_clipper():
    with schemdraw.Drawing(show=False) as d:
        d += elm.SourceSin().up().label("V1\n1.5 V\n1 MHz")
        d += elm.Line().right().length(0.6)
        d += elm.Dot().label("a", "top")
        d += elm.Resistor().right().label("R1  1kΩ")
        d += elm.Dot().label("b", "top")
        d.push()
        d += elm.Diode().down().label("D1")
        d += elm.Ground()
        d.pop()
    save(d, "sch_diode_clipper")


def cubic_nl():
    with schemdraw.Drawing(show=False) as d:
        d += elm.SourceSin().up().label("I1\n0.1 mA\n100 MHz")
        d += elm.Dot().label("n", "left")
        d.push()
        d += elm.Resistor().right().label("R1\n1kΩ")
        d += elm.Ground()
        d.pop()
        d += elm.SourceControlledI().down().label("Bnl\nI = 0.5m·V(n)³")
        d += elm.Ground()
    save(d, "sch_cubic_nl")


def osdi_diode():
    with schemdraw.Drawing(show=False) as d:
        d += elm.SourceSin().up().label("V1\n0.6 V\n100 MHz")
        d += elm.Line().right().length(0.6)
        d += elm.Dot().label("a", "top")
        d += elm.Resistor().right().label("R1  1kΩ")
        d += elm.Dot().label("b", "top")
        d.push()
        d += elm.Diode().down().label("N1  odio\n(Verilog-A)")
        d += elm.Ground()
        d.pop()
    save(d, "sch_osdi_diode")


def diode_mixer():
    with schemdraw.Drawing(show=False) as d:
        d += elm.SourceSin().up().label("Vlo\n0.4 V\n1 MHz")
        d += elm.Line().right().length(0.5)
        d += elm.Resistor().right().label("Rlo 200Ω")
        d += elm.Dot().label("a", "top")
        d.push()
        d += elm.SourceSin().down().label("Vrf\nAC 1", "left")
        d += elm.Ground()
        d.pop()
        d += elm.Diode().right().label("D1")
        d += elm.Dot().label("b", "top")
        d.push()
        d += elm.Resistor().down().label("Rif\n1kΩ")
        d += elm.Ground()
        d.pop()
        d += elm.Line().right().length(1)
        d += elm.Capacitor().down().label("Cif\n100pF")
        d += elm.Ground()
    save(d, "sch_diode_mixer")


def two_tone_cubic():
    with schemdraw.Drawing(show=False) as d:
        # left column: two stacked tone sources -> node n2
        d += elm.Ground()
        d += elm.SourceSin().up().label("V1\n100 MHz")
        d += elm.Dot().label("n1", "left")
        d += elm.SourceSin().up().label("V2\n110 MHz")
        n2 = d.add(elm.Dot().label("n2", "left"))
        d += elm.Resistor().right().label("Rhi  1MΩ")
        d += elm.Ground()
        # right column: cubic controlled source -> out, with load Rout
        d += elm.SourceControlledV().up().at((6, 0)).label("Bout\nV = 0.5·V(n2)³", "left")
        out = d.add(elm.Dot().label("out", "top"))
        d.push()
        d += elm.Resistor().right().label("Rout\n1kΩ")
        d += elm.Ground()
        d.pop()
        d += elm.Ground().at((6, 0))
        # control arrow: Bout is driven by V(n2)
        d += elm.Wire("-|", arrow="->").at(n2.center).to((6, 1.5)).color("#888").label("senses V(n2)", "top", fontsize=9)
    save(d, "sch_two_tone_cubic")


def lc_oscillator():
    with schemdraw.Drawing(show=False) as d:
        d += elm.Line().right().length(1)
        d += elm.Dot().label("n", "top")
        d.push()
        d += elm.Inductor().down().label("L1\n1µH")
        d += elm.Ground()
        d.pop()
        d += elm.Line().right().length(2.6)
        d.push()
        d += elm.Capacitor().down().label("C1\n1nF")
        d += elm.Ground()
        d.pop()
        d += elm.Line().right().length(2.6)
        d.push()
        d += elm.Resistor().down().label("R1\n100kΩ", "left")
        d += elm.Ground()
        d.pop()
        d += elm.Line().right().length(3.2)
        d += elm.SourceControlledI().down().label("Bnl (neg. R)\nI=2m·V−5m·V³", "right")
        d += elm.Ground()
    save(d, "sch_lc_osc")


def rlc_tank():
    with schemdraw.Drawing(show=False) as d:
        d += elm.SourceSin().up().label("V1\n1 V @ f0")
        d += elm.Line().right().length(0.5)
        d += elm.Inductor().right().label("L1  1µH")
        d += elm.Dot().label("a", "top")
        d.push()
        d += elm.Capacitor().down().label("C1\n1nF")
        d += elm.Ground()
        d.pop()
        d += elm.Line().right().length(1)
        d += elm.Resistor().down().label("R1\n100kΩ")
        d += elm.Ground()
    save(d, "sch_rlc_tank")


def psp_2port():
    with schemdraw.Drawing(show=False) as d:
        d += elm.SourceSin().up().label("port 1\nz0=50Ω")
        d += elm.Resistor().right().label("Rs  50Ω")
        d += elm.Dot().label("out", "top")
        d.push()
        d += elm.Resistor().down().label("Rl\n200Ω")
        d += elm.Ground()
        d.pop()
        d += elm.Line().right().length(1)
        d += elm.SourceSin().down().label("port 2\nz0=50Ω")
        d += elm.Ground()
    save(d, "sch_psp_2port")


if __name__ == "__main__":
    rc_lowpass_2port()
    diode_clipper()
    cubic_nl()
    osdi_diode()
    diode_mixer()
    two_tone_cubic()
    lc_oscillator()
    rlc_tank()
    psp_2port()
