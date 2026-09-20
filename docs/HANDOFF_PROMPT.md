# 다른 AI 세션에 넘길 프롬프트

아래 블록 전체를 새 세션 첫 메시지로 붙여 넣으면 된다. 저장소를 함께 주면 더 좋다:
https://github.com/ranssist/chiton-helmet-sim

---

## 프로젝트 인수인계

너는 이미 만들어져 돌아가는 Python + Streamlit 시뮬레이터를 이어받는다. 새로 설계하지 말고,
아래 규칙과 구조를 지키면서 요청받은 부분만 고쳐라.

### 1. 무엇을 하는 프로그램인가

군부(chiton)의 겹판 구조를 모방한 **접이식 분할 헬멧**의 설계를 검증하는 낙하 충격 시뮬레이터다.
강구를 가이드관으로 떨어뜨려 3D 프린팅 원판 쿠폰을 때리는 소규모 실험(ASTM D5420 방식)을 모사하고,
그 실험 데이터로 모델을 보정한 뒤, 구성·타격 위치별 50 % 파손 에너지(E50)와 임계 높이(h50),
분할 손실률을 추정한다. 헬멧 수준에서는 셸 무게·면밀도와 헤드폼 둔탁 충격을 Ops-Core FAST SF와 비교한다.

**범위 밖(절대 하지 말 것)**: 방탄 성능 예측. 용어도 '방탄판'이 아니라 '충격 분산판'을 쓴다.
IHPS·FAST 같은 복합재 셸의 성능을 예측하지 않는다. FAST SF 수치는 치수·무게·시험 조건의 비교 기준일 뿐이다.

### 2. 절대 규칙

1. **내부 계산은 전부 SI.** g, mm, cm, 층 단위 변환은 `chiton_sim/units.py`와 `app.py`에서만 한다.
   `tests/test_provenance.py::test_no_ui_unit_conversion_inside_calc_modules`가 이를 강제한다.
2. **출처 없는 값을 지어내지 않는다.** 물성·계수에는 출처 주석(URL 또는 문헌)을 단다.
   못 찾으면 `unverified(...)` + `# TODO(source)`로 두고 UI에 "미확인"으로 표시한다.
3. **모든 값에 라벨**: `문헌값` `계산값` `가정` `미확인` `보정 후` (`provenance.Label`).
   결과 블록에는 `문헌값 기반(보정 전)` 또는 `실측 보정 후`(`provenance.Basis`)를 붙인다.
   해석식이 없는 항목은 `해석 불가·실측 보정값`, 데이터가 없으면 숫자 대신 `실측 필요`를 낸다.
4. **seam(이음선)·triple_junction(삼중 교차점)에는 해석식이 없다.** 보정 데이터가 없으면 수치를 만들지 말고
   `NEEDS_MEASUREMENT`를 반환한다. 이미 그렇게 구현돼 있으니 되돌리지 마라.
5. **파손 판정 기준이 비어 있으면 보정을 차단한다**(`CalibrationBlockedError`).
6. 수식·인용이 확실하지 않으면 **구현 전에 문헌으로 확인**하고 `PLAN.md` §1에 기록한다.

### 3. 구조

```
chiton_sim/provenance.py  Quantity(value, unit, label, source, note, sd, low, high), Basis, ModelWarning, 예외
chiton_sim/units.py       UI 전용 단위 변환 + CSV → SI (drop_table_to_si)
chiton_sim/materials.py   Bambu PLA Basic TDS, 크롬강 AISI 52100, EPP(ARPRO), 표준대기, g0
chiton_sim/ball.py        질량↔지름, 규격 강구(인치), GuideTube(PET병 모드 포함), 통과 검사
chiton_sim/fall.py        낙하 ODE(solve_ivp), Morrison C_d(Re), K_tube, 벽 손실 η, height_for_energy
chiton_sim/contact.py     Hertz(참고), ThorntonLaw(하중·제하·재하중·일·잔류압흔·반발계수 닫힌 해)
chiton_sim/plate.py       D, K_b(고정단/단순지지/실측), K_m(막), 유효질량 ¼, Roark 참고 응력
chiton_sim/impact.py      2자유도(기본)·SDOF·강체 지지, 이벤트 기반 접촉/분리, 에너지 분배, 적용범위 경고
chiton_sim/segments.py    구성×타격위치, Kt, 면밀도, 같은두께/같은면밀도, SiteCalibration
chiton_sim/failure.py     참고 판정, 주 판정 E_c(t)=C·tⁿ, 벡터화 에너지균형, 몬테카를로
chiton_sim/calibration.py CSV 스키마·정규화, 판정기준 저장, 관손실·p_y·판강성 적합, Bruceton, 로지스틱, 손실률, 접힘추세, 점토
chiton_sim/helmet.py      셸 무게·면밀도·역산, 헤드폼 1자유도, 설계 창, 측정 가능성
chiton_sim/planner.py     동일 에너지 2조합, Fisher 검정, 계단법 도우미, 시편 수, 곡면 확인
app.py                    Streamlit UI 5탭(판 충돌/분할 비교/헬멧/보정/실험 계획)
scripts/make_virtual_data.py  가상 CSV 생성   scripts/error_budget.py  오차 예산 재계산
tests/                    pytest 100건        docs/error_budget.md  오차 분석
```

