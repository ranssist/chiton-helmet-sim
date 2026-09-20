"""군부 겹판 접이식 분할 헬멧 — 낙하 충격 시뮬레이터 (Streamlit UI).

단위 변환(g, mm, cm, 층)은 이 파일과 chiton_sim.units 에서만 한다. 계산은 전부 SI 다.
실행: streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from chiton_sim import units
from chiton_sim.ball import Ball, GuideTube, STANDARD_BALL_INCHES
from chiton_sim.calibration import (
    CRITERIA_SUGGESTIONS, FailureCriteria, RigSetup, fold_trend, load_criteria, run_calibration,
    save_criteria, validate_schema,
)
from chiton_sim.contact import SRC_THORNTON, SRC_YIELD_16
from chiton_sim.fall import H_MAX, H_MIN, FallParams, simulate_fall
from chiton_sim.failure import failure_probability_curve, main_judgment, reference_judgment
from chiton_sim.helmet import (
    BLUNT_G_LIMIT, BLUNT_VELOCITY, FASTSF_AREAL_DENSITY, FASTSF_SHELL_L_DATASHEET,
    FASTSF_SHELL_L_NEXTGEN, FASTSF_SIZES, FASTSF_XXL_NOTE, FMVSS218_HEADFORMS, LinerModel,
    measurement_check, required_spread_area, segmented_spread_area, shell_areal_density,
    shell_mass, simulate_headform, thickness_for_mass,
)
from chiton_sim.impact import IMPULSE_NOTE
from chiton_sim.materials import (
    BAMBU_PLA_BASIC, EPP_ARPRO_TABLE, EPP_NOTE, epp_stress, user_filament,
)
from chiton_sim.planner import (
    curvature_check, equal_energy_pair, specimen_plan, staircase_progress, velocity_effect_test,
)
from chiton_sim.provenance import (
    NEEDS_MEASUREMENT, NOT_ANALYZABLE, Basis, Label, Quantity, Severity, SimInputError,
    WarningLog, assumed, computed, unverified,
)
from chiton_sim.segments import (
    CONFIG_TYPES, FASTENER_TYPES, IMPACT_SITES, JOINT_TYPES, VENT_TYPES, FastenerSpec,
    SpecimenConfig, VentSpec, areal_density, assess_site, equal_areal_density_thickness,
    overlap_ratio,
)

ACCENT = "#C2410C"
GRAYS = ["#111111", "#555555", "#888888", "#BBBBBB", "#DDDDDD"]
DISCLAIMER = """**범위와 면책** · 이 시뮬레이터는 PLA 등 FDM 출력물의 둔탁 충격 거동 모델이다.
방탄 성능은 다루지 않으며, 용어는 '방탄판'이 아니라 '충격 분산판'을 쓴다.
IHPS·FAST(UHMWPE 등 복합재 셸)의 성능을 예측하지 않는다. FAST SF 수치는 치수·무게·시험 조건의 비교 기준으로만 쓴다."""

st.set_page_config(page_title="군부 겹판 분할 헬멧 낙하 충격 시뮬레이터", layout="wide")
st.markdown(
    f"""<style>
    .stApp {{ background:#FFFFFF; }}
    div[data-testid="stMetricValue"] {{ font-size:1.25rem; }}
    .lbl {{ font-size:0.78rem; color:#666; }}
    .acc {{ color:{ACCENT}; }}
    </style>""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# 표시 도우미
# ---------------------------------------------------------------------------
def q_text(q: Quantity, fmt: str = "{:.4g}", scale: float = 1.0, unit: str = "") -> str:
    if not q.known:
        return f"미확인 · {q.note}"
    return f"{fmt.format(q.value * scale)} {unit or q.unit} [{q.label.value}]"


def show_warnings(log: WarningLog) -> None:
    for w in log:
        if w.severity is Severity.WARNING:
            st.warning(f"⚠ {w.message}")
        elif w.severity is Severity.BLOCK:
            st.error(w.message)
        else:
            st.info(w.message)


def plotly_layout(fig: go.Figure, xtitle: str, ytitle: str, height: int = 340) -> go.Figure:
    fig.update_layout(template="simple_white", height=height, margin=dict(l=60, r=20, t=30, b=50),
                      font=dict(color="#1A1A1A"), xaxis_title=xtitle, yaxis_title=ytitle,
                      showlegend=True, legend=dict(orientation="h", y=1.12, x=0))
    return fig


def download_df(df: pd.DataFrame, name: str, key: str) -> None:
    st.download_button("CSV 내보내기", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=name, mime="text/csv", key=key)


PLOT_CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}


# ---------------------------------------------------------------------------
# 사이드바 입력
# ---------------------------------------------------------------------------
def sidebar():
    s = {}
    st.sidebar.header("낙하 조건")
    mode = st.sidebar.radio("모드", ["가이드관 낙하탑 (1.5–2 m)", "5층 낙하 (12–15 m)"], index=0)
    how = st.sidebar.radio("높이 입력", ["직접 (m)", "층수 × 층고 + 시작 높이"], index=0, horizontal=True)
    if how == "직접 (m)":
        default = 2.0 if mode.startswith("가이드관") else 13.0
        h = st.sidebar.number_input("낙하 높이 [m]", H_MIN, H_MAX, default, 0.05)
    else:
        n = st.sidebar.number_input("층수", 0.0, 8.0, 5.0, 1.0)
        fh = st.sidebar.number_input("층고 [m]", 1.0, 6.0, 2.8, 0.1)
        h0 = st.sidebar.number_input("시작 높이 [m]", 0.0, 5.0, 1.0, 0.1)
        h = units.height_from_floors(n, fh, h0)
        st.sidebar.caption(f"= {h:.2f} m")
    s["height"] = float(h)

    st.sidebar.header("구슬")
    pick = st.sidebar.selectbox("규격 강구 스냅", ["(질량 직접 입력)"] + list(STANDARD_BALL_INCHES))
    if pick == "(질량 직접 입력)":
        g = st.sidebar.number_input("질량 [g]", 0.5, 2000.0, 28.27, 0.01)
        ball = Ball.from_mass(units.g_to_kg(g))
    else:
        ball = Ball.standard(pick)
    st.sidebar.caption(f"질량 {units.kg_to_g(ball.mass):.2f} g · 지름 {units.m_to_mm(ball.diameter):.3f} mm "
                       f"(크롬강 7.81 g/cm³ [문헌값])")
    s["ball"] = ball

    st.sidebar.header("가이드관")
    use_tube = st.sidebar.checkbox("가이드관 사용", value=True)
    tube = None
    if use_tube:
        tmode = st.sidebar.radio("관 종류", ["직접 입력", "500 mL PET병"], horizontal=True)
        length = st.sidebar.number_input("관 길이 [m]", 0.1, 20.0, min(1.8, s["height"]), 0.1)
        if tmode == "직접 입력":
            idmm = st.sidebar.number_input("최소 내경 [mm]", 5.0, 200.0, 22.0, 0.5)
            clr = st.sidebar.number_input("여유 [mm]", 0.0, 10.0, 1.0, 0.1)
            tube = GuideTube(assumed(units.mm_to_m(idmm), "m", "사용자 입력 내경"), length,
                             assumed(units.mm_to_m(clr), "m", "사용자 입력 여유"))
        else:
            tube = GuideTube.pet_bottle(length)
    s["tube"] = tube

    st.sidebar.header("시편 구성")
    cfg_type = st.sidebar.selectbox("config_type", CONFIG_TYPES)
    t_mm = st.sidebar.number_input("두께 [mm]", 0.4, 20.0, 3.0, 0.1)
    a_mm = st.sidebar.number_input("고정 링 내반경 [mm]", 5.0, 200.0, 40.0, 1.0)
    bc = st.sidebar.selectbox("경계조건", ["clamped", "simply_supported"],
                              format_func=lambda x: "고정단" if x == "clamped" else "단순지지")
    orient = st.sidebar.selectbox("출력 방향", ["XY", "Z"])
    infill = st.sidebar.slider("인필 [%]", 10, 100, 100, 5)
    annealed = st.sidebar.checkbox("어닐링함 (55 °C·8 h)", value=True)
    ovl_mm = n_seg = 0.0
    lock = False
    joint = None
    seam_mm = None
    if cfg_type != "monolithic":
        n_seg = st.sidebar.number_input("분할 판 수", 2, 24, 3, 1)
        lock = st.sidebar.checkbox("잠금(lock)", value=True)
        joint = st.sidebar.selectbox("joint_type", JOINT_TYPES)
        if cfg_type == "segmented_overlap":
            ovl_mm = st.sidebar.number_input("겹침 폭 [mm]", 0.0, 50.0, 5.0, 0.5)
            sl = st.sidebar.number_input("이음선 총 길이 [mm] (CAD, 0=미입력)", 0.0, 2000.0, 120.0, 5.0)
            seam_mm = sl if sl > 0 else None

    st.sidebar.header("군부의 눈 요소")
    fst = st.sidebar.selectbox("fastener_type", ["(없음)"] + list(FASTENER_TYPES))
    fastener = None
    if fst != "(없음)":
        c1, c2 = st.sidebar.columns(2)
        fn = c1.number_input("개수", 1, 20, 4, 1)
        fd = c2.number_input("구멍 지름 [mm]", 1.0, 20.0, 4.0, 0.5)
        fp = c1.number_input("피치 [mm]", 2.0, 200.0, 20.0, 1.0)
        fe = c2.number_input("모서리 거리 [mm]", 1.0, 100.0, 8.0, 0.5)
        use_lim = st.sidebar.checkbox("p/d·e/d 기준값 직접 입력 (문헌 기준 미확인)")
        pd_min = assumed(st.sidebar.number_input("p/d 최소", 1.0, 10.0, 4.0, 0.1), "-", "사용자 입력") if use_lim else None
        ed_min = assumed(st.sidebar.number_input("e/d 최소", 1.0, 10.0, 3.0, 0.1), "-", "사용자 입력") if use_lim else None
        kw = {}
        if pd_min is not None:
            kw = {"p_d_min": pd_min, "e_d_min": ed_min}
        fastener = FastenerSpec(fst, int(fn), units.mm_to_m(fd), units.mm_to_m(fp), units.mm_to_m(fe), **kw)
    vt = st.sidebar.selectbox("vent_type", ["(없음)"] + list(VENT_TYPES))
    vent = None
    if vt != "(없음)":
        c1, c2 = st.sidebar.columns(2)
        vn = c1.number_input("통기구 개수", 1, 40, 6, 1)
        vd = c2.number_input("통기구 지름 [mm]", 1.0, 40.0, 8.0, 0.5)
        vent = VentSpec(vt, int(vn), units.mm_to_m(vd))

    s["cfg"] = SpecimenConfig(
        config_type=cfg_type, thickness=units.mm_to_m(t_mm), ring_radius=units.mm_to_m(a_mm),
        orientation=orient, infill=infill / 100.0, annealed=annealed, bc=bc,
        overlap=units.mm_to_m(ovl_mm), n_segments=int(n_seg) if cfg_type != "monolithic" else 1,
        lock=lock, joint_type=joint,
        seam_length=units.mm_to_m(seam_mm) if seam_mm else None,
        fastener=fastener, vent=vent,
    )
    s["site"] = st.sidebar.selectbox("타격 위치 (impact_site)", IMPACT_SITES)

    st.sidebar.header("재료")
    mat_choice = st.sidebar.radio("재료", ["Bambu PLA Basic (TDS)", "사용자 TDS 입력"], index=0)
    if mat_choice.startswith("Bambu"):
        material = BAMBU_PLA_BASIC
    else:
        with st.sidebar.expander("사용자 TDS", expanded=True):
            name = st.text_input("이름", "PETG (사용자)")
            src = st.text_input("출처 URL (없으면 '미확인'으로 표시)", "")
            rho = st.number_input("밀도 [g/cm³]", 0.5, 3.0, 1.27, 0.01)
            nu = st.number_input("푸아송비 (가정)", 0.1, 0.49, 0.38, 0.01)
            fm = st.number_input("굽힘탄성률 XY [MPa]", 100.0, 10000.0, 1500.0, 10.0)
            fs = st.number_input("굽힘강도 XY [MPa]", 5.0, 300.0, 60.0, 1.0)
            fmz = st.number_input("굽힘탄성률 Z [MPa]", 100.0, 10000.0, 1300.0, 10.0)
            fsz = st.number_input("굽힘강도 Z [MPa]", 5.0, 300.0, 40.0, 1.0)
        material = user_filament(
            name, src or None, rho * 1e3, nu,
            {"flex_modulus": fm * 1e6, "flex_strength": fs * 1e6, "tensile_strength": None,
             "youngs_modulus": None, "elongation": None, "impact_unnotched": None},
            {"flex_modulus": fmz * 1e6, "flex_strength": fsz * 1e6, "tensile_strength": None,
             "youngs_modulus": None, "elongation": None, "impact_unnotched": None},
        )
    s["material"] = material

    st.sidebar.header("보정")
    rep = st.session_state.get("report")
    # 보정 결과가 새로 생기면 키가 바뀌어 기본값(True)으로 다시 그려진다
    s["use_calib"] = st.sidebar.checkbox("보정 결과 사용", value=bool(rep), disabled=not rep,
                                         key=f"use_calib_{bool(rep)}")
    if rep and s["use_calib"]:
        st.sidebar.caption(f"η = {rep.tube.eta.value:.4f}, p_y = {rep.py.py.value/1e6:.0f} MPa [보정 후]"
                           if rep.tube and rep.py else "보정 결과 일부만 적용")
    return s


def current_params(s) -> FallParams:
    rep = st.session_state.get("report")
    if s["use_calib"] and rep is not None:
        return rep.params
    return FallParams()


def current_py(s) -> Quantity:
    rep = st.session_state.get("report")
    if s["use_calib"] and rep is not None and rep.py is not None:
        return rep.py.py
    Y = s["material"].props(s["cfg"].orientation).flex_strength
    if not Y.known:
        return unverified("Pa", "굽힘강도 미입력 — p_y 를 정할 수 없다")
    return Quantity(1.6 * Y.value, "Pa", Label.ASSUMPTION, None,
                    f"p_y = 1.6·Y (Y=굽힘강도 대용값). {SRC_YIELD_16}")


# ---------------------------------------------------------------------------
# 탭 1 — 판 충돌
# ---------------------------------------------------------------------------
def tab_impact(s):
    cfg, mat = s["cfg"], s["material"]
    params = current_params(s)
    py = current_py(s)
    try:
        fall = simulate_fall(s["ball"], s["height"], s["tube"], params)
    except (SimInputError, Exception) as exc:  # GuideTubeError 포함
        st.error(str(exc))
        return
    basis = Basis.POST if (fall.basis is Basis.POST or py.label is Label.CALIBRATED) else Basis.PRE
    st.markdown(f"#### 결과 기준: <span class='acc'>{basis.value}</span>", unsafe_allow_html=True)

    try:
        assess = assess_site(s["ball"], fall.v_impact, mat, cfg, s["site"], py,
                             calib=_site_calib(s), mode="2dof")
    except SimInputError as exc:
        st.error(str(exc))
        return

    if not assess.numeric:
        st.error(f"{s['site']} 위치: {assess.status} — 이 위치에는 신뢰할 해석식이 없다. "
                 "보정 데이터를 올리면 실측 기반 값으로 표시한다.")
        show_warnings(assess.warnings)
        return

    bc0 = "clamped" if "clamped" in assess.cases else list(assess.cases)[0]
    case = assess.cases[bc0]
    imp = case.impact
    strength = mat.props(cfg.orientation).flex_strength
    ref = reference_judgment(case.sigma_local, strength)
    rep = st.session_state.get("report")
    fit = None
    if s["use_calib"] and rep is not None:
        fit = rep.ec_fits.get((cfg.config_type, s["site"]))
    main = main_judgment(imp.E_abs, fit, cfg.thickness)

    cols = st.columns(6)
    cols[0].metric("충돌 속도", f"{fall.v_impact:.2f} m/s", f"손실 {fall.loss_frac*100:.2f} %")
    cols[1].metric("충돌 에너지", f"{fall.energy:.3f} J")
    cols[2].metric("충격량", f"{imp.J*1e3:.1f} mN·s", f"e = {imp.e:.2f}")
    cols[3].metric("최대 접촉력", f"{imp.F_max:.0f} N", f"판 반력 {imp.F_plate_max:.0f} N")
    cols[4].metric("접촉시간", f"{imp.tc*1e3:.3f} ms", f"접촉 {imp.n_contacts}회")
    verdict = "파손" if ref.fail else "유지"
    if main.fail is not None:
        verdict = f"{verdict} / 주판정 {'파손' if main.fail else '유지'}"
    cols[5].metric("판정", verdict, f"여유율 {ref.margin:.2f}")
    st.caption(f"참고 판정: 굽힘응력 {case.sigma_local/1e6:.0f} MPa vs 굽힘강도 {ref.strength/1e6:.0f} MPa "
               f"[문헌값] · 주 판정: {q_text(main.Ec, unit='J')} · {IMPULSE_NOTE}")

    if len(assess.cases) > 1:
        other = assess.cases["simply_supported"]
        st.info("분할 + 잠금 on: 고정단(상한)~단순지지(하한) 구간으로 본다 — "
                f"최대 접촉력 {other.impact.F_max:.0f}–{imp.F_max:.0f} N, "
                f"응력 {min(case.sigma_local, other.sigma_local)/1e6:.0f}–"
                f"{max(case.sigma_local, other.sigma_local)/1e6:.0f} MPa")

    c1, c2 = st.columns([3, 2])
    with c1:
        fig = go.Figure()
        for i, (bc, cr) in enumerate(assess.cases.items()):
            fig.add_trace(go.Scatter(x=cr.impact.t * 1e3, y=cr.impact.F, mode="lines",
                                     name=f"F(t) · {bc}", line=dict(color=ACCENT if i == 0 else GRAYS[1])))
        plotly_layout(fig, "시간 [ms]", "접촉력 [N]")
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)
    with c2:
        e = imp.energy
        fig2 = go.Figure(go.Bar(
            x=["판 굽힘·진동", "압흔 소성", "반발"],
            y=[e["plate"], e["plastic"], e["rebound"]],
            marker_color=[GRAYS[1], ACCENT, GRAYS[3]]))
        plotly_layout(fig2, "", "에너지 [J]")
        st.plotly_chart(fig2, width="stretch", config=PLOT_CONFIG)
        st.caption(f"입력 {e['in']:.3f} J · 검산 오차 {abs(e['balance_err'])*100:.2g} % · "
                   f"∫F dt 검산 {imp.J_rel_err*100:.1e} %")

    with st.expander("참고: 탄성 Hertz 값과 적용범위"):
        h = imp.hertz_ref
        st.write(f"- δmax {h.delta_max*1e6:.1f} µm · Fmax {h.F_max:.0f} N · 접촉시간 {h.tc*1e6:.1f} µs · "
                 f"p₀ {h.p0/1e6:.0f} MPa [계산값]")
        st.write(f"- 잔류 압흔 {imp.dent*1e3:.3f} mm · 접촉 반경 {imp.contact_radius*1e3:.2f} mm · "
                 f"구슬/판 질량비 {imp.mass_ratio:.2f}")
        st.write(f"- p_y = {q_text(py, '{:.0f}', 1e-6, 'MPa')}")
        st.caption(SRC_THORNTON)
    show_warnings(assess.warnings)

    with st.expander("불확실성: 몬테카를로 파손확률 곡선과 h50"):
        c1, c2, c3 = st.columns(3)
        h_lo = c1.number_input("높이 하한 [m]", H_MIN, H_MAX, H_MIN, 0.1, key="mc_lo")
        h_hi = c2.number_input("높이 상한 [m]", H_MIN, H_MAX, min(3.0, H_MAX), 0.1, key="mc_hi")
        n_mc = c3.select_slider("표본 수", [500, 1000, 2000, 4000], value=2000)
        if st.button("몬테카를로 실행", key="run_mc"):
            hs = np.linspace(h_lo, max(h_hi, h_lo + 0.1), 14)
            with st.spinner("표본 계산 중..."):
                mc = failure_probability_curve(
                    s["ball"], mat, cfg.orientation, cfg.thickness, cfg.ring_radius, bc0, hs, py,
                    Kt=(case.Kt.value if case.Kt is not None else 1.0), fall_params=params,
                    fit=fit, n=int(n_mc))
            fig = go.Figure(go.Scatter(x=mc.heights, y=mc.p_fail, mode="lines+markers",
                                       line=dict(color=ACCENT), name="파손확률"))
            fig.add_hline(y=0.5, line=dict(color=GRAYS[2], dash="dot"))
            if mc.h50:
                fig.add_vline(x=mc.h50, line=dict(color=GRAYS[1], dash="dash"),
                              annotation_text=f"h50 = {mc.h50:.2f} m")
            plotly_layout(fig, "낙하 높이 [m]", "파손확률")
            st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)
            st.caption(
                f"기준 [{mc.basis}] · 판정 {'주 판정(E_abs vs E_c)' if mc.criterion == 'main' else '참고 판정(σ vs 굽힘강도)'} · "
                f"표본 {mc.n_samples}회 · TDS ±를 1σ로 해석(가정 A-02) · "
                f"2자유도/에너지균형 보정비 {mc.correction.mean():.2f} [계산값, A-17]"
                + ("" if mc.h50 else " · 이 높이 범위에서 50 %를 지나지 않는다"))
            show_warnings(mc.warnings)

    df = pd.DataFrame({"t_s": imp.t, "F_N": imp.F, "delta_m": imp.delta, "w_m": imp.w})
    download_df(df, "impact_timeseries.csv", "dl_impact")


def _site_calib(s):
    rep = st.session_state.get("report")
    if not s["use_calib"] or rep is None:
        return None
    key = (s["cfg"].config_type, s["site"], 0, s["cfg"].thickness)
    return rep.site_calibs.get(key)


# ---------------------------------------------------------------------------
# 탭 2 — 분할 비교
# ---------------------------------------------------------------------------
def tab_compare(s):
    rep = st.session_state.get("report")
    cfg, mat = s["cfg"], s["material"]
    rho = mat.density
    basis_txt = Basis.POST.value if (rep and s["use_calib"]) else Basis.PRE.value
    st.markdown(f"#### 결과 기준: <span class='acc'>{basis_txt}</span>", unsafe_allow_html=True)

    mode = st.radio("비교 기준", ["같은 두께", "같은 면밀도"], horizontal=True)
    r_ov = overlap_ratio(cfg)
    st.caption(f"겹침 면적비 {q_text(r_ov)} · 면밀도 "
               f"{units.kg_m2_to_g_cm2(areal_density(rho.value, cfg.thickness, r_ov.value or 0.0)):.4f} g/cm² [계산값]"
               if rho.known else "밀도 미확인")
    if mode == "같은 면밀도" and r_ov.known and rho.known:
        st.caption(f"같은 면밀도 기준: 일체형 두께 "
                   f"{units.m_to_mm(equal_areal_density_thickness(cfg.thickness, r_ov.value)):.2f} mm 와 비교")

    if rep is None or not s["use_calib"]:
        st.warning("보정 데이터가 없다. 구성·위치별 E50 은 실측에서만 얻을 수 있다 — "
                   f"'{NEEDS_MEASUREMENT}'. 보정 탭에서 CSV 를 올리면 여기에 표시된다.")
        return

    rows = []
    for g in rep.groups:
        key = g.key
        if mode == "같은 면밀도" and key.get("thickness_m") != cfg.thickness:
            pass
        rows.append({
            "구성": key["config_type"], "위치": key["impact_site"],
            "접힘": key.get("fold_cycles"), "두께 [mm]": units.m_to_mm(key.get("thickness_m", 0)),
            "E50 [J]": g.E50.value, "라벨": g.E50.label.value if g.E50.known else NEEDS_MEASUREMENT,
            "n": g.n,
        })
    df = pd.DataFrame(rows)
    ref_rows = df[(df["구성"] == "monolithic") & (df["위치"] == "center")]
    base = float(ref_rows["E50 [J]"].iloc[0]) if not ref_rows.empty else None

    fig = go.Figure(go.Bar(
        x=[f"{r['구성']}<br>{r['위치']} · {r['접힘']}회 · {r['두께 [mm]']:.1f} mm" for _, r in df.iterrows()],
        y=df["E50 [J]"],
        marker_color=[ACCENT if (r["구성"] != "monolithic" or r["위치"] != "center") else GRAYS[0]
                      for _, r in df.iterrows()]))
    if base:
        fig.add_hline(y=base, line=dict(color=GRAYS[2], dash="dash"),
                      annotation_text="일체형 center 기준선", annotation_position="top left")
    plotly_layout(fig, "", "E50 [J]", 420)
    st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)

    lt = pd.DataFrame([{
        "구성": l.key["config_type"], "위치": l.key["impact_site"], "접힘": l.key.get("fold_cycles"),
        "분할 손실률": l.loss, "95% CI 하한": None if l.ci is None else l.ci[0],
        "95% CI 상한": None if l.ci is None else l.ci[1],
        "Bruceton 기준": l.loss_bruceton, "방법": l.method,
        "라벨": NOT_ANALYZABLE if l.key["impact_site"] in ("seam", "triple_junction") else "보정 후",
    } for l in rep.losses])
    st.markdown("**분할 손실률** = 1 − E50(구성, 위치) / E50(일체형, center)")
    st.dataframe(lt, width="stretch", hide_index=True)
    download_df(lt, "loss_ratio.csv", "dl_loss")


