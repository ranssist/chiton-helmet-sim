import math

import numpy as np
import pytest

from chiton_sim.ball import Ball
from chiton_sim.contact import ThorntonLaw, effective_modulus
from chiton_sim.failure import (
    energy_balance, failure_probability_curve, fit_critical_energy, main_judgment,
    reference_judgment,
)
from chiton_sim.impact import simulate_impact
from chiton_sim.materials import BAMBU_PLA_BASIC
from chiton_sim.plate import equivalent_load_radius, plate_from_material, reference_stress
from chiton_sim.provenance import NEEDS_MEASUREMENT, Basis, Label, Quantity

BALL = Ball.standard('3/4"')
PLATE = plate_from_material(BAMBU_PLA_BASIC, "XY", 3e-3, 0.040)
PY = Quantity(1.6 * 76e6, "Pa", Label.ASSUMPTION, None, "1.6Y")


def test_roark_ss_minus_clamped_center_and_r0_switch():
    P, r0 = 500.0, 0.5e-3
    c = reference_stress(P, PLATE, r0, "clamped")
    s = reference_stress(P, PLATE, r0, "simply_supported")
    assert s.center - c.center == pytest.approx(3 * P / (2 * math.pi * PLATE.t**2))
    assert c.edge == pytest.approx(3 * P / (2 * math.pi * PLATE.t**2))
    t = PLATE.t
    assert equivalent_load_radius(0.4 * t, t) == pytest.approx(math.sqrt(1.6 * (0.4 * t) ** 2 + t**2) - 0.675 * t)
    assert equivalent_load_radius(0.6 * t, t) == 0.6 * t


def test_energy_balance_matches_sdof_simulation():
    law = ThorntonLaw(effective_modulus(210e9, 0.3, PLATE.E, PLATE.nu), BALL.radius, PY.value)
    v = 6.25
    r = simulate_impact(BALL, v, PLATE, law, "sdof")
    F, d, E_abs = energy_balance(0.5 * BALL.mass * v**2, law.E_star, BALL.radius, PY.value, PLATE.k_bending())
    assert float(F) == pytest.approx(r.F_max, rel=1e-3)
    assert float(E_abs) == pytest.approx(r.E_abs, rel=2e-3)


def test_reference_judgment():
    j = reference_judgment(90e6, BAMBU_PLA_BASIC.props("XY").flex_strength)
    assert j.fail and j.margin == pytest.approx(76 / 90) and j.basis == Basis.PRE.value


def test_critical_energy_fit_recovers_power_law():
    t = np.array([2e-3, 3e-3, 4e-3, 2e-3, 3e-3, 4e-3])
    C, n = 5e3, 1.7
    E = C * t**n * np.array([1.02, 0.98, 1.01, 0.99, 1.02, 0.98])
    fit = fit_critical_energy(t, E)
    assert fit.n == pytest.approx(n, abs=0.1)
    assert fit.Ec(3e-3).label is Label.CALIBRATED
    one = fit_critical_energy(np.array([3e-3, 3e-3]), np.array([0.4, 0.5]))
    assert one.n is None and one.Ec(3e-3).known and not one.Ec(4e-3).known
    mj = main_judgment(0.3, one, 4e-3)
    assert mj.fail is None and mj.basis == NEEDS_MEASUREMENT
    assert main_judgment(0.3, None, 3e-3).fail is None


def test_monte_carlo_reproducible_and_monotone():
    hs = np.linspace(0.3, 3.0, 8)
    kw = dict(ball=BALL, material=BAMBU_PLA_BASIC, orientation="XY", t=3e-3, a=0.040, bc="clamped",
              heights=hs, py=PY, n=2000, seed=1)
    r1 = failure_probability_curve(**kw)
    r2 = failure_probability_curve(**kw)
    assert np.array_equal(r1.p_fail, r2.p_fail)
    assert np.all(np.diff(r1.p_fail) >= -0.02)
    assert r1.criterion == "reference" and r1.basis == Basis.PRE.value
    assert r1.p_fail[0] < r1.p_fail[-1]