### 4. 물리 모델 (구현된 식 전부)

**낙하** `m dv/dt = m g₀ − ½ρ_air C_d(Re) A v|v| K_tube`, `Re = ρvD/μ`,
C_d 는 Morrison(2013) 상관식(Re ≤ 1e6), `v_impact = v_ODE(1 − η_wall)`.
공기 ρ = 1.2250 kg/m³, μ = 1.7894e-5 Pa·s (US Std Atm 1976), g₀ = 9.80665.

**접촉(Hertz, 참고용)** `E* = [(1−ν₁²)/E₁+(1−ν₂²)/E₂]⁻¹`, `F = (4/3)E*√R δ^1.5`,
`δmax = (15mv²/(16E*√R))^(2/5)`, `a = √(Rδ)`, `p₀ = 3F/(2πa²)`,
`tc = 2.8683 (m²/(RvE*²))^(1/5)` (He & Wettlaufer 2013). `p₀ > 1.6Y` 이면 탄성 무효 경고.

**접촉(Thornton 1997, 실제 사용)**
`δ_y = R(πp_y/(2E*))²`, `F_y = (4/3)E*√R δ_y^1.5`,
하중 `F = F_y + πp_yR(δ−δ_y)`,
제하 `R_p = (4E*/(3F_max))((2F_max+F_y)/(2πp_y))^1.5`, `δ_p = δ_max − (3F_max/(4E*√R_p))^(2/3)`,
`F = (4/3)E*√R_p (δ−δ_p)^1.5`. 잔류 압흔 = δ_p. 초기값 `p_y = 1.6Y`(Y=굽힘강도 대용값), 실측 압흔으로 보정.

**판** `D = Et³/(12(1−ν²))`, 고정단 `K_b = 16πD/a²`, 단순지지 `K_b = 16π(1+ν)D/((3+ν)a²)`,
막 `K_m = (353−191ν)πEt/(648(1−ν)a²)` (고정단·이동불가, Shivakumar Table 1),
판 반력 `P = K_b w + K_m w³`, 유효 판 질량 = 링 내부 판 질량의 ¼,
Roark 소면적 하중 `r′₀ = √(1.6r₀²+t²) − 0.675t` (r₀<0.5t),
`σ_c = 3P/(2πt²)[(1+ν)ln(a/r′₀) + c]` (c=1 단순지지, 0 고정단), 고정단 가장자리 `3P/(2πt²)`.

**2자유도 충돌** `m₁ẍ₁ = −F_c(δ)`, `m₂ẍ₂ = F_c(δ) − P(x₂)`, `δ = x₁ − x₂`, 접촉은 단방향(인장 불허).
검산: `∫F dt = m₁v_in(1+e)` 와 에너지 수지 오차 < 0.5 %.

**빠른 에너지 균형(몬테카를로용)** `E_in = W_load(δ) + ½K_b w² + ¼K_m w⁴`, `P = K_b w + K_m w³`,
접촉 역함수는 닫힌 해. 명목 2자유도/에너지균형 비를 보정계수로 곱한다.

**판정** 참고: `Kt·σ_Roark` vs 굽힘강도. 주: `E_abs = E_in − E_rebound` vs `E_c(t) = C·tⁿ`(실측 적합).
Kt 초기값 1.87 (NACA TN-740), 보정 시 `Kt_eff = √(E50_center/E50_site)`.

**헬멧** `m_shell = ρAt(1+r_ov)`, 헤드폼 `m ẍ = −σ(x/t_liner)A_spread`, `v₀ = 3.048 m/s`,
`s_min = v²/(2a)`, 설계 창 `m v²/(2σ s) ≤ A_spread ≤ 150 g₀ m/σ`,
측정 가능성 `N = T·f_s`, 피크 오차 `1 − cos(π/2N)`, 센서는 2차 Butterworth로 근사.

**통계** Bruceton(Dixon–Mood) `μ = x′ + d(A/N ± ½)`, `σ = 1.620d((NB−A²)/N² + 0.029)`,
첫 반응 변화 한 단계 전부터 센다. 로지스틱 `E50 = −b₀/b₁`, 델타법 CI.
분할 손실률 `L = 1 − E50/E50_ref`, 로그비 델타법 CI.

