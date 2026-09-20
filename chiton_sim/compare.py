"""재료 비교 — 같은 두께 / 같은 면밀도에서 무엇이 유리한가.

비교 항목은 이 모델이 실제로 계산할 수 있는 것뿐이다: 면밀도, 셸 무게, 판 강성,
최대 접촉력·판 반력, 굽힘응력과 여유율, 흡수 에너지, 참고 판정 임계 높이(h50).

**방탄 성능 비교가 아니다.** 복합 적층판은 층간 박리·섬유 파단·변형률 속도 의존성을 이 모델이
보지 못하므로, 결과에 경고가 함께 나온다(materials.material_warnings).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.optimize import brentq

from .ball import Ball, GuideTube
from .contact import ThorntonLaw, effective_modulus
from .fall import H_MAX, H_MIN, FallParams, simulate_fall
from .failure import energy_balance, reference_judgment
from .impact import ImpactResult, simulate_impact
from .materials import FilamentMaterial, material_warnings
from .plate import Plate, reference_stress
from .provenance import Basis, Label, Quantity, Severity, WarningLog

BASES = ("same_thickness", "same_areal_density")


@dataclass
class MaterialRow:
    name: str
    kind: str                      # "filament" | "composite"
    printable: bool
    thickness: float               # m
    density: float | None          # kg/m³
    areal_density: float | None    # kg/m²
    shell_mass: float | None       # kg (셸 표면적을 줬을 때)
    k_bending: float | None        # N/m
    F_max: float | None            # 최대 접촉력 N
    F_plate: float | None          # 판 반력 N
    sigma: float | None            # 굽힘응력 Pa
    strength: float | None         # 굽힘강도 Pa
    margin: float | None           # 강도/응력 (<1 이면 파손)
    E_abs: float | None            # 흡수 에너지 J
    h50: float | None              # 참고 판정 임계 높이 m
    impact: ImpactResult | None = field(default=None, repr=False)
    warnings: WarningLog = field(default_factory=WarningLog)

    @property
    def analyzable(self) -> bool:
        return self.sigma is not None

    @property
    def specific_margin(self) -> float | None:
        """면밀도 1 kg/m² 당 여유율 — 무게 대비 효율."""
        if self.margin is None or not self.areal_density:
            return None
        return self.margin / self.areal_density


def _thickness_for(basis: str, t_ref: float, rho_ref: float, rho: float) -> float:
    if basis == "same_thickness":
        return t_ref
    if basis == "same_areal_density":
        return t_ref * rho_ref / rho
    raise ValueError(f"basis 는 {BASES} 중 하나")


def compare_materials(
    materials: list[FilamentMaterial],
    ball: Ball,
    height: float,
    t_ref: float,
    a: float,
    bc: str = "clamped",
    orientation: str = "XY",
    py_ratio: float = 1.6,
    basis: str = "same_thickness",
    area: Quantity | None = None,
    overlap_ratio: float = 0.0,
    tube: GuideTube | None = None,
    fall_params: FallParams = FallParams(),
    membrane: bool = False,
    reference: FilamentMaterial | None = None,
    with_h50: bool = True,
) -> list[MaterialRow]:
    """재료별로 같은 조건에서의 충돌 응답을 계산한다. 기준 재료는 면밀도 환산의 기준이다."""
    if basis not in BASES:
        raise ValueError(f"basis 는 {BASES} 중 하나")
    ref = reference or materials[0]
    rho_ref = ref.density.require("기준 재료 밀도")
    fall = simulate_fall(ball, height, tube, fall_params)
    rows: list[MaterialRow] = []

    for m in materials:
        log = material_warnings(m, orientation)
        props = m.props(orientation)
        rho = m.density.value if m.density.known else None
        t = _thickness_for(basis, t_ref, rho_ref, rho) if rho else t_ref
        ad = rho * t if rho else None
        mass = (rho * area.value * t * (1.0 + overlap_ratio)
                if (rho and area is not None and area.known) else None)

        row = MaterialRow(m.name, m.kind, m.printable, t, rho, ad, mass,
                          None, None, None, None, None, None, None, None, warnings=log)

        if not (props.flex_modulus.known and props.flex_strength.known and rho):
            rows.append(row)
            continue

        E, sf = props.flex_modulus.value, props.flex_strength.value
        nu = m.poisson.require("푸아송비")
        plate = Plate(E=E, nu=nu, rho=rho, t=t, a=a, bc=bc, membrane=membrane)
        law = ThorntonLaw(effective_modulus(ball.material.E.require(), ball.material.nu.require(), E, nu),
                          ball.radius, py_ratio * sf)
        imp = simulate_impact(ball, fall.v_impact, plate, law, "2dof", yield_proxy=sf)
        log.extend(imp.warnings)
        sigma = reference_stress(imp.F_plate_max, plate, imp.contact_radius).max
        judg = reference_judgment(sigma, props.flex_strength)

        row.k_bending = plate.k_bending()
        row.F_max, row.F_plate, row.sigma = imp.F_max, imp.F_plate_max, sigma
        row.strength, row.margin, row.E_abs = sf, judg.margin, imp.E_abs
        row.impact = imp
        if with_h50:
            row.h50 = _h50(ball, plate, law, sf, imp, fall, tube, fall_params)
        rows.append(row)
    return rows


def _h50(ball, plate, law, sf, imp_ref, fall_ref, tube, fall_params) -> float | None:
    """참고 판정이 뒤집히는 높이. 2자유도 명목해로 보정한 에너지 균형 모델로 빠르게 푼다(A-17)."""
    R = ball.radius
    F_eb_ref, _, _ = energy_balance(fall_ref.energy, law.E_star, R, law.py,
                                    plate.k_bending(), plate.k_membrane)
    corr = imp_ref.F_plate_max / float(F_eb_ref)

    def margin(h: float) -> float:
        e_in = simulate_fall(ball, h, tube, fall_params).energy
        F, d, _ = energy_balance(e_in, law.E_star, R, law.py, plate.k_bending(), plate.k_membrane)
        sigma = reference_stress(corr * float(F), plate, math.sqrt(R * float(d))).max
        return sigma - sf

    if margin(H_MIN) > 0:
        return H_MIN
    if margin(H_MAX) < 0:
        return None            # 허용 높이 범위 안에서는 파손 판정이 나오지 않는다
    return brentq(margin, H_MIN, H_MAX, xtol=1e-3)


def rank(rows: list[MaterialRow], by: str = "margin") -> list[MaterialRow]:
    """유리한 순서로 정렬한다. by: margin(여유율) | specific_margin(무게 대비) | areal_density(가벼운 순)."""
    keyed = [r for r in rows if getattr(r, by, None) is not None]
    rest = [r for r in rows if getattr(r, by, None) is None]
    reverse = by != "areal_density"
    return sorted(keyed, key=lambda r: getattr(r, by), reverse=reverse) + rest


def comparison_basis(materials: list[FilamentMaterial], py_calibrated: bool = False) -> Basis:
    return Basis.POST if py_calibrated else Basis.PRE
