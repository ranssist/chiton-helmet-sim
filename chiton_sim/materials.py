"""재료·물리 상수 프리셋 (SI). 모든 값에 출처를 단다. 출처가 없으면 unverified() + TODO.

값은 문헌 단위를 SI 로 옮겨 적었다 (MPa → Pa, g/cm³ → kg/m³, psi → Pa).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .provenance import Label, Quantity, assumed, computed, unverified

# ---------------------------------------------------------------------------
# 출처
# ---------------------------------------------------------------------------
SRC_BAMBU_PLA = (
    "Bambu Lab, PLA Basic Technical Data Sheet V3.0, "
    "https://wiki.bambulab.com/filament-acc/abs-asa-pc/bambu_pla_basic_technical_data_sheet.pdf"
)
SRC_AZOM_52100 = "AZoM, AISI 52100 Alloy Steel (UNS G52986), https://www.azom.com/article.aspx?ArticleID=6704"
SRC_USSA1976 = (
    "U.S. Standard Atmosphere 1976 (NASA-TM-X-74335), sea level table via "
    "https://www.pdas.com/bigtables.html"
)
SRC_G0 = "3rd CGPM (1901), standard acceleration of gravity; NIST SP 330"
SRC_ARPRO_EPP = (
    "JSP ARPRO EPP physical properties (ARPLANK sheet, ASTM D3575, typical values), "
    "https://www.foam-industries.com/hubfs/Technical%20Documents/TechDataHome_PhysicalPropertyInformation_EPPproducts.pdf"
)
SRC_PSI = "NIST SP 811 (2008), 1 psi = 6.894757 kPa"
SRC_BAMBU_PETG_HF = (
    "Bambu Lab, PETG HF Technical Data Sheet V1.0, "
    "https://store.bblcdn.com/3a230e260a3a47c2b0db0156e07eef91.pdf"
)
SRC_ARAMID_EPOXY = (
    "N.M. Meliande 외, Curaua–aramid hybrid laminated composites for impact applications: "
    "Flexural, Charpy impact and elastic properties, Polymers 14(18):3749 (2022), "
    "doi:10.3390/polym14183749 — 100 % 아라미드(에폭시 기지, 섬유부피 73.3 %) 적층판, ASTM D790-17"
)
SRC_UHMWPE = (
    "J. Bian 외, Polymers 16(21):2985 (2024), doi:10.3390/polym16212985 Table 3 "
    "(원출처 P. Hu 외, Compos. Struct. 290:115499 (2022)) — UHMWPE 적층판 시뮬레이션 입력 물성"
)
SRC_FASTSF_SHELL = (
    "Ops-Core FAST SF Data Sheet (Gentex, REV.20230306): 면밀도 5957 g/m², 셸 두께 5.58 mm 에서 "
    "밀도를 역산했다. 셸은 탄소·UHMWPE·아라미드 하이브리드다"
)

# ---------------------------------------------------------------------------
# 물리 상수
# ---------------------------------------------------------------------------
G0 = Quantity(9.80665, "m/s^2", Label.LITERATURE, SRC_G0, "표준 중력(정의값)")
AIR_DENSITY = Quantity(1.2250, "kg/m^3", Label.LITERATURE, SRC_USSA1976, "해면 288.15 K")
AIR_VISCOSITY = Quantity(1.7894e-5, "Pa*s", Label.LITERATURE, SRC_USSA1976, "해면 288.15 K")
PSI_TO_PA = 6894.757  # SRC_PSI

# ---------------------------------------------------------------------------
# 강구 (크롬강 AISI 52100)
# ---------------------------------------------------------------------------
STEEL_DENSITY = Quantity(7810.0, "kg/m^3", Label.LITERATURE, SRC_AZOM_52100, "7.81 g/cm³")
STEEL_E = Quantity(
    210e9, "Pa", Label.LITERATURE, SRC_AZOM_52100,
    "문헌 범위 190–210 GPa, 기본값은 범위 상단(요청값)", low=190e9, high=210e9,
)
STEEL_NU = Quantity(
    0.30, "-", Label.LITERATURE, SRC_AZOM_52100,
    "문헌 범위 0.27–0.30, 기본값은 범위 상단(요청값)", low=0.27, high=0.30,
)


@dataclass(frozen=True)
class BallMaterial:
    name: str
    density: Quantity
    E: Quantity
    nu: Quantity


CHROME_STEEL = BallMaterial("크롬강 AISI 52100", STEEL_DENSITY, STEEL_E, STEEL_NU)

# ---------------------------------------------------------------------------
# 필라멘트
# ---------------------------------------------------------------------------
ORIENTATIONS = ("XY", "Z")


@dataclass(frozen=True)
class OrientationProps:
    flex_modulus: Quantity
    flex_strength: Quantity
    tensile_strength: Quantity
    youngs_modulus: Quantity
    elongation: Quantity
    impact_unnotched: Quantity  # J/m² (ISO 179). 모델에는 쓰지 않고 표시만 한다.


@dataclass(frozen=True)
class FilamentMaterial:
    name: str
    density: Quantity
    poisson: Quantity
    xy: OrientationProps
    z: OrientationProps
    tds_infill: float = 1.0      # TDS 시편 인필 비율
    tds_annealed: bool = True    # TDS 시편 어닐링 여부
    source: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    kind: str = "filament"       # "filament"(출력 가능) | "composite"(실제 방탄모 계열, 비교용)
    printable: bool = True

    def props(self, orientation: str) -> OrientationProps:
        """출력 방향별 물성. XY=평판을 눕혀 출력, Z=세워 출력(가정 A-04)."""
        if orientation == "XY":
            return self.xy
        if orientation == "Z":
            return self.z
        raise ValueError(f"orientation 은 {ORIENTATIONS} 중 하나: {orientation!r}")


def _lit(v: float, sd: float | None, unit: str, note: str = "") -> Quantity:
    return Quantity(v, unit, Label.LITERATURE, SRC_BAMBU_PLA, note, sd=sd)


BAMBU_PLA_BASIC = FilamentMaterial(
    name="Bambu PLA Basic (TDS V3.0)",
    density=_lit(1240.0, None, "kg/m^3", "ISO 1183, 1.24 g/cm³"),
    # TDS 에 푸아송비가 없다 → 가정 A-01 (요청서 지정 0.36)
    poisson=assumed(0.36, "-", "TDS에 없음 — 가정값(A-01)"),
    xy=OrientationProps(
        flex_modulus=_lit(2750e6, 160e6, "Pa", "ISO 178"),
        flex_strength=_lit(76e6, 5e6, "Pa", "ISO 178"),
        tensile_strength=_lit(35e6, 4e6, "Pa", "ISO 527"),
        youngs_modulus=_lit(2580e6, 220e6, "Pa", "ISO 527"),
        elongation=_lit(0.122, 0.018, "-", "ISO 527, 12.2 %"),
        impact_unnotched=_lit(26.6e3, 2.8e3, "J/m^2", "ISO 179 비노치 (노치 7.9±1.2 kJ/m²)"),
    ),
    z=OrientationProps(
        flex_modulus=_lit(2370e6, 150e6, "Pa", "ISO 178"),
        flex_strength=_lit(59e6, 6e6, "Pa", "ISO 178"),
        tensile_strength=_lit(31e6, 3e6, "Pa", "ISO 527"),
        youngs_modulus=_lit(2060e6, 170e6, "Pa", "ISO 527"),
        elongation=_lit(0.075, 0.013, "-", "ISO 527, 7.5 %"),
        impact_unnotched=_lit(13.8e3, 0.9e3, "J/m^2", "ISO 179"),
    ),
    tds_infill=1.0,
    tds_annealed=True,
    source=SRC_BAMBU_PLA,
    notes=("TDS 시편: 인필 100 %, 노즐 220 °C, 55 °C·8 h 어닐링 후 시험",),
)


def _petg(v: float, sd: float | None, unit: str, note: str = "") -> Quantity:
    return Quantity(v, unit, Label.LITERATURE, SRC_BAMBU_PETG_HF, note, sd=sd)


BAMBU_PETG_HF = FilamentMaterial(
    name="Bambu PETG HF (TDS V1.0)",
    density=_petg(1280.0, None, "kg/m^3", "ISO 1183, 1.28 g/cm³"),
    poisson=assumed(0.40, "-", "TDS에 없음 — PETG 일반값 가정(A-28)"),
    xy=OrientationProps(
        flex_modulus=_petg(2050e6, 120e6, "Pa", "ISO 178"),
        flex_strength=_petg(64e6, 3e6, "Pa", "ISO 178"),
        tensile_strength=_petg(34e6, 4e6, "Pa", "ISO 527"),
        youngs_modulus=_petg(1810e6, 190e6, "Pa", "ISO 527"),
        elongation=_petg(0.086, 0.012, "-", "ISO 527, 8.6 %"),
        impact_unnotched=_petg(31.5e3, 2.2e3, "J/m^2", "ISO 179 비노치 (노치 6.2±1.8 kJ/m²)"),
    ),
    z=OrientationProps(
        flex_modulus=_petg(1810e6, 140e6, "Pa", "ISO 178"),
        flex_strength=_petg(48e6, 4e6, "Pa", "ISO 178"),
        tensile_strength=_petg(23e6, 4e6, "Pa", "ISO 527"),
        youngs_modulus=_petg(1540e6, 130e6, "Pa", "ISO 527"),
        elongation=_petg(0.051, 0.008, "-", "ISO 527, 5.1 %"),
        impact_unnotched=_petg(10.6e3, 1.2e3, "J/m^2", "ISO 179"),
    ),
    source=SRC_BAMBU_PETG_HF,
    notes=("TDS 시편: 인필 100 %, 노즐 255 °C, 75 °C·8 h 어닐링 후 시험",
           "제조사는 PETG HF 출력물의 어닐링을 권하지 않는다"),
)


# ---------------------------------------------------------------------------
# 실제 방탄모 계열 셸 재질 — 둔탁 충격 비교용이며 방탄 성능과 무관하다
# ---------------------------------------------------------------------------
COMPOSITE_NOTE = (
    "복합 적층판이다. 이 모델은 등방성 평판·Thornton 접촉을 가정하므로 층간 박리, 섬유 파단, "
    "변형률 속도 의존성을 보지 못한다. 방탄 성능 비교가 아니라 같은 두께·면밀도에서의 "
    "굽힘 강성과 무게 비교로만 쓴다"
)


def _iso_props(E: Quantity, S: Quantity) -> OrientationProps:
    """면내 등방으로 본 적층판: 굽힘 물성만 채우고 나머지는 미확인."""
    return OrientationProps(
        flex_modulus=E, flex_strength=S,
        tensile_strength=unverified("Pa", "적층판 인장강도 — 이 모델에 쓰지 않는다"),
        youngs_modulus=E, elongation=unverified("-", "미확인"),
        impact_unnotched=unverified("J/m^2", "미확인"),
    )


ARAMID_EPOXY = FilamentMaterial(
    name="아라미드/에폭시 적층판 (문헌 시험편)",
    density=Quantity(1320.0, "kg/m^3", Label.LITERATURE, SRC_ARAMID_EPOXY, "논문 시편 질량·치수 기준"),
    poisson=assumed(0.30, "-", "적층판 면내 푸아송비 — 논문에 없어 가정(A-29)"),
    xy=_iso_props(
        Quantity(10.38e9, "Pa", Label.LITERATURE, SRC_ARAMID_EPOXY, "굽힘탄성률 10.38 ± 0.60 GPa", sd=0.60e9),
        Quantity(109.02e6, "Pa", Label.LITERATURE, SRC_ARAMID_EPOXY, "굽힘강도 109.02 ± 10.83 MPa", sd=10.83e6),
    ),
    z=_iso_props(
        Quantity(10.38e9, "Pa", Label.LITERATURE, SRC_ARAMID_EPOXY, "면내 값과 같게 둔다(적층판)", sd=0.60e9),
        Quantity(109.02e6, "Pa", Label.LITERATURE, SRC_ARAMID_EPOXY, "면내 값과 같게 둔다(적층판)", sd=10.83e6),
    ),
    tds_annealed=False, source=SRC_ARAMID_EPOXY,
    notes=(COMPOSITE_NOTE, "PASGT·ACH 의 PVB-페놀릭 기지와는 기지 수지가 다르다(에폭시)"),
    kind="composite", printable=False,
)

UHMWPE_LAMINATE = FilamentMaterial(
    name="UHMWPE 적층판 (Dyneema 계열)",
    density=Quantity(970.0, "kg/m^3", Label.LITERATURE, SRC_UHMWPE, "0.97 g/cm³"),
    poisson=assumed(0.30, "-", "문헌 표에 없어 가정(A-29)"),
    xy=_iso_props(
        Quantity(30.7e9, "Pa", Label.LITERATURE, SRC_UHMWPE,
                 "면내 탄성계수 E1=E2=30.7 GPa — 굽힘탄성률이 아니다. 굽힘에서는 이보다 낮게 나온다"),
        unverified("Pa", "굽힘강도 미확인 — 인장 3.1 GPa 는 굽힘 파손 기준이 아니다. 실측 입력 필요"),
    ),
    z=_iso_props(
        Quantity(1.97e9, "Pa", Label.LITERATURE, SRC_UHMWPE, "두께 방향 E3 = 1.97 GPa"),
        unverified("Pa", "굽힘강도 미확인"),
    ),
    tds_annealed=False, source=SRC_UHMWPE,
    notes=(COMPOSITE_NOTE,
           "굽힘·전단이 약한 재료다. 굽힘강도가 미확인이라 파손 판정은 나오지 않는다(면밀도·강성 비교만 가능)"),
    kind="composite", printable=False,
)

FASTSF_HYBRID_SHELL = FilamentMaterial(
    name="FAST SF 하이브리드 셸 (탄소+UHMWPE+아라미드)",
    density=computed(5.957 / 5.58e-3, "kg/m^3", "데이터시트 면밀도 5957 g/m² ÷ 두께 5.58 mm"),
    poisson=assumed(0.30, "-", "미확인 — 가정(A-29)"),
    xy=_iso_props(unverified("Pa", "굽힘탄성률 미확인 — 제조사 비공개"),
                  unverified("Pa", "굽힘강도 미확인 — 제조사 비공개")),
    z=_iso_props(unverified("Pa", "미확인"), unverified("Pa", "미확인")),
    tds_annealed=False, source=SRC_FASTSF_SHELL,
    notes=(COMPOSITE_NOTE, "무게·면밀도 비교 기준으로만 쓴다. 굽힘 물성이 없어 충돌 해석은 하지 못한다"),
    kind="composite", printable=False,
)

MATERIAL_LIBRARY: dict[str, FilamentMaterial] = {
    m.name: m for m in (BAMBU_PLA_BASIC, BAMBU_PETG_HF, ARAMID_EPOXY, UHMWPE_LAMINATE,
                        FASTSF_HYBRID_SHELL)
}


def material_warnings(material: FilamentMaterial, orientation: str = "XY"):
    """재료 선택에 따른 적용범위 경고."""
    from .provenance import Severity, WarningLog
    log = WarningLog()
    if material.kind == "composite":
        log.add("composite_material", Severity.WARNING, f"{material.name}: {COMPOSITE_NOTE}")
    p = material.props(orientation)
    if not p.flex_strength.known:
        log.add("no_flex_strength", Severity.WARNING,
                f"{material.name}: 굽힘강도가 미확인이라 파손 판정을 낼 수 없다 — 면밀도·강성만 비교한다")
    if not p.flex_modulus.known:
        log.add("no_flex_modulus", Severity.WARNING,
                f"{material.name}: 굽힘탄성률이 미확인이라 충돌 해석을 하지 못한다")
    return log


def user_filament(
    name: str,
    source: str | None,
    density: float | None,
    poisson: float | None,
    xy: dict[str, float | None],
    z: dict[str, float | None],
    sd_xy: dict[str, float] | None = None,
    sd_z: dict[str, float] | None = None,
) -> FilamentMaterial:
    """사용자가 입력한 TDS 값(PETG, TPU 등)으로 재료를 만든다.

    출처(source)가 있으면 문헌값, 없거나 값이 비면 미확인으로 표시한다.
    xy/z 키: flex_modulus, flex_strength, tensile_strength, youngs_modulus, elongation, impact_unnotched (SI)
    """
    units = {
        "flex_modulus": "Pa", "flex_strength": "Pa", "tensile_strength": "Pa",
        "youngs_modulus": "Pa", "elongation": "-", "impact_unnotched": "J/m^2",
    }

    def q(v: float | None, unit: str, sd: float | None = None) -> Quantity:
        if v is None:
            return unverified(unit, "사용자 TDS 미입력")  # TODO(source): 사용자 입력 필요
        if source:
            return Quantity(float(v), unit, Label.LITERATURE, source, "사용자 입력 TDS", sd=sd)
        return Quantity(float(v), unit, Label.UNVERIFIED, None, "출처 없는 사용자 입력", sd=sd)

    def op(d: dict, sd: dict | None) -> OrientationProps:
        sd = sd or {}
        return OrientationProps(**{k: q(d.get(k), u, sd.get(k)) for k, u in units.items()})

    nu = (
        assumed(poisson, "-", "사용자 입력 푸아송비")
        if poisson is not None
        else unverified("-", "푸아송비 미입력")  # TODO(source)
    )
    return FilamentMaterial(
        name=name, density=q(density, "kg/m^3"), poisson=nu,
        xy=op(xy, sd_xy), z=op(z, sd_z), source=source or "",
        tds_annealed=False,
    )


# ---------------------------------------------------------------------------
# 라이너 폼 (EPP) — 준정적 압축강도, ASTM D3575 전형값
# ---------------------------------------------------------------------------
# 밀도 [kg/m³] (= g/L) → {압축 변형률: 압축강도[Pa]}
EPP_ARPRO_TABLE: dict[float, dict[float, float]] = {
    20.0: {0.10: 11.7 * PSI_TO_PA, 0.25: 14.5 * PSI_TO_PA, 0.50: 23.5 * PSI_TO_PA, 0.75: 45.0 * PSI_TO_PA},
    30.0: {0.10: 18.0 * PSI_TO_PA, 0.25: 23.5 * PSI_TO_PA, 0.50: 33.5 * PSI_TO_PA, 0.75: 64.0 * PSI_TO_PA},
    45.0: {0.10: 32.0 * PSI_TO_PA, 0.25: 42.0 * PSI_TO_PA, 0.50: 54.0 * PSI_TO_PA, 0.75: 111.0 * PSI_TO_PA},
    60.0: {0.10: 44.0 * PSI_TO_PA, 0.25: 57.0 * PSI_TO_PA, 0.50: 73.0 * PSI_TO_PA, 0.75: 155.0 * PSI_TO_PA},
}
EPP_NOTE = "포장재 등급 표(ARPLANK), 준정적 — 헬멧 등급과 동일한지 미확인, 변형률 속도 경화 미반영(A-20)"


def epp_stress(density_kg_m3: float, strain: float) -> Quantity:
    """ARPRO 표의 압축강도 한 점(문헌값)."""
    try:
        v = EPP_ARPRO_TABLE[float(density_kg_m3)][float(strain)]
    except KeyError as exc:
        raise ValueError("표에 있는 밀도(20/30/45/60 kg/m³)와 변형률(0.10/0.25/0.50/0.75)만 가능") from exc
    return Quantity(v, "Pa", Label.LITERATURE, SRC_ARPRO_EPP, EPP_NOTE)


# 폼 치밀화 변형률 ε_D: Gibson–Ashby 식을 원문으로 확인하지 못했다 (PLAN L21).
FOAM_DENSIFICATION_STRAIN = unverified("-", "치밀화 변형률 — 사용자 입력 필요")  # TODO(source)
