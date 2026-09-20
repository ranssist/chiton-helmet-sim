import math

import pytest

from chiton_sim.helmet import (
    ARDUINO_SAMPLE_RATE, BLUNT_G_LIMIT, BLUNT_VELOCITY, FASTSF_AREAL_DENSITY, FASTSF_SIZES,
    FASTSF_SHELL_L_DATASHEET, FASTSF_SHELL_L_NEXTGEN, FMVSS218_HEADFORMS, HEADFORM_MASS,
    LinerModel, measurement_check, required_spread_area, segmented_spread_area, shell_areal_density,
    shell_mass, simulate_headform, thickness_for_mass,
)
from chiton_sim.materials import BAMBU_PLA_BASIC, G0, epp_stress
from chiton_sim.provenance import Basis, Label, Quantity, SimInputError, assumed, computed, unverified

G = G0.value
M_HEAD = Quantity(5.0, "kg", Label.LITERATURE, "FMVSS 218", "중형 헤드폼 참고값")
AREA_L = Quantity(955e-4, "m^2", Label.LITERATURE, "FAST SF 데이터시트", "사이즈 L 커버리지")


def test_constant_plateau_reproduces_uniform_deceleration():
    """σ·A/m 이 일정하면 a = σA/m, s = v²/(2a) 여야 한다."""
    sigma, A, m = 290e3, 0.025, 5.0
    liner = LinerModel(thickness=0.030, plateau=Quantity(sigma, "Pa", Label.LITERATURE, "test"))
    r = simulate_headform(M_HEAD, liner, Quantity(A, "m^2", Label.ASSUMPTION, None, "test"))
    a_expect = sigma * A / m / G
    assert r.a_max_g == pytest.approx(a_expect, rel=1e-9)
    v = BLUNT_VELOCITY.value
    assert r.stroke == pytest.approx(v**2 / (2 * a_expect * G), rel=1e-6)
    assert r.s_min == pytest.approx(r.stroke, rel=1e-6)
    assert r.pulse_duration == pytest.approx(v / (a_expect * G), rel=1e-6)


def test_150g_limit_gives_3_16_mm():
    v = BLUNT_VELOCITY.value
    assert v**2 / (2 * BLUNT_G_LIMIT.value * G) == pytest.approx(3.16e-3, abs=0.01e-3)


def test_bottoming_detected_for_thin_liner():
    liner = LinerModel(thickness=0.006, plateau=Quantity(290e3, "Pa", Label.LITERATURE, "t"))
    r = simulate_headform(M_HEAD, liner, assumed(0.01, "m^2", "작은 분산 면적"))
    assert r.bottoming and "bottoming" in r.warnings.codes()
    assert not r.passes_150g or r.a_max_g <= 150


def test_required_spread_area_window():
    liner = LinerModel(thickness=0.020, plateau=Quantity(290e3, "Pa", Label.LITERATURE, "t"))
    lo, hi = required_spread_area(M_HEAD, liner)
    v, m, sigma = BLUNT_VELOCITY.value, 5.0, 290e3
    assert lo.value == pytest.approx(m * v**2 / (2 * sigma * 0.020))
    assert hi.value == pytest.approx(150 * G * m / sigma)
    r = simulate_headform(M_HEAD, liner, computed(hi.value, "m^2", "상한"))
    assert r.a_max_g == pytest.approx(150.0, rel=1e-6) and not r.bottoming


def test_epp_curve_liner_runs():
    curve = tuple((s, epp_stress(45.0, s).value) for s in (0.10, 0.25, 0.50, 0.75))
    liner = LinerModel(thickness=0.020, curve=curve)
    r = simulate_headform(M_HEAD, liner, assumed(0.03, "m^2", "가정"))
    assert r.a_max_g > 0 and r.stroke < 0.020


def test_shell_mass_and_inverse_roundtrip():
    rho = BAMBU_PLA_BASIC.density.value
    m = shell_mass(rho, AREA_L, 3e-3, 0.15)
    t = thickness_for_mass(rho, AREA_L, m.value, 0.15)
    assert t.value == pytest.approx(3e-3, rel=1e-12)
    assert shell_areal_density(rho, 3e-3, 0.15).value == pytest.approx(rho * 3e-3 * 1.15)
    assert not shell_mass(rho, unverified("m^2"), 3e-3).known


def test_fastsf_reference_values():
    assert FASTSF_SIZES["L"][2] == pytest.approx(955e-4)
    assert FASTSF_SHELL_L_DATASHEET.value == 0.655 and FASTSF_SHELL_L_NEXTGEN.value == 0.557
    assert FASTSF_AREAL_DENSITY.value == pytest.approx(5.957)
    assert all(q.label is Label.LITERATURE for q in FMVSS218_HEADFORMS.values())
    assert not HEADFORM_MASS.known    # FTHS 헤드폼 질량은 미확인
    with pytest.raises(SimInputError):
        HEADFORM_MASS.require("헤드폼 질량")


def test_segmented_spread_area_rules():
    a = segmented_spread_area(0.01, lock=False)
    assert a.value == 0.01 and a.label is Label.ASSUMPTION
    b = segmented_spread_area(0.01, lock=True)
    assert b.value == 0.01  # β 보정 전 0
    c = segmented_spread_area(0.01, lock=True, beta=Quantity(0.4, "-", Label.CALIBRATED))
    assert c.value == pytest.approx(0.014) and c.label is Label.CALIBRATED


def test_measurement_feasibility():
    slow = measurement_check(2.0e-3)            # 헤드폼 펄스 ~2 ms
    fast = measurement_check(0.2e-3)            # 판 충돌 접촉시간 ~0.2 ms
    assert slow.samples_per_pulse == pytest.approx(20.0) and slow.ok
    assert not fast.ok and "measurement" in fast.warnings.codes()
    three = measurement_check(2.0e-3, n_channels=3)
    assert three.samples_per_pulse == pytest.approx(20 / 3, rel=1e-9)
    bw = measurement_check(2.0e-3, sensor_bandwidth=200.0)
    assert bw.bandwidth_error is not None and bw.bandwidth_error > 0
    assert ARDUINO_SAMPLE_RATE.label is Label.LITERATURE
