"""실측 보정 (PLAN §3-G).

입력 CSV 는 실험 기록 단위(mm, g, %)다. units.drop_table_to_si() 로 SI 열을 만든 뒤 이 모듈에 넘긴다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.optimize import least_squares, minimize_scalar

from .ball import Ball, GuideTube
from .contact import ThorntonLaw, effective_modulus
from .fall import FallParams, simulate_fall
from .failure import CriticalEnergyFit, fit_critical_energy
from .impact import simulate_impact
from .materials import BAMBU_PLA_BASIC, FilamentMaterial, ORIENTATIONS
from .plate import plate_from_material
from .provenance import (
    NOT_ANALYZABLE, Basis, CalibrationBlockedError, Label, Quantity, Severity, SimInputError,
    WarningLog,
)
from .segments import (
    CONFIG_TYPES, FASTENER_TYPES, IMPACT_SITES, JOINT_TYPES, SiteCalibration, VENT_TYPES,
)

# ---------------------------------------------------------------------------
# CSV 스키마
# ---------------------------------------------------------------------------
REQUIRED_COLUMNS = (
    "specimen_id", "config_type", "overlap_mm", "n_segments", "lock", "joint_type",
    "thickness_mm", "orientation", "infill_pct", "fastener_type", "vent_type",
    "impact_site", "fold_cycles", "ball_g", "height_m",
    "v_measured_mps", "result", "failure_mode", "dent_mm", "bfd_mm", "clay_cal_mm",
)
OPTIONAL_COLUMNS = ("test_date", "v_rebound_mps")
_NONE = ("none", "", "nan", "-")
CATEGORICAL = {
    "config_type": CONFIG_TYPES,
    "impact_site": IMPACT_SITES,
    "orientation": ORIENTATIONS,
    "result": ("pass", "fail"),
    "joint_type": JOINT_TYPES + _NONE,
    "fastener_type": FASTENER_TYPES + _NONE,
    "vent_type": VENT_TYPES + _NONE,
}
NUMERIC_REQUIRED = ("overlap_mm", "n_segments", "thickness_mm", "infill_pct", "fold_cycles",
                    "ball_g", "height_m")
NUMERIC_OPTIONAL = ("v_measured_mps", "dent_mm", "bfd_mm", "clay_cal_mm", "v_rebound_mps")
_LOCK_TRUE = ("on", "true", "1", "yes", "y", "t")
_LOCK_FALSE = ("off", "false", "0", "no", "n", "f")


def validate_schema(df: pd.DataFrame) -> list[str]:
    """스키마 오류 목록(행 번호와 열 이름 포함). 비어 있으면 통과."""
    errs: list[str] = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        errs.append(f"필수 열 누락: {', '.join(missing)}")
        return errs
    for col, allowed in CATEGORICAL.items():
        vals = df[col].astype("object").where(df[col].notna(), "none").astype(str).str.strip().str.lower()
        allowed_lc = {a.lower() for a in allowed}
        for i, v in vals.items():
            if v not in allowed_lc:
                errs.append(f"{i + 2}행 {col}: 허용되지 않는 값 {v!r} (허용: {', '.join(allowed)})")
    lk = df["lock"].astype(str).str.strip().str.lower()
    for i, v in lk.items():
        if v not in _LOCK_TRUE + _LOCK_FALSE:
            errs.append(f"{i + 2}행 lock: on/off 로 적어야 한다 (받은 값 {v!r})")
    for col in NUMERIC_REQUIRED:
        bad = pd.to_numeric(df[col], errors="coerce").isna()
        for i in df.index[bad]:
            errs.append(f"{i + 2}행 {col}: 숫자가 필요하다 (받은 값 {df.loc[i, col]!r})")
    for col in NUMERIC_OPTIONAL:
        if col in df.columns:
            raw = df[col].astype("object").where(df[col].notna(), "").astype(str).str.strip().str.lower()
            blank = df[col].isna() | raw.isin(_NONE)
            bad = pd.to_numeric(df[col], errors="coerce").isna() & ~blank
            for i in df.index[bad]:
                errs.append(f"{i + 2}행 {col}: 숫자 또는 빈칸이어야 한다 (받은 값 {df.loc[i, col]!r})")
    return errs


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """문자열 정리, lock→bool, fail→bool. SI 변환은 units.drop_table_to_si 가 한다."""
    out = df.copy()
    for col in CATEGORICAL:
        if col in out.columns:
            out[col] = (out[col].astype("object").where(out[col].notna(), "none")
                        .astype(str).str.strip().str.lower())
    out["orientation"] = out["orientation"].str.upper()   # 재료 프리셋은 XY / Z 표기
    out["lock"] = out["lock"].astype(str).str.strip().str.lower().isin(_LOCK_TRUE)
    out["fail"] = out["result"].astype(str).str.strip().str.lower().eq("fail")
    for col in NUMERIC_REQUIRED + NUMERIC_OPTIONAL:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


# ---------------------------------------------------------------------------
# 파손 판정 기준 (보정 전제조건)
# ---------------------------------------------------------------------------
CRITERIA_SUGGESTIONS = ("관통 균열", "조각 이탈", "잠금 풀림", "받침 탈락")


@dataclass(frozen=True)
class FailureCriteria:
    items: tuple[str, ...] = ()
    created: str | None = None

    @property
    def empty(self) -> bool:
        return len([s for s in self.items if s.strip()]) == 0

    def to_json(self) -> str:
        return json.dumps({"criteria": list(self.items), "created": self.created},
                          ensure_ascii=False, indent=2)


def save_criteria(path: str | Path, items) -> FailureCriteria:
    c = FailureCriteria(tuple(items), datetime.now(timezone.utc).isoformat(timespec="seconds"))
    Path(path).write_text(c.to_json(), encoding="utf-8")
    return c


def load_criteria(path: str | Path) -> FailureCriteria:
    p = Path(path)
    if not p.exists():
        return FailureCriteria()
    d = json.loads(p.read_text(encoding="utf-8"))
    return FailureCriteria(tuple(d.get("criteria", [])), d.get("created"))


def require_criteria(criteria: FailureCriteria) -> None:
    if criteria is None or criteria.empty:
        raise CalibrationBlockedError(
            "파손 판정 기준이 비어 있다 — 실험 전에 기준을 입력·저장해야 보정을 실행할 수 있다"
        )


# ---------------------------------------------------------------------------
# 시험 장치
# ---------------------------------------------------------------------------
SRC_CLAY = (
    "NRC, Testing of Body Armor Materials: Phase III (2012), NIJ 점토 낙하 보정 — 63.5 mm 강구 5회, "
    "개별 19±3 mm, 평균 19±2 mm, https://www.nationalacademies.org/read/13390/chapter/6 ; "
    "구 질량 1043±5 g, 낙하 2.0 m 는 2차 자료 수준에서 확인. "
    "NIJ 0101.04 Addendum B 는 Roma Plastilina No.1 을 지정 배면재로 명시"
)
CLAY_TARGET_RP1 = Quantity(0.019, "m", Label.LITERATURE, SRC_CLAY, "RP1 기준 평균 압입 깊이")
CLAY_TOL_AVG_RP1 = Quantity(0.002, "m", Label.LITERATURE, SRC_CLAY, "평균 허용폭 ±2 mm")
CLAY_TOL_IND_RP1 = Quantity(0.003, "m", Label.LITERATURE, SRC_CLAY, "개별 허용폭 ±3 mm")


@dataclass(frozen=True)
class RigSetup:
    ring_radius: float                      # m
    bc: str = "clamped"
    tube: GuideTube | None = None
    material: FilamentMaterial = BAMBU_PLA_BASIC
    clay_target: Quantity = CLAY_TARGET_RP1
    clay_tol_avg: Quantity = CLAY_TOL_AVG_RP1
    clay_tol_ind: Quantity = CLAY_TOL_IND_RP1


def _ball(row) -> Ball:
    return Ball.from_mass(float(row["ball_kg"]))


def _row_velocity(row, rig: RigSetup, params: FallParams) -> float:
    v = row.get("v_measured_mps")
    if v is not None and not (isinstance(v, float) and math.isnan(v)):
        return float(v)
    return simulate_fall(_ball(row), float(row["height_m"]), rig.tube, params).v_impact


def _row_energy(row, rig: RigSetup, params: FallParams) -> float:
    return 0.5 * float(row["ball_kg"]) * _row_velocity(row, rig, params) ** 2


# ---------------------------------------------------------------------------
# 관 손실 적합
# ---------------------------------------------------------------------------
@dataclass
class TubeFit:
    eta: Quantity
    K_tube: Quantity
    n: int
    rmse_pre: float
    rmse_post: float
    warnings: WarningLog

    @property
    def params(self) -> FallParams:
        return FallParams(K_tube=self.K_tube, eta_wall=self.eta)


def fit_tube(df: pd.DataFrame, rig: RigSetup, fit_K: bool = False) -> TubeFit:
    """실측 속도로 벽 손실률 η(와 선택적으로 K_tube)를 적합한다."""
    log = WarningLog()
    rows = df[df["v_measured_mps"].notna()]
    if rows.empty:
        raise SimInputError("v_measured_mps 실측값이 없어 관 손실을 적합할 수 없다")
    vm = rows["v_measured_mps"].to_numpy(float)

    def model_v(K: float) -> np.ndarray:
        p = FallParams(K_tube=Quantity(K, "-", Label.CALIBRATED))
        return np.array([simulate_fall(_ball(r), float(r["height_m"]), rig.tube, p).v_impact
                         for _, r in rows.iterrows()])

    v0 = model_v(1.0)
    K_val, K_label = 1.0, Label.ASSUMPTION
    if fit_K:
        if rows["height_m"].nunique() < 3:
            log.add("K_identifiability", Severity.WARNING,
                    "높이 수준이 3개 미만이라 K_tube 와 η 를 함께 적합할 식별성이 부족하다 — η 만 적합한다")
        else:
            def resid(p):
                K, eta = math.exp(p[0]), p[1]
                return model_v(K) * (1 - eta) - vm
            sol = least_squares(resid, [0.0, 0.0], bounds=([math.log(0.05), -0.5], [math.log(50.0), 0.9]))
            K_val, K_label = math.exp(sol.x[0]), Label.CALIBRATED
            v0 = model_v(K_val)
    scale = float(vm @ v0 / (v0 @ v0))        # 최소제곱 해 (선형)
    eta = 1.0 - scale
    rmse_pre = float(np.sqrt(np.mean((v0 - vm) ** 2)))
    rmse_post = float(np.sqrt(np.mean((v0 * scale - vm) ** 2)))
    if not -0.5 < eta < 0.9:
        log.add("eta_range", Severity.WARNING, f"적합된 손실률 η = {eta:.3f} 가 비현실적이다 — 데이터 확인 필요")
    return TubeFit(
        Quantity(eta, "-", Label.CALIBRATED, None, "실측 속도 최소제곱"),
        Quantity(K_val, "-", K_label, None, "K_tube" + ("(적합)" if K_label is Label.CALIBRATED else "(기본 1.0)")),
        len(rows), rmse_pre, rmse_post, log,
    )


# ---------------------------------------------------------------------------
# 판 강성 적합 (정적 압입 시험) — 경계조건 가정을 없앤다
# ---------------------------------------------------------------------------
@dataclass
class PlateStiffnessFit:
    kb: Quantity            # N/m
    km: Quantity | None     # N/m³ (막 항을 같이 적합했을 때)
    r2: float
    n: int
    rmse: float             # N
    warnings: WarningLog


def fit_plate_stiffness(deflection_m, load_N, with_membrane: bool = False) -> PlateStiffnessFit:
    """정적 압입 시험(하중-처짐)으로 K_b (필요하면 K_m 까지) 를 적합한다.

    모델: P = K_b·w + K_m·w³ (원점을 지나는 최소제곱). 경계조건을 가정하지 않으므로
    '고정단이냐 단순지지냐'에서 오는 가장 큰 불확실성이 제거된다.
    """
    log = WarningLog()
    w = np.asarray(deflection_m, float)
    P = np.asarray(load_N, float)
    if w.size != P.size or w.size < 2:
        raise SimInputError("처짐과 하중을 2점 이상, 같은 개수로 입력해야 한다")
    if np.any(w <= 0) or np.any(P < 0):
        raise SimInputError("처짐은 양수, 하중은 0 이상이어야 한다")
    X = np.column_stack([w, w**3]) if with_membrane else w.reshape(-1, 1)
    coef, *_ = np.linalg.lstsq(X, P, rcond=None)
    pred = X @ coef
    ss_res = float(((P - pred) ** 2).sum())
    ss_tot = float(((P - P.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = math.sqrt(ss_res / w.size)
    kb = float(coef[0])
    km = float(coef[1]) if with_membrane else None
    if kb <= 0:
        raise SimInputError("적합된 판 강성이 0 이하다 — 데이터를 확인해야 한다")
    if with_membrane and km is not None and km < 0:
        log.add("km_negative", Severity.WARNING,
                "적합된 막 강성이 음수다 — 처짐 범위가 좁거나 잡음이 크다. 막 항 없이 적합하는 편이 낫다")
    if w.size < 4:
        log.add("stiffness_n", Severity.INFO, f"{w.size}점으로 적합했다 — 5점 이상을 권장한다")
    return PlateStiffnessFit(
        Quantity(kb, "N/m", Label.CALIBRATED, None, "정적 압입 시험 최소제곱"),
        Quantity(km, "N/m^3", Label.CALIBRATED, None, "정적 압입 시험 최소제곱") if km is not None else None,
        r2, int(w.size), rmse, log,
    )


# ---------------------------------------------------------------------------
# p_y 적합 (압흔 깊이)
# ---------------------------------------------------------------------------
@dataclass
class PyFit:
    py: Quantity
    py_pre: Quantity
    n: int
    rmse_pre: float
    rmse_post: float
    warnings: WarningLog


FIT_MAX_CONDITIONS = 24     # p_y 적합에 쓰는 조건 수 상한(속도)


def _dent_model(py: float, conds: list[tuple], rig: RigSetup, mode: str, n_seg: int = 40,
                rtol: float = 1e-7, step_div: int = 120) -> np.ndarray:
    out = []
    for mass, v, t, orient in conds:
        ball = Ball.from_mass(mass)
        plate = plate_from_material(rig.material, orient, t, rig.ring_radius, rig.bc)
        law = ThorntonLaw(effective_modulus(ball.material.E.require(), ball.material.nu.require(),
                                            plate.E, plate.nu), ball.radius, py)
        out.append(simulate_impact(ball, v, plate, law, mode, n_per_segment=n_seg,
                                   rtol=rtol, step_div=step_div).dent)
    return np.array(out)


def fit_py(df: pd.DataFrame, rig: RigSetup, params: FallParams, py_pre: Quantity,
           mode: str = "2dof") -> PyFit:
    """실측 압흔 깊이로 한계 접촉압 p_y 를 적합한다."""
    log = WarningLog()
    rows = df[df["dent_m"].notna()] if "dent_m" in df.columns else df.iloc[0:0]
    if rows.empty:
        raise SimInputError("dent_mm 실측값이 없어 p_y 를 적합할 수 없다")
    conds, dents = [], []
    for _, r in rows.iterrows():
        conds.append((float(r["ball_kg"]), _row_velocity(r, rig, params),
                      float(r["thickness_m"]), str(r["orientation"]).upper()))
        dents.append(float(r["dent_m"]))
    # 같은 조건은 한 번만 계산하고, 조건 수가 많으면 고르게 솎아낸다(속도)
    uniq = sorted(set(conds))
    if len(uniq) > FIT_MAX_CONDITIONS:
        pick = np.linspace(0, len(uniq) - 1, FIT_MAX_CONDITIONS).round().astype(int)
        keep = {uniq[i] for i in pick}
        sel = [i for i, c in enumerate(conds) if c in keep]
        log.add("py_subsample", Severity.INFO,
                f"조건 {len(uniq)}개 중 {FIT_MAX_CONDITIONS}개만 써서 p_y 를 적합했다(속도)")
        conds = [conds[i] for i in sel]
        dents = [dents[i] for i in sel]
        uniq = sorted(keep)
    idx = [uniq.index(c) for c in conds]
    dents = np.array(dents)

    def rmse(py: float) -> float:
        pred = _dent_model(py, uniq, rig, mode)[idx]
        return float(np.sqrt(np.mean((pred - dents) ** 2)))

    p0 = py_pre.require("p_y 초기값")
    res = minimize_scalar(lambda lp: rmse(math.exp(lp)),
                          bounds=(math.log(0.2 * p0), math.log(6.0 * p0)),
                          method="bounded", options={"xatol": 2e-3})
    py = math.exp(res.x)
    if not (0.25 * p0 < py < 5.0 * p0):
        log.add("py_range", Severity.WARNING,
                f"적합된 p_y = {py/1e6:.0f} MPa 가 초기값의 0.25–5배 밖이다 — 데이터·모드 확인 필요")
    return PyFit(Quantity(py, "Pa", Label.CALIBRATED, None, "실측 압흔 최소제곱"),
                 py_pre, len(rows), rmse(p0), rmse(py), log)


# ---------------------------------------------------------------------------
# Bruceton 계단법 (Dixon–Mood)
# ---------------------------------------------------------------------------
SRC_DIXON_MOOD = (
    "W.J. Dixon & A.M. Mood, J. Am. Stat. Assoc. 43:109–126 (1948) (원문 유료). "
    "식은 M.T. Chao & C.D. Fuh, Statistica Sinica 11:1–21 (2001) 식 (5.1)·(5.4) 로 확인: "
    "μ = x' + d(A/N ± ½), σ = 1.620 d((NB − A²)/N² + 0.029)"
)


@dataclass
class BrucetonResult:
    mean: float
    sd: float
    N: int
    A: float
    B: float
    M: float
    event: str            # 분석에 쓴 덜 빈번한 사건: "fail" | "pass"
    d: float
    x0: float
    n_used: int
    n_discarded: int
    warnings: WarningLog


def bruceton(levels, fails, d: float | None = None, discard_run_in: bool = True,
             origin: float | None = None) -> BrucetonResult:
    """ASTM D5420 방식 계단법의 Dixon–Mood 평균·표준편차.

    levels: 시험 수준(높이 등) 순서열, fails: 파손 여부(True=파손) 순서열
    discard_run_in: 첫 반응 변화 한 단계 전부터 센다(문헌 관행).
    """
    log = WarningLog()
    x = np.asarray(levels, float)
    f = np.asarray(fails, bool)
    if x.size != f.size or x.size == 0:
        raise SimInputError("levels 와 fails 의 길이가 같아야 한다")
    start = 0
    if discard_run_in:
        chg = np.nonzero(f != f[0])[0]
        if chg.size == 0:
            raise SimInputError("반응 변화가 없어 계단법 해석을 할 수 없다(모두 pass 또는 모두 fail)")
        start = max(int(chg[0]) - 1, 0)
    xu, fu = x[start:], f[start:]
    levels_sorted = np.unique(x)
    if d is None:
        diffs = np.diff(levels_sorted)
        d = float(np.min(diffs)) if diffs.size else 0.0
    if d <= 0:
        raise SimInputError("계단 간격 d 를 정할 수 없다(수준이 하나뿐)")
    spacing = (levels_sorted - levels_sorted[0]) / d
    if np.max(np.abs(spacing - np.round(spacing))) > 1e-6:
        log.add("uneven_levels", Severity.WARNING, "시험 수준 간격이 일정하지 않다 — Dixon–Mood 가정 위반")

    n_fail, n_pass = int(fu.sum()), int((~fu).sum())
    use_fail = n_fail <= n_pass
    sel = fu if use_fail else ~fu
    sign = -0.5 if use_fail else 0.5
    if sel.sum() == 0:
        raise SimInputError("덜 빈번한 사건이 없어 해석할 수 없다")
    x0 = origin if origin is not None else float(np.min(xu[sel]))
    i = np.round((xu[sel] - x0) / d)
    N = int(sel.sum())
    A = float(i.sum())
    B = float((i**2).sum())
    M = (N * B - A**2) / N**2
    mean = x0 + d * (A / N + sign)
    sd = 1.620 * d * (M + 0.029)
    if M <= 0.3:
        log.add("bruceton_M", Severity.WARNING,
                f"M = {M:.2f} ≤ 0.3: Dixon–Mood 표준편차 추정의 신뢰도가 낮다")
    if xu.size < 20:
        log.add("bruceton_n", Severity.WARNING,
                f"유효 시험 {xu.size}회 < 20회: 계단법은 조합당 20–30회가 필요하다")
    return BrucetonResult(mean, sd, N, A, B, M, "fail" if use_fail else "pass", d, x0,
                          int(xu.size), int(start), log)


# ---------------------------------------------------------------------------
# 로지스틱 회귀
# ---------------------------------------------------------------------------
@dataclass
class LogisticResult:
    E50: float | None
    se: float | None
    ci: tuple[float, float] | None
    b0: float | None
    b1: float | None
    cov: np.ndarray | None
    n: int
    warnings: WarningLog


def logistic_e50(energy, fail, alpha: float = 0.05) -> LogisticResult:
    """fail ~ logit(b0 + b1 E) 를 적합해 E50 = −b0/b1 과 델타법 CI 를 낸다."""
    log = WarningLog()
    E = np.asarray(energy, float)
    y = np.asarray(fail, float)
    n = E.size
    if np.unique(y).size < 2:
        log.add("logit_one_class", Severity.WARNING, "모두 pass 또는 모두 fail — 로지스틱 추정 불가")
        return LogisticResult(None, None, None, None, None, None, n, log)
    if E[y == 1].size and E[y == 0].size and E[y == 0].max() < E[y == 1].min():
        log.add("logit_separation", Severity.WARNING,
                "완전 분리(모든 파손이 모든 비파손보다 높은 에너지) — 로지스틱 추정 불가")
        return LogisticResult(None, None, None, None, None, None, n, log)
    X = sm.add_constant(E)
    try:
        res = sm.GLM(y, X, family=sm.families.Binomial()).fit()
    except Exception as exc:  # statsmodels 수렴 실패
        log.add("logit_fail", Severity.WARNING, f"로지스틱 적합 실패: {exc}")
        return LogisticResult(None, None, None, None, None, None, n, log)
    b0, b1 = float(res.params[0]), float(res.params[1])
    cov = np.asarray(res.cov_params(), float)
    if b1 <= 0:
        log.add("logit_slope", Severity.WARNING, "에너지가 커질수록 파손이 늘어나는 관계가 아니다 — 결과 해석 주의")
        return LogisticResult(None, None, None, b0, b1, cov, n, log)
    e50 = -b0 / b1
    grad = np.array([-1.0 / b1, b0 / b1**2])
    se = float(math.sqrt(max(grad @ cov @ grad, 0.0)))
    z = stats.norm.ppf(1 - alpha / 2)
    return LogisticResult(e50, se, (e50 - z * se, e50 + z * se), b0, b1, cov, n, log)


# ---------------------------------------------------------------------------
# 그룹 분석
# ---------------------------------------------------------------------------
GROUP_KEYS_DEFAULT = ("config_type", "impact_site", "fold_cycles", "thickness_m")


@dataclass
class GroupResult:
    key: dict
    n: int
    bruceton: BrucetonResult | None
    h50: float | None
    E50_bruceton: float | None
    logistic: LogisticResult
    warnings: WarningLog
    ball_kg: float | None = None   # 그룹 안에서 구슬이 하나일 때만

    @property
    def E50(self) -> Quantity:
        if self.logistic.E50 is not None:
            return Quantity(self.logistic.E50, "J", Label.CALIBRATED, None, "로지스틱 E50")
        if self.E50_bruceton is not None:
            return Quantity(self.E50_bruceton, "J", Label.CALIBRATED, None, "Bruceton E50")
        return Quantity(None, "J", Label.UNVERIFIED, None, "E50 추정 불가")


def analyze_groups(df: pd.DataFrame, rig: RigSetup, params: FallParams,
                   keys: tuple[str, ...] = GROUP_KEYS_DEFAULT) -> list[GroupResult]:
    out: list[GroupResult] = []
    for kv, g in df.groupby(list(keys), dropna=False, sort=False):
        kv = kv if isinstance(kv, tuple) else (kv,)
        log = WarningLog()
        br: BrucetonResult | None = None
        h50 = E50_br = None
        if g["ball_kg"].nunique() > 1:
            log.add("mixed_balls", Severity.WARNING, "한 그룹에 서로 다른 구슬 질량이 섞여 있다 — 계단법 생략")
        else:
            try:
                br = bruceton(g["height_m"].to_numpy(float), g["fail"].to_numpy(bool))
                log.extend(br.warnings)
                h50 = br.mean
                ball = Ball.from_mass(float(g["ball_kg"].iloc[0]))
                E50_br = simulate_fall(ball, h50, rig.tube, params).energy
            except SimInputError as exc:
                log.add("bruceton_fail", Severity.WARNING, f"계단법 해석 불가: {exc}")
        energies = np.array([_row_energy(r, rig, params) for _, r in g.iterrows()])
        lg = logistic_e50(energies, g["fail"].to_numpy(bool))
        log.extend(lg.warnings)
        bk = float(g["ball_kg"].iloc[0]) if g["ball_kg"].nunique() == 1 else None
        out.append(GroupResult(dict(zip(keys, kv)), len(g), br, h50, E50_br, lg, log, bk))
    return out


# ---------------------------------------------------------------------------
# 분할 손실률
# ---------------------------------------------------------------------------
@dataclass
class LossRatio:
    key: dict
    ref_key: dict
    loss: float | None
    ci: tuple[float, float] | None
    method: str
    loss_bruceton: float | None
    warnings: WarningLog


def loss_ratio(group: GroupResult, ref: GroupResult, alpha: float = 0.05) -> LossRatio:
    """분할 손실률 L = 1 − E50(구성, 위치)/E50(monolithic, center), 95 % CI 는 로그비 델타법."""
    log = WarningLog()
    lb = None
    if group.E50_bruceton and ref.E50_bruceton:
        lb = 1.0 - group.E50_bruceton / ref.E50_bruceton
    a, b = group.logistic, ref.logistic
    if a.E50 is None or b.E50 is None or a.se is None or b.se is None or a.E50 <= 0 or b.E50 <= 0:
        log.add("loss_ci", Severity.WARNING, "로지스틱 E50 이 없어 손실률 신뢰구간을 낼 수 없다")
        return LossRatio(group.key, ref.key, lb, None, "bruceton", lb, log)
    log_r = math.log(a.E50) - math.log(b.E50)
    sd = math.sqrt((a.se / a.E50) ** 2 + (b.se / b.E50) ** 2)
    z = stats.norm.ppf(1 - alpha / 2)
    hi_r, lo_r = math.exp(log_r + z * sd), math.exp(log_r - z * sd)
    return LossRatio(group.key, ref.key, 1.0 - math.exp(log_r), (1.0 - hi_r, 1.0 - lo_r),
                     "delta(logistic)", lb, log)


def bootstrap_loss_ratio(energy_g, fail_g, energy_ref, fail_ref, n_resamples: int = 300,
                         seed: int = 20260920) -> tuple[float, float] | None:
    """참고용 부트스트랩 CI. 계단법의 순서 의존성을 무시한다는 한계가 있다."""
    rng = np.random.default_rng(seed)
    idx_g = np.arange(len(energy_g))
    idx_r = np.arange(len(energy_ref))

    def stat(ig, ir):
        a = logistic_e50(np.asarray(energy_g)[ig.astype(int)], np.asarray(fail_g)[ig.astype(int)])
        b = logistic_e50(np.asarray(energy_ref)[ir.astype(int)], np.asarray(fail_ref)[ir.astype(int)])
        if a.E50 is None or b.E50 is None or b.E50 <= 0:
            return np.nan
        return 1.0 - a.E50 / b.E50

    try:
        res = stats.bootstrap((idx_g, idx_r), stat, vectorized=False, paired=False,
                              n_resamples=n_resamples, random_state=rng, method="percentile")
    except Exception:
        return None
    lo, hi = float(res.confidence_interval.low), float(res.confidence_interval.high)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    return lo, hi


def loss_table(groups: list[GroupResult]) -> list[LossRatio]:
    """monolithic·center 를 같은 두께·접힘 조건에서 찾아 기준선으로 삼는다."""
    out = []
    for g in groups:
        if g.key.get("config_type") == "monolithic" and g.key.get("impact_site") == "center":
            continue
        ref = next((r for r in groups
                    if r.key.get("config_type") == "monolithic" and r.key.get("impact_site") == "center"
                    and r.key.get("thickness_m") == g.key.get("thickness_m")
                    and r.key.get("fold_cycles") == g.key.get("fold_cycles")), None)
        if ref is None:
            ref = next((r for r in groups if r.key.get("config_type") == "monolithic"
                        and r.key.get("impact_site") == "center"), None)
        if ref is None:
            continue
        out.append(loss_ratio(g, ref))
    return out


# ---------------------------------------------------------------------------
# 접힘 횟수 추세
# ---------------------------------------------------------------------------
@dataclass
class FoldTrend:
    config_type: str
    impact_site: str
    folds: np.ndarray
    E50: np.ndarray
    slope: float | None
    slope_ci: tuple[float, float] | None
    label: str
    warnings: WarningLog


def fold_trend(groups: list[GroupResult], config_type: str, impact_site: str,
               thickness: float | None = None) -> FoldTrend:
    log = WarningLog()
    sel = [g for g in groups
           if g.key.get("config_type") == config_type and g.key.get("impact_site") == impact_site
           and (thickness is None or g.key.get("thickness_m") == thickness)
           and g.E50.known]
    sel.sort(key=lambda g: g.key.get("fold_cycles", 0))
    folds = np.array([float(g.key.get("fold_cycles", 0)) for g in sel])
    e50 = np.array([g.E50.value for g in sel])
    if np.unique(folds).size < 2:
        log.add("fold_data", Severity.WARNING, "접힘 수준이 2개 미만이라 추세를 낼 수 없다")
        return FoldTrend(config_type, impact_site, folds, e50, None, None, NOT_ANALYZABLE, log)
    lr = stats.linregress(folds, e50)
    ci = None
    if folds.size > 2:
        t = stats.t.ppf(0.975, folds.size - 2)
        ci = (lr.slope - t * lr.stderr, lr.slope + t * lr.stderr)
    else:
        log.add("fold_ci", Severity.INFO, "접힘 수준이 2개라 기울기 신뢰구간은 낼 수 없다")
    return FoldTrend(config_type, impact_site, folds, e50, float(lr.slope), ci, NOT_ANALYZABLE, log)


# ---------------------------------------------------------------------------
# 배면 점토 검사
# ---------------------------------------------------------------------------
def check_clay(df: pd.DataFrame, rig: RigSetup) -> pd.DataFrame:
    """점토 보정 기준을 벗어난 행(또는 날)의 bfd 에 경고를 붙인다. bfd 는 비교 지표로만 쓴다."""
    out = df.copy()
    target = rig.clay_target.require("점토 기준값")
    tol_i = rig.clay_tol_ind.require("개별 허용폭")
    tol_a = rig.clay_tol_avg.require("평균 허용폭")
    flag = pd.Series(False, index=out.index)
    msg = pd.Series("", index=out.index)
    cal = out.get("clay_cal_m")
    if cal is None:
        out["clay_flag"] = True
        out["clay_msg"] = "점토 보정값 없음 — bfd 비교 불가"
        return out
    bad_ind = cal.notna() & ((cal - target).abs() > tol_i)
    flag |= bad_ind
    msg[bad_ind] = "개별 점토 보정값이 허용폭 밖"
    missing = cal.isna() & out.get("bfd_m", pd.Series(np.nan, index=out.index)).notna()
    flag |= missing
    msg[missing] = "점토 보정값 없음"
    if "test_date" in out.columns:
        for day, g in out.groupby("test_date"):
            c = g["clay_cal_m"].dropna()
            if c.empty:
                continue
            if abs(c.mean() - target) > tol_a:
                flag.loc[g.index] = True
                msg.loc[g.index] = f"{day}: 그날 점토 평균이 허용폭 밖 ({c.mean():.4f} m)"
    out["clay_flag"] = flag
    out["clay_msg"] = msg
    return out


# ---------------------------------------------------------------------------
# 보정 전/후 오차표
# ---------------------------------------------------------------------------
def error_table(tube: TubeFit | None, py: PyFit | None) -> pd.DataFrame:
    rows = []
    if tube is not None:
        rows.append({"항목": "충돌 속도 v [m/s]", "n": tube.n,
                     "RMSE 보정 전": tube.rmse_pre, "RMSE 보정 후": tube.rmse_post,
                     "비고": f"η = {tube.eta.value:.4f}, K_tube = {tube.K_tube.value:.3g}"})
    if py is not None:
        rows.append({"항목": "압흔 깊이 [m]", "n": py.n,
                     "RMSE 보정 전": py.rmse_pre, "RMSE 보정 후": py.rmse_post,
                     "비고": f"p_y = {py.py.value/1e6:.0f} MPa (초기값 {py.py_pre.value/1e6:.0f} MPa)"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 임계에너지 적합과 위치별 보정값
# ---------------------------------------------------------------------------
def critical_energy_fits(groups: list[GroupResult], rig: RigSetup, py: Quantity,
                         mode: str = "2dof") -> dict[tuple[str, str], CriticalEnergyFit]:
    """(구성, 위치)별로 E_c(t) = C·tⁿ 을 적합한다. E50 조건에서 모델이 계산한 흡수에너지를 쓴다."""
    buckets: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for g in groups:
        if not g.E50.known or g.ball_kg is None or "thickness_m" not in g.key:
            continue
        t = float(g.key["thickness_m"])
        key = (g.key["config_type"], g.key["impact_site"])
        ball = Ball.from_mass(g.ball_kg)
        v = math.sqrt(2 * g.E50.value / ball.mass)
        plate = plate_from_material(rig.material, "XY", t, rig.ring_radius, rig.bc)
        law = ThorntonLaw(effective_modulus(ball.material.E.require(), ball.material.nu.require(),
                                            plate.E, plate.nu), ball.radius, py.require())
        imp = simulate_impact(ball, v, plate, law, mode, n_per_segment=80)
        buckets.setdefault(key, []).append((t, imp.E_abs))
    return {k: fit_critical_energy(np.array([t for t, _ in v]), np.array([e for _, e in v]))
            for k, v in buckets.items() if v}


def site_calibrations(groups: list[GroupResult]) -> dict[tuple, SiteCalibration]:
    """segments.assess_site 에 넘길 (구성, 위치, 접힘, 두께) → SiteCalibration."""
    by_center = {(g.key["config_type"], g.key.get("fold_cycles"), g.key.get("thickness_m")): g
                 for g in groups if g.key.get("impact_site") == "center"}
    out = {}
    for g in groups:
        c = by_center.get((g.key["config_type"], g.key.get("fold_cycles"), g.key.get("thickness_m")))
        out[(g.key["config_type"], g.key["impact_site"], g.key.get("fold_cycles"),
             g.key.get("thickness_m"))] = SiteCalibration(
            E50=g.E50 if g.E50.known else None,
            E50_center=c.E50 if (c is not None and c.E50.known) else None,
        )
    return out


# ---------------------------------------------------------------------------
# 전체 실행
# ---------------------------------------------------------------------------
@dataclass
class CalibrationReport:
    tube: TubeFit | None
    py: PyFit | None
    groups: list[GroupResult]
    losses: list[LossRatio]
    clay: pd.DataFrame
    errors: pd.DataFrame
    ec_fits: dict
    site_calibs: dict
    params: FallParams
    basis: str = Basis.POST.value
    warnings: WarningLog = field(default_factory=WarningLog)


def run_calibration(df_si: pd.DataFrame, criteria: FailureCriteria, rig: RigSetup,
                    py_pre: Quantity, fit_K: bool = False,
                    keys: tuple[str, ...] = GROUP_KEYS_DEFAULT) -> CalibrationReport:
    """CSV(SI 변환 완료) → 보정 결과 일괄 계산. 판정 기준이 비어 있으면 차단한다."""
    require_criteria(criteria)
    errs = validate_schema(df_si)
    if errs:
        raise SimInputError("CSV 스키마 오류:\n" + "\n".join(errs[:20]))
    df = normalize(df_si)
    log = WarningLog()

    unknown = sorted(set(df.loc[df["fail"], "failure_mode"].astype(str).str.strip()) - set(criteria.items) - set(_NONE))
    if unknown:
        log.add("criteria_mismatch", Severity.WARNING,
                f"판정 기준에 없는 failure_mode: {', '.join(unknown)}")

    tube = py = None
    params = FallParams()
    try:
        tube = fit_tube(df, rig, fit_K)
        params = tube.params
        log.extend(tube.warnings)
    except SimInputError as exc:
        log.add("no_velocity", Severity.INFO, f"관 손실 미보정: {exc}")
    try:
        py = fit_py(df, rig, params, py_pre)
        log.extend(py.warnings)
    except SimInputError as exc:
        log.add("no_dent", Severity.INFO, f"p_y 미보정: {exc}")
    py_q = py.py if py is not None else py_pre

    groups = analyze_groups(df, rig, params, keys)
    for g in groups:
        log.extend(g.warnings)
    losses = loss_table(groups)
    clay = check_clay(df, rig)
    ec = critical_energy_fits(groups, rig, py_q)
    return CalibrationReport(tube, py, groups, losses, clay, error_table(tube, py), ec,
                             site_calibrations(groups), params, Basis.POST.value, log)