### 5. 검증 상태 (건드리면 깨지는 것들)

`pytest` 100건 통과(약 70초). 문헌 대조가 테스트에 박혀 있다.
- Hertz `tc`·`F_max`가 McLaskey & Glaser(2010) JASA 128:1087 식 (4)·(6)과 0.3 % 이내
- Thornton 수치 적분이 Thornton(1997) 반발계수 닫힌 해(Jackson 외 2010 식 2)와 0.5 % 이내
- Shivakumar NASA TM-85703 Fig. 7(Al 판 a=38, h=3.2 mm, 강구 R=19 mm, 2.54 m/s → 0.607 ms) ±10 %
- 무감쇠 2자유도 에너지 보존 < 0.5 %, 강체/SDOF 탄성에서 `∫F dt = 2mv`
- Bruceton 공개 예제(Wikipedia Example 1, 44회 원자료 → N=20, A=55, 50 % 수준 3.45) 재현
- 분할 손실률이 참값 0.30인 가상 데이터를 복원하고 CI가 참값을 포함
- 항력 0이면 `v = √(2gh)` 상대오차 < 1e-6

### 6. 기준 조건에서 나오는 값 (회귀 감각용)

3/4" 크롬강 구(28.27 g), 2 m 낙하, PLA 3 mm, 링 내반경 40 mm, 고정단, 막 강성 포함:
충돌 6.25 m/s, 에너지 0.552 J, 최대 접촉력 약 1.1 kN, 판 반력 약 507 N, 접촉시간 약 1.0 ms,
반발계수 약 0.82, 잔류 압흔 약 0.16 mm, w/t 약 0.64, 굽힘응력 약 115 MPa(굽힘강도 76 MPa → 파손 판정).
보정 전 참고 판정 h50 ≈ 1.0 m.

### 7. 오차 예산 (docs/error_budget.md)

파라미터 불확실성 RSS ±15 %(굽힘강도 ±13 %가 지배)보다 모델 가정이 크다:
경계조건 고정단↔단순지지 **+78 %**, 판 관성 무시 −22 %, p_y 1.6→3.0Y −11 %, 막 효과 누락 −10 %.
그래서 **보정 전 예측은 "2배 이내"**로 본다. 보정 후 같은 조건 재현은 ±10~20 %(시편 수에 좌우).
줄이는 순서: 판 강성 실측 → 시편 수 → 압흔으로 p_y 보정 → 막 효과 포함 → 치수 실측.

### 8. 아직 미확인(TODO) — 값을 지어내지 마라

- FTHS(FAST SF 시험 규격) 헤드폼 질량: 공개 자료 없음. FMVSS 218(3.5/5.0/6.1 kg)은 '다른 규격 참고값'
- FDM PLA 체결부 p/d·e/d 기준: 표준 없음 → 사용자 입력
- 폼 치밀화 변형률 ε_D: Gibson–Ashby 식 원문 확인 실패 → 사용자 입력, 없으면 기하학적 상한
- ASTM D5420 본문(지지링·타구 치수): 유료 → Dixon–Mood로 대체
- PET병 병목 내경: 도면값 없음 → 21 mm 가정 + 경고
- PLA 푸아송비: TDS에 없음 → 0.36 가정
- Shivakumar 전단 강성 K_s: 스캔 OCR이 깨져 확인 실패 → 미구현
- Thornton 1997 원문(ASME 유료) 미열람: 식은 arXiv:2104.00344와 Jackson 외(2010)로 교차 확인

### 9. 실행

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows. PowerShell에서는 && 대신 ; 를 쓴다
.venv/Scripts/python -m pytest -q
.venv/Scripts/streamlit run app.py              # 또는 run.bat 더블클릭
PYTHONPATH=. .venv/Scripts/python scripts/error_budget.py
```

### 10. 작업 방식

- 모듈 하나를 고치면 해당 테스트를 돌려 통과를 확인하고 다음으로 넘어간다.
- 라이브러리를 우선 쓴다(numpy, scipy, pandas, statsmodels, streamlit, plotly). 직접 구현은 물리 모델과
  Dixon–Mood 합산식뿐이다.
- 새 가정을 넣으면 `PLAN.md` §4 가정 목록에 ID를 붙여 적고 UI에 '가정'으로 표시한다.
- 새 문헌을 확인하면 `PLAN.md` §1 표에 출처와 상태(원문 확인/2차 교차 확인/미확인)를 남긴다.
- 사용자는 한국어로 소통한다.
