"""A~F 등급 — 어떤 수치가 나와야 좋은가.

두 가지를 구분한다.
1. **절대 등급**: 기준선이 있는 지표. 기준선은 문헌값(150 g, FAST SF 무게·면밀도)이거나
   물리적 경계(응력 = 강도, 스트로크 = 라이너 두께)이거나 사용자가 정한 목표다.
   점수 = 기준선 대비 여유(클수록 좋게 정규화)이고, 점수 1.0 이 '기준 충족'이다.
2. **상대 등급**: 기준선이 없는 지표. 비교 대상 안에서의 순위로만 매기고 그렇게 표시한다.

A~F 경계(cuts)는 문헌 근거가 있는 값이 아니라 **가정**이다. 기본값을 쓰되 UI 에서 조절할 수 있고,
등급 옆에는 항상 원래 수치와 기준선을 같이 보여 준다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .provenance import Label, Quantity

GRADES = ("A", "B", "C", "D", "E", "F")
# 점수(기준선 대비) → 등급 경계. 가정이며 사용자가 바꿀 수 있다.
DEFAULT_CUTS: tuple[float, float, float, float, float] = (1.5, 1.2, 1.0, 0.85, 0.7)
GRADE_MEANING = {
    "A": "기준 대비 큰 여유", "B": "여유 있음", "C": "기준 충족(경계)",
    "D": "기준 약간 미달", "E": "미달", "F": "크게 미달",
}


def cuts_note(cuts=DEFAULT_CUTS) -> str:
    return (f"A ≥ {cuts[0]:.2f}, B ≥ {cuts[1]:.2f}, C ≥ {cuts[2]:.2f}(기준 충족), "
            f"D ≥ {cuts[3]:.2f}, E ≥ {cuts[4]:.2f}, 그 아래 F — 경계는 가정이다")


@dataclass(frozen=True)
class GradeScale:
    """한 지표의 채점 기준."""

    name: str
    better: str                 # "high" | "low"
    anchor: Quantity            # 기준선 (문헌값/계산값/가정)
    unit_scale: float = 1.0     # 표시용 배율 (SI → 표시 단위)
    unit: str = ""
    cuts: tuple[float, float, float, float, float] = DEFAULT_CUTS

    def score(self, value: float) -> float | None:
        """기준선 대비 점수. 1.0 이 기준 충족이고 클수록 좋다."""
        if value is None or not self.anchor.known:
            return None
        a = float(self.anchor.value)
        if self.better == "high":
            return value / a if a else None
        if value <= 0:
            return float("inf")
        return a / value

    def with_anchor(self, value: float, label: Label = Label.ASSUMPTION,
                    note: str = "사용자 목표") -> "GradeScale":
        return replace(self, anchor=Quantity(value, self.anchor.unit, label, self.anchor.source, note))


@dataclass(frozen=True)
class Grade:
    metric: str
    value: float | None
    score: float | None
    letter: str                 # A~F 또는 "-"(계산 불가)
    kind: str                   # "절대" | "상대"
    anchor_text: str
    meaning: str = ""

    @property
    def known(self) -> bool:
        return self.letter in GRADES


def _letter(score: float | None, cuts=DEFAULT_CUTS) -> str:
    if score is None:
        return "-"
    for g, c in zip(GRADES, cuts):
        if score >= c:
            return g
    return "F"


def grade(value: float | None, scale: GradeScale) -> Grade:
    """절대 등급. 기준선이 미확인이면 '-' 를 낸다(등급을 지어내지 않는다)."""
    s = scale.score(value) if value is not None else None
    letter = _letter(s, scale.cuts)
    if scale.anchor.known:
        anchor_text = (f"기준 {scale.anchor.value * scale.unit_scale:.4g} {scale.unit}"
                       f" [{scale.anchor.label.value}]")
    else:
        anchor_text = f"기준 미확인 — {scale.anchor.note}"
    return Grade(scale.name, value, s, letter, "절대", anchor_text, GRADE_MEANING.get(letter, ""))


def relative_grades(values: list[float | None], better: str = "high",
                    metric: str = "") -> list[Grade]:
    """기준선이 없는 지표: 비교 대상 안의 순위로만 등급을 매긴다."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out: list[Grade] = [Grade(metric, v, None, "-", "상대", "비교 대상 없음") for v in values]
    if not idx:
        return out
    order = sorted(idx, key=lambda i: values[i], reverse=(better == "high"))
    n = len(order)
    for rank0, i in enumerate(order):
        letter = GRADES[min(int(rank0 * len(GRADES) / n), len(GRADES) - 1)] if n > 1 else "C"
        out[i] = Grade(metric, values[i], None, letter, "상대",
                       f"{n}개 중 {rank0 + 1}위 — 순위 기준(절대 기준 없음)",
                       "비교 대상 안에서의 순위일 뿐이다")
    return out


