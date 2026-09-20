import math

import pytest

from chiton_sim.ball import (
    Ball, GuideTube, PET_WARNING, check_ball_in_tube, diameter_from_mass,
    mass_from_diameter, snap_to_standard,
)
from chiton_sim.fall import FallParams, height_for_energy, morrison_cd, simulate_fall
from chiton_sim.materials import G0
from chiton_sim.provenance import Basis, GuideTubeError, Label, Quantity, SimInputError

G = G0.value
BALL = Ball.standard('3/4"')


@pytest.mark.parametrize("h", [0.3, 2.0, 15.0])
def test_no_drag_matches_free_fall(h):
    r = simulate_fall(BALL, h, params=FallParams(drag=False))
    assert abs(r.v_impact / math.sqrt(2 * G * h) - 1) < 1e-6
    assert abs(r.t_fall / math.sqrt(2 * h / G) - 1) < 1e-6


@pytest.mark.parametrize("m", [1e-3, 0.0283, 1.043])
def test_mass_diameter_roundtrip(m):
    rho = 7810.0
    assert mass_from_diameter(diameter_from_mass(m, rho), rho) == pytest.approx(m, rel=1e-12)


def test_standard_ball_values():
    b = Ball.standard('3/4"')
    assert b.diameter == pytest.approx(0.01905)
    assert b.mass == pytest.approx(7810 * math.pi * 0.01905**3 / 6)
    assert snap_to_standard(0.0165).name == '5/8"'


def test_ball_larger_than_tube_raises():
    tube = GuideTube(Quantity(0.020, "m", Label.ASSUMPTION, None, "test"), 1.8)
    check_ball_in_tube(Ball.standard('5/8"'), tube)
    with pytest.raises(GuideTubeError):
        check_ball_in_tube(Ball.standard('3/4"'), tube)  # 19.05 > 20 − 1
    with pytest.raises(GuideTubeError):
        simulate_fall(Ball.standard('3/4"'), 1.8, tube)


def test_pet_mode_warning():
    log = check_ball_in_tube(Ball.standard('3/4"'), GuideTube.pet_bottle(1.8))
    assert any(w.message == PET_WARNING for w in log)
    with pytest.raises(GuideTubeError):
        check_ball_in_tube(Ball.standard('7/8"'), GuideTube.pet_bottle(1.8))


def test_height_range_enforced():
    with pytest.raises(SimInputError):
        simulate_fall(BALL, 0.2)
    with pytest.raises(SimInputError):
        simulate_fall(BALL, 20.5)


def test_strain_rate_warning_above_10mps():
    assert "strain_rate" not in simulate_fall(BALL, 2.0).warnings.codes()
    assert "strain_rate" in simulate_fall(BALL, 13.0).warnings.codes()


def test_drag_small_but_positive_and_tube_factor():
    r = simulate_fall(BALL, 2.0)
    assert 0 < r.loss_frac < 0.01
    tube = GuideTube(Quantity(0.022, "m", Label.ASSUMPTION, None, "t"), 1.8)
    r2 = simulate_fall(BALL, 2.0, tube, FallParams(K_tube=Quantity(20.0, "-", Label.CALIBRATED)))
    assert r2.v_impact < r.v_impact
    assert r2.basis is Basis.POST and r.basis is Basis.PRE


def test_wall_loss_applied():
    p = FallParams(eta_wall=Quantity(0.05, "-", Label.CALIBRATED))
    r0, r1 = simulate_fall(BALL, 2.0), simulate_fall(BALL, 2.0, params=p)
    assert r1.v_impact == pytest.approx(0.95 * r0.v_impact)


def test_morrison_limits():
    assert morrison_cd(1e-3) == pytest.approx(24e3, rel=1e-3)   # 크리핑 흐름
    assert 0.35 < morrison_cd(8e3) < 0.45                          # 낙하 구간


def test_height_for_energy_inverse():
    h = height_for_energy(BALL, 1.0)
    assert simulate_fall(BALL, h).energy == pytest.approx(1.0, rel=1e-5)
