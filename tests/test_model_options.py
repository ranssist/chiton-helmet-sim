"""오차를 줄이는 모델 옵션: 실측 판 강성, 막 강성 (PLAN §3-C, §3-E)."""

import math

import numpy as np
import pytest

from chiton_sim.ball import Ball
from chiton_sim.calibration import fit_plate_stiffness
from chiton_sim.contact import ThorntonLaw, effective_modulus
from chiton_sim.failure import energy_balance, failure_probability_curve, k_membrane_array
from chiton_sim.impact import simulate_impact
from chiton_sim.materials import BAMBU_PLA_BASIC
from chiton_sim.plate import Plate, plate_from_material
from chiton_sim.provenance import Basis, Label, Quantity, SimInputError
from chiton_sim.segments import SpecimenConfig, assess_site

BALL = Ball.standard('3/4"')
PY = Quantity(1.6 * 76e6, "Pa", Label.ASSUMPTION, None, "1.6Y")
PLATE = plate_from_material(BAMBU_PLA_BASIC, "XY", 3e-3, 0.040, "clamped")


def test_membrane_stiffness_formula_and_effect():
    """Shivakumar TM-85703 Table 1 (고정단·이동불가): Km = (353−191ν)πEh/(648(1−ν)a²)."""
    p = plate_from_material(BAMBU_PLA_BASIC, "XY", 3e-3, 0.040, "clamped", membrane=True)
    E, nu, t, a = p.E, p.nu, p.t, p.a
    assert p.k_membrane == pytest.approx((353 - 191 * nu) * math.pi * E * t / (648 * (1 - nu) * a**2))
    assert p.k_membrane == pytest.approx(k_membrane_array(E, nu, t, a, "clamped", True))
    # 단순지지 식은 원문에서 확인하지 못했으므로 0 으로 둔다
    assert plate_from_material(BAMBU_PLA_BASIC, "XY", 3e-3, 0.040, "simply_supported",
                               membrane=True).k_membrane == 0.0
    # 막 항은 처짐을 줄이고 반력을 키운다
    w = 2.0e-3
    assert p.force(w) > PLATE.force(w)
    assert p.energy(w) > PLATE.energy(w)


def test_membrane_changes_impact_result_in_expected_direction():
    law = ThorntonLaw(effective_modulus(210e9, 0.30, PLATE.E, PLATE.nu), BALL.radius, PY.value)
    p_mem = plate_from_material(BAMBU_PLA_BASIC, "XY", 3e-3, 0.040, "clamped", membrane=True)
    v = 6.25
    r0 = simulate_impact(BALL, v, PLATE, law, "sdof")
    r1 = simulate_impact(BALL, v, p_mem, law, "sdof")
    assert r1.w_max < r0.w_max                      # 막 항이 판을 뻣뻣하게 만든다
    assert r1.F_plate_max > r0.F_plate_max
    assert 1.05 < r1.F_plate_max / r0.F_plate_max < 1.30   # 2 m 낙하에서 10 % 남짓
    assert abs(r1.energy["balance_err"]) < 5e-3     # 에너지 수지는 여전히 맞는다


def test_energy_balance_with_membrane_matches_sdof_simulation():
    p_mem = plate_from_material(BAMBU_PLA_BASIC, "XY", 3e-3, 0.040, "clamped", membrane=True)
    law = ThorntonLaw(effective_modulus(210e9, 0.30, p_mem.E, p_mem.nu), BALL.radius, PY.value)
    v = 6.25
    r = simulate_impact(BALL, v, p_mem, law, "sdof")
    F, d, E_abs = energy_balance(0.5 * BALL.mass * v**2, law.E_star, BALL.radius, PY.value,
                                 p_mem.k_bending(), p_mem.k_membrane)
    assert float(F) == pytest.approx(r.F_plate_max, rel=2e-3)
    assert float(E_abs) == pytest.approx(r.E_abs, rel=5e-3)


def test_measured_stiffness_overrides_boundary_condition():
    k = 1.5e5
    p = Plate(E=PLATE.E, nu=PLATE.nu, rho=PLATE.rho, t=PLATE.t, a=PLATE.a, bc="clamped", k_measured=k)
    assert p.k_bending() == k
    assert p.k_bending("clamped") == pytest.approx(PLATE.k_bending())   # 이론값은 그대로 조회 가능
    assert p.fixity() == pytest.approx(k / PLATE.k_bending())


def test_fit_plate_stiffness_recovers_known_values():
    kb_true, km_true = 2.1e5, 9.0e9
    w = np.linspace(0.2e-3, 3.0e-3, 8)
    P = kb_true * w + km_true * w**3
    f1 = fit_plate_stiffness(w, P, with_membrane=True)
    assert f1.kb.value == pytest.approx(kb_true, rel=1e-6)
    assert f1.km.value == pytest.approx(km_true, rel=1e-6)
    assert f1.kb.label is Label.CALIBRATED and f1.r2 > 0.999
    # 막 항 없이 적합하면 선형 강성만 나온다
    f2 = fit_plate_stiffness(w, kb_true * w)
    assert f2.kb.value == pytest.approx(kb_true, rel=1e-9) and f2.km is None
    with pytest.raises(SimInputError):
        fit_plate_stiffness([1e-3], [10.0])


def test_assess_site_with_measured_stiffness_has_single_case():
    seg = dict(config_type="segmented_overlap", thickness=3e-3, ring_radius=0.040,
               overlap=5e-3, n_segments=3, lock=True, seam_length=0.12)
    a_assumed = assess_site(BALL, 6.25, BAMBU_PLA_BASIC, SpecimenConfig(**seg), "center", PY)
    a_measured = assess_site(BALL, 6.25, BAMBU_PLA_BASIC,
                             SpecimenConfig(**seg, k_measured=1.8e5), "center", PY)
    assert len(a_assumed.cases) == 2          # 고정단~단순지지 구간
    assert len(a_measured.cases) == 1         # 실측 강성이면 구간이 필요 없다
    assert "k_measured" in a_measured.warnings.codes()


def test_monte_carlo_with_measured_stiffness_is_post_calibration():
    hs = np.linspace(0.3, 3.0, 6)
    mc = failure_probability_curve(BALL, BAMBU_PLA_BASIC, "XY", 3e-3, 0.040, "clamped", hs, PY,
                                   n=400, k_measured=Quantity(1.8e5, "N/m", Label.CALIBRATED),
                                   membrane=True)
    assert mc.basis == Basis.POST.value
    assert np.all(np.diff(mc.p_fail) >= -0.02)
