"""헬멧 수준: 무게·면밀도 비교, 헤드폼 둔탁 충격 추정, 측정 가능성 (PLAN §3-H).

FAST SF 수치는 치수·무게·시험 조건의 비교 기준으로만 쓴다. 이 모델은 복합재 셸의 성능을 예측하지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp
from scipy.signal import butter, sosfilt

from .materials import G0
from .provenance import (
    Basis, Label, Quantity, Severity, WarningLog, assumed, computed, unverified,
)

SRC_FASTSF = (
    "Ops-Core FAST SF High Cut Helmet System Data Sheet (Gentex, REV.20230306), "
    "https://img.trex-arms.com/wp/uploads/2023/09/FAST_SF_Ops-Core_Data_Sheet.pdf"
)
SRC_RTS = (
    "RTS Tactical 제품 페이지 — 차세대 FAST SF 사이즈 L 셸 557 g, "
    "https://www.rtstactical.com/products/ops-core-fast-sf-super-high-cut-lightweight-advanced-ballistic-helmet-system"
)
SRC_FMVSS218 = "49 CFR 571.218 (FMVSS No. 218) 헤드폼 질량, https://www.law.cornell.edu/cfr/text/49/571.218"
SRC_ARDUINO = (
    "Arduino 공식 언어 레퍼런스 analogRead(): ATmega 보드에서 1회 약 100 µs → 최대 약 10,000회/s, "
    "https://github.com/arduino/reference-en (Language/Functions/Analog IO/analogRead.adoc)"
)

# --- FAST SF 비교 기준 ------------------------------------------------------
FASTSF_SIZES = {  # 사이즈: (머리둘레 하한 m, 상한 m, 커버리지 m², 데이터시트 셸 질량 kg)
    "M": (0.53, 0.56, 884e-4, 0.630),
    "L": (0.56, 0.59, 955e-4, 0.655),
    "XL": (0.59, 0.62, 1052e-4, 0.750),
    "XXL": (0.62, 0.645, 1103e-4, 0.780),
}
FASTSF_XXL_NOTE = "XXL 머리둘레 상한은 데이터시트 64 cm, 판매 페이지 64.5 cm 로 다르다"
FASTSF_SHELL_L_NEXTGEN = Quantity(0.557, "kg", Label.LITERATURE, SRC_RTS, "차세대 FAST SF 사이즈 L 셸")
FASTSF_SHELL_L_DATASHEET = Quantity(0.655, "kg", Label.LITERATURE, SRC_FASTSF, "데이터시트(2023) 사이즈 L 셸, 추정 ±3 %")
FASTSF_AREAL_DENSITY = Quantity(5.957, "kg/m^2", Label.LITERATURE, SRC_FASTSF, "1.22 lbs/ft²")
FASTSF_SHELL_THICKNESS = Quantity(5.58e-3, "m", Label.LITERATURE, SRC_FASTSF, '0.220"')
FASTSF_SYSTEM_L = Quantity(1.089, "kg", Label.LITERATURE, SRC_FASTSF, "셸+Vented Lux 라이너+Occ-Dial")
BLUNT_G_LIMIT = Quantity(150.0, "-", Label.LITERATURE, SRC_FASTSF, "둔탁 충격 최대 150 g")
BLUNT_VELOCITY = Quantity(3.048, "m/s", Label.LITERATURE, SRC_FASTSF, "10 ft/s (1 ft = 0.3048 m)")

# 시험 규격(FTHS/PS-1228)의 헤드폼 질량은 공개 자료에서 확인하지 못했다 (PLAN L17)
HEADFORM_MASS = unverified("kg", "FTHS 헤드폼 질량 — 공개 자료 없음, 사용자 입력 필요")  # TODO(source)
FMVSS218_HEADFORMS = {  # 다른 규격 참고값: FAST SF 시험과 같은 헤드폼인지 미확인
    "FMVSS 218 소": Quantity(3.5, "kg", Label.LITERATURE, SRC_FMVSS218, "3.4–3.6 kg", low=3.4, high=3.6),
    "FMVSS 218 중": Quantity(5.0, "kg", Label.LITERATURE, SRC_FMVSS218, "4.9–5.1 kg", low=4.9, high=5.1),
    "FMVSS 218 대": Quantity(6.1, "kg", Label.LITERATURE, SRC_FMVSS218, "6.0–6.2 kg", low=6.0, high=6.2),
}

ARDUINO_SAMPLE_RATE = Quantity(1.0e4, "1/s", Label.LITERATURE, SRC_ARDUINO, "단일 채널 기준")


# ---------------------------------------------------------------------------
# 무게·면밀도
# ---------------------------------------------------------------------------
def shell_mass(rho: float, area: Quantity, t: float, overlap_ratio: float = 0.0) -> Quantity:
    """셸 질량 [kg] = ρ · A · t · (1 + 겹침 면적비). A 가 미확인이면 계산하지 않는다."""
    if not area.known:
        return unverified("kg", "셸 표면적(CAD) 미입력 — 무게를 계산하지 않는다")
    return computed(rho * area.value * t * (1.0 + overlap_ratio), "kg", "ρ·A·t·(1+겹침 면적비)")


def thickness_for_mass(rho: float, area: Quantity, target_mass: float, overlap_ratio: float = 0.0) -> Quantity:
    """목표 무게 → 허용 두께 [m] (역산)."""
    if not area.known:
        return unverified("m", "셸 표면적(CAD) 미입력")
    return computed(target_mass / (rho * area.value * (1.0 + overlap_ratio)), "m", "목표 무게 역산")


def shell_areal_density(rho: float, t: float, overlap_ratio: float = 0.0) -> Quantity:
    return computed(rho * t * (1.0 + overlap_ratio), "kg/m^2", "ρ·t·(1+겹침 면적비)")


# ---------------------------------------------------------------------------
# 헤드폼 둔탁 충격 (1자유도)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LinerModel:
    """라이너 압축 거동. plateau 상수(요청서 방식) 또는 σ(ε) 점열(ARPRO 표)."""

    thickness: float                   # m
    plateau: Quantity | None = None    # Pa
    curve: tuple[tuple[float, float], ...] | None = None   # ((변형률, Pa), ...)
    densification_strain: Quantity = field(default_factory=lambda: unverified(
        "-", "치밀화 변형률 — 문헌 확인 실패, 사용자 입력 필요"))  # TODO(source)

    def stress(self, strain: float) -> float:
        if self.curve:
            xs = [c[0] for c in self.curve]
            ys = [c[1] for c in self.curve]
            return float(np.interp(min(max(strain, 0.0), 1.0), xs, ys))
        return self.plateau.require("라이너 평탄응력")

    @property
    def usable_stroke(self) -> float:
        """바닥침 전까지 쓸 수 있는 스트로크 [m]. ε_D 가 없으면 기하학적 상한(두께)을 쓴다."""
        e = self.densification_strain
        return self.thickness * (e.value if e.known else 1.0)


@dataclass
class HeadformResult:
    a_max_g: float
    stroke: float
    pulse_duration: float
    bottoming: bool
    s_min: float                 # v²/(2a_max) 검산용 이상 한계
    passes_150g: bool
    A_spread: Quantity
    basis: str
    warnings: WarningLog
    t: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))
    a_g: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))
    x: np.ndarray = field(repr=False, default_factory=lambda: np.empty(0))


def simulate_headform(
    mass: Quantity,
    liner: LinerModel,
    A_spread: Quantity,
    v0: Quantity = BLUNT_VELOCITY,
    basis: Basis = Basis.PRE,
    n_out: int = 400,
) -> HeadformResult:
    """헤드폼 + 라이너 1자유도: m ẍ = −σ(x/t) · A_spread (A-18)."""
    log = WarningLog()
    m = mass.require("헤드폼 질량")
    A = A_spread.require("하중 분산 면적")
    v = v0.require("충돌 속도")
    g0 = G0.require()
    s_avail = liner.usable_stroke
    if not liner.densification_strain.known:
        log.add("densification", Severity.INFO,
                "치밀화 변형률 미확인 — 바닥침 판정에 기하학적 상한(스트로크 ≤ 라이너 두께)을 쓴다")

    def rhs(_t, y):
        return [y[1], -liner.stress(min(y[0], liner.thickness) / liner.thickness) * A / m]

    def stopped(_t, y):
        return y[1]
    stopped.terminal, stopped.direction = True, -1

    def bottom(_t, y):
        return y[0] - s_avail
    bottom.terminal, bottom.direction = True, 1

    t_guess = 4.0 * s_avail / v if s_avail > 0 else 1e-3
    sol = solve_ivp(rhs, (0.0, 10 * t_guess), [0.0, v], method="DOP853", rtol=1e-10, atol=1e-13,
                    events=[stopped, bottom], dense_output=True, max_step=t_guess / 200)
    t_end = float(sol.t[-1])
    tt = np.linspace(0.0, t_end, n_out)
    xs, vs = sol.sol(tt)
    a = np.array([liner.stress(min(x, liner.thickness) / liner.thickness) * A / m for x in xs])
    a_g = a / g0
    a_max = float(np.max(a_g))
    stroke = float(xs[-1])
    bottoming = sol.t_events[1].size > 0
    if bottoming:
        log.add("bottoming", Severity.WARNING,
                f"바닥침: 필요한 스트로크가 사용 가능한 {s_avail:.4f} m 를 넘는다 — "
                "실제 가속도는 이 결과보다 훨씬 커진다(모델 적용범위 밖)")
    if a_max > BLUNT_G_LIMIT.value:
        log.add("g_limit", Severity.WARNING, f"최대 가속도 {a_max:.0f} g > 기준 {BLUNT_G_LIMIT.value:.0f} g")
    s_min = v**2 / (2.0 * a_max * g0)
    # 펄스 길이는 압축 구간(속도가 0이 될 때까지)이다. 폼의 반발 구간은 모델에 없다.
    return HeadformResult(a_max, stroke, t_end, bottoming, s_min,
                          a_max <= BLUNT_G_LIMIT.value, A_spread, basis.value, log, tt, a_g, xs)


def required_spread_area(mass: Quantity, liner: LinerModel, v0: Quantity = BLUNT_VELOCITY,
                         g_limit: float = 150.0) -> tuple[Quantity, Quantity]:
    """일정 감속 가정에서 (바닥침을 피하는 최소 면적, g 기준을 지키는 최대 면적).

    A_min = m v²/(2 σ s_avail),  A_max = g_limit·g₀·m/σ  — 가정 없이 유도되는 설계 창이다.
    """
    m = mass.require("헤드폼 질량")
    v = v0.require()
    g0 = G0.require()
    sigma = liner.stress(0.25)
    s = liner.usable_stroke
    return (computed(m * v**2 / (2.0 * sigma * s), "m^2", "바닥침 회피 최소 분산 면적"),
            computed(g_limit * g0 * m / sigma, "m^2", f"{g_limit:.0f} g 이하 최대 분산 면적"))


def segmented_spread_area(plate_area: float, lock: bool, beta: Quantity | None = None) -> Quantity:
    """분할형 A_spread: 판 1장 면적이 상한, 잠금 on 이면 인접판 기여율 β 를 더한다 (A-19)."""
    if not lock:
        return assumed(plate_area, "m^2", "분할·잠금 없음: 판 1장 면적(상한)")
    b = beta.value if (beta is not None and beta.known) else 0.0
    note = "분할·잠금 on: 판 1장 면적 × (1+β)" + ("" if (beta and beta.known) else ", β 보정 전 0")
    return Quantity(plate_area * (1.0 + b), "m^2",
                    Label.CALIBRATED if (beta is not None and beta.label is Label.CALIBRATED) else Label.ASSUMPTION,
                    None, note)


# ---------------------------------------------------------------------------
# 측정 가능성
# ---------------------------------------------------------------------------
@dataclass
class MeasurementCheck:
    pulse_duration: float
    samples_per_pulse: float
    sampling_error: float          # 피크 놓침 오차 (0–1)
    bandwidth_error: float | None  # 센서 대역 제한에 의한 피크 감쇠 (0–1)
    total_error: float
    tolerance: float
    ok: bool
    warnings: WarningLog


def measurement_check(pulse_duration: float, sample_rate: Quantity = ARDUINO_SAMPLE_RATE,
                      n_channels: int = 1, sensor_bandwidth: float | None = None,
                      tolerance: float = 0.05) -> MeasurementCheck:
    """예측 펄스를 지금 장비로 잡을 수 있는지 본다.

    - 샘플링: 반정현 펄스를 N개로 나눠 잡을 때 최악 피크 오차 = 1 − cos(π/(2N)) (계산값)
    - 센서 대역: 2차 Butterworth 저역통과(가정 A-21)를 펄스에 적용해 피크 감쇠를 계산
    - 허용오차(기본 5 %)는 사용자 설정이다.
    """
    log = WarningLog()
    fs = sample_rate.require("샘플링 속도") / max(n_channels, 1)
    if n_channels > 1:
        log.add("channels", Severity.INFO, f"{n_channels}채널로 나누면 채널당 {fs:.0f} S/s 다")
    N = pulse_duration * fs
    samp_err = 1.0 - math.cos(math.pi / (2.0 * N)) if N >= 1 else 1.0
    bw_err = None
    if sensor_bandwidth:
        fs_fine = max(200.0 / pulse_duration, 20.0 * sensor_bandwidth)
        t = np.arange(0.0, 3.0 * pulse_duration, 1.0 / fs_fine)
        x = np.where(t <= pulse_duration, np.sin(np.pi * t / pulse_duration), 0.0)
        sos = butter(2, sensor_bandwidth, "low", fs=fs_fine, output="sos")
        y = sosfilt(sos, x)
        bw_err = float(max(0.0, 1.0 - np.max(y) / np.max(x)))
    total = samp_err + (bw_err or 0.0)
    ok = N >= 2 and total <= tolerance
    if not ok:
        log.add("measurement", Severity.WARNING,
                f"측정 불가, 장비 변경 필요: 펄스당 {N:.1f} 샘플, 예상 피크 오차 {total*100:.1f} % "
                f"> 허용 {tolerance*100:.0f} %")
    return MeasurementCheck(pulse_duration, N, samp_err, bw_err, total, tolerance, ok, log)
