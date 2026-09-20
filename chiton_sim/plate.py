"""원판 굽힘 강성·유효질량·참고 응력 (PLAN §3-C)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .materials import FilamentMaterial

SRC_KB = (
    "K.N. Shivakumar, W. Elber, W. Illg, NASA TM-85703 (1983) Table 1 / J. Appl. Mech. 52:674 (1985), "
    "doi:10.1115/1.3169120 — Timoshenko & Woinowsky-Krieger (1959) 판 이론"
)
SRC_MEFF = "Shivakumar 외 NASA TM-85703: 유효 판 질량 = 전체 질량의 1/4 (Leissa, NASA SP-160 인용)"
SRC_ROARK = (
    "Roark's Formulas for Stress and Strain (등가반경 r'0 = √(1.6r0²+t²) − 0.675t, r0 < 0.5t), "
    "MITcalc 문서 인용 https://www.mitcalc.com/doc/plates/help/en/plates.htm ; "
    "중앙·가장자리 응력은 키르히호프 원판 모멘트 해로 유도 검산 (Roark 표 번호 원서 미확인, TODO)"
)

BOUNDARY_CONDITIONS = ("clamped", "simply_supported")


@dataclass(frozen=True)
class Plate:
    E: float        # Pa (굽힘탄성률 사용, 가정 A-23)
    nu: float
    rho: float      # kg/m³
    t: float        # 두께 m
    a: float        # 고정 링 내반경 m
    bc: str = "clamped"

    def __post_init__(self) -> None:
        if self.bc not in BOUNDARY_CONDITIONS:
            raise ValueError(f"bc 는 {BOUNDARY_CONDITIONS} 중 하나")
        if min(self.E, self.rho, self.t, self.a) <= 0 or not (0 <= self.nu < 0.5):
            raise ValueError("판 물성·치수가 올바르지 않다")

    @property
    def D(self) -> float:
        """굽힘 강성 D = E t³ / (12(1−ν²))."""
        return self.E * self.t**3 / (12.0 * (1.0 - self.nu**2))

    def k_bending(self, bc: str | None = None) -> float:
        """중앙 집중하중에 대한 판 강성 [N/m]."""
        bc = bc or self.bc
        if bc == "clamped":
            return 16.0 * math.pi * self.D / self.a**2
        if bc == "simply_supported":
            return 16.0 * math.pi * (1.0 + self.nu) * self.D / ((3.0 + self.nu) * self.a**2)
        raise ValueError(bc)

    @property
    def mass(self) -> float:
        """링 내부 판 질량 [kg]."""
        return self.rho * math.pi * self.a**2 * self.t

    @property
    def m_eff(self) -> float:
        return 0.25 * self.mass

    def with_bc(self, bc: str) -> "Plate":
        return Plate(self.E, self.nu, self.rho, self.t, self.a, bc)


def plate_from_material(
    material: FilamentMaterial, orientation: str, t: float, a: float, bc: str = "clamped"
) -> Plate:
    p = material.props(orientation)
    return Plate(
        E=p.flex_modulus.require("굽힘탄성률"),
        nu=material.poisson.require("푸아송비"),
        rho=material.density.require("밀도"),
        t=t, a=a, bc=bc,
    )


def equivalent_load_radius(r0: float, t: float) -> float:
    """Roark 등가반경: r0 < 0.5t 이면 √(1.6r0² + t²) − 0.675t, 아니면 r0."""
    if r0 < 0.5 * t:
        return math.sqrt(1.6 * r0**2 + t**2) - 0.675 * t
    return r0


@dataclass(frozen=True)
class PlateStress:
    center: float
    edge: float
    r0_eq: float

    @property
    def max(self) -> float:
        return max(self.center, self.edge)


def reference_stress(P: float, plate: Plate, r0: float, bc: str | None = None) -> PlateStress:
    """소면적 중앙하중 P 에 의한 판 최대 굽힘응력 [Pa].

    σ_c = 3P/(2πt²)·[(1+ν)ln(a/r'0) + c], c = 1(단순지지), 0(고정단);
    고정단 가장자리 σ_e = 3P/(2πt²).
    """
    bc = bc or plate.bc
    t, a, nu = plate.t, plate.a, plate.nu
    r = equivalent_load_radius(r0, t)
    base = 3.0 * P / (2.0 * math.pi * t**2)
    log_term = (1.0 + nu) * math.log(a / r) if r < a else 0.0
    if bc == "clamped":
        return PlateStress(base * log_term, base, r)
    return PlateStress(base * (log_term + 1.0), 0.0, r)
