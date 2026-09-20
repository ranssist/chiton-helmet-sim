"""라벨·출처 규칙과 SI 원칙 검사 (PLAN §5, §6)."""

import re
from dataclasses import fields
from pathlib import Path

import pytest

from chiton_sim import materials as M
from chiton_sim import units
from chiton_sim.provenance import Label, Quantity, SimInputError, WarningLog, Severity, unverified

PKG = Path(__file__).resolve().parents[1] / "chiton_sim"


def _all_quantities():
    for name, mat in M.MATERIAL_LIBRARY.items():
        yield f"{name}.density", mat.density
        yield f"{name}.poisson", mat.poisson
        for side in ("xy", "z"):
            op = getattr(mat, side)
            for f in fields(op):
                yield f"{name}.{side}.{f.name}", getattr(op, f.name)
    for name in dir(M):
        obj = getattr(M, name)
        if isinstance(obj, Quantity):
            yield name, obj
    for side in ("xy", "z"):
        op = getattr(M.BAMBU_PLA_BASIC, side)
        for f in fields(op):
            yield f"PLA.{side}.{f.name}", getattr(op, f.name)
    yield "PLA.density", M.BAMBU_PLA_BASIC.density
    yield "PLA.poisson", M.BAMBU_PLA_BASIC.poisson


def test_every_preset_has_source_or_is_labelled():
    for name, q in _all_quantities():
        if q.label is Label.LITERATURE:
            assert q.source, name
        elif q.label is Label.UNVERIFIED:
            assert q.value is None or q.source is None, name
        else:
            assert q.label in (Label.ASSUMPTION, Label.COMPUTED), name
            assert q.note, f"{name}: 가정·계산값에는 설명이 필요"


def test_literature_without_source_is_rejected():
    with pytest.raises(ValueError):
        Quantity(1.0, "Pa", Label.LITERATURE, None)
    with pytest.raises(ValueError):
        Quantity(None, "Pa", Label.ASSUMPTION)


def test_unverified_require_raises():
    with pytest.raises(SimInputError):
        unverified("kg").require("헤드폼 질량")


def test_pla_tds_values_match_sheet():
    p = M.BAMBU_PLA_BASIC
    assert p.density.value == 1240.0
    assert p.props("XY").flex_modulus.value == 2750e6 and p.props("XY").flex_modulus.sd == 160e6
    assert p.props("Z").flex_strength.value == 59e6
    assert p.props("Z").tensile_strength.value == 31e6
    assert p.poisson.label is Label.ASSUMPTION and p.poisson.value == 0.36


def test_epp_table_and_units():
    q = M.epp_stress(45, 0.25)
    assert q.label is Label.LITERATURE
    assert q.value == pytest.approx(42 * 6894.757)


def test_warning_log_dedup():
    log = WarningLog()
    log.add("x", Severity.WARNING, "a")
    log.add("x", Severity.WARNING, "a")
    assert len(log) == 1


def test_ui_units_roundtrip():
    assert units.kg_to_g(units.g_to_kg(28.27)) == pytest.approx(28.27)
    assert units.height_from_floors(5, 2.8, 1.0) == pytest.approx(15.0)
    assert units.kg_m2_to_g_cm2(5.957) == pytest.approx(0.5957)


def test_no_ui_unit_conversion_inside_calc_modules():
    """계산 모듈에 g/mm/cm 변환 상수가 없어야 한다 (units.py 제외)."""
    pat = re.compile(r"(\*|/)\s*(1000(\.0)?|1e3|1e-3|0\.001|100\.0|1e4|1e-4)\b")
    for f in PKG.glob("*.py"):
        if f.name == "units.py":
            continue
        src = f.read_text(encoding="utf-8")
        assert "import units" not in src and "from .units" not in src, f.name
        for i, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]
            assert not pat.search(code), f"{f.name}:{i}: {line.strip()}"
