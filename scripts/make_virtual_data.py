"""가상(VIRTUAL) 낙하 시험 데이터 생성기 — 실측이 아니다.

계단법 시퀀스를 '참값' 로지스틱 곡선에서 뽑고, 속도·압흔은 모델에 잡음을 얹어 만든다.
생성 파일: data/sample_VIRTUAL_drop_tests.csv
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from chiton_sim.ball import Ball
from chiton_sim.contact import ThorntonLaw, effective_modulus
from chiton_sim.fall import FallParams, height_for_energy, simulate_fall
from chiton_sim.impact import simulate_impact
from chiton_sim.materials import BAMBU_PLA_BASIC
from chiton_sim.plate import plate_from_material
from chiton_sim.provenance import Label, Quantity

# 참값(가상)
ETA_TRUE = 0.030
PY_TRUE = 2.2 * 76e6
RING_R = 0.040
BALL = Ball.standard('3/4"')
STEP = 0.15          # 계단 간격 [m]
N_TRIALS = 24
SLOPE = 14.0         # 로지스틱 기울기 [1/J]

# (config, site, fold, thickness_m, overlap_mm, n_seg, lock, joint, E50_true[J])
GROUPS = [
    ("monolithic",        "center",           0,   3.0e-3, 0.0, 1, "off", "none",          0.62),
    ("monolithic",        "center",           0,   2.5e-3, 0.0, 1, "off", "none",          0.43),
    ("segmented_overlap", "center",           0,   3.0e-3, 5.0, 3, "on",  "print_in_place", 0.55),
    ("segmented_overlap", "center",           100, 3.0e-3, 5.0, 3, "on",  "print_in_place", 0.50),
    ("segmented_overlap", "center",           500, 3.0e-3, 5.0, 3, "on",  "print_in_place", 0.42),
    ("segmented_overlap", "seam",             0,   3.0e-3, 5.0, 3, "on",  "print_in_place", 0.34),
    ("segmented_overlap", "triple_junction",  0,   3.0e-3, 5.0, 3, "on",  "print_in_place", 0.27),
    ("segmented_butt",    "center",           0,   3.0e-3, 0.0, 3, "off", "tpu_hinge",      0.40),
    ("segmented_butt",    "seam",             0,   3.0e-3, 0.0, 3, "off", "tpu_hinge",      0.21),
]
MODES = {"center": "관통 균열", "seam": "잠금 풀림", "triple_junction": "조각 이탈"}
DATES = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05"]
BAD_CLAY_DATE = "2026-03-04"          # 이 날은 점토 보정이 기준을 벗어난다


def energy(h: float) -> float:
    p = FallParams(eta_wall=Quantity(ETA_TRUE, "-", Label.CALIBRATED))
    return simulate_fall(BALL, h, params=p).energy


def v_true(h: float) -> float:
    p = FallParams(eta_wall=Quantity(ETA_TRUE, "-", Label.CALIBRATED))
    return simulate_fall(BALL, h, params=p).v_impact


def dent_true(v: float, t: float) -> float:
    plate = plate_from_material(BAMBU_PLA_BASIC, "XY", t, RING_R, "clamped")
    law = ThorntonLaw(effective_modulus(210e9, 0.30, plate.E, plate.nu), BALL.radius, PY_TRUE)
    return simulate_impact(BALL, v, plate, law, "2dof", n_per_segment=60).dent


def main() -> None:
    rng = np.random.default_rng(20260920)
    rows = []
    sid = 0
    dent_cache: dict[tuple, float] = {}
    for gi, (cfg, site, fold, t, ovl, nseg, lock, joint, e50) in enumerate(GROUPS):
        # 시작 높이는 참값 E50 근처의 계단 격자점 (계단법 권장: 평균 근처에서 시작)
        p_true = FallParams(eta_wall=Quantity(ETA_TRUE, "-", Label.CALIBRATED))
        h = round(height_for_energy(BALL, e50, params=p_true) / STEP) * STEP
        for k in range(N_TRIALS):
            sid += 1
            h = min(max(h, 0.30), 3.0)
            E = energy(h)
            p_fail = 1.0 / (1.0 + math.exp(-SLOPE * (E - e50)))
            fail = bool(rng.random() < p_fail)
            v = v_true(h) * (1 + rng.normal(0, 0.005))
            date = DATES[(gi + k // 8) % len(DATES)]
            dent = ""
            if k % 3 == 0:
                key = (round(h, 3), t)
                if key not in dent_cache:
                    dent_cache[key] = dent_true(v, t)
                dent = round(dent_cache[key] * 1000 + rng.normal(0, 0.01), 3)
            clay = 22.6 if date == BAD_CLAY_DATE else round(float(rng.normal(19.0, 0.7)), 1)
            rows.append({
                "specimen_id": f"S{sid:03d}", "config_type": cfg, "overlap_mm": ovl,
                "n_segments": nseg, "lock": lock, "joint_type": joint,
                "thickness_mm": round(t * 1000, 2), "orientation": "XY", "infill_pct": 100,
                "fastener_type": "none", "vent_type": "none", "impact_site": site,
                "fold_cycles": fold, "ball_g": round(BALL.mass * 1000, 2), "height_m": round(h, 3),
                "v_measured_mps": round(v, 3), "result": "fail" if fail else "pass",
                "failure_mode": MODES.get(site, "관통 균열") if fail else "none",
                "dent_mm": dent, "bfd_mm": round(float(rng.normal(6.0 if cfg == "monolithic" else 8.0, 0.8)), 2),
                "clay_cal_mm": clay, "test_date": date, "v_rebound_mps": "",
            })
            h += -STEP if fail else STEP
    df = pd.DataFrame(rows)
    out = Path(__file__).resolve().parents[1] / "data" / "sample_VIRTUAL_drop_tests.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        f.write("# VIRTUAL DATA — 가상 데이터이며 실측이 아니다. 모델 시연·테스트 용도로만 쓴다.\n")
        f.write(f"# 생성: scripts/make_virtual_data.py, 참값 eta_wall={ETA_TRUE}, p_y={PY_TRUE/1e6:.0f} MPa, "
                f"링 내반경={RING_R*1000:.0f} mm, 고정단\n")
        df.to_csv(f, index=False)
    print(f"{out} 에 {len(df)}행 생성 (fail 비율 {df['result'].eq('fail').mean():.2f})")


if __name__ == "__main__":
    main()
