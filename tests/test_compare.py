"""재료 비교 (PLAN §3-E 확장): 같은 두께 / 같은 면밀도, 미확인 물성 처리."""

import pytest

from chiton_sim.ball import Ball
from chiton_sim.compare import compare_materials, rank
from chiton_sim.materials import (
    ARAMID_EPOXY, BAMBU_PETG_HF, BAMBU_PLA_BASIC, FASTSF_HYBRID_SHELL, MATERIAL_LIBRARY,
    UHMWPE_LAMINATE, material_warnings,
)
from chiton_sim.provenance import Label, Quantity

BALL = Ball.standard('3/4"')
ALL = list(MATERIAL_LIBRARY.values())
AREA = Quantity(955e-4, "m^2", Label.LITERATURE, "FAST SF 데이터시트", "사이즈 L 커버리지")


def test_petg_hf_matches_tds():
    p = BAMBU_PETG_HF.props("XY")
    assert BAMBU_PETG_HF.density.value == 1280.0
    assert (p.flex_modulus.value, p.flex_modulus.sd) == (2050e6, 120e6)
    assert (p.flex_strength.value, p.flex_strength.sd) == (64e6, 3e6)
    assert BAMBU_PETG_HF.props("Z").flex_strength.value == 48e6
    assert BAMBU_PETG_HF.kind == "filament" and BAMBU_PETG_HF.printable


def test_real_helmet_materials_are_labelled_and_sourced():
    for m in (ARAMID_EPOXY, UHMWPE_LAMINATE, FASTSF_HYBRID_SHELL):
        assert m.kind == "composite" and not m.printable
        assert m.source and "복합 적층판" in "".join(m.notes)
        assert "composite_material" in material_warnings(m).codes()
    # 아라미드는 굽힘 물성이 있고, 나머지 둘은 굽힘강도가 미확인이다
    assert ARAMID_EPOXY.props("XY").flex_strength.value == pytest.approx(109.02e6)
    assert ARAMID_EPOXY.props("XY").flex_modulus.value == pytest.approx(10.38e9)
    assert not UHMWPE_LAMINATE.props("XY").flex_strength.known
    assert not FASTSF_HYBRID_SHELL.props("XY").flex_modulus.known
    # FAST SF 셸 밀도는 데이터시트 면밀도/두께에서 계산한 값이다
    assert FASTSF_HYBRID_SHELL.density.label is Label.COMPUTED
    assert FASTSF_HYBRID_SHELL.density.value == pytest.approx(5.957 / 5.58e-3)


def test_same_thickness_basis():
    rows = compare_materials(ALL, BALL, 2.0, 3e-3, 0.040, area=AREA, with_h50=False)
    assert all(r.thickness == 3e-3 for r in rows)
    for r in rows:
        if r.density:
            assert r.areal_density == pytest.approx(r.density * 3e-3)
            assert r.shell_mass == pytest.approx(r.density * 955e-4 * 3e-3)


def test_same_areal_density_basis_equalizes_mass():
    rows = compare_materials(ALL, BALL, 2.0, 3e-3, 0.040, basis="same_areal_density",
                             area=AREA, reference=BAMBU_PLA_BASIC, with_h50=False)
    ad = [r.areal_density for r in rows if r.areal_density]
    assert all(x == pytest.approx(ad[0]) for x in ad)
    uh = next(r for r in rows if r.name == UHMWPE_LAMINATE.name)
    assert uh.thickness == pytest.approx(3e-3 * 1240.0 / 970.0)   # 가벼운 재료는 두꺼워진다


def test_unknown_properties_are_reported_not_invented():
    rows = compare_materials([UHMWPE_LAMINATE, FASTSF_HYBRID_SHELL], BALL, 2.0, 3e-3, 0.040,
                             with_h50=False)
    for r in rows:
        assert not r.analyzable
        assert r.margin is None and r.sigma is None and r.h50 is None
        assert r.areal_density is not None          # 밀도는 있으니 면밀도는 나온다
        assert "no_flex_strength" in r.warnings.codes() or "no_flex_modulus" in r.warnings.codes()


def test_analyzable_materials_produce_consistent_numbers():
    rows = compare_materials([BAMBU_PLA_BASIC, BAMBU_PETG_HF, ARAMID_EPOXY], BALL, 2.0, 3e-3, 0.040)
    by = {r.name: r for r in rows}
    aram, pla = by[ARAMID_EPOXY.name], by[BAMBU_PLA_BASIC.name]
    assert aram.k_bending > pla.k_bending          # 적층판이 훨씬 뻣뻣하다
    assert aram.sigma > pla.sigma                  # 뻣뻣하면 하중을 더 끌어와 응력이 커진다
    for r in rows:
        assert r.margin == pytest.approx(r.strength / r.sigma)
        assert 0 < r.h50 <= 20.0
        assert r.E_abs > 0


def test_rank_orders_and_keeps_unknowns_last():
    rows = compare_materials(ALL, BALL, 2.0, 3e-3, 0.040, with_h50=False)
    ranked = rank(rows, "margin")
    known = [r for r in ranked if r.margin is not None]
    assert known == sorted(known, key=lambda r: r.margin, reverse=True)
    assert all(r.margin is None for r in ranked[len(known):])
    light = rank(rows, "areal_density")
    assert light[0].name == UHMWPE_LAMINATE.name   # 가장 가볍다
