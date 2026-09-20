import pytest

from chiton_sim.ball import GuideTube
from chiton_sim.fall import H_MAX, H_MIN, simulate_fall
from chiton_sim.planner import (
    curvature_check, equal_energy_pair, specimen_plan, staircase_next, staircase_progress,
    velocity_effect_test,
)
from chiton_sim.provenance import Label, Quantity, SimInputError


def test_equal_energy_pair_matches_target():
    p = equal_energy_pair(0.6)
    assert p.usable
    assert p.light.energy == pytest.approx(0.6, rel=1e-4)
    assert p.heavy.energy == pytest.approx(0.6, rel=1e-4)
    assert p.light.ball.mass < p.heavy.ball.mass
    assert p.light.height > p.heavy.height
    assert p.v_ratio > 1.0
    assert simulate_fall(p.light.ball, p.light.height).energy == pytest.approx(0.6, rel=1e-4)


def test_equal_energy_pair_respects_tube_and_range():
    tube = GuideTube(Quantity(0.020, "m", Label.ASSUMPTION, None, "t"), 1.8)
    p = equal_energy_pair(0.6, tube)
    assert p.usable and p.heavy.ball.diameter <= 0.019
    assert equal_energy_pair(500.0).usable is False   # 20 m 로도 못 내는 에너지


def test_velocity_effect_fisher():
    same = velocity_effect_test(10, 20, 9, 20)
    diff = velocity_effect_test(18, 20, 3, 20)
    assert same["p_value"] > 0.05 and "유의하지 않" in same["verdict"]
    assert diff["p_value"] < 0.05 and diff["verdict"] == "속도 효과 있음(유의)"


def test_staircase_helper():
    assert staircase_next(1.5, failed=True, step=0.15) == pytest.approx(1.35)
    assert staircase_next(1.5, failed=False, step=0.15) == pytest.approx(1.65)
    assert staircase_next(H_MIN, failed=True, step=0.15) == H_MIN       # 하한에서 멈춤
    assert staircase_next(H_MAX, failed=False, step=0.5) == H_MAX
    with pytest.raises(SimInputError):
        staircase_next(1.0, True, 0.0)
    pr = staircase_progress([1.5, 1.35, 1.5, 1.65], [True, False, True, False], 0.15)
    assert pr.n == 4 and pr.reversals == 3 and pr.next_height == pytest.approx(1.8)
    assert "n_low" in pr.warnings.codes()
    flat = staircase_progress([1.0, 1.15, 1.3, 1.45], [False] * 4, 0.15)
    assert "no_reversal" in flat.warnings.codes()


def test_specimen_plan_counts():
    df = specimen_plan(["monolithic", "segmented_overlap"], ["center", "seam"], [0, 100, 500])
    assert len(df) == 9          # 일체형에는 seam 조합이 없다
    assert df.attrs["total_min"] == 9 * 20 and df.attrs["total_rec"] == 9 * 30


def test_curvature_check_table():
    df = curvature_check({("segmented_overlap", "center"): 0.55, ("segmented_overlap", "seam"): 0.34},
                         {("segmented_overlap", "center"): 0.47})
    row = df[df["조건"].str.contains("center")].iloc[0]
    assert row["차이 [J]"] == pytest.approx(-0.08) and row["해석"] == "곡률·형상 효과"
    assert df[df["조건"].str.contains("seam")].iloc[0]["해석"] == "헬멧 실측 필요"
