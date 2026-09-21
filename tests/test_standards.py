"""비교 규격(FAST SF · MICH/ACH · ACH Gen II): 출처 있는 값만 담고, 무게의 '범위'를 섞지 않는다."""

import pytest

from chiton_sim.helmet import (
    ACH_BLUNT_G_LIMIT, ACH_GEN2_AREAL_DENSITY, ACH_SIZES, BLUNT_G_LIMIT, FASTSF_AREAL_DENSITY,
    HELMET_STANDARDS, standard_warnings,
)
from chiton_sim.provenance import Label


def test_every_known_value_carries_a_source():
    """문헌값이면 출처가 있어야 하고, 없으면 미확인이어야 한다."""
    for std in HELMET_STANDARDS.values():
        for q in [std.blunt_g, std.blunt_v, std.areal_density, std.shell_thickness]:
            assert (q.label is Label.UNVERIFIED) or (q.source and "http" in q.source)
        for spec in std.sizes.values():
            assert spec.mass.label is Label.LITERATURE and "http" in spec.mass.source
            assert spec.coverage.label in (Label.LITERATURE, Label.UNVERIFIED)


def test_ach_blunt_criterion_matches_fast_sf():
    """MSA 공보의 '150 g @ 10 fps' 는 FAST SF 기준과 같은 값이다."""
    assert ACH_BLUNT_G_LIMIT.value == BLUNT_G_LIMIT.value == 150.0
    ach = HELMET_STANDARDS["ACH"]
    assert ach.blunt_v.value == pytest.approx(3.048)
    assert "10 fps" in ach.blunt_g.note or "10 ft/s" in ach.blunt_v.note


def test_ach_sizes_follow_the_army_chart_boundaries():
    """PS 642: 22.5 in = 573 mm, 23.5 in = 597 mm 경계. M 하한·XL 상한은 차트에 없다."""
    assert ACH_SIZES["M"] == (None, 0.573)
    assert ACH_SIZES["L"] == (0.573, 0.597)
    assert ACH_SIZES["XL"] == (0.597, None)
    sizes = HELMET_STANDARDS["ACH"].sizes
    assert sizes["M"].circ_mid == pytest.approx(0.573)        # 한쪽만 있으면 그 값
    assert sizes["L"].circ_mid == pytest.approx(0.585)
    assert HELMET_STANDARDS["FAST_SF"].sizes["L"].circ_mid == pytest.approx(0.575)


def test_mass_scope_difference_is_warned_not_hidden():
    """ACH 무게는 셸 단독이 아니다 — 경고 없이 셸 무게와 비교하면 안 된다."""
    ach = standard_warnings(HELMET_STANDARDS["ACH"])
    assert "STD_MASS_SCOPE" in ach.codes() and "STD_AD_UNKNOWN" in ach.codes()
    fast = standard_warnings(HELMET_STANDARDS["FAST_SF"])
    assert "STD_MASS_SCOPE" not in fast.codes() and "STD_AD_UNKNOWN" not in fast.codes()
    assert all("STD_BALLISTIC" in w.codes() for w in (ach, fast))


def test_areal_density_anchors():
    """면밀도 기준: FAST SF 는 문헌값, 원본 ACH 는 미확인, Gen II 는 문헌값."""
    assert FASTSF_AREAL_DENSITY.value == pytest.approx(5.957)
    assert HELMET_STANDARDS["ACH"].areal_density.value is None
    assert ACH_GEN2_AREAL_DENSITY.value == pytest.approx(6.9)
    assert "1.38" in ACH_GEN2_AREAL_DENSITY.note