# ---------------------------------------------------------------------------
# 탭 3 — 헬멧
# ---------------------------------------------------------------------------
def tab_helmet(s):
    mat = s["material"]
    st.markdown("#### 셸 무게·면밀도")
    c1, c2, c3, c4 = st.columns(4)
    size = c1.selectbox("사이즈 (FAST SF 기준)", list(FASTSF_SIZES), index=1)
    lo, hi, cov, shell_kg = FASTSF_SIZES[size]
    c1.caption(f"머리둘레 {lo*100:.0f}–{hi*100:.1f} cm [문헌값]" + (f" · {FASTSF_XXL_NOTE}" if size == "XXL" else ""))
    a_cm2 = c2.number_input("셸 표면적 A [cm²] (CAD 실측, 0 = 미입력)", 0.0, 5000.0, 0.0, 10.0)
    t_mm = c3.number_input("셸 두께 [mm]", 0.5, 20.0, 4.0, 0.1)
    r_ov = c4.number_input("겹침 면적비", 0.0, 1.0, 0.15, 0.01)
    area = computed(units.cm2_to_m2(a_cm2), "m^2", "CAD 입력") if a_cm2 > 0 else unverified(
        "m^2", "CAD 실측 미입력")
    rho = mat.density

    if area.known and rho.known:
        m = shell_mass(rho.value, area, units.mm_to_m(t_mm), r_ov)
        ad = shell_areal_density(rho.value, units.mm_to_m(t_mm), r_ov)
        cc = st.columns(4)
        cc[0].metric("셸 질량", f"{units.kg_to_g(m.value):.0f} g", f"[{m.label.value}]")
        cc[1].metric("면밀도", f"{units.kg_m2_to_g_cm2(ad.value):.4f} g/cm²")
        cc[2].metric("FAST SF L 셸", f"{units.kg_to_g(FASTSF_SHELL_L_NEXTGEN.value):.0f} / "
                                     f"{units.kg_to_g(FASTSF_SHELL_L_DATASHEET.value):.0f} g", "차세대 / 데이터시트")
        cc[3].metric("FAST SF 면밀도", f"{units.kg_m2_to_g_cm2(FASTSF_AREAL_DENSITY.value):.4f} g/cm²")
        fig = go.Figure(go.Bar(x=["이 설계", "FAST SF 차세대 L", "FAST SF 데이터시트 L"],
                               y=[units.kg_to_g(m.value), units.kg_to_g(FASTSF_SHELL_L_NEXTGEN.value),
                                  units.kg_to_g(FASTSF_SHELL_L_DATASHEET.value)],
                               marker_color=[ACCENT, GRAYS[2], GRAYS[3]]))
        plotly_layout(fig, "", "셸 질량 [g]", 300)
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)
        tgt = st.number_input("목표 셸 무게 [g] → 허용 두께 역산", 100.0, 2000.0, 557.0, 1.0)
        t_allow = thickness_for_mass(rho.value, area, units.g_to_kg(tgt), r_ov)
        st.caption(f"허용 두께 {units.m_to_mm(t_allow.value):.2f} mm [{t_allow.label.value}]")
    else:
        st.warning("셸 표면적(CAD)이 미확인이라 무게를 계산하지 않는다.")

    st.markdown("---")
    st.markdown(f"#### 헤드폼 둔탁 충격 (기준 {BLUNT_G_LIMIT.value:.0f} g @ 10 ft/s = {BLUNT_VELOCITY.value:.3f} m/s)")
    h1, h2, h3 = st.columns(3)
    preset = h1.selectbox("헤드폼 질량", ["(직접 입력)"] + list(FMVSS218_HEADFORMS))
    if preset == "(직접 입력)":
        mh = h1.number_input("질량 [kg]", 1.0, 12.0, 5.0, 0.1)
        mass = assumed(mh, "kg", "사용자 입력 헤드폼 질량")
    else:
        mass = FMVSS218_HEADFORMS[preset]
        h1.caption("FTHS(FAST SF 시험) 헤드폼 질량은 공개 자료 없음 — 다른 규격 참고값 [문헌값]")
    tl_mm = h2.number_input("라이너 두께 [mm]", 3.0, 60.0, 20.0, 1.0)
    liner_mode = h2.radio("라이너 모델", ["평탄응력 σ", "ARPRO σ(ε) 곡선"], horizontal=True)
    if liner_mode == "평탄응력 σ":
        rho_epp = h3.selectbox("EPP 밀도 [g/L] (제조사 표)", ["(직접 입력)"] + [f"{d:.0f}" for d in EPP_ARPRO_TABLE])
        if rho_epp == "(직접 입력)":
            sig = h3.number_input("σ_plateau [kPa]", 10.0, 3000.0, 290.0, 10.0)
            sigma_q = assumed(sig * 1e3, "Pa", "사용자 입력 평탄응력")
        else:
            strain = h3.selectbox("기준 변형률", [0.10, 0.25, 0.50, 0.75], index=1)
            sigma_q = epp_stress(float(rho_epp), strain)
            h3.caption(f"{q_text(sigma_q, '{:.0f}', 1e-3, 'kPa')} · {EPP_NOTE}")
        liner = LinerModel(units.mm_to_m(tl_mm), plateau=sigma_q)
    else:
        d_epp = h3.selectbox("EPP 밀도 [g/L]", [f"{d:.0f}" for d in EPP_ARPRO_TABLE], index=2)
        curve = tuple((st_, epp_stress(float(d_epp), st_).value) for st_ in (0.10, 0.25, 0.50, 0.75))
        liner = LinerModel(units.mm_to_m(tl_mm), curve=curve)
        h3.caption(EPP_NOTE)
    eps_d = st.checkbox("치밀화 변형률 ε_D 입력 (미입력 시 기하학적 상한 사용)")
    if eps_d:
        liner = LinerModel(liner.thickness, liner.plateau, liner.curve,
                           assumed(st.slider("ε_D", 0.3, 0.95, 0.8, 0.01), "-", "사용자 입력"))

    a1, a2 = st.columns(2)
    spread_mode = a1.radio("하중 분산 면적 A_spread [가정]", ["일체형: 투영면적 × f", "분할형: 판 1장 면적"])
    if spread_mode.startswith("일체형"):
        f_mono = a1.number_input("f (투영면적 대비 분산 비율)", 0.01, 1.0, 0.25, 0.01)
        base_area = area.value if area.known else cov
        A = assumed(base_area * f_mono, "m^2", f"[가정] 일체형: 투영면적 × {f_mono:.2f}")
        a1.caption("f 는 문헌 근거가 없는 가정이다. 값에 따라 결과가 크게 달라진다.")
    else:
        pa = a1.number_input("판 1장 면적 [cm²]", 1.0, 1000.0, 120.0, 1.0)
        beta = a1.number_input("인접판 기여율 β (보정 파라미터)", 0.0, 2.0, 0.0, 0.05)
        A = segmented_spread_area(units.cm2_to_m2(pa), s["cfg"].lock,
                                  assumed(beta, "-", "보정 전 사용자 입력") if beta else None)
    r = simulate_headform(mass, liner, A)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("최대 가속도", f"{r.a_max_g:.0f} g", "기준 이하" if r.passes_150g else "기준 초과")
    m2.metric("필요 스트로크", f"{r.stroke*1e3:.1f} mm", f"라이너 {tl_mm:.0f} mm")
    m3.metric("펄스 길이(압축)", f"{r.pulse_duration*1e3:.2f} ms")
    m4.metric("s_min = v²/2a", f"{r.s_min*1e3:.2f} mm", "검산용 이상 한계")
    lo_a, hi_a = required_spread_area(mass, liner)
    st.caption(f"설계 창 [계산값]: 바닥침을 피하려면 A_spread ≥ {units.m2_to_cm2(lo_a.value):.0f} cm², "
               f"150 g 이하를 지키려면 A_spread ≤ {units.m2_to_cm2(hi_a.value):.0f} cm²")

    fig = go.Figure(go.Scatter(x=r.t * 1e3, y=r.a_g, mode="lines", name="헤드폼 가속도",
                               line=dict(color=ACCENT)))
    fig.add_hline(y=BLUNT_G_LIMIT.value, line=dict(color=GRAYS[1], dash="dash"),
                  annotation_text="150 g 기준")
    plotly_layout(fig, "시간 [ms]", "가속도 [g]")
    st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)
    show_warnings(r.warnings)

    st.markdown("**측정 가능성**")
    c1, c2, c3 = st.columns(3)
    nch = c1.number_input("채널 수", 1, 8, 3, 1)
    bw = c2.number_input("가속도계 대역폭 [Hz] (데이터시트, 0=미입력)", 0.0, 20000.0, 1000.0, 50.0)
    tol = c3.slider("허용 피크 오차", 0.01, 0.3, 0.05, 0.01)
    mc = measurement_check(r.pulse_duration, n_channels=int(nch),
                           sensor_bandwidth=bw or None, tolerance=tol)
    st.write(f"- 펄스당 샘플 {mc.samples_per_pulse:.1f}개 · 샘플링 피크 오차 {mc.sampling_error*100:.1f} % "
             + (f"· 대역 감쇠 {mc.bandwidth_error*100:.1f} %" if mc.bandwidth_error is not None else "")
             + f" · 합계 {mc.total_error*100:.1f} % → {'측정 가능' if mc.ok else '측정 불가, 장비 변경 필요'}")
    show_warnings(mc.warnings)


