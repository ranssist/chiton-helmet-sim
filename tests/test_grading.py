"""A~F 등급: 기준선 있는 지표는 절대, 없는 지표는 상대. 기준이 미확인이면 등급을 만들지 않는다."""

import math

import pytest

from chiton_sim.grading import (
    DEFAULT_CUTS, GRADES, areal_density_scale, blunt_g_scale, bottoming_scale, cuts_note, grade,
    h50_scale, margin_scale, overall, relative_grades, shell_mass_scale,
)
from chiton_sim.helmet import BLUNT_G_LIMIT, FASTSF_AREAL_DENSITY, FASTSF_SHELL_L_NEXTGEN
from chiton_sim.provenance import Label, Quantity, assumed, unverified


def test_blunt_g_uses_datasheet_limit_and_lower_is_better():
    sc = blunt_g_scale(BLUNT_G_LIMIT)
    assert sc.anchor.value == 150.0 and sc.anchor.label is Label.LITERATURE
    assert grade(150.0, sc).letter == "C"        # 기준 충족 경계
    assert grade(100.0, sc).letter == "A"        # 점수 1.5
    assert grade(125.0, sc).letter == "B"        # 점수 1.2
    assert grade(175.0, sc).letter == "D"        # 점수 0.857 (D 경계 0.85)
    assert grade(180.0, sc).letter == "E"        # 점수 0.833
    assert grade(300.0, sc).letter == "F"
    assert grade(150.0, sc).score == pytest.approx(1.0)
    assert "문헌값" in grade(150.0, sc).anchor_text


def test_margin_boundary_is_physical():
    sc = margin_scale()
    assert sc.anchor.value == 1.0 and sc.anchor.label is Label.COMPUTED
    assert grade(1.0, sc).letter == "C" and grade(1.6, sc).letter == "A"
    assert grade(0.5, sc).letter == "F"
    assert grade(1.0, sc).meaning == "기준 충족(경계)"


def test_higher_is_better_and_lower_is_better_are_symmetric():
    hi = h50_scale(Quantity(2.0, "m", Label.ASSUMPTION, None, "시험 높이"))
    lo = shell_mass_scale(FASTSF_SHELL_L_NEXTGEN)
    assert hi.score(3.0) == pytest.approx(1.5) and grade(3.0, hi).letter == "A"
    assert lo.score(0.557 / 1.5) == pytest.approx(1.5) and grade(0.557 / 1.5, lo).letter == "A"
    assert lo.score(1.114) == pytest.approx(0.5)          # 두 배 무거우면 점수 0.5
    assert areal_density_scale(FASTSF_AREAL_DENSITY).anchor.value == pytest.approx(5.957)


def test_unknown_anchor_or_value_gives_no_grade():
    sc = shell_mass_scale(unverified("kg", "목표 무게 미입력"))
    g = grade(0.5, sc)
    assert g.letter == "-" and not g.known and "미확인" in g.anchor_text
    assert grade(None, margin_scale()).letter == "-"


def test_zero_or_negative_value_for_lower_is_better():
    sc = bottoming_scale(Quantity(0.02, "m", Label.COMPUTED, None, "사용 가능 스트로크"))
    assert math.isinf(grade(0.0, sc).score) and grade(0.0, sc).letter == "A"
    assert grade(0.02, sc).letter == "C"                 # 딱 바닥침 경계
    assert grade(0.04, sc).letter == "F"                 # 두 배 필요 → 바닥침


def test_custom_cuts_are_honoured():
    strict = blunt_g_scale(BLUNT_G_LIMIT, cuts=(3.0, 2.0, 1.5, 1.2, 1.0))
    assert grade(150.0, strict).letter == "E"            # 같은 값도 기준을 올리면 E 로 내려간다
    assert grade(200.0, strict).letter == "F"            # 점수 0.75
    assert grade(50.0, strict).letter == "A"
    assert "경계는 가정이다" in cuts_note(DEFAULT_CUTS)


def test_relative_grades_rank_within_the_set():
    gs = relative_grades([10.0, 5.0, 1.0], better="high", metric="강성")
    assert [g.letter for g in gs] == ["A", "C", "E"]
    assert all(g.kind == "상대" for g in gs)
    assert "순위 기준" in gs[0].anchor_text
    low = relative_grades([10.0, 5.0, 1.0], better="low")
    assert [g.letter for g in low] == ["E", "C", "A"]
    with_none = relative_grades([3.0, None, 1.0], better="high")
    assert with_none[1].letter == "-" and with_none[0].letter == "A"


def test_overall_refuses_when_too_many_metrics_unknown():
    """굽힘 물성이 없는 재료가 '모르는 항목을 빼서' 좋은 등급을 받으면 안 된다."""
    sc = margin_scale()
    gs = [grade(None, sc), grade(None, sc), grade(1.6, sc), grade(1.6, sc)]   # 2개만 채점 가능
    assert overall(gs, min_known=3).letter == "-"
    assert "미확인" in overall(gs, min_known=3).anchor_text
    assert overall(gs).letter == "A"          # min_known 없으면 종전대로 평균
    assert overall([grade(1.6, sc)] * 3, min_known=3).letter == "A"


def test_overall_averages_known_grades_only():
    sc = margin_scale()
    gs = [grade(1.6, sc), grade(1.0, sc), grade(None, sc)]      # A, C, -
    o = overall(gs)
    assert o.letter == "B" and o.known                          # (5+3)/2 = 4 → B
    assert "2개 지표" in o.anchor_text
    assert overall([grade(None, sc)]).letter == "-"
    weighted = overall([grade(1.6, sc), grade(1.0, sc)], weights=[5.0, 1.0])
    assert weighted.letter in ("A", "B") and GRADES.index(weighted.letter) <= GRADES.index(o.letter)
