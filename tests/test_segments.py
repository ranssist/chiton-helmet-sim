import math

import pytest

from chiton_sim.ball import Ball
from chiton_sim.materials import BAMBU_PLA_BASIC
from chiton_sim.provenance import (
    NEEDS_MEASUREMENT, NOT_ANALYZABLE, Basis, Label, Quantity, SimInputError, assumed,
)
from chiton_sim.segments import (
    KT_HOLE_BENDING, FastenerSpec, SiteCalibration, SpecimenConfig, VentSpec, areal_density,
    assess_site, equal_areal_density_thickness, overlap_ratio,
)

BALL = Ball.standard('3/4"')
V = 6.25
PY = Quantity(1.6 * 76e6, "Pa", Label.ASSUMPTION, None, "1.6Y")
MONO = SpecimenConfig("monolithic", 3e-3, 0.040)
OVL = SpecimenConfig("segmented_overlap", 3e-3, 0.040, overlap=5e-3, n_segments=3, lock=True,
                     joint_type="tpu_hinge", seam_length=0.12)


@pytest.mark.parametrize("site", ["seam", "triple_junction"])
def test_seam_without_calibration_is_needs_measurement(site):
    a = assess_site(BALL, V, BAMBU_PLA_BASIC, OVL, site, PY)
    assert a.status == NEEDS_MEASUREMENT
    assert not a.numeric and a.cases == {}


def test_seam_with_calibration_is_not_analyzable_with_knockdown():
    cal = SiteCalibration(E50=Quantity(0.35, "J", Label.CALIBRATED), E50_center=Quantity(0.5, "J", Label.CALIBRATED))
    a = assess_site(BALL, V, BAMBU_PLA_BASIC, OVL, "seam", PY, cal)
    assert a.status == NOT_ANALYZABLE
    assert cal.knockdown.value == pytest.approx(0.7)


def test_monolithic_has_no_seam():
    with pytest.raises(SimInputError):
        assess_site(BALL, V, BAMBU_PLA_BASIC, MONO, "seam", PY)


def test_areal_density_matches_inputs():
    r = overlap_ratio(OVL)
    assert r.value == pytest.approx(0.12 * 5e-3 / (math.pi * 0.04**2))
    rho = BAMBU_PLA_BASIC.density.value
    assert areal_density(rho, 3e-3, r.value) == pytest.approx(1240 * 3e-3 * (1 + r.value), rel=1e-15)
    assert areal_density(rho, 3e-3, 0.0) == pytest.approx(3.72)  # kg/m² = 0.372 g/cm²
    assert equal_areal_density_thickness(3e-3, r.value) == pytest.approx(3e-3 * (1 + r.value))
    no_cad = SpecimenConfig("segmented_overlap", 3e-3, 0.04, overlap=5e-3, n_segments=3)
    assert overlap_ratio(no_cad).label is Label.UNVERIFIED


def test_center_bc_rules():
    a = assess_site(BALL, V, BAMBU_PLA_BASIC, MONO, "center", PY)
    assert set(a.cases) == {"clamped"} and a.status == Basis.PRE.value
    b = assess_site(BALL, V, BAMBU_PLA_BASIC, OVL, "center", PY)
    assert set(b.cases) == {"clamped", "simply_supported"}
    nolock = SpecimenConfig("segmented_butt", 3e-3, 0.040, n_segments=3, lock=False)
    c = assess_site(BALL, V, BAMBU_PLA_BASIC, nolock, "center", PY)
    assert set(c.cases) == {"simply_supported"} and "no_lock" in c.warnings.codes()


def test_bonded_receiver_has_no_kt_and_detach_mode():
    cfg = SpecimenConfig("monolithic", 3e-3, 0.040,
                         fastener=FastenerSpec("bonded_receiver", 4, 4e-3, 20e-3, 8e-3))
    a = assess_site(BALL, V, BAMBU_PLA_BASIC, cfg, "fastener", PY)
    assert all(c.Kt is None for c in a.cases.values())
    assert all(c.sigma_local == pytest.approx(c.stress.max) for c in a.cases.values())
    assert a.extra_modes["받침 탈락"] == NEEDS_MEASUREMENT


def test_through_screw_applies_kt_and_spacing_check():
    f = FastenerSpec("through_screw", 4, 4e-3, 10e-3, 6e-3)
    cfg = SpecimenConfig("monolithic", 3e-3, 0.040, fastener=f)
    a = assess_site(BALL, V, BAMBU_PLA_BASIC, cfg, "fastener", PY)
    c = a.cases["clamped"]
    assert c.Kt is KT_HOLE_BENDING and c.sigma_local == pytest.approx(1.87 * c.stress.max)
    assert "fastener_p/d_unverified" in a.warnings.codes()
    f2 = FastenerSpec("through_screw", 4, 4e-3, 10e-3, 6e-3,
                      p_d_min=assumed(3.0, "-", "사용자 입력"), e_d_min=assumed(2.0, "-", "사용자 입력"))
    a2 = assess_site(BALL, V, BAMBU_PLA_BASIC, SpecimenConfig("monolithic", 3e-3, 0.04, fastener=f2), "fastener", PY)
    assert {"fastener_p/d", "fastener_e/d"} <= a2.warnings.codes()


def test_vent_types():
    lv = SpecimenConfig("monolithic", 3e-3, 0.04, vent=VentSpec("liner_vent", 6, 8e-3))
    assert assess_site(BALL, V, BAMBU_PLA_BASIC, lv, "opening", PY).cases["clamped"].Kt is None
    st = SpecimenConfig("monolithic", 3e-3, 0.04, vent=VentSpec("shell_through", 6, 8e-3))
    assert assess_site(BALL, V, BAMBU_PLA_BASIC, st, "opening", PY).cases["clamped"].Kt.value == 1.87
    oc = SpecimenConfig("segmented_overlap", 3e-3, 0.04, overlap=5e-3, n_segments=3, lock=True,
                        vent=VentSpec("overlap_channel", 6, 3e-3))
    assert assess_site(BALL, V, BAMBU_PLA_BASIC, oc, "opening", PY).status == NEEDS_MEASUREMENT


def test_tds_condition_warnings():
    cfg = SpecimenConfig("monolithic", 3e-3, 0.04, infill=0.4, annealed=False)
    a = assess_site(BALL, V, BAMBU_PLA_BASIC, cfg, "center", PY)
    assert {"infill", "annealing"} <= a.warnings.codes()
