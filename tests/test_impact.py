import math

import pytest

from chiton_sim.ball import Ball, mass_from_diameter
from chiton_sim.contact import ThorntonLaw, effective_modulus, thornton_restitution_closed
from chiton_sim.impact import simulate_impact
from chiton_sim.materials import BAMBU_PLA_BASIC, CHROME_STEEL, BallMaterial
from chiton_sim.plate import Plate, plate_from_material
from chiton_sim.provenance import Label, Quantity

BALL = Ball.standard('3/4"')
PLATE = plate_from_material(BAMBU_PLA_BASIC, "XY", t=3e-3, a=0.040, bc="clamped")
ES = effective_modulus(210e9, 0.30, PLATE.E, PLATE.nu)
ELASTIC = ThorntonLaw(ES, BALL.radius, math.inf)
PLASTIC = ThorntonLaw(ES, BALL.radius, 1.6 * 76e6)
V = math.sqrt(2 * 9.80665 * 2.0)


def test_2dof_elastic_energy_conserved():
    r = simulate_impact(BALL, V, PLATE, ELASTIC, "2dof")
    assert r.energy["plastic"] == 0.0
    assert abs(r.energy["balance_err"]) < 5e-3
    assert r.e < 1.0  # 판 진동에 에너지가 남아 공 반발계수는 1보다 작다


@pytest.mark.parametrize("mode", ["rigid", "sdof"])
def test_e_equals_one_gives_impulse_2mv(mode):
    r = simulate_impact(BALL, V, PLATE, ELASTIC, mode)
    assert r.e == pytest.approx(1.0, abs=5e-3)
    assert r.J == pytest.approx(2 * BALL.mass * V, rel=5e-3)


@pytest.mark.parametrize("mode", ["2dof", "sdof", "rigid"])
def test_impulse_check_and_energy_balance_plastic(mode):
    r = simulate_impact(BALL, V, PLATE, PLASTIC, mode)
    assert r.J_rel_err < 5e-3
    assert abs(r.energy["balance_err"]) < 5e-3
    assert r.dent > 0 and 0 < r.e < 1


def test_rigid_ode_matches_thornton_closed_form():
    r = simulate_impact(BALL, V, None, PLASTIC, "rigid")
    e_ref = thornton_restitution_closed(V, PLASTIC.yield_velocity(BALL.mass))
    assert r.e == pytest.approx(e_ref, rel=5e-3)


def test_shivakumar_fig7_duration_sdof():
    """Shivakumar, Elber & Illg, NASA TM-85703 (1983) Fig. 7 / Table 2:
    Al 판 a = 38 mm, h = 3.2 mm, 고정단, 강구 R = 19 mm, V0 = 2.54 m/s → 접촉시간 0.607 ms (TDOF·SDOF 동일).
    본 모델은 전단 강성을 생략(A-07)하므로 약 −4 % 차이가 예상된다. 허용 ±10 %.
    https://ntrs.nasa.gov/api/citations/19840003151/downloads/19840003151.pdf"""
    steel = BallMaterial("steel (Shivakumar Table 2)",
                         Quantity(7971.8, "kg/m^3", Label.LITERATURE, "NASA TM-85703 Table 2"),
                         Quantity(199.95e9, "Pa", Label.LITERATURE, "NASA TM-85703 Table 2"),
                         Quantity(0.33, "-", Label.LITERATURE, "NASA TM-85703 Table 2"))
    d = 0.038
    ball = Ball(mass_from_diameter(d, 7971.8), d, steel)
    al = Plate(E=68.95e9, nu=0.33, rho=2768.0, t=3.2e-3, a=0.038, bc="clamped")
    law = ThorntonLaw(effective_modulus(199.95e9, 0.33, 68.95e9, 0.33), 0.019, math.inf)
    r = simulate_impact(ball, 2.54, al, law, "sdof")
    assert r.tc == pytest.approx(0.607e-3, rel=0.10)
    assert ball.mass / al.m_eff == pytest.approx(23, rel=0.05)  # 논문의 MI/MP = 23


def test_applicability_warnings():
    r = simulate_impact(BALL, V, PLATE, PLASTIC, "2dof")
    assert r.mass_ratio == pytest.approx(BALL.mass / PLATE.mass)
    codes = r.warnings.codes()
    assert "mass_ratio_mid" in codes or "wave_dominated" in codes
    thin = plate_from_material(BAMBU_PLA_BASIC, "XY", t=1e-3, a=0.050)
    r2 = simulate_impact(BALL, V, thin, PLASTIC, "2dof", yield_proxy=76e6)
    assert "membrane" in r2.warnings.codes()
    assert "hertz_yield" in r2.warnings.codes()
    big = Ball.standard('1/4"')
    r3 = simulate_impact(big, V, plate_from_material(BAMBU_PLA_BASIC, "XY", 5e-3, 0.05), PLASTIC, "2dof")
    assert "wave_dominated" in r3.warnings.codes()


def test_simply_supported_softer_than_clamped():
    rc = simulate_impact(BALL, V, PLATE, PLASTIC, "2dof")
    rs = simulate_impact(BALL, V, PLATE.with_bc("simply_supported"), PLASTIC, "2dof")
    assert rs.w_max > rc.w_max
    assert rs.tc > rc.tc
