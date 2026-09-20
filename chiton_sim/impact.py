"""구슬-판 충돌: 2자유도 스프링-질량 모델 (PLAN §3-D).

Shivakumar, Elber & Illg (1985) J. Appl. Mech. 52:674, doi:10.1115/1.3169120 의 2자유도 모델을 따르되
- 접촉 스프링: Thornton(1997) 탄성-완전소성 (contact.py)
- 판 스프링: 굽힘만 (전단·막 강성 생략, 가정 A-07)
- 접촉은 단방향(인장 불허)이며 분리·재접촉을 허용한다. 원 모델은 인장 접촉을 허용한다.

m1 ẍ1 = −F_c(δ),   m2 ẍ2 = F_c(δ) − K_b x2,   δ = x1 − x2
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from .ball import Ball
from .contact import HertzImpact, ThorntonLaw, check_hertz_validity, hertz_impact
from .fall import V_STRAIN_RATE
from .plate import Plate
from .provenance import Basis, Severity, WarningLog

IMPULSE_NOTE = "충격량은 공 질량·속도·반발계수로 거의 정해지므로 파손 판정 지표가 아님"

# 적용범위 기준
SRC_OLSSON = "R. Olsson, Compos. Part A 31:879 (2000) — 충격체가 판 질량의 약 1/4 미만이면 파동 지배"
MASS_RATIO_WAVE = 0.25        # Olsson (2000)
MASS_RATIO_QUASI = 3.5        # Shivakumar 외 NASA TM-85703: 충격체 > 판 질량 3.5배면 판 관성 무시 가능
W_OVER_T_INFO = 0.2           # Shivakumar 외 (Timoshenko 인용): w/h ≤ 0.2 에서 막 효과 무시 가능
W_OVER_T_WARN = 0.5           # 요청서 지정 경고 임계

MODES = ("2dof", "sdof", "rigid")


@dataclass
class ImpactResult:
    mode: str
    v_in: float
    v_out: float
    e: float
    F_max: float            # 최대 접촉력 [N]
    F_plate_max: float      # 최대 판 반력 K_b·w_max [N]
    w_max: float            # 최대 판 중앙 처짐 [m]
    delta_max: float        # 최대 접근량 [m]
    dent: float             # 잔류 압흔 깊이 δ_p [m]
    contact_radius: float   # 최대하중 시 접촉 반경 [m]
    tc: float               # 첫 접촉 ~ 마지막 분리 [s]
    n_contacts: int
    J: float                # ∫F dt [N·s]
    J_expected: float       # m1(v_in − v_out) = m1 v_in (1+e)
    J_rel_err: float
    avg_force: float        # J / tc
    energy: dict[str, float]
    mass_ratio: float       # m1 / 판 전체 질량 (rigid 이면 inf)
    hertz_ref: HertzImpact
    basis: Basis
    warnings: WarningLog
    t: np.ndarray = field(repr=False)
    F: np.ndarray = field(repr=False)
    delta: np.ndarray = field(repr=False)
    w: np.ndarray = field(repr=False)
    v1: np.ndarray = field(repr=False)

    @property
    def E_abs(self) -> float:
        """판이 흡수한 에너지 = E_in − E_rebound (가정 A-16)."""
        return self.energy["in"] - self.energy["rebound"]


class _Contact:
    """Thornton 이력 상태."""

    def __init__(self, law: ThorntonLaw):
        self.law = law
        self.dmax = 0.0
        self.Fm = 0.0
        self.Rp = law.R
        self.dp = 0.0

    def force(self, mode: str, d: float) -> float:
        if mode == "load":
            return self.law.force_load(d)
        if mode == "unload":
            return self.law.force_unload(d, self.Rp, self.dp)
        return 0.0

    def turn(self, d: float) -> None:
        self.dmax = max(self.dmax, d)
        self.Fm, self.Rp, self.dp = self.law.unload_params(self.dmax)


def _time_scales(m1: float, law: ThorntonLaw, v: float, Kb: float | None, m2: float | None,
                 step_div: int = 300):
    h = hertz_impact(m1, law.R, v, law.E_star)
    ts = h.tc
    step = h.tc / step_div
    if Kb:
        ts = max(ts, math.pi * math.sqrt(m1 / Kb))
        step = min(step, ts / step_div)
        if m2:
            step = min(step, 2 * math.pi * math.sqrt(m2 / Kb) / max(step_div // 5, 10))
    return h, ts, step


def _run_2dof(m1, m2, Kb, law, v_in, n_seg, rtol=1e-10, step_div=300):
    c = _Contact(law)
    h, ts, max_step = _time_scales(m1, law, v_in, Kb, m2, step_div)
    t_end = 12.0 * ts
    omega = math.sqrt(Kb / m2)

    def rhs_for(mode):
        def rhs(_t, y):
            F = c.force(mode, y[0] - y[2])
            return [y[1], -F / m1, y[3], (F - Kb * y[2]) / m2, F]
        return rhs

    y = np.array([0.0, v_in, 0.0, 0.0, 0.0])
    t0, mode = 0.0, "load"
    ts_out, ys_out, modes_out = [], [], []
    contacts: list[list[float]] = [[0.0, math.nan]]
    ended_in_contact = False
    while t0 < t_end:
        if mode == "load":
            ev = lambda t, y: y[1] - y[3]
            ev.terminal, ev.direction = True, -1
            events = [ev]
        elif mode == "unload":
            sep = lambda t, y: (y[0] - y[2]) - c.dp
            sep.terminal, sep.direction = True, -1
            rel = lambda t, y: (y[0] - y[2]) - c.dmax
            rel.terminal, rel.direction = True, 1
            events = [sep, rel]
        else:
            A = math.hypot(y[2], y[3] / omega)  # 자유 진동 진폭
            touch = lambda t, y: (y[0] - y[2]) - c.dp
            touch.terminal, touch.direction = True, 1
            gone = lambda t, y, A=A: (y[0] - c.dp) + A * 1.0000001
            gone.terminal, gone.direction = True, -1
            events = [touch, gone]
        sol = solve_ivp(rhs_for(mode), (t0, t_end), y, method="DOP853", rtol=rtol, atol=1e-14,
                        events=events, dense_output=True, max_step=max_step)
        t1 = sol.t[-1]
        tt = np.linspace(t0, t1, n_seg)
        ts_out.append(tt)
        ys_out.append(sol.sol(tt))
        modes_out.append((mode, tt.size))
        y = sol.y[:, -1].copy()
        hit = [i for i, te in enumerate(sol.t_events) if te.size]
        t0 = t1
        if not hit:
            ended_in_contact = mode != "free"
            break
        i = hit[0]
        if mode == "load":
            c.turn(y[0] - y[2])
            mode = "unload"
        elif mode == "unload":
            if i == 0:
                mode = "free"
                contacts[-1][1] = t1
            else:
                mode = "load"
        else:
            if i == 0:
                mode = "unload" if c.dmax > 0 else "load"
                contacts.append([t1, math.nan])
            else:
                break  # 재접촉 불가: 종료
    return c, h, ts_out, ys_out, modes_out, contacts, y, ended_in_contact


def _solve_w(c: _Contact, mode: str, x1: float, Kb: float | None) -> float:
    """SDOF/강체 지지: 판 처짐 w (K_b w = F_c(x1 − w))."""
    if Kb is None:
        return 0.0
    if c.force(mode, x1) <= 0.0:
        return 0.0
    g = lambda w: Kb * w - c.force(mode, x1 - w)
    return brentq(g, 0.0, x1, xtol=1e-16, rtol=1e-13)


def _run_1dof(m1, Kb, law, v_in, n_seg, rtol=1e-10, step_div=300):
    c = _Contact(law)
    h, ts, max_step = _time_scales(m1, law, v_in, Kb, None, step_div)
    t_end = 12.0 * ts

    def rhs_for(mode):
        def rhs(_t, y):
            w = _solve_w(c, mode, y[0], Kb)
            F = c.force(mode, y[0] - w)
            return [y[1], -F / m1, F]
        return rhs

    y = np.array([0.0, v_in, 0.0])
    t0, mode = 0.0, "load"
    ts_out, ys_out, modes_out = [], [], []
    ended_in_contact = True
    x1_turn = 0.0
    while t0 < t_end:
        if mode == "load":
            ev = lambda t, y: y[1]
            ev.terminal, ev.direction = True, -1
            events = [ev]
        else:
            sep = lambda t, y: y[0] - c.dp
            sep.terminal, sep.direction = True, -1
            rel = lambda t, y: y[0] - x1_turn
            rel.terminal, rel.direction = True, 1
            events = [sep, rel]
        sol = solve_ivp(rhs_for(mode), (t0, t_end), y, method="DOP853", rtol=rtol, atol=1e-14,
                        events=events, dense_output=True, max_step=max_step)
        t1 = sol.t[-1]
        tt = np.linspace(t0, t1, n_seg)
        ts_out.append(tt)
        ys_out.append(sol.sol(tt))
        modes_out.append((mode, tt.size))
        y = sol.y[:, -1].copy()
        hit = [i for i, te in enumerate(sol.t_events) if te.size]
        t0 = t1
        if not hit:
            break
        if mode == "load":
            x1_turn = y[0]
            w = _solve_w(c, "load", y[0], Kb)
            c.turn(y[0] - w)
            mode = "unload"
        elif hit[0] == 0:
            ended_in_contact = False
            break
        else:
            mode = "load"
    return c, h, ts_out, ys_out, modes_out, [[0.0, t0]], y, ended_in_contact


def simulate_impact(
    ball: Ball,
    v_in: float,
    plate: Plate | None,
    law: ThorntonLaw,
    mode: str = "2dof",
    yield_proxy: float | None = None,
    basis: Basis = Basis.PRE,
    n_per_segment: int = 400,
    rtol: float = 1e-10,
    step_div: int = 300,
) -> ImpactResult:
    """구슬이 판 중앙을 v_in [m/s] 로 칠 때의 응답.

    mode: "2dof"(기본) | "sdof"(판 질량 무시) | "rigid"(강체 지지)
    yield_proxy: Hertz 유효성 검사용 Y [Pa] (굽힘강도 대용값, A-05)
    rtol/step_div: 적합 루프처럼 속도가 필요할 때 낮춘다(기본값은 정밀 계산용)
    """
    if mode not in MODES:
        raise ValueError(f"mode 는 {MODES} 중 하나")
    if v_in <= 0:
        raise ValueError("충돌 속도는 양수여야 한다")
    if mode != "rigid" and plate is None:
        raise ValueError("판이 필요하다")
    log = WarningLog()
    m1 = ball.mass
    Kb = None if mode == "rigid" else plate.k_bending()
    m2 = plate.m_eff if plate is not None else None

    if mode == "2dof":
        c, href, ts_out, ys_out, modes_out, contacts, y_end, open_ = _run_2dof(
            m1, m2, Kb, law, v_in, n_per_segment, rtol, step_div)
        t = np.concatenate(ts_out)
        Y = np.concatenate(ys_out, axis=1)
        x1, v1, x2, v2, Jst = Y
        mode_arr = np.concatenate([[m] * n for m, n in modes_out])
        delta = x1 - x2
        w = x2
        F = np.array([c.force(md, d) for md, d in zip(mode_arr, delta)])
        v_out = float(y_end[1])
        J = float(y_end[4])
        E_plate = 0.5 * m2 * y_end[3] ** 2 + 0.5 * Kb * y_end[2] ** 2
    else:
        c, href, ts_out, ys_out, modes_out, contacts, y_end, open_ = _run_1dof(
            m1, Kb, law, v_in, n_per_segment, rtol, step_div)
        t = np.concatenate(ts_out)
        Y = np.concatenate(ys_out, axis=1)
        x1, v1, Jst = Y
        mode_arr = np.concatenate([[m] * n for m, n in modes_out])
        w = np.array([_solve_w(c, md, xx, Kb) for md, xx in zip(mode_arr, x1)])
        delta = x1 - w
        F = np.array([c.force(md, d) for md, d in zip(mode_arr, delta)])
        v_out = float(y_end[1])
        J = float(y_end[2])
        E_plate = 0.0

    if open_:
        log.add("no_separation", Severity.WARNING, "적분 시간 안에 접촉이 끝나지 않았다(결과 불완전)")
    contacts = [ci for ci in contacts if not math.isnan(ci[1])] or contacts
    t_last = contacts[-1][1] if not math.isnan(contacts[-1][1]) else float(t[-1])
    tc = t_last - contacts[0][0]

    E_in = 0.5 * m1 * v_in**2
    E_reb = 0.5 * m1 * v_out**2
    E_pl = law.work_load(c.dmax) - law.work_unload(c.dmax) if c.dmax > law.delta_y else 0.0
    balance = E_in - E_reb - E_pl - E_plate
    energy = {"in": float(E_in), "rebound": float(E_reb), "plastic": float(E_pl),
              "plate": float(E_plate), "balance_err": float(balance / E_in)}

    J_exp = m1 * (v_in - v_out)
    e = -v_out / v_in
    w_max = float(np.max(w)) if w.size else 0.0
    mass_ratio = m1 / plate.mass if (plate is not None and mode != "rigid") else math.inf

    # --- 적용범위 경고 ----------------------------------------------------
    if plate is not None and mode != "rigid":
        if mass_ratio < MASS_RATIO_WAVE:
            log.add("wave_dominated", Severity.WARNING,
                    f"구슬/판 질량비 {mass_ratio:.2f} < 0.25: 파동 지배 충돌이라 준정적 모델이 부정확하다 (Olsson 2000)")
        elif mass_ratio < MASS_RATIO_QUASI:
            log.add("mass_ratio_mid", Severity.INFO,
                    f"구슬/판 질량비 {mass_ratio:.2f}: 중간 영역 — 판 관성을 무시할 수 없어 2자유도 결과를 쓴다 (Shivakumar 1985)")
        wt = w_max / plate.t
        if wt > W_OVER_T_WARN:
            log.add("membrane", Severity.WARNING, f"처짐 w/t = {wt:.2f} > 0.5: 막(membrane) 효과가 누락된다")
        elif wt > W_OVER_T_INFO:
            log.add("membrane_info", Severity.INFO,
                    f"처짐 w/t = {wt:.2f} > 0.2: 막 효과가 나타나기 시작할 수 있다 (Shivakumar 1985)")
    if v_in > V_STRAIN_RATE:
        log.add("strain_rate", Severity.WARNING, f"충돌 속도 {v_in:.2f} m/s > 10 m/s: 변형률 속도 효과 누락")
    if yield_proxy is not None:
        check_hertz_validity(href.p0, yield_proxy, log)

    return ImpactResult(
        mode=mode, v_in=v_in, v_out=v_out, e=e,
        F_max=float(np.max(F)), F_plate_max=(Kb * w_max if Kb else float(np.max(F))),
        w_max=w_max, delta_max=c.dmax, dent=c.dp, contact_radius=law.contact_radius(c.dmax),
        tc=tc, n_contacts=len(contacts), J=J, J_expected=J_exp,
        J_rel_err=abs(J - J_exp) / J_exp, avg_force=J / tc if tc > 0 else math.nan,
        energy=energy, mass_ratio=mass_ratio, hertz_ref=href, basis=basis, warnings=log,
        t=t, F=F, delta=delta, w=w, v1=v1,
    )
