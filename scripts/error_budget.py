"""보정 전 예측이 실제 실험과 얼마나 어긋날지: 항목별 민감도와 오차 예산.

기준 조건: 3/4" 크롬강 구, PLA Basic XY, 두께 3 mm, 고정 링 내반경 40 mm, 고정단.
판정은 참고 판정(Roark 굽힘응력 = 굽힘강도)을 쓴다. 지표는 임계 높이 h50.
"""
import math
import sys

import numpy as np
from scipy.optimize import brentq

from chiton_sim.ball import Ball
from chiton_sim.contact import ThorntonLaw, effective_modulus
from chiton_sim.fall import simulate_fall
from chiton_sim.impact import simulate_impact
from chiton_sim.plate import Plate, reference_stress

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BALL = Ball.standard('3/4"')
RHO, NU = 1240.0, 0.36
E0, SF0, T0, A0 = 2750e6, 76e6, 3.0e-3, 0.040
STEEL_E, STEEL_NU = 210e9, 0.30


def h_crit(E=E0, sf=SF0, py_ratio=1.6, bc="clamped", mode="2dof", t=T0, a=A0,
           ball=BALL, e_steel=STEEL_E, nu_steel=STEEL_NU):
    """참고 판정이 파손으로 뒤집히는 낙하 높이 [m]."""
    plate = Plate(E=E, nu=NU, rho=RHO, t=t, a=a, bc=bc)
    law = ThorntonLaw(effective_modulus(e_steel, nu_steel, E, NU), ball.radius, py_ratio * sf)

    def margin(h):
        v = simulate_fall(ball, h).v_impact
        r = simulate_impact(ball, v, plate, law, mode, n_per_segment=60, rtol=1e-8, step_div=150)
        return reference_stress(r.F_plate_max, plate, r.contact_radius).max - sf

    lo, hi = 0.3, 20.0
    if margin(lo) > 0:
        return lo
    if margin(hi) < 0:
        return float("nan")
    return brentq(margin, lo, hi, xtol=1e-3)


def at_2m(E=E0, sf=SF0, py_ratio=1.6, bc="clamped", mode="2dof", t=T0):
    plate = Plate(E=E, nu=NU, rho=RHO, t=t, a=A0, bc=bc)
    law = ThorntonLaw(effective_modulus(STEEL_E, STEEL_NU, E, NU), BALL.radius, py_ratio * sf)
    v = simulate_fall(BALL, 2.0).v_impact
    r = simulate_impact(BALL, v, plate, law, mode, n_per_segment=200)
    s = reference_stress(r.F_plate_max, plate, r.contact_radius).max
    return r, s


base_h = h_crit()
base_r, base_s = at_2m()
print(f"[기준] h50 = {base_h:.3f} m | 2 m 낙하에서 Fmax = {base_r.F_max:.0f} N, "
      f"판 반력 {base_r.F_plate_max:.0f} N, σ = {base_s/1e6:.1f} MPa, w/t = {base_r.w_max/T0:.2f}, "
      f"압흔 {base_r.dent*1e3:.3f} mm, e = {base_r.e:.3f}")
print()

cases = [
    ("굽힘탄성률 -1σ (2590 MPa)", dict(E=2590e6), "파라미터"),
    ("굽힘탄성률 +1σ (2910 MPa)", dict(E=2910e6), "파라미터"),
    ("굽힘강도 -1σ (71 MPa)", dict(sf=71e6), "파라미터"),
    ("굽힘강도 +1σ (81 MPa)", dict(sf=81e6), "파라미터"),
    ("강구 E 190 GPa, ν 0.27", dict(e_steel=190e9, nu_steel=0.27), "파라미터"),
    ("두께 -0.05 mm (프린터 공차)", dict(t=2.95e-3), "파라미터"),
    ("두께 +0.05 mm", dict(t=3.05e-3), "파라미터"),
    ("링 반경 +0.5 mm (치구 공차)", dict(a=0.0405), "파라미터"),
    ("p_y = 3.0·Y (Thornton 범위 상단)", dict(py_ratio=3.0), "모델 형태"),
    ("경계조건 단순지지", dict(bc="simply_supported"), "모델 형태"),
    ("판 관성 무시 (SDOF)", dict(mode="sdof"), "모델 형태"),
]

rows = []
for name, kw, kind in cases:
    h = h_crit(**kw)
    d = (h / base_h - 1) * 100
    rows.append((name, kind, h, d))
    print(f"{name:32s} {kind:6s} h50 = {h:6.3f} m   ({d:+6.1f} %)")

print()
# --- 막(membrane) 효과: Shivakumar Table 1 의 Km (고정단·이동불가) 을 넣었을 때의 정적 추정 ---
# Km = (353 - 191ν)πE h / (648(1-ν)a²),  P = Kb·w + Km·w³
Kb = 16 * math.pi * (E0 * T0**3 / (12 * (1 - NU**2))) / A0**2
Km = (353 - 191 * NU) * math.pi * E0 * T0 / (648 * (1 - NU) * A0**2)
law = ThorntonLaw(effective_modulus(STEEL_E, STEEL_NU, E0, NU), BALL.radius, 1.6 * SF0)
E_in = simulate_fall(BALL, 2.0).energy


def solve_static(with_membrane: bool):
    """에너지 균형(판 질량 무시): E_in = W_contact(δ) + ½Kb w² + ¼Km w⁴, F = Kb w + Km w³."""
    def total(w):
        F = Kb * w + (Km * w**3 if with_membrane else 0.0)
        # 접촉 변형: F = law.force_load(δ) 를 δ 에 대해 역산
        hi_d = 1e-6
        while law.force_load(hi_d) < F:
            hi_d *= 2.0
        d = brentq(lambda x: law.force_load(x) - F, 0.0, hi_d)
        return law.work_load(d) + 0.5 * Kb * w**2 + (0.25 * Km * w**4 if with_membrane else 0.0), F
    w = brentq(lambda w: total(w)[0] - E_in, 1e-9, 0.02)
    return w, total(w)[1]


w_lin, F_lin = solve_static(False)
w_mem, F_mem = solve_static(True)
print(f"[막 효과] Kb = {Kb/1e3:.1f} kN/m, Km = {Km/1e9:.2f} GN/m³")
print(f"  굽힘만:     w = {w_lin*1e3:.2f} mm, F = {F_lin:.0f} N")
print(f"  막 포함:    w = {w_mem*1e3:.2f} mm, F = {F_mem:.0f} N  → 힘 {100*(F_mem/F_lin-1):+.1f} %, "
      f"처짐 {100*(w_mem/w_lin-1):+.1f} %")
print()

# --- 합산 ---
par = [abs(d) for _, k, _, d in rows if k == "파라미터"]
mod = [abs(d) for _, k, _, d in rows if k == "모델 형태"]
rss_par = math.sqrt(sum((d / 100) ** 2 for d in par[::2]) if par else 0) * 100
print(f"파라미터 효과 개별 범위: {min(par):.1f} ~ {max(par):.1f} %")
print(f"모델 형태 효과 개별 범위: {min(mod):.1f} ~ {max(mod):.1f} %")
print(f"막 효과(정적 추정, 힘 기준): {100*(F_mem/F_lin-1):+.1f} %")
