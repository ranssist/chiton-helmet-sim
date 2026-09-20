"""구슬(강구)과 가이드관."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .materials import CHROME_STEEL, BallMaterial
from .provenance import GuideTubeError, Label, Quantity, Severity, WarningLog, assumed

INCH = 0.0254  # m, 정의값 (1959 international yard and pound agreement)

# 규격 강구 공칭 지름 (인치 분수). 공칭 치수는 인치 정의값으로 환산한 것이다.
STANDARD_BALL_INCHES: dict[str, float] = {
    '1/4"': 1 / 4, '5/16"': 5 / 16, '3/8"': 3 / 8, '7/16"': 7 / 16, '1/2"': 1 / 2,
    '9/16"': 9 / 16, '5/8"': 5 / 8, '11/16"': 11 / 16, '3/4"': 3 / 4, '13/16"': 13 / 16,
    '7/8"': 7 / 8, '15/16"': 15 / 16, '1"': 1.0, '1-1/8"': 1.125, '1-1/4"': 1.25,
    '1-1/2"': 1.5, '2"': 2.0, '2-1/2"': 2.5,
}


def diameter_from_mass(mass: float, density: float) -> float:
    """구의 지름 [m] = (6m/(πρ))^(1/3)."""
    if mass <= 0 or density <= 0:
        raise ValueError("질량과 밀도는 양수여야 한다")
    return (6.0 * mass / (math.pi * density)) ** (1.0 / 3.0)


def mass_from_diameter(diameter: float, density: float) -> float:
    """구의 질량 [kg] = ρπd³/6."""
    if diameter <= 0 or density <= 0:
        raise ValueError("지름과 밀도는 양수여야 한다")
    return density * math.pi * diameter**3 / 6.0


@dataclass(frozen=True)
class Ball:
    mass: float        # kg
    diameter: float    # m
    material: BallMaterial = CHROME_STEEL
    name: str = ""

    @property
    def radius(self) -> float:
        return self.diameter / 2.0

    @property
    def area(self) -> float:
        """투영 면적 [m²]."""
        return math.pi * self.diameter**2 / 4.0

    @classmethod
    def from_mass(cls, mass: float, material: BallMaterial = CHROME_STEEL) -> "Ball":
        rho = material.density.require("강구 밀도")
        return cls(mass, diameter_from_mass(mass, rho), material, "질량 입력")

    @classmethod
    def standard(cls, name: str, material: BallMaterial = CHROME_STEEL) -> "Ball":
        d = STANDARD_BALL_INCHES[name] * INCH
        return cls(mass_from_diameter(d, material.density.require()), d, material, name)


def standard_balls(material: BallMaterial = CHROME_STEEL) -> list[Ball]:
    return [Ball.standard(n, material) for n in STANDARD_BALL_INCHES]


def snap_to_standard(mass: float, material: BallMaterial = CHROME_STEEL) -> Ball:
    """입력 질량에 가장 가까운 규격 강구."""
    return min(standard_balls(material), key=lambda b: abs(b.mass - mass))


# ---------------------------------------------------------------------------
# 가이드관
# ---------------------------------------------------------------------------
PET_WARNING = (
    '병목 내경 약 21~22 mm로 추정(도면값 미확인), 3/4" 볼이 사실상 상한, 이음부 손실은 실측 필요'
)


@dataclass(frozen=True)
class GuideTube:
    inner_diameter: Quantity          # 최소 내경 [m]
    length: float                     # 관 길이 [m] (관 하단 = 시편 면)
    clearance: Quantity = assumed(1e-3, "m", "구슬-관 여유 기본 1 mm (요청서 지정)")
    mode: str = "custom"              # "custom" | "pet_bottle"

    @classmethod
    def pet_bottle(cls, length: float) -> "GuideTube":
        # 요청서의 추정 범위 21–22 mm 중 하한을 보수적으로 사용 (도면값 미확인)
        idq = Quantity(21e-3, "m", Label.ASSUMPTION, None, "500 mL PET병 병목 내경 추정 하한 — 도면값 미확인")
        return cls(idq, length, mode="pet_bottle")


def check_ball_in_tube(ball: Ball, tube: GuideTube, log: WarningLog | None = None) -> WarningLog:
    """구슬 지름 > 내경 − 여유 이면 GuideTubeError. PET 모드면 경고를 추가한다."""
    log = log if log is not None else WarningLog()
    if tube.mode == "pet_bottle":
        log.add("pet_bottle", Severity.WARNING, PET_WARNING)
    limit = tube.inner_diameter.require("가이드관 내경") - tube.clearance.require("여유")
    if ball.diameter > limit:
        raise GuideTubeError(
            f"구슬 지름 {ball.diameter:.5f} m > 관 내경 − 여유 {limit:.5f} m: 계산을 차단한다"
        )
    if tube.length <= 0:
        raise GuideTubeError("가이드관 길이는 양수여야 한다")
    return log
