"""분할 구조와 타격 위치 (PLAN §3-E).

- center: 경계조건 규칙에 따라 수치 해석
- seam / triple_junction: 신뢰할 해석식 없음 → 실측 knockdown 으로만 처리, 데이터 없으면 '실측 필요'
- opening / fastener: 응력집중계수 문헌값을 초기값으로, 실측으로 보정
- bonded_receiver: 구멍이 없으므로 Kt 미적용, '받침 탈락'을 별도 파손 모드로 둔다
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .ball import Ball
from .contact import ThorntonLaw, effective_modulus
from .impact import ImpactResult, simulate_impact
from .materials import FilamentMaterial
from .plate import PlateStress, plate_from_material, reference_stress
from .provenance import (
    NEEDS_MEASUREMENT, NOT_ANALYZABLE, Basis, Label, Quantity, Severity, SimInputError,
    WarningLog, computed, unverified,
)

CONFIG_TYPES = ("monolithic", "segmented_butt", "segmented_overlap")
IMPACT_SITES = ("center", "seam", "triple_junction", "opening", "fastener")
JOINT_TYPES = ("tpu_hinge", "fabric_layer", "print_in_place", "snap")
FASTENER_TYPES = ("through_screw", "bonded_receiver", "hybrid")
VENT_TYPES = ("liner_vent", "overlap_channel", "shell_through")

SRC_KT = (
    "C. Dumont, NACA TN-740 (1939): 판 굽힘(단축), 구멍 지름 ≫ 두께, 이론 Kt = 1.87 (실측 1.85), "
    "https://ntrs.nasa.gov/citations/19930081505"
)
KT_HOLE_BENDING = Quantity(1.87, "-", Label.LITERATURE, SRC_KT, "단축 굽힘 기준 초기값 — 실측 보정 대상")
KT_EQUIBIAXIAL = computed(2.0, "-", "등이축 굽힘, 키르히호프 판 해에서 직접 유도(참고용, 문헌 아님)")

# 체결부 간격 기준: FDM PLA + 열압입 인서트에 대한 표준·문헌 기준을 찾지 못했다 (PLAN L22)
PITCH_RATIO_MIN = unverified("-", "p/d 최소 기준 — 사용자 입력 필요")  # TODO(source)
EDGE_RATIO_MIN = unverified("-", "e/d 최소 기준 — 사용자 입력 필요")   # TODO(source)


@dataclass(frozen=True)
class FastenerSpec:
    type: str
    n: int
    d: float        # 구멍 지름 m
    pitch: float    # 피치 m
    edge: float     # 모서리 거리 m
    p_d_min: Quantity = PITCH_RATIO_MIN
    e_d_min: Quantity = EDGE_RATIO_MIN

    def __post_init__(self):
        if self.type not in FASTENER_TYPES:
            raise ValueError(f"fastener_type 은 {FASTENER_TYPES} 중 하나")

    @property
    def has_hole(self) -> bool:
        return self.type in ("through_screw", "hybrid")


@dataclass(frozen=True)
class VentSpec:
    type: str
    n: int
    d: float        # m

    def __post_init__(self):
        if self.type not in VENT_TYPES:
            raise ValueError(f"vent_type 은 {VENT_TYPES} 중 하나")


@dataclass(frozen=True)
class SpecimenConfig:
    config_type: str
    thickness: float          # m
    ring_radius: float        # 고정 링 내반경 m
    orientation: str = "XY"
    infill: float = 1.0       # 0–1
    annealed: bool = True
    bc: str = "clamped"       # 일체형에서 사용자가 고른 경계조건
    overlap: float = 0.0      # 겹침 폭 m
    n_segments: int = 1
    lock: bool = False
    joint_type: str | None = None
    seam_length: float | None = None   # 쿠폰 내 이음선 총 길이 m (CAD)
    fastener: FastenerSpec | None = None
    vent: VentSpec | None = None
    membrane: bool = False             # 막 강성 포함 (고정단 이론식)
    k_measured: float | None = None    # 정적 압입 시험으로 잰 판 강성 [N/m]
    km_measured: float | None = None   # 같은 시험에서 적합한 막 강성 [N/m³]

    def __post_init__(self):
        if self.config_type not in CONFIG_TYPES:
            raise ValueError(f"config_type 은 {CONFIG_TYPES} 중 하나")
        if self.joint_type is not None and self.joint_type not in JOINT_TYPES:
            raise ValueError(f"joint_type 은 {JOINT_TYPES} 중 하나")
        if not (0 < self.infill <= 1):
            raise ValueError("infill 은 0–1 비율")
        if self.config_type == "monolithic" and self.n_segments != 1:
            raise ValueError("monolithic 은 n_segments = 1")

    @property
    def segmented(self) -> bool:
        return self.config_type != "monolithic"


# ---------------------------------------------------------------------------
# 면밀도
# ---------------------------------------------------------------------------
def overlap_ratio(cfg: SpecimenConfig) -> Quantity:
    """r_ov = A_overlap / A_projected, A_overlap = 이음선 길이 × 겹침 폭 (A-14)."""
    if cfg.config_type != "segmented_overlap" or cfg.overlap == 0.0:
        return computed(0.0, "-", "겹침 없음")
    if cfg.seam_length is None:
        return unverified("-", "이음선 길이(CAD) 미입력")  # TODO(source): CAD 값 입력 필요
    area = math.pi * cfg.ring_radius**2
    return computed(cfg.seam_length * cfg.overlap / area, "-", "이음선 길이 × 겹침 폭 / 투영면적 (A-14)")


def areal_density(rho: float, t: float, r_ov: float) -> float:
    """면밀도 [kg/m²] = ρ · t · (1 + r_ov)."""
    return rho * t * (1.0 + r_ov)


def equal_areal_density_thickness(t: float, r_ov: float) -> float:
    """겹침 구성과 같은 면밀도가 되는 일체형 두께 [m] = t (1 + r_ov)."""
    return t * (1.0 + r_ov)


# ---------------------------------------------------------------------------
# 보정 입력
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SiteCalibration:
    """calibration.py 가 만든 실측 결과. E50 은 충돌 에너지 기준 [J]."""

    E50: Quantity | None = None           # 이 (구성, 위치) 실측 E50
    E50_center: Quantity | None = None    # 같은 구성 center 실측 E50
    detach_E50: Quantity | None = None    # 받침 탈락 모드 실측 E50

    @property
    def knockdown(self) -> Quantity | None:
        if self.E50 is None or self.E50_center is None:
            return None
        return Quantity(self.E50.require() / self.E50_center.require(), "-", Label.CALIBRATED,
                        None, "knockdown = E50(site)/E50(center)")

    @property
    def Kt_eff(self) -> Quantity | None:
        if self.E50 is None or self.E50_center is None:
            return None
        # 선형 판 강성에서 σ ∝ F ∝ √E  →  Kt_eff = √(E50_center / E50_site)  (계산값, 선형 가정)
        return Quantity(math.sqrt(self.E50_center.require() / self.E50.require()), "-",
                        Label.CALIBRATED, None, "√(E50_center/E50_site), 선형 강성 가정에서 유도")


# ---------------------------------------------------------------------------
# 평가
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    bc: str
    impact: ImpactResult
    stress: PlateStress
    Kt: Quantity | None
    sigma_local: float        # Kt 적용 후 [Pa]


@dataclass
class SiteAssessment:
    config: SpecimenConfig
    site: str
    status: str               # Basis 값 | NEEDS_MEASUREMENT | NOT_ANALYZABLE
    cases: dict[str, CaseResult] = field(default_factory=dict)
    extra_modes: dict[str, str] = field(default_factory=dict)
    calibration: SiteCalibration | None = None
    warnings: WarningLog = field(default_factory=WarningLog)

    @property
    def numeric(self) -> bool:
        return bool(self.cases)


def _bcs_for(cfg: SpecimenConfig, log: WarningLog) -> list[str]:
    if cfg.k_measured is not None:
        log.add("k_measured", Severity.INFO,
                "판 강성 실측값을 쓴다 — 고정단/단순지지 가정에서 오는 불확실성이 사라진다")
        return [cfg.bc]
    if not cfg.segmented:
        return [cfg.bc]
    if cfg.lock:
        return ["clamped", "simply_supported"]  # 상한~하한 구간 (A-13)
    log.add("no_lock", Severity.WARNING,
            "잠금 없음: 단순지지 이하로 처리한다 — 실제 강성·강도는 이 결과보다 낮을 수 있다")
    return ["simply_supported"]


def _check_conditions(cfg: SpecimenConfig, material: FilamentMaterial, log: WarningLog) -> None:
    if cfg.infill < material.tds_infill:
        log.add("infill", Severity.WARNING,
                f"인필 {cfg.infill*100:.0f} % < TDS 시편 {material.tds_infill*100:.0f} %: TDS 값 적용 불가, 실측 보정 필요")
    if material.tds_annealed and not cfg.annealed:
        log.add("annealing", Severity.WARNING, "TDS 시편은 55 °C·8 h 어닐링 후 시험 — 비어닐링 출력물과 다를 수 있다")


def _check_fastener(f: FastenerSpec, log: WarningLog) -> None:
    for name, ratio, lim in (("p/d", f.pitch / f.d, f.p_d_min), ("e/d", f.edge / f.d, f.e_d_min)):
        if not lim.known:
            log.add(f"fastener_{name}_unverified", Severity.INFO,
                    f"{name} = {ratio:.2f}: 기준값 미확인 — 문헌·표준 기준을 찾지 못해 사용자 입력 필요")
        elif ratio < lim.value:
            log.add(f"fastener_{name}", Severity.WARNING, f"{name} = {ratio:.2f} < 기준 {lim.value:.2f}")


def assess_site(
    ball: Ball,
    v_impact: float,
    material: FilamentMaterial,
    cfg: SpecimenConfig,
    site: str,
    py: Quantity,
    calib: SiteCalibration | None = None,
    mode: str = "2dof",
    ball_E: float | None = None,
    ball_nu: float | None = None,
) -> SiteAssessment:
    if site not in IMPACT_SITES:
        raise ValueError(f"impact_site 는 {IMPACT_SITES} 중 하나")
    if site in ("seam", "triple_junction") and not cfg.segmented:
        raise SimInputError("일체형에는 이음선·삼중 교차점이 없다")
    if site == "opening" and cfg.vent is None:
        raise SimInputError("opening 타격에는 통기구(vent) 정보가 필요하다")
    if site == "fastener" and cfg.fastener is None:
        raise SimInputError("fastener 타격에는 체결부 정보가 필요하다")

    log = WarningLog()
    _check_conditions(cfg, material, log)
    basis = Basis.POST if py.label is Label.CALIBRATED else Basis.PRE
    out = SiteAssessment(cfg, site, basis.value, calibration=calib, warnings=log)

    # --- 해석식 없는 위치: 실측으로만 ---------------------------------------
    seam_like = site in ("seam", "triple_junction") or (
        site == "opening" and cfg.vent is not None and cfg.vent.type == "overlap_channel")
    if seam_like:
        if calib is None or calib.E50 is None:
            out.status = NEEDS_MEASUREMENT
        else:
            out.status = NOT_ANALYZABLE
        return out

    # --- Kt 결정 -------------------------------------------------------------
    Kt: Quantity | None = None
    if site == "opening":
        if cfg.vent.type == "shell_through":
            Kt = KT_HOLE_BENDING
        else:  # liner_vent: 셸 관통 없음
            log.add("liner_vent", Severity.INFO, "라이너 성형 통기구: 셸 관통이 없어 응력집중을 적용하지 않는다")
    elif site == "fastener":
        f = cfg.fastener
        if f.has_hole:
            _check_fastener(f, log)
            Kt = KT_HOLE_BENDING
        if f.type in ("bonded_receiver", "hybrid"):
            if calib is not None and calib.detach_E50 is not None:
                out.extra_modes["받침 탈락"] = NOT_ANALYZABLE
            else:
                out.extra_modes["받침 탈락"] = NEEDS_MEASUREMENT
    if Kt is not None and calib is not None and calib.Kt_eff is not None:
        Kt = calib.Kt_eff

    # --- 판 해석 -------------------------------------------------------------
    E1 = ball_E if ball_E is not None else ball.material.E.require()
    nu1 = ball_nu if ball_nu is not None else ball.material.nu.require()
    for bc in _bcs_for(cfg, log):
        plate = plate_from_material(material, cfg.orientation, cfg.thickness, cfg.ring_radius, bc,
                                    membrane=cfg.membrane, k_measured=cfg.k_measured,
                                    km_measured=cfg.km_measured)
        law = ThorntonLaw(effective_modulus(E1, nu1, plate.E, plate.nu), ball.radius, py.require("p_y"))
        Y = material.props(cfg.orientation).flex_strength.value
        imp = simulate_impact(ball, v_impact, plate, law, mode, yield_proxy=Y, basis=basis)
        log.extend(imp.warnings)
        st = reference_stress(imp.F_plate_max, plate, imp.contact_radius)
        k = Kt.value if Kt is not None else 1.0
        out.cases[bc] = CaseResult(bc, imp, st, Kt, k * st.max)
    return out
