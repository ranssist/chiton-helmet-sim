"""값의 출처·라벨·경고를 다루는 공통 타입 (PLAN §5)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class Label(str, Enum):
    """모든 수치 옆에 붙는 값 라벨."""

    LITERATURE = "문헌값"
    COMPUTED = "계산값"
    ASSUMPTION = "가정"
    UNVERIFIED = "미확인"
    CALIBRATED = "보정 후"


class Basis(str, Enum):
    """모든 출력 블록 머리에 붙는 결과 기준 라벨."""

    PRE = "문헌값 기반(보정 전)"
    POST = "실측 보정 후"


# 특수 라벨
NOT_ANALYZABLE = "해석 불가·실측 보정값"
NEEDS_MEASUREMENT = "실측 필요"


class SimInputError(ValueError):
    """입력이 모델 적용범위나 허용범위를 벗어났다."""


class GuideTubeError(SimInputError):
    """구슬이 가이드관을 통과하지 못한다."""


class CalibrationBlockedError(RuntimeError):
    """파손 판정 기준 등 보정 전제조건이 비어 있어 보정을 실행할 수 없다."""


@dataclass(frozen=True)
class Quantity:
    """SI 값 + 라벨 + 출처.

    - label=LITERATURE 이면 source 가 반드시 있어야 한다.
    - value=None 은 label=UNVERIFIED 일 때만 허용한다(출처를 못 찾은 값, 코드에는 TODO).
    - sd 는 1σ (TDS 의 ± 값을 1σ 로 해석하는 것은 가정 A-02).
    - low/high 는 문헌이 범위로 준 값의 경계.
    """

    value: float | None
    unit: str
    label: Label
    source: str | None = None
    note: str = ""
    sd: float | None = None
    low: float | None = None
    high: float | None = None

    def __post_init__(self) -> None:
        if self.value is None and self.label is not Label.UNVERIFIED:
            raise ValueError("value=None 은 label=미확인 에서만 허용된다")
        if self.label is Label.LITERATURE and not self.source:
            raise ValueError("문헌값에는 출처(source)가 필요하다")

    @property
    def known(self) -> bool:
        return self.value is not None

    def require(self, what: str = "") -> float:
        """값이 없으면(미확인) SimInputError. 계산에 필요한 값을 꺼낼 때 쓴다."""
        if self.value is None:
            raise SimInputError(f"{what or '값'}이(가) 미확인이다. 입력이 필요하다.")
        return float(self.value)

    def calibrated(self, value: float, note: str = "") -> "Quantity":
        return replace(self, value=float(value), label=Label.CALIBRATED, note=note, sd=None)


def unverified(unit: str, note: str = "") -> Quantity:
    """출처를 찾지 못한 값. 코드에서 호출하는 자리에 TODO(source) 주석을 단다."""
    return Quantity(None, unit, Label.UNVERIFIED, None, note)


def assumed(value: float, unit: str, note: str) -> Quantity:
    return Quantity(float(value), unit, Label.ASSUMPTION, None, note)


def computed(value: float, unit: str, note: str = "") -> Quantity:
    return Quantity(float(value), unit, Label.COMPUTED, None, note)


class Severity(str, Enum):
    INFO = "정보"
    WARNING = "경고"
    BLOCK = "차단"


@dataclass(frozen=True)
class ModelWarning:
    code: str
    severity: Severity
    message: str


@dataclass
class WarningLog:
    items: list[ModelWarning] = field(default_factory=list)

    def add(self, code: str, severity: Severity, message: str) -> None:
        if not any(w.code == code for w in self.items):
            self.items.append(ModelWarning(code, severity, message))

    def extend(self, other: "WarningLog") -> None:
        for w in other.items:
            self.add(w.code, w.severity, w.message)

    def codes(self) -> set[str]:
        return {w.code for w in self.items}

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