# ---------------------------------------------------------------------------
# 탭 4 — 보정
# ---------------------------------------------------------------------------
def tab_calibration(s):
    st.markdown("#### 1. 파손 판정 기준 (실험 전 입력·저장)")
    path = Path("data/criteria.json")
    cur = st.session_state.get("criteria") or load_criteria(path)
    items = st.multiselect("판정 기준", list(CRITERIA_SUGGESTIONS) + list(cur.items),
                           default=list(cur.items) or list(CRITERIA_SUGGESTIONS[:1]))
    extra = st.text_input("기준 추가 (쉼표로 구분)", "")
    if extra:
        items = items + [x.strip() for x in extra.split(",") if x.strip()]
    if st.button("기준 저장"):
        path.parent.mkdir(exist_ok=True)
        saved = save_criteria(path, items)          # data/criteria.json 에 기록 (작성 시각 포함)
        st.session_state["criteria"] = saved
        st.success(f"기준 {len(items)}개를 {path} 에 저장: {', '.join(items)}")
    criteria = st.session_state.get("criteria") or load_criteria(path)
    if criteria.empty:
        st.error("기준이 비어 있으면 보정을 실행할 수 없다.")

    st.markdown("#### 2. CSV 업로드")
    up = st.file_uploader("시험 결과 CSV", type=["csv"])
    use_sample = st.checkbox("가상 샘플 데이터 사용 (VIRTUAL — 실측 아님)", value=not up)
    df_raw = None
    if up is not None:
        df_raw = pd.read_csv(up, comment="#")
    elif use_sample:
        p = Path("data/sample_VIRTUAL_drop_tests.csv")
        if p.exists():
            df_raw = pd.read_csv(p, comment="#")
            st.caption("⚠ 가상 데이터다. 실측이 아니다.")
    if df_raw is None:
        return
    errs = validate_schema(df_raw)
    if errs:
        st.error("스키마 오류:\n\n" + "\n".join(f"- {e}" for e in errs[:15]))
        return
    st.success(f"스키마 통과 · {len(df_raw)}행")

    st.markdown("#### 3. 시험 장치·점토 기준")
    c1, c2, c3 = st.columns(3)
    a_mm = c1.number_input("고정 링 내반경 [mm]", 5.0, 200.0, units.m_to_mm(s["cfg"].ring_radius), 1.0)
    bc = c2.selectbox("경계조건", ["clamped", "simply_supported"])
    clay_t = c3.number_input("점토 기준 깊이 [mm]", 1.0, 60.0, 19.0, 0.5)
    c4, c5 = st.columns(2)
    tol_a = c4.number_input("평균 허용폭 ± [mm]", 0.1, 10.0, 2.0, 0.1)
    tol_i = c5.number_input("개별 허용폭 ± [mm]", 0.1, 10.0, 3.0, 0.1)
    rig = RigSetup(units.mm_to_m(a_mm), bc, s["tube"], s["material"],
                   assumed(units.mm_to_m(clay_t), "m", "사용자 기준"),
                   assumed(units.mm_to_m(tol_a), "m", "사용자 허용폭"),
                   assumed(units.mm_to_m(tol_i), "m", "사용자 허용폭"))

    if st.button("보정 실행", type="primary", disabled=criteria.empty):
        with st.spinner("적합 중..."):
            df_si = units.drop_table_to_si(df_raw)
            try:
                rep = run_calibration(df_si, criteria, rig, current_py(s))
            except Exception as exc:
                st.error(str(exc))
                return
            st.session_state["report"] = rep
        st.success("보정 완료 — 사이드바의 '보정 결과 사용'이 켜진 상태로 다른 탭에 반영된다")
        st.rerun()
    rep = st.session_state.get("report")
    if rep is None:
        return

    st.markdown("#### 4. 보정 전/후")
    st.dataframe(rep.errors, width="stretch", hide_index=True)
    st.caption(f"η = {rep.tube.eta.value:.4f} [보정 후] · K_tube = {rep.tube.K_tube.value:.3g} · "
               f"p_y = {rep.py.py.value/1e6:.0f} MPa [보정 후] (초기값 {rep.py.py_pre.value/1e6:.0f} MPa)"
               if rep.tube and rep.py else "일부 항목만 보정")
    gdf = pd.DataFrame([{
        "구성": g.key["config_type"], "위치": g.key["impact_site"], "접힘": g.key.get("fold_cycles"),
        "두께 [mm]": units.m_to_mm(g.key.get("thickness_m", 0)), "n": g.n,
        "h50 [m]": g.h50, "E50 Bruceton [J]": g.E50_bruceton, "E50 로지스틱 [J]": g.logistic.E50,
        "95% CI": None if g.logistic.ci is None else f"{g.logistic.ci[0]:.3f}–{g.logistic.ci[1]:.3f}",
    } for g in rep.groups])
    st.dataframe(gdf, width="stretch", hide_index=True)
    download_df(gdf, "calibration_groups.csv", "dl_groups")

    st.markdown("#### 5. 접힘 횟수 – E50")
    cfgs = sorted({g.key["config_type"] for g in rep.groups})
    cc1, cc2 = st.columns(2)
    sel_cfg = cc1.selectbox("구성", cfgs)
    sel_site = cc2.selectbox("위치", sorted({g.key["impact_site"] for g in rep.groups
                                            if g.key["config_type"] == sel_cfg}))
    ft = fold_trend(rep.groups, sel_cfg, sel_site)
    if ft.slope is not None:
        fig = go.Figure(go.Scatter(x=ft.folds, y=ft.E50, mode="markers+lines", line=dict(color=ACCENT)))
        plotly_layout(fig, "접힘 횟수", "E50 [J]", 300)
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)
        st.caption(f"기울기 {ft.slope:.3e} J/회" +
                   (f" · 95% CI {ft.slope_ci[0]:.2e} – {ft.slope_ci[1]:.2e}" if ft.slope_ci else "") +
                   f" · 라벨 [{ft.label}]")
    else:
        st.caption(f"접힘 수준이 2개 미만이라 추세를 낼 수 없다 · 라벨 [{ft.label}]")
    show_warnings(ft.warnings)

    st.markdown("#### 6. 배면 점토·bfd")
    clay = rep.clay
    flagged = int(clay["clay_flag"].sum())
    if flagged:
        st.warning(f"점토 기준을 벗어난 행 {flagged}개 — 해당 bfd 는 비교에서 제외하거나 경고와 함께 본다")
    fig = go.Figure()
    for i, (cfg_name, g) in enumerate(clay.groupby("config_type")):
        fig.add_trace(go.Box(y=units.m_to_mm(g["bfd_m"]), name=str(cfg_name),
                             marker_color=ACCENT if i == 0 else GRAYS[min(i, 4)]))
    plotly_layout(fig, "", "bfd [mm]", 300)
    st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)
    st.caption("bfd 는 합불 기준이 아니라 구성 간 비교 지표로만 쓴다.")
    show_warnings(rep.warnings)


