"""구-평판 접촉: 탄성 Hertz(참고)와 Thornton(1997) 탄성-완전소성 (PLAN §3-B).

강구는 탄성, 소성은 판에서만 일어난다고 본다(A-06). 평판이므로 R = 구슬 반경.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.optimize import brentq

from .provenance import Severity, WarningLog

SRC_HERTZ_TC = (
    "A. He & J.S. Wettlaufer, Hertz beyond expectations, arXiv:1306.4952 (2013) "
    "— T = 2.8683 (M²/(R V E²))^(1/5)"
)
SRC_YIELD_16 = (
    "H.A. Burgoyne & C. Daraio, PRE 89, 032203 (2014) — yield onset p0 = 1.6·σy (von Mises), "
    "https://authors.library.caltech.edu/44661/1/PhysRevE.89.032203.pdf"
)
SRC_THORNTON = (
    "C. Thornton, J. Appl. Mech. 64(2):383–386 (1997). 원문 미열람 — 식은 arXiv:2104.00344 식(1)–(5), "
    "반발계수 닫힌 해는 R.L. Jackson, I. Green, D.B. Marghitu, Nonlinear Dyn. 60:217 (2010) 식(2)에서 확인"
)

# Hertz 충돌시간 계수: Johnson(1985) 2.94·(15/16)^(2/5) = 2.8683 (He & Wettlaufer 2013)
HERTZ_TC_COEF = 2.8683
# 항복 시작 p0/Y (von Mises, Burgoyne & Daraio 2014). ν 에 약하게 의존함 (Jackson 외 2010)
YIELD_ONSET_RATIO = 1.6


def effective_modulus(E1: float, nu1: float, E2: float, nu2: float) -> float:
    """E* = [(1−ν1²)/E1 + (1−ν2²)/E2]⁻¹."""
    return 1.0 / ((1.0 - nu1**2) / E1 + (1.0 - nu2**2) / E2)


def hertz_force(delta: float, E_star: float, R: float) -> float:
    return (4.0 / 3.0) * E_star * math.sqrt(R) * max(delta, 0.0) ** 1.5


@dataclass(frozen=True)
class HertzImpact:
    delta_max: float   # m
    F_max: float       # N
    a_max: float       # 접촉 반경 m
    p0: float          # 최대 접촉압 Pa
    tc: float          # 접촉시간 s


def hertz_impact(m: float, R: float, v: float, E_star: float) -> HertzImpact:
    """강체 지지 위 탄성 Hertz 충돌의 닫힌 해 (참고용)."""
    d = (15.0 * m * v**2 / (16.0 * E_star * math.sqrt(R))) ** 0.4
    F = hertz_force(d, E_star, R)
    a = math.sqrt(R * d)
    p0 = 3.0 * F / (2.0 * math.pi * a**2)
    tc = HERTZ_TC_COEF * (m**2 / (R * v * E_star**2)) ** 0.2
    return HertzImpact(d, F, a, p0, tc)


def check_hertz_validity(p0: float, Y: float, log: WarningLog) -> bool:
    """p0 > 1.6Y 이면 '탄성 모델 무효(국부 항복)' 경고. True = 탄성 유효."""
    if p0 > YIELD_ONSET_RATIO * Y:
        log.add(
            "hertz_yield", Severity.WARNING,
            f"탄성 모델 무효(국부 항복): p0 = {p0/1e6:.0f} MPa > 1.6·Y = {1.6*Y/1e6:.0f} MPa "
            "(Y는 굽힘강도 대용값)",
        )
        return False
    return True


@dataclass(frozen=True)
class ThorntonLaw:
    """Thornton(1997) 탄성-완전소성 접촉 법칙. py=inf 이면 순수 Hertz."""

    E_star: float
    R: float
    py: float  # 한계 접촉압 [Pa]

    @property
    def elastic(self) -> bool:
        return math.isinf(self.py)

    @property
    def delta_y(self) -> float:
        """δ_y = R (π p_y / (2E*))²."""
        if self.elastic:
            return math.inf
        return self.R * (math.pi * self.py / (2.0 * self.E_star)) ** 2

    @property
    def F_y(self) -> float:
        if self.elastic:
            return math.inf
        return hertz_force(self.delta_y, self.E_star, self.R)

    # --- 하중 -------------------------------------------------------------
    def force_load(self, delta: float) -> float:
        if delta <= 0.0:
            return 0.0
        dy = self.delta_y
        if delta <= dy:
            return hertz_force(delta, self.E_star, self.R)
        return self.F_y + math.pi * self.py * self.R * (delta - dy)

    def work_load(self, delta: float) -> float:
        """하중 곡선 아래 면적 ∫0^δ F dδ [J]."""
        if delta <= 0.0:
            return 0.0
        k = (8.0 / 15.0) * self.E_star * math.sqrt(self.R)
        dy = self.delta_y
        if delta <= dy:
            return k * delta**2.5
        x = delta - dy
        return k * dy**2.5 + self.F_y * x + 0.5 * math.pi * self.py * self.R * x**2

    def stiffness_load(self, delta: float) -> float:
        if delta <= 0.0:
            return 0.0
        if delta <= self.delta_y:
            return 2.0 * self.E_star * math.sqrt(self.R * delta)
        return math.pi * self.py * self.R

    # --- 제하·재하중 ------------------------------------------------------
    def unload_params(self, delta_max: float) -> tuple[float, float, float]:
        """(F_max, R_p, δ_p). 항복 전이면 R_p = R, δ_p = 0."""
        Fm = self.force_load(delta_max)
        if delta_max <= self.delta_y:
            return Fm, self.R, 0.0
        Rp = (4.0 * self.E_star / (3.0 * Fm)) * ((2.0 * Fm + self.F_y) / (2.0 * math.pi * self.py)) ** 1.5
        dp = delta_max - (3.0 * Fm / (4.0 * self.E_star * math.sqrt(Rp))) ** (2.0 / 3.0)
        return Fm, Rp, dp

    def force_unload(self, delta: float, Rp: float, dp: float) -> float:
        return (4.0 / 3.0) * self.E_star * math.sqrt(Rp) * max(delta - dp, 0.0) ** 1.5

    def work_unload(self, delta_max: float) -> float:
        """제하 시 돌려받는 탄성 에너지 [J]."""
        _, Rp, dp = self.unload_params(delta_max)
        return (8.0 / 15.0) * self.E_star * math.sqrt(Rp) * (delta_max - dp) ** 2.5

    def contact_radius(self, delta: float) -> float:
        """a = √(Rδ) (Thornton 모델은 소성 구간에서도 a² = Rδ 를 쓴다)."""
        return math.sqrt(self.R * max(delta, 0.0))

    # --- 강체 지지 닫힌 해 --------------------------------------------------
    def yield_velocity(self, m: float) -> float:
        """항복이 막 시작하는 충돌 속도: ½ m V_y² = W_load(δ_y)."""
        if self.elastic:
            return math.inf
        return math.sqrt(2.0 * self.work_load(self.delta_y) / m)

    def rigid_impact(self, m: float, v: float) -> tuple[float, float, float]:
        """강체 지지 위 충돌: (반발계수 e, δ_max, 잔류 압흔 δ_p). 에너지 균형으로 푼다."""
        E_in = 0.5 * m * v**2
        hi = 1e-9
        while self.work_load(hi) < E_in:
            hi *= 2.0
        dmax = brentq(lambda d: self.work_load(d) - E_in, 0.0, hi, xtol=1e-15, rtol=1e-13)
        W_back = self.work_unload(dmax)
        _, _, dp = self.unload_params(dmax)
        return math.sqrt(W_back / E_in), dmax, dp


def thornton_restitution_closed(v: float, v_y: float) -> float:
    """Thornton(1997) 반발계수 닫힌 해 (Jackson, Green & Marghitu 2010 식 2 로 확인)."""
    if v <= v_y:
        return 1.0
    r = v_y / v
    return (
        math.sqrt(6.0 * math.sqrt(3.0) / 5.0)
        * math.sqrt(1.0 - r * r / 6.0)
        * (r / (r + 2.0 * math.sqrt(6.0 / 5.0 - r * r / 5.0))) ** 0.25
    )