def overall(grades: list[Grade], weights: list[float] | None = None,
            min_known: int | None = None) -> Grade:
    """등급 평균(A=5 … F=0). 가중치는 기본 동일하며 가정이다.

    min_known 을 주면 채점 가능한 지표가 그보다 적을 때 등급을 내지 않는다.
    모르는 지표를 빼고 평균내면 '물성이 미확인인 재료'가 오히려 좋아 보이기 때문이다.
    """
    known = [(g, (weights[i] if weights else 1.0)) for i, g in enumerate(grades) if g.known]
    if not known:
        return Grade("종합", None, None, "-", "절대", "채점 가능한 지표가 없다")
    if min_known is not None and len(known) < min_known:
        return Grade("종합", None, None, "-", "절대",
                     f"채점 가능한 지표 {len(known)}개 < 필요 {min_known}개 — 미확인 물성 때문에 종합 등급을 내지 않는다",
                     "지표 부족")
    pts = {g: 5 - i for i, g in enumerate(GRADES)}
    total = sum(pts[g.letter] * w for g, w in known)
    wsum = sum(w for _, w in known)
    avg = total / wsum
    letter = GRADES[max(0, min(len(GRADES) - 1, round(5 - avg)))]
    kinds = {g.kind for g, _ in known}
    return Grade("종합", avg, None, letter, "혼합" if len(kinds) > 1 else kinds.pop(),
                 f"{len(known)}개 지표 평균(가중치 동일, 가정)", GRADE_MEANING.get(letter, ""))


# ---------------------------------------------------------------------------
# 기준선이 있는 지표들
# ---------------------------------------------------------------------------
def blunt_g_scale(limit: Quantity, cuts=DEFAULT_CUTS) -> GradeScale:
    """헤드폼 최대 가속도 — 낮을수록 좋다. 기준 150 g (FAST SF 데이터시트)."""
    return GradeScale("헤드폼 최대 가속도", "low", limit, 1.0, "g", cuts)


def shell_mass_scale(target: Quantity, cuts=DEFAULT_CUTS) -> GradeScale:
    """셸 무게 — 가벼울수록 좋다. 기준은 FAST SF L 셸 또는 사용자 목표."""
    return GradeScale("셸 무게", "low", target, 1e3, "g", cuts)


def areal_density_scale(target: Quantity, cuts=DEFAULT_CUTS) -> GradeScale:
    """면밀도 — 낮을수록 좋다. 기준 FAST SF 5957 g/m²."""
    return GradeScale("면밀도", "low", target, 1e3, "g/m²", cuts)


def margin_scale(cuts=DEFAULT_CUTS) -> GradeScale:
    """굽힘응력 여유율 — 1.0 이 응력 = 강도인 물리적 경계다."""
    return GradeScale("굽힘응력 여유율", "high",
                      Quantity(1.0, "-", Label.COMPUTED, None, "응력 = 굽힘강도인 경계"), 1.0, "", cuts)


def h50_scale(target_height: Quantity, cuts=DEFAULT_CUTS) -> GradeScale:
    """임계 높이 h50 — 시험(또는 사용) 높이보다 높아야 좋다."""
    return GradeScale("임계 높이 h50", "high", target_height, 1.0, "m", cuts)


def bottoming_scale(available_stroke: Quantity, cuts=DEFAULT_CUTS) -> GradeScale:
    """필요 스트로크 — 라이너가 쓸 수 있는 스트로크보다 작아야 한다(물리적 경계)."""
    return GradeScale("필요 스트로크", "low", available_stroke, 1e3, "mm", cuts)


def loss_ratio_scale(allowed: Quantity, cuts=DEFAULT_CUTS) -> GradeScale:
    """분할 손실률 — 낮을수록 좋다. 허용치는 사용자가 정한다(문헌 기준 없음)."""
    return GradeScale("분할 손실률", "low", allowed, 100.0, "%", cuts)


def measurement_scale(tolerance: Quantity, cuts=DEFAULT_CUTS) -> GradeScale:
    """예상 피크 오차 — 허용오차보다 작아야 한다."""
    return GradeScale("측정 피크 오차", "low", tolerance, 100.0, "%", cuts)
