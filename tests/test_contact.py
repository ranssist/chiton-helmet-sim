import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from chiton_sim.contact import (
    HERTZ_TC_COEF, ThorntonLaw, check_hertz_validity, effective_modulus, hertz_force,
    hertz_impact, thornton_restitution_closed,
)
from chiton_sim.provenance import WarningLog

# 강구(3/4") → PLA 평판 기본 조건
E_STEEL, NU_STEEL, RHO_STEEL = 210e9, 0.30, 7810.0
E_PLA, NU_PLA = 2750e6, 0.36
R = 0.01905 / 2
M = RHO_STEEL * 4 / 3 * math.pi * R**3
ES = effective_modulus(E_STEEL, NU_STEEL, E_PLA, NU_PLA)


def test_tc_coefficient_matches_he_wettlaufer():
    # He & Wettlaufer, arXiv:1306.4952: T = 2.8683 (M²/(R V E²))^(1/5)
    # Johnson (1985): t = 2.94 δ*/v, δ* = (15mv²/(16E*√R))^(2/5). 2.94 는 반올림값이고,
    # 정확값은 2∫₀¹ dx/√(1−x^(5/2)) = 2.9432 → 2.9432·(15/16)^(2/5) = 2.8683
    from scipy.integrate import quad
    c = 2 * quad(lambda x: 1 / math.sqrt(1 - x**2.5), 0, 1)[0]
    assert HERTZ_TC_COEF == pytest.approx(2.8683, abs=1e-4)
    assert c * (15 / 16) ** 0.4 == pytest.approx(HERTZ_TC_COEF, rel=1e-4)


@pytest.mark.parametrize(
    "ball, plate",
    [
        # (ρ, E, ν) — McLaskey & Glaser 2010 Table I 계열의 강구/강판, 강구/알루미늄판, 그리고 PLA
        ((7850.0, 200e9, 0.29), (200e9, 0.29)),
        ((7850.0, 200e9, 0.29), (70e9, 0.33)),
        ((RHO_STEEL, E_STEEL, NU_STEEL), (E_PLA, NU_PLA)),
    ],
)
@pytest.mark.parametrize("d, v", [(1.0e-3, 1.58), (2.38e-3, 2.5), (0.01905, 6.26)])
def test_hertz_matches_mclaskey_glaser_2010(ball, plate, d, v):
    """출처: G.C. McLaskey & S.D. Glaser, J. Acoust. Soc. Am. 128(3):1087–1096 (2010), 식 (4)·(6):
    tc = 4.53 (4ρ₁π(δ₁+δ₂)/3)^(2/5) R₁ v₀^(-1/5),  fmax = 1.917 ρ₁^(3/5) (δ₁+δ₂)^(-2/5) R₁² v₀^(6/5),
    δᵢ = (1−νᵢ²)/(πEᵢ).  https://courses.cit.cornell.edu/mclaskey/pubs/JASA2010.pdf
    문헌 계수(4.53, 1.917)의 반올림 때문에 허용오차 0.3 %."""
    rho1, E1, nu1 = ball
    E2, nu2 = plate
    R1 = d / 2
    m = rho1 * 4 / 3 * math.pi * R1**3
    dsum = (1 - nu1**2) / (math.pi * E1) + (1 - nu2**2) / (math.pi * E2)
    tc_ref = 4.53 * (4 * rho1 * math.pi * dsum / 3) ** 0.4 * R1 * v**-0.2
    f_ref = 1.917 * rho1**0.6 * dsum**-0.4 * R1**2 * v**1.2
    h = hertz_impact(m, R1, v, effective_modulus(E1, nu1, E2, nu2))
    assert h.tc == pytest.approx(tc_ref, rel=3e-3)
    assert h.F_max == pytest.approx(f_ref, rel=3e-3)


def test_hertz_closed_form_vs_ode():
    v = 6.26
    h = hertz_impact(M, R, v, ES)

    def rhs(_t, y):
        return [y[1], -hertz_force(y[0], ES, R) / M]

    def sep(_t, y):
        return y[0]
    sep.terminal, sep.direction = True, -1
    sol = solve_ivp(rhs, (0, 10 * h.tc), [0.0, v], events=sep, rtol=1e-11, atol=1e-15,
                    method="DOP853", dense_output=True, max_step=h.tc / 200)
    tc = sol.t_events[0][0]
    tt = np.linspace(0, tc, 4001)
    Fmax = max(hertz_force(x, ES, R) for x in sol.sol(tt)[0])
    assert tc == pytest.approx(h.tc, rel=5e-3)
    assert Fmax == pytest.approx(h.F_max, rel=5e-3)


def test_yield_warning():
    h = hertz_impact(M, R, 6.26, ES)
    log = WarningLog()
    assert not check_hertz_validity(h.p0, 76e6, log)  # 2 m 낙하 강구는 PLA 를 국부 항복시킨다
    assert "hertz_yield" in log.codes()


LAW = ThorntonLaw(ES, R, 1.6 * 76e6)


@pytest.mark.parametrize("v", [0.5, 1.0, 2.0, 4.0, 6.26, 12.0])
def test_thornton_rigid_matches_closed_form(v):
    e, dmax, dp = LAW.rigid_impact(M, v)
    e_ref = thornton_restitution_closed(v, LAW.yield_velocity(M))
    assert e == pytest.approx(e_ref, rel=5e-3)
    assert 0 < dp < dmax


def test_thornton_below_yield_is_elastic():
    vy = LAW.yield_velocity(M)
    e, _, dp = LAW.rigid_impact(M, 0.9 * vy)
    assert e == pytest.approx(1.0, abs=1e-9) and dp == 0.0


def test_thornton_continuity():
    dy = LAW.delta_y
    assert LAW.force_load(dy * (1 - 1e-12)) == pytest.approx(LAW.force_load(dy * (1 + 1e-12)), rel=1e-9)
    Fm, Rp, dp = LAW.unload_params(3 * dy)
    assert LAW.force_unload(3 * dy, Rp, dp) == pytest.approx(Fm, rel=1e-9)
    assert Rp > R


def test_elastic_law_is_hertz():
    law = ThorntonLaw(ES, R, math.inf)
    assert law.force_load(1e-5) == pytest.approx(hertz_force(1e-5, ES, R))
    e, _, dp = law.rigid_impact(M, 6.26)
    assert e == pytest.approx(1.0) and dp == 0.0
