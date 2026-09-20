"""UI 전용 단위 변환. 계산 모듈(chiton_sim/*)은 이 모듈을 import 하지 않는다."""

from __future__ import annotations

G_PER_KG = 1000.0
MM_PER_M = 1000.0
CM2_PER_M2 = 1.0e4


def g_to_kg(g: float) -> float:
    return g / G_PER_KG


def kg_to_g(kg: float) -> float:
    return kg * G_PER_KG


def mm_to_m(mm: float) -> float:
    return mm / MM_PER_M


def m_to_mm(m: float) -> float:
    return m * MM_PER_M


def cm2_to_m2(cm2: float) -> float:
    return cm2 / CM2_PER_M2


def m2_to_cm2(m2: float) -> float:
    return m2 * CM2_PER_M2


def kg_m2_to_g_cm2(kg_m2: float) -> float:
    """면밀도 kg/m² → g/cm²."""
    return kg_m2 * G_PER_KG / CM2_PER_M2


def pa_to_mpa(pa: float) -> float:
    return pa / 1.0e6


def drop_table_to_si(df):
    """실험 CSV(mm, g, %) → SI 열로 변환한 새 DataFrame. 원래 열은 남겨 둔다.

    overlap_mm→overlap_m, thickness_mm→thickness_m, infill_pct→infill_frac, ball_g→ball_kg,
    dent_mm→dent_m, bfd_mm→bfd_m, clay_cal_mm→clay_cal_m
    """
    import pandas as pd

    out = df.copy()
    conv = {
        "overlap_mm": ("overlap_m", 1 / MM_PER_M),
        "thickness_mm": ("thickness_m", 1 / MM_PER_M),
        "infill_pct": ("infill_frac", 1 / 100.0),
        "ball_g": ("ball_kg", 1 / G_PER_KG),
        "dent_mm": ("dent_m", 1 / MM_PER_M),
        "bfd_mm": ("bfd_m", 1 / MM_PER_M),
        "clay_cal_mm": ("clay_cal_m", 1 / MM_PER_M),
    }
    for src, (dst, k) in conv.items():
        if src in out.columns:
            out[dst] = pd.to_numeric(out[src], errors="coerce") * k
    return out


def height_from_floors(n_floors: float, floor_height_m: float, start_height_m: float = 0.0) -> float:
    """낙하 높이 = 층수 × 층고 + 시작 높이 [m]."""
    if n_floors < 0 or floor_height_m <= 0:
        raise ValueError("층수는 0 이상, 층고는 양수여야 한다")
    return n_floors * floor_height_m + start_height_m
