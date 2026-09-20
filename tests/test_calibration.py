import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chiton_sim import units
from chiton_sim.ball import Ball
from chiton_sim.calibration import (
    CLAY_TARGET_RP1, FailureCriteria, GROUP_KEYS_DEFAULT, RigSetup, analyze_groups, bruceton,
    check_clay, fit_py, fit_tube, load_criteria, logistic_e50, loss_ratio, normalize,
    require_criteria, run_calibration, save_criteria, validate_schema,
)
from chiton_sim.contact import ThorntonLaw, effective_modulus
from chiton_sim.fall import FallParams, simulate_fall
from chiton_sim.impact import simulate_impact
from chiton_sim.materials import BAMBU_PLA_BASIC
from chiton_sim.plate import plate_from_material
from chiton_sim.provenance import CalibrationBlockedError, Label, Quantity, SimInputError

DATA = Path(__file__).resolve().parents[1] / "data" / "sample_VIRTUAL_drop_tests.csv"
RIG = RigSetup(ring_radius=0.040, bc="clamped")
BALL = Ball.standard('3/4"')
PY_PRE = Quantity(1.6 * 76e6, "Pa", Label.ASSUMPTION, None, "1.6Y")

# Wikipedia "Bruceton analysis" Example 1 의 원자료(44회). 집계표는 첫 반전 한 단계 전부터 센 것이며
# N = 20, A = 55(원점 3.0), 50 % 수준 = 3.0 + 0.2(55/20 − 0.5) = 3.45.
WIKI_LEVELS = [4.0, 3.8, 3.6, 3.4, 3.2, 3.4, 3.6, 3.4, 3.2, 3.4, 3.2, 3.4, 3.2, 3.4, 3.6, 3.4,
               3.2, 3.4, 3.6, 3.4, 3.2, 3.4, 3.2, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 3.8, 3.6, 3.8,
               3.6, 3.4, 3.6, 3.4, 3.6, 3.4, 3.6, 3.4, 3.6, 3.4, 3.6, 3.4]
WIKI_RESULTS = "XXXX00XX0X0X00XX00XX0XX00000XX0XX0X0X0X0X0X0"


def test_bruceton_reproduces_published_example():
    fails = [c == "X" for c in WIKI_RESULTS]
    r = bruceton(WIKI_LEVELS, fails, d=0.2, origin=3.0)
    assert r.N == 20 and r.A == 55 and r.event == "fail"
    assert r.mean == pytest.approx(3.45, abs=1e-12)
    assert r.B == 167 and r.M == pytest.approx((20 * 167 - 55**2) / 400)
    assert r.sd == pytest.approx(1.620 * 0.2 * (r.M + 0.029))
    assert r.n_discarded == 3 and r.n_used == 41


def test_bruceton_origin_invariance_and_guards():
    fails = [c == "X" for c in WIKI_RESULTS]
    auto = bruceton(WIKI_LEVELS, fails, d=0.2)
    assert auto.mean == pytest.approx(3.45, abs=1e-12)
    with pytest.raises(SimInputError):
        bruceton([1.0, 1.1, 1.2], [False, False, False])


def test_schema_validation_reports_row_and_column():
    df = pd.read_csv(DATA, comment="#")
    assert validate_schema(df) == []
    bad = df.copy()
    bad["height_m"] = bad["height_m"].astype(object)
    bad.loc[0, "result"] = "maybe"
    bad.loc[1, "height_m"] = "높음"
    errs = validate_schema(bad)
    assert any("2행 result" in e for e in errs) and any("3행 height_m" in e for e in errs)
    assert "필수 열 누락" in validate_schema(df.drop(columns=["dent_mm"]))[0]


def test_criteria_block_calibration(tmp_path):
    df = units.drop_table_to_si(pd.read_csv(DATA, comment="#"))
    with pytest.raises(CalibrationBlockedError):
        run_calibration(df, FailureCriteria(), RIG, PY_PRE)
    p = tmp_path / "criteria.json"
    assert load_criteria(p).empty
    c = save_criteria(p, ["관통 균열"])
    assert not load_criteria(p).empty and c.created
    require_criteria(load_criteria(p))


