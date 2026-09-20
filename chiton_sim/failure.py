"""파손 판정과 불확실성 (PLAN §3-F).

- 참고 판정: Roark 판 중앙 굽힘응력(×Kt) vs 굽힘강도  → 문헌값 기반(보정 전)
- 주 판정:   판 흡수 에너지 E_abs vs 임계에너지 E_c(t) = C·tⁿ (구성·위치별 실측 적합) → 실측 보정 후
- 몬테카를로: TDS ± 범위 샘플링(±=1σ, 가정 A-02), 높이별 파손확률 곡선과 h50
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from .ball import Ball
from .contact import ThorntonLaw, effective_modulus
from .fall import FallParams, simulate_fall
from .impact import simulate_impact
from .materials import FilamentMaterial
from .plate import plate_from_material
from .provenance import NEEDS_MEASUREMENT, Basis, Label, Quantity, SimInputError, WarningLog


# ---------------------------------------------------------------------------
# 참고 판정
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReferenceJudgment:
    sigma: float          # 판정 응력 [Pa] (Kt 적용 후)
    strength: float       # 굽힘강도 [Pa]
    margin: float         # strength / sigma  (< 1 이면 파손)
    fail: bool
    basis: str = Basis.PRE.value


def reference_judgment(sigma: float, strength: Quantity) -> ReferenceJudgment:
    s = strength.require("굽힘강도")
    return ReferenceJudgment(sigma, s, s / sigma if sigma > 0 else math.inf, sigma > s)


# ---------------------------------------------------------------------------
# 주 판정: E_c(t) = C·tⁿ
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CriticalEnergyFit:
    """log E_c = log C + n log t 적합 결과 (구성·위치별)."""

    thicknesses: tuple[float, ...]
    C: float | None
    n: float | None
    se_log: float | None           # 예측 로그 표준오차(잔차)
    cov: np.ndarray | None = field(default=None, repr=False)   # (log C, n) 공분산
    single: tuple[float, float] | None = None                  # 두께 1개일 때 (t, E_c)

    def Ec(self, t: float) -> Quantity:
        if self.n is not None:
            return Quantity(self.C * t**self.n, "J", Label.CALIBRATED, None, "E_c = C·tⁿ 적합")
        if self.single is not None and math.isclose(t, self.single[0], rel_tol=1e-9):
            return Quantity(self.single[1], "J", Label.CALIBRATED, None, "측정 두께 1개 — 이 두께에서만 유효")
        return Quantity(None, "J", Label.UNVERIFIED, None, f"{NEEDS_MEASUREMENT}: 두께 지수 n 미정")

    def sample_log_Ec(self, t: float, rng: np.random.Generator, n: int) -> np.ndarray:
        """E_c(t) 의 로그 표본 (계수 공분산 + 잔차)."""
        if self.n is None:
            v = self.Ec(t).require("E_c")
            return np.full(n, math.log(v))
        x = np.array([1.0, math.log(t)])
        mean = math.log(self.C) + self.n * math.log(t)
        var = float(x @ self.cov @ x) + (self.se_log or 0.0) ** 2
        return rng.normal(mean, math.sqrt(max(var, 0.0)), n)


def fit_critical_energy(thickness: np.ndarray, E_abs50: np.ndarray) -> CriticalEnergyFit:
    """두께별 임계 흡수에너지(E50 조건)로 C, n 을 적합한다."""
    t = np.asarray(thickness, float)
    E = np.asarray(E_abs50, float)
    if t.size == 0 or np.any(E <= 0) or np.any(t <= 0):
        raise SimInputError("양수 두께·에너지 데이터가 필요하다")
    uniq = np.unique(t)
    if uniq.size == 1:
        return CriticalEnergyFit(tuple(uniq), None, None, None, single=(float(uniq[0]), float(np.exp(np.mean(np.log(E))))))
    lr = stats.linregress(np.log(t), np.log(E))
    x = np.log(t)
    resid = np.log(E) - (lr.intercept + lr.slope * x)
    dof = max(t.size - 2, 1)
    s2 = float(resid @ resid) / dof
    X = np.column_stack([np.ones_like(x), x])
    cov = s2 * np.linalg.inv(X.T @ X) if t.size > 2 else np.diag([lr.intercept_stderr**2, lr.stderr**2])
    return CriticalEnergyFit(tuple(uniq), math.exp(lr.intercept), lr.slope, math.sqrt(s2), cov)


@dataclass(frozen=True)
class MainJudgment:
    E_abs: float
    Ec: Quantity
    fail: bool | None     # None = 판정 불가(실측 필요)
    basis: str


def main_judgment(E_abs: float, fit: CriticalEnergyFit | None, t: float) -> MainJudgment:
    if fit is None:
        return MainJudgment(E_abs, Quantity(None, "J", Label.UNVERIFIED, None, NEEDS_MEASUREMENT), None,
                            "미확인·실측 보정 필요")
    Ec = fit.Ec(t)
    if not Ec.known:
        return MainJudgment(E_abs, Ec, None, NEEDS_MEASUREMENT)
    return MainJudgment(E_abs, Ec, E_abs > Ec.value, Basis.POST.value)


# ---------------------------------------------------------------------------
# 빠른 에너지 균형 모델 (Shivakumar E-B + Thornton 접촉, 판 질량 무시) — numpy 벡터화
# ---------------------------------------------------------------------------
def _hertz_F(d, Es, R):
    return (4.0 / 3.0) * Es * np.sqrt(R) * np.maximum(d, 0.0) ** 1.5


def _thornton_F_W(d, Es, R, py):
    dy = R * (np.pi * py / (2.0 * Es)) ** 2
    Fy = _hertz_F(dy, Es, R)
    k = (8.0 / 15.0) * Es * np.sqrt(R)
    el = d <= dy
    x = d - dy
    F = np.where(el, _hertz_F(d, Es, R), Fy + np.pi * py * R * x)
    W = np.where(el, k * np.maximum(d, 0.0) ** 2.5, k * dy**2.5 + Fy * x + 0.5 * np.pi * py * R * x**2)
    return F, W, dy, Fy


def _thornton_W_unload(dmax, Es, R, py):
    F, _, dy, Fy = _thornton_F_W(dmax, Es, R, py)
    plastic = dmax > dy
    Rp = np.where(plastic, (4.0 * Es / (3.0 * F)) * ((2.0 * F + Fy) / (2.0 * np.pi * py)) ** 1.5, R)
    dp = np.where(plastic, dmax - (3.0 * F / (4.0 * Es * np.sqrt(Rp))) ** (2.0 / 3.0), 0.0)
    return (8.0 / 15.0) * Es * np.sqrt(Rp) * (dmax - dp) ** 2.5


def k_bending_array(E, nu, t, a, bc):
    D = E * t**3 / (12.0 * (1.0 - nu**2))
    if bc == "clamped":
        return 16.0 * np.pi * D / a**2
    return 16.0 * np.pi * (1.0 + nu) * D / ((3.0 + nu) * a**2)


def roark_array(P, t, a, nu, r0, bc):
    r = np.where(r0 < 0.5 * t, np.sqrt(1.6 * r0**2 + t**2) - 0.675 * t, r0)
    base = 3.0 * P / (2.0 * np.pi * t**2)
    lt = np.where(r < a, (1.0 + nu) * np.log(a / r), 0.0)
    if bc == "clamped":
        return np.maximum(base * lt, base)
    return base * (lt + 1.0)


def energy_balance(E_in, Es, R, py, Kb, iters: int = 80):
    """E_in = W_load(δ) + F(δ)²/(2K_b) 를 δ 에 대해 이분법으로 푼다. 반환 (F_max, δ_max, E_abs)."""
    E_in, Es, py, Kb = np.broadcast_arrays(*(np.asarray(v, float) for v in (E_in, Es, py, Kb)))

    def total(d):
        F, W, _, _ = _thornton_F_W(d, Es, R, py)
        return W + F**2 / (2.0 * Kb)

    hi = np.full(E_in.shape, 1e-6)
    for _ in range(60):
        low = total(hi) < E_in
        if not low.any():
            break
        hi = np.where(low, hi * 2.0, hi)
    lo = np.zeros_like(hi)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        below = total(mid) < E_in
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    d = 0.5 * (lo + hi)
    F, W, _, _ = _thornton_F_W(d, Es, R, py)
    E_abs = W - _thornton_W_unload(d, Es, R, py)   # 판 질량 무시: 판 탄성에너지는 모두 반환
    return F, d, E_abs


# ---------------------------------------------------------------------------
# 몬테카를로
# ---------------------------------------------------------------------------
@dataclass
class MonteCarloResult:
    heights: np.ndarray
    p_fail: np.ndarray
    h50: float | None             # None = 격자 범위 안에서 50 % 를 지나지 않음
    criterion: str                # "reference" | "main"
    basis: str
    n_samples: int
    correction: np.ndarray        # 높이별 2DOF/E-B 보정비 (A-17)
    warnings: WarningLog


def _interp_h50(h: np.ndarray, p: np.ndarray) -> float | None:
    above = np.nonzero(p >= 0.5)[0]
    if above.size == 0:
        return None
    i = above[0]
    if i == 0:
        return float(h[0]) if p[0] == 0.5 else None
    return float(np.interp(0.5, [p[i - 1], p[i]], [h[i - 1], h[i]]))


def failure_probability_curve(
    ball: Ball,
    material: FilamentMaterial,
    orientation: str,
    t: float,
    a: float,
    bc: str,
    heights: np.ndarray,
    py: Quantity,
    Kt: float = 1.0,
    fall_params: FallParams = FallParams(),
    fit: CriticalEnergyFit | None = None,
    n: int = 2000,
    seed: int = 20260920,
) -> MonteCarloResult:
    """높이별 파손확률. fit 이 있으면 주 판정(E_abs vs E_c), 없으면 참고 판정(σ vs 굽힘강도)."""
    rng = np.random.default_rng(seed)
    props = material.props(orientation)
    nu = material.poisson.require("푸아송비")

    def normal_pos(q: Quantity) -> np.ndarray:
        mu = q.require()
        sd = q.sd or 0.0
        x = rng.normal(mu, sd, n) if sd > 0 else np.full(n, mu)
        return np.maximum(x, 1e-6 * mu)   # 0 이하 절단

    E_p = normal_pos(props.flex_modulus)
    sig_f = normal_pos(props.flex_strength)
    bm = ball.material
    E_b = rng.uniform(bm.E.low or bm.E.value, bm.E.high or bm.E.value, n)
    nu_b = rng.uniform(bm.nu.low or bm.nu.value, bm.nu.high or bm.nu.value, n)
    Es = effective_modulus(E_b, nu_b, E_p, nu)
    calibrated_py = py.label is Label.CALIBRATED
    # 보정 전: p_y = 1.6·Y, Y = 굽힘강도 표본 (A-05)
    py_s = np.full(n, py.require("p_y")) if calibrated_py else (py.require() / props.flex_strength.value) * sig_f
    Kb = k_bending_array(E_p, nu, t, a, bc)
    R = ball.radius

    # 명목값
    plate_nom = plate_from_material(material, orientation, t, a, bc)
    Es_nom = effective_modulus(bm.E.value, bm.nu.value, plate_nom.E, nu)
    law_nom = ThorntonLaw(Es_nom, R, py.require())
    log = WarningLog()
    log_Ec = fit.sample_log_Ec(t, rng, n) if fit is not None else None

    p_fail = np.empty(len(heights))
    corr = np.empty(len(heights))
    for i, h in enumerate(heights):
        fr = simulate_fall(ball, float(h), params=fall_params)
        E_in = fr.energy
        imp = simulate_impact(ball, fr.v_impact, plate_nom, law_nom, "2dof")
        log.extend(imp.warnings)
        F_nom, _, Eabs_nom = energy_balance(E_in, Es_nom, R, py.require(), plate_nom.k_bending())
        F, d, E_abs = energy_balance(E_in, Es, R, py_s, Kb)
        if fit is None:
            corr[i] = imp.F_plate_max / float(F_nom)
            sigma = Kt * roark_array(corr[i] * F, t, a, nu, np.sqrt(R * d), bc)
            p_fail[i] = np.mean(sigma > sig_f)
        else:
            corr[i] = imp.E_abs / float(Eabs_nom) if Eabs_nom > 0 else 1.0
            p_fail[i] = np.mean(np.log(np.maximum(corr[i] * E_abs, 1e-300)) > log_Ec)
    basis = Basis.POST.value if (fit is not None or calibrated_py or fall_params.basis is Basis.POST) else Basis.PRE.value
    return MonteCarloResult(np.asarray(heights, float), p_fail, _interp_h50(np.asarray(heights, float), p_fail),
                            "main" if fit is not None else "reference", basis, n, corr, log)