# ---------------------------------------------------------------------------
# 탭 5 — 실험 계획
# ---------------------------------------------------------------------------
def tab_planner(s):
    params = current_params(s)
    st.markdown("#### 동일 에너지 2조합 (속도 효과 판정용)")
    c1, c2 = st.columns([1, 2])
    E = c1.number_input("목표 충돌 에너지 [J]", 0.05, 50.0, 0.60, 0.05)
    hb1 = c1.number_input("가능한 최소 높이 [m]", H_MIN, H_MAX, H_MIN, 0.1)
    hb2 = c1.number_input("가능한 최대 높이 [m]", H_MIN, H_MAX, 2.0, 0.1)
    pair = equal_energy_pair(E, s["tube"], params, (hb1, max(hb2, hb1)))
    if pair.usable:
        df = pd.DataFrame([
            {"구분": "가벼운 공·높은 높이", "강구": pair.light.ball.name,
             "질량 [g]": units.kg_to_g(pair.light.ball.mass), "높이 [m]": pair.light.height,
             "충돌 속도 [m/s]": pair.light.v_impact, "에너지 [J]": pair.light.energy},
            {"구분": "무거운 공·낮은 높이", "강구": pair.heavy.ball.name,
             "질량 [g]": units.kg_to_g(pair.heavy.ball.mass), "높이 [m]": pair.heavy.height,
             "충돌 속도 [m/s]": pair.heavy.v_impact, "에너지 [J]": pair.heavy.energy},
        ])
        c2.dataframe(df.round(3), width="stretch", hide_index=True)
        c2.caption(f"속도비 {pair.v_ratio:.2f} — 두 조건의 파손 비율이 다르면 속도(변형률 속도) 효과가 있다고 본다")
    show_warnings(pair.warnings)
    f1, f2, f3, f4 = st.columns(4)
    fl = f1.number_input("가벼운 공 파손 수", 0, 100, 5)
    nl = f2.number_input("가벼운 공 시험 수", 1, 100, 20)
    fh = f3.number_input("무거운 공 파손 수", 0, 100, 12)
    nh = f4.number_input("무거운 공 시험 수", 1, 100, 20)
    res = velocity_effect_test(int(fl), int(nl), int(fh), int(nh))
    st.write(f"Fisher 정확검정 p = {res['p_value']:.4f} → **{res['verdict']}**")

    st.markdown("---")
    st.markdown("#### 계단법 도우미")
    c1, c2 = st.columns([1, 2])
    step = c1.number_input("계단 크기 [m]", 0.01, 2.0, 0.15, 0.01)
    seq = c2.text_input("진행 기록 (높이:결과, 예 1.50:f, 1.35:p)", "1.50:f, 1.35:p, 1.50:f")
    try:
        hs, fs = [], []
        for part in seq.split(","):
            h, r = part.strip().split(":")
            hs.append(float(h))
            fs.append(r.strip().lower().startswith("f"))
        pr = staircase_progress(hs, fs, step)
        st.write(f"진행 {pr.n}회 · 반전 {pr.reversals}회 · **다음 낙하 높이 {pr.next_height:.2f} m**")
        show_warnings(pr.warnings)
    except Exception:
        st.caption("형식: 높이:결과 (f=파손, p=유지) 쉼표 구분")

    st.markdown("---")
    st.markdown("#### 시편 수")
    c1, c2, c3 = st.columns(3)
    cfgs = c1.multiselect("구성", list(CONFIG_TYPES), default=list(CONFIG_TYPES))
    sites = c2.multiselect("타격 위치", list(IMPACT_SITES), default=["center", "seam", "triple_junction"])
    folds = c3.multiselect("접힘 횟수", [0, 100, 500], default=[0, 100, 500])
    plan = specimen_plan(cfgs, sites, folds)
    if not plan.empty:
        st.dataframe(plan, width="stretch", hide_index=True)
        st.caption(f"합계 최소 {plan.attrs['total_min']}개 / 권장 {plan.attrs['total_rec']}개 · {plan.attrs['note']}")
        download_df(plan, "specimen_plan.csv", "dl_plan")

    st.markdown("---")
    st.markdown("#### 곡면 헬멧 확인")
    rep = st.session_state.get("report")
    flat = {(g.key["config_type"], g.key["impact_site"]): g.E50.value
            for g in (rep.groups if rep else []) if g.E50.known}
    if not flat:
        st.caption("보정 결과가 있으면 평판 E50 예측이 여기에 채워진다.")
    else:
        txt = st.text_input("헬멧 실측 E50 입력 (구성/위치=값, 쉼표 구분)", "")
        meas = {}
        for part in txt.split(","):
            if "=" in part:
                k, v = part.split("=")
                ks = tuple(k.strip().split("/"))
                try:
                    meas[ks] = float(v)
                except ValueError:
                    pass
        st.dataframe(curvature_check(flat, meas).round(3), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
def main():
    st.title("군부 겹판 접이식 분할 헬멧 — 낙하 충격 시뮬레이터")
    st.caption("모든 값에 라벨을 붙인다: 문헌값 · 계산값 · 가정 · 미확인 · 보정 후")
    s = sidebar()
    t1, t2, t3, t4, t5 = st.tabs(["판 충돌", "분할 비교", "헬멧", "보정", "실험 계획"])
    with t1:
        tab_impact(s)
    with t2:
        tab_compare(s)
    with t3:
        tab_helmet(s)
    with t4:
        tab_calibration(s)
    with t5:
        tab_planner(s)
    st.markdown("---")
    st.caption(DISCLAIMER)


main()