def test_tube_fit_recovers_known_wall_loss():
    eta_true = 0.04
    hs = [0.6, 1.0, 1.5, 2.0, 2.6]
    v = [simulate_fall(BALL, h).v_impact * (1 - eta_true) for h in hs]
    df = pd.DataFrame({"ball_kg": BALL.mass, "height_m": hs, "v_measured_mps": v})
    fit = fit_tube(df, RIG)
    assert fit.eta.value == pytest.approx(eta_true, abs=1e-6)
    assert fit.eta.label is Label.CALIBRATED
    assert fit.rmse_post < fit.rmse_pre / 100


def test_py_fit_recovers_known_value():
    py_true = 2.2 * 76e6
    plate = plate_from_material(BAMBU_PLA_BASIC, "XY", 3e-3, RIG.ring_radius, "clamped")
    law = ThorntonLaw(effective_modulus(210e9, 0.3, plate.E, plate.nu), BALL.radius, py_true)
    vs = [4.0, 5.5, 6.5]
    dents = [simulate_impact(BALL, v, plate, law, "2dof", n_per_segment=80).dent for v in vs]
    df = pd.DataFrame({"ball_kg": BALL.mass, "height_m": [1.0] * 3, "v_measured_mps": vs,
                       "thickness_m": 3e-3, "orientation": "XY", "dent_m": dents})
    fit = fit_py(df, RIG, FallParams(), PY_PRE)
    assert fit.py.value == pytest.approx(py_true, rel=0.05)
    assert fit.rmse_post < fit.rmse_pre


def test_loss_ratio_on_known_virtual_data():
    """참값 E50 = 1.00 J(기준) vs 0.70 J(분할) → 손실률 0.30."""
    rng = np.random.default_rng(7)
    slope = 12.0

    def sample(e50, n=600):
        E = rng.uniform(0.2, 1.8, n)
        p = 1 / (1 + np.exp(-slope * (E - e50)))
        return E, rng.random(n) < p

    E_ref, f_ref = sample(1.00)
    E_g, f_g = sample(0.70)
    ref = logistic_e50(E_ref, f_ref)
    grp = logistic_e50(E_g, f_g)
    assert ref.E50 == pytest.approx(1.00, abs=0.06) and grp.E50 == pytest.approx(0.70, abs=0.06)

    class G:  # loss_ratio 는 GroupResult 의 logistic/E50_bruceton 만 본다
        def __init__(self, lg):
            self.logistic, self.key, self.E50_bruceton = lg, {}, None

    lr = loss_ratio(G(grp), G(ref))
    assert lr.loss == pytest.approx(0.30, abs=0.07)
    assert lr.ci[0] < 0.30 < lr.ci[1] and lr.method == "delta(logistic)"


def test_clay_flags_out_of_tolerance_day():
    df = normalize(units.drop_table_to_si(pd.read_csv(DATA, comment="#")))
    out = check_clay(df, RIG)
    bad = out[out["test_date"] == "2026-03-04"]
    assert bad["clay_flag"].all() and bad["clay_msg"].str.contains("허용폭 밖").all()
    assert not out[out["test_date"] == "2026-03-02"]["clay_flag"].all()
    assert CLAY_TARGET_RP1.label is Label.LITERATURE


def test_full_run_on_virtual_data():
    df = units.drop_table_to_si(pd.read_csv(DATA, comment="#"))
    crit = FailureCriteria(("관통 균열", "조각 이탈", "잠금 풀림", "받침 탈락"), "2026-03-01")
    rep = run_calibration(df, crit, RIG, PY_PRE)
    assert rep.tube.eta.value == pytest.approx(0.030, abs=0.01)     # 생성 참값 0.030
    assert rep.py.py.value == pytest.approx(2.2 * 76e6, rel=0.25)   # 생성 참값 2.2Y
    assert len(rep.groups) == 9
    mono = next(g for g in rep.groups if g.key["config_type"] == "monolithic"
                and g.key["thickness_m"] == pytest.approx(3e-3))
    assert mono.E50.value == pytest.approx(0.62, abs=0.12)          # 생성 참값 0.62 J
    seam = next(g for g in rep.groups if g.key["impact_site"] == "seam"
                and g.key["config_type"] == "segmented_overlap")
    assert seam.E50.value == pytest.approx(0.34, abs=0.12)
    losses = {(l.key["config_type"], l.key["impact_site"]): l for l in rep.losses}
    assert losses[("segmented_overlap", "seam")].loss == pytest.approx(1 - 0.34 / 0.62, abs=0.2)
    assert not rep.errors.empty
    assert ("segmented_overlap", "center") in rep.ec_fits
