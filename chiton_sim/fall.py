"""낙하 모델 (PLAN §3-A).

m dv/dt = m g − ½ ρ_air C_d(Re) A v|v| K(z),   v_impact = v_ODE · (1 − η_wall)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from .ball import Ball, GuideTube, check_ball_in_tube
from .materials import AIR_DENSITY, AIR_VISCOSITY, G0
from .provenance import Basis, Label, Quantity, Severity, SimInputError, WarningLog, assumed

H_MIN, H_MAX = 0.3, 20.0          # 입력 허용 범위 [m] (요청서)
V_STRAIN_RATE = 10.0              # m/s, 이 이상이면 변형률 속도 효과 미반영 경고 (요청서)
RE_MAX_MORRISON = 1.0e6           # Morrison(2013) 권장 상한

SRC_MORRISON = (
    "F.A. Morrison, Data Correlation for Drag Coefficient for Sphere (2016); "
    "An Introduction to Fluid Mechanics, Cambridge UP (2013) Fig. 8.13, "
    "https://pages.mtu.edu/~fmorriso/DataCorrelationForSphereDrag2016.pdf"
)


def morrison_cd(re: np.ndarray | float) -> np.ndarray | float:
    """구 항력계수 C_d(Re) — Morrison (2013) 식 (1). Re ≤ 1e6 에서 사용."""
    re = np.asarray(re, dtype=float)
    re = np.maximum(re, 1e-12)
    cd = (
        24.0 / re
        + 2.6 * (re / 5.0) / (1.0 + (re / 5.0) ** 1.52)
        + 0.411 * (re / 2.63e5) ** -7.94 / (1.0 + (re / 2.63e5) ** -8.00)
        + 0.25 * (re / 1.0e6) / (1.0 + re / 1.0e6)
    )
    return cd if cd.ndim else float(cd)


@dataclass(frozen=True)
class FallParams:
    K_tube: Quantity = assumed(1.0, "-", "관 폐색 보정계수 기본 1.0 (보정 대상, A-11)")
    eta_wall: Quantity = assumed(0.0, "-", "벽 손실 = 충돌 속도 손실률, 보정 전 0 (A-12)")
    drag: bool = True

    @property
    def basis(self) -> Basis:
        if Label.CALIBRATED in (self.K_tube.label, self.eta_wall.label):
            return Basis.POST
        return Basis.PRE


@dataclass
class FallResult:
    height: float
    v_ode: float            # 벽 손실 적용 전 [m/s]
    v_impact: float         # 충돌 속도 [m/s]
    t_fall: float           # 낙하 시간 [s]
    loss_frac: float        # 1 − v_impact/√(2gh)
    energy: float           # ½ m v_impact² [J]
    basis: Basis
    warnings: WarningLog
    t: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))
    z: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))
    v: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))


def _check_height(h: float) -> None:
    if not (H_MIN <= h <= H_MAX):
        raise SimInputError(f"낙하 높이 {h:.3f} m 가 허용 범위 {H_MIN}–{H_MAX} m 밖이다")


def simulate_fall(
    ball: Ball,
    height: float,
    tube: GuideTube | None = None,
    params: FallParams = FallParams(),
) -> FallResult:
    _check_height(height)
    log = WarningLog()
    if tube is not None:
        check_ball_in_tube(ball, tube, log)
    g = G0.require()
    rho = AIR_DENSITY.require()
    mu = AIR_VISCOSITY.require()
    m, D, A = ball.mass, ball.diameter, ball.area
    K = params.K_tube.require("K_tube")
    z_tube = height - tube.length if tube is not None else math.inf  # 관 입구까지의 낙하 거리

    def rhs(_t, y):
        z, v = y
        if not params.drag or v == 0.0:
            return [v, g]
        re = rho * abs(v) * D / mu
        k = K if z >= z_tube else 1.0
        fd = 0.5 * rho * morrison_cd(re) * A * v * abs(v) * k
        return [v, g - fd / m]

    def hit(_t, y):
        return y[0] - height

    hit.terminal = True
    hit.direction = 1
    t_guess = math.sqrt(2 * height / g)
    sol = solve_ivp(rhs, (0.0, 10 * t_guess), [0.0, 0.0], method="DOP853",
                    rtol=1e-11, atol=1e-13, events=hit, dense_output=False, max_step=t_guess / 50)
    if sol.t_events[0].size == 0:
        raise RuntimeError("낙하 적분이 충돌 이벤트에 도달하지 못했다")
    t_hit = float(sol.t_events[0][0])
    v_ode = float(sol.y_events[0][0][1])
    eta = params.eta_wall.require("η_wall")
    v_imp = v_ode * (1.0 - eta)
    v_free = math.sqrt(2 * g * height)

    re_max = rho * v_ode * D / mu
    if params.drag and re_max > RE_MAX_MORRISON:
        log.add("re_range", Severity.WARNING, f"Re={re_max:.3g} > 1e6: Morrison 상관식 적용범위 밖")
    if v_imp > V_STRAIN_RATE:
        log.add("strain_rate", Severity.WARNING,
                f"충돌 속도 {v_imp:.2f} m/s > 10 m/s: 변형률 속도 효과 미반영")

    return FallResult(
        height=height, v_ode=v_ode, v_impact=v_imp, t_fall=t_hit,
        loss_frac=1.0 - v_imp / v_free, energy=0.5 * m * v_imp**2,
        basis=params.basis, warnings=log, t=sol.t, z=sol.y[0], v=sol.y[1],
    )


def height_for_energy(
    ball: Ball,
    energy: float,
    tube: GuideTube | None = None,
    params: FallParams = FallParams(),
) -> float:
    """충돌 에너지 ½mv² 가 energy 가 되는 낙하 높이 [m] (brentq 역산)."""
    def f(h):
        return simulate_fall(ball, h, tube, params).energy - energy

    lo, hi = H_MIN, H_MAX
    flo, fhi = f(lo), f(hi)
    if flo > 0 or fhi < 0:
        raise SimInputError(
            f"목표 에너지 {energy:.4g} J 는 이 구슬로 {H_MIN}–{H_MAX} m 범위에서 만들 수 없다"
        )
    return brentq(f, lo, hi, xtol=1e-6)
