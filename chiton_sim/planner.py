"""실험 설계 보조 (PLAN §3-I)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from scipy import stats

from .ball import Ball, GuideTube, check_ball_in_tube, standard_balls
from .calibration import (  # noqa: F401  (UI 재노출)
    CRITERIA_SUGGESTIONS, FailureCriteria, load_criteria, require_criteria, save_criteria,
)
from .fall import H_MAX, H_MIN, FallParams, height_for_energy, simulate_fall
from .provenance import GuideTubeError, Severity, SimInputError, WarningLog

SRC_D5420_N = (
    "ASTM D5420 요약(Intertek): 계단법 최적 결과에는 최소 30 시편, "
    "https://intertek.com/polymers/testlopedia/gardner-impact"
)
RECOMMENDED_PER_COMBO = (20, 30)   # 조합당 권장 시험 횟수 (요청서 20–30, D5420 요약은 최소 30 권장)


# ---------------------------------------------------------------------------
# 동일 에너지 2조합
# ---------------------------------------------------------------------------
@dataclass
class EnergyOption:
    ball: Ball
    height: float
    v_impact: float
    energy: float


@dataclass
class EqualEnergyPair:
    target: float
    light: EnergyOption | None
    heavy: EnergyOption | None
    v_ratio: float | None
    warnings: WarningLog = field(default_factory=WarningLog)

    @property
    def usable(self) -> bool:
        return self.light is not None and self.heavy is not None


def energy_options(target_energy: float, tube: GuideTube | None = None,
                   params: FallParams = FallParams(), balls: list[Ball] | None = None,
                   height_bounds: tuple[float, float] = (H_MIN, H_MAX)) -> list[EnergyOption]:
    """목표 충돌 에너지를 낼 수 있는 (규격 강구, 높이) 조합."""
    out: list[EnergyOption] = []
    lo, hi = height_bounds
    for b in balls or standard_balls():
        if tube is not None:
            try:
                check_ball_in_tube(b, tube)
            except GuideTubeError:
                continue
        try:
            h = height_for_energy(b, target_energy, tube, params)
        except SimInputError:
            continue
        if not (lo <= h <= hi):
            continue
        r = simulate_fall(b, h, tube, params)
        out.append(EnergyOption(b, h, r.v_impact, r.energy))
    return out


def equal_energy_pair(target_energy: float, tube: GuideTube | None = None,
                      params: FallParams = FallParams(),
                      height_bounds: tuple[float, float] = (H_MIN, H_MAX)) -> EqualEnergyPair:
    """같은 에너지를 '가벼운 공·높은 높이'와 '무거운 공·낮은 높이'로 내는 두 조건을 제안한다."""
    log = WarningLog()
    opts = energy_options(target_energy, tube, params, height_bounds=height_bounds)
    if len(opts) < 2:
        log.add("no_pair", Severity.WARNING,
                f"{height_bounds[0]:.2f}–{height_bounds[1]:.2f} m 와 가이드관 조건에서 "
                f"목표 {target_energy:.3g} J 를 내는 조합이 2개 미만이다")
        return EqualEnergyPair(target_energy, None, None, None, log)
    opts.sort(key=lambda o: o.ball.mass)
    light, heavy = opts[0], opts[-1]
    ratio = light.v_impact / heavy.v_impact
    if ratio < 1.3:
        log.add("weak_contrast", Severity.INFO,
                f"두 조건의 속도비가 {ratio:.2f} 로 작다 — 속도 효과를 가리기 어렵다")
    return EqualEnergyPair(target_energy, light, heavy, ratio, log)


def velocity_effect_test(fail_light: int, n_light: int, fail_heavy: int, n_heavy: int,
                         alpha: float = 0.05) -> dict:
    """같은 에너지 두 조건의 파손 비율 차이 검정 (Fisher 정확검정)."""
    table = [[fail_light, n_light - fail_light], [fail_heavy, n_heavy - fail_heavy]]
    odds, p = stats.fisher_exact(table)
    return {
        "table": table, "odds_ratio": float(odds), "p_value": float(p),
        "verdict": "속도 효과 있음(유의)" if p < alpha else "속도 효과가 유의하지 않음",
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# 계단법 도우미
# ---------------------------------------------------------------------------
def staircase_next(height: float, failed: bool, step: float,
                   bounds: tuple[float, float] = (H_MIN, H_MAX)) -> float:
    """직전 결과로 다음 낙하 높이를 안내한다. 파손이면 한 단계 낮추고, 아니면 높인다."""
    if step <= 0:
        raise SimInputError("계단 크기는 양수여야 한다")
    nxt = height - step if failed else height + step
    lo, hi = bounds
    return min(max(nxt, lo), hi)


@dataclass
class StaircaseProgress:
    n: int
    reversals: int
    next_height: float | None
    warnings: WarningLog


def staircase_progress(heights, fails, step: float,
                       bounds: tuple[float, float] = (H_MIN, H_MAX)) -> StaircaseProgress:
    log = WarningLog()
    hs, fs = list(heights), list(fails)
    if len(hs) != len(fs):
        raise SimInputError("높이와 결과의 길이가 같아야 한다")
    rev = sum(1 for i in range(1, len(fs)) if fs[i] != fs[i - 1])
    nxt = staircase_next(hs[-1], bool(fs[-1]), step, bounds) if hs else None
    if len(hs) < RECOMMENDED_PER_COMBO[0]:
        log.add("n_low", Severity.INFO,
                f"{len(hs)}회 진행 — 계단법은 조합당 {RECOMMENDED_PER_COMBO[0]}–{RECOMMENDED_PER_COMBO[1]}회가 필요하다")
    if rev == 0 and len(hs) >= 4:
        log.add("no_reversal", Severity.WARNING, "아직 반전이 없다 — 시작 높이가 평균에서 멀 수 있다")
    if nxt is not None and nxt in bounds:
        log.add("bound", Severity.WARNING, f"다음 높이가 허용 범위 경계({nxt:.2f} m)에 걸렸다")
    return StaircaseProgress(len(hs), rev, nxt, log)


# ---------------------------------------------------------------------------
# 시편 수
# ---------------------------------------------------------------------------
def specimen_plan(configs, sites, folds, per_combo: tuple[int, int] = RECOMMENDED_PER_COMBO) -> pd.DataFrame:
    """구성 × 타격 위치 × 접힘 횟수 조합별 필요 시편 수."""
    rows = []
    for c in configs:
        for s in sites:
            for f in folds:
                if c == "monolithic" and s in ("seam", "triple_junction"):
                    continue
                rows.append({"config_type": c, "impact_site": s, "fold_cycles": f,
                             "최소 시편": per_combo[0], "권장 시편": per_combo[1]})
    df = pd.DataFrame(rows)
    if not df.empty:
        df.attrs["total_min"] = int(df["최소 시편"].sum())
        df.attrs["total_rec"] = int(df["권장 시편"].sum())
        df.attrs["note"] = f"계단법은 조합당 {per_combo[0]}–{per_combo[1]}회가 필요하다 ({SRC_D5420_N})"
    return df


# ---------------------------------------------------------------------------
# 곡면 헬멧 확인
# ---------------------------------------------------------------------------
def curvature_check(flat_predictions: dict, helmet_measurements: dict) -> pd.DataFrame:
    """평판 E50 예측과 헬멧 실측(소수 회)을 나란히 두고 차이를 '곡률·형상 효과'로 기록한다."""
    rows = []
    for key, flat in flat_predictions.items():
        meas = helmet_measurements.get(key)
        rows.append({
            "조건": " / ".join(str(k) for k in (key if isinstance(key, tuple) else (key,))),
            "평판 E50 [J]": flat,
            "헬멧 실측 E50 [J]": meas,
            "차이 [J]": None if meas is None else meas - flat,
            "비율": None if (meas is None or not flat) else meas / flat,
            "해석": "곡률·형상 효과" if meas is not None else "헬멧 실측 필요",
        })
    return pd.DataFrame(rows)
