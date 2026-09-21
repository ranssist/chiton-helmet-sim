# PLAN.md — 군부 겹판 접이식 분할 헬멧 낙하 충격 시뮬레이터

- 상태: **v0.2 (2026-09-20)** — 사용자 확인 완료("진행"). §9의 Q1–Q7은 모두 제안대로 채택했다.
- 이 문서에는 모듈 구조, 수식, 가정, 성공 기준, 그리고 구현 전 문헌 확인 결과(§1)를 담았다.
- 확인이 필요한 결정 사항은 §9에 모았다.

---

## 0. 범위와 면책 (UI 하단과 README에 그대로 게시)

- 이 시뮬레이터는 **PLA 등 FDM 출력물의 둔탁 충격 거동 모델**이다.
- 방탄 성능은 다루지 않는다. 용어는 '방탄판'이 아니라 **'충격 분산판'**을 쓴다.
- IHPS·FAST(UHMWPE 등 복합재 셸)의 성능을 예측하지 않는다. FAST SF 수치는 치수·무게·시험 조건의 **비교 기준**으로만 쓴다.

---

## 1. 문헌 확인 결과 (구현 전 검증 기록)

상태 표기: ✅ 원문 확인 · ◐ 2차 문헌 교차 확인(원문 미열람) · ⚠ 요청서와 불일치 · ❌ 미확인 → `TODO`, UI에는 "미확인"으로 표시

| # | 항목 | 확인 내용 | 출처 | 상태 |
|---|---|---|---|---|
| L1 | Bambu PLA Basic TDS V3.0 | 굽힘탄성률 XY 2750±160 / Z 2370±150 MPa, 굽힘강도 76±5 / 59±6 MPa, ISO 179 비노치 26.6±2.8 / 13.8±0.9 kJ/m² (XY 노치 7.9±1.2), 인장강도 XY 35±4 / Z 31±3 MPa, 영률 XY 2580±220 / Z 2060±170 MPa, 파단연신율 12.2±1.8 / 7.5±1.3 %, **밀도 1.24 g/cm³ (ISO 1183)**. 시편 조건: 인필 100 %, 노즐 220 °C, **55 °C·8 h 어닐링 후 시험**. 푸아송비는 TDS에 없음 | https://wiki.bambulab.com/filament-acc/abs-asa-pc/bambu_pla_basic_technical_data_sheet.pdf (원 URL은 HTTP 402. 동일 V3.0 사본 files.bbystatic.com으로 확인) | ✅ |
| L2 | 크롬강 AISI 52100 | ρ 7.81 g/cm³, E 190–210 GPa, ν 0.27–0.30. 기본값은 E 210 GPa, ν 0.30으로 한다(범위 안이며 요청값과 같음). 강구 물성을 범위 안에서 바꿔도 PLA와의 E*는 0.2 % 미만으로 변한다(계산값) | https://www.azom.com/article.aspx?ArticleID=6704 | ✅ |
| L3 | 구 항력 C_d(Re) | Morrison(2013) 상관식, 적용 Re ≤ 10⁶ (식은 §3-A) | https://pages.mtu.edu/~fmorriso/DataCorrelationForSphereDrag2016.pdf | ✅ |
| L4 | 공기 물성 | 해면 288.15 K에서 ρ = 1.2250 kg/m³, μ = 1.7894×10⁻⁵ Pa·s | U.S. Standard Atmosphere 1976 (NASA-TM-X-74335), 표 사본 https://www.pdas.com/bigtables.html | ✅ |
| L4b | 표준 중력 | g₀ = 9.80665 m/s² (정의값) | 3rd CGPM (1901), NIST SP 330 | 정의값(원문 미조회) |
| L5 | Hertz 충돌시간 | He & Wettlaufer: T = **2.8683**(M²/(R V E²))^(1/5). McLaskey & Glaser(2010) 식 4·6(δᵢ = (1−νᵢ²)/(πEᵢ))을 E*로 환산하면 계수가 2.866과 1.915이 되어, §3-B의 tc(2.868)·Fmax 식과 반올림 범위에서 일치(계산값). 식 6의 원 계수는 1.917 | https://ar5iv.arxiv.org/html/1306.4952 , McLaskey & Glaser, JASA 128(3):1087 (2010), https://courses.cit.cornell.edu/mclaskey/pubs/JASA2010.pdf | ✅ / ◐(McLaskey 식의 π 기호가 PDF 추출에서 깨져 있어 식 구조로 판단) |
| L6 | 항복 시작 p₀ ≈ 1.6Y | von Mises 기준으로 J₂를 각도·깊이에 대해 최대화해 1.6을 얻음. δ_y, F_y 식 제시 | Burgoyne & Daraio, PRE 89, 032203 (2014), https://authors.library.caltech.edu/44661/1/PhysRevE.89.032203.pdf | ✅ |
| L6b | 1.6의 ν 의존성 | 항복 속도가 ν에 따라 최대 약 50 %까지 달라질 수 있다고 지적 → UI에 "ν = 0.36 가정 시 1.6Y 근사" 주석 | Jackson, Green & Marghitu, Nonlinear Dyn. 60:217 (2010) | ◐ |
| L7 | Thornton (1997) | 서지 J. Appl. Mech. 64(2):383–386 확인. 원문은 ASME 유료라 미열람. 하중·제하 식과 R_p, δ_p는 arXiv:2104.00344 식(1)–(5)에서, 반발계수 닫힌 해는 Jackson 외(2010) 식(2)에서 확인. 두 식을 수치 적분하면 닫힌 해와 **0.00 %** 일치(스크래치 계산, V = 0.5–6.26 m/s). p_y/Y = 1.6–3.0 범위. Thornton 모델이 e를 과소예측한다는 보고 있음 | https://arxiv.org/pdf/2104.00344 , Jackson 외(2010) | ◐ (원문 대조는 TODO) |
| L8 | 원판 굽힘 강성 | 고정단 K_b = 4πEh³/(3(1−ν²)a²) = 16πD/a². 단순지지 K_b = 4πEh³/(3(3+ν)(1−ν)a²) = 16π(1+ν)D/((3+ν)a²) | Shivakumar 외 NASA TM-85703 Table 1 (Timoshenko & Woinowsky-Krieger 1959, Volmir 인용) | ✅ |
| L9 | Shivakumar, Elber & Illg | NASA TM-85703 (1983), J. Appl. Mech. 52(3):674–680 (1985). **유효 판 질량 = 판 전체 질량의 1/4**(Leissa NASA SP-160 인용). 충격체 질량이 판 질량의 3.5배를 넘으면 판 질량을 무시해도 됨. **막 효과 무시 조건 w/h ≤ 0.2**. 원 모델은 굽힘·전단·막 강성을 모두 포함하고, 접촉력의 인장을 허용함(분리 불허). 검증 사례: Al 판 a = 38 mm, h = 3.2 mm, 강구 R = 19 mm, 2.54 m/s → 접촉시간 0.607 ms | https://ntrs.nasa.gov/api/citations/19840003151/downloads/19840003151.pdf , https://doi.org/10.1115/1.3169120 | ✅ / ⚠ 막 효과 임계값 0.2(문헌)와 0.5(요청서)가 다름 → §9 Q1 |
| L10 | Roark 소면적 하중 | 등가반경 r′₀ = √(1.6r₀² + t²) − 0.675t (r₀ < 0.5t일 때). 중앙 응력은 σ = 3P/(2πt²)·[(1+ν)ln(a/r′₀) + c]이며 단순지지 c = 1, 고정단 c = 0. 고정단 가장자리 응력은 3P/(2πt²) | MITcalc 문서(Roark 인용) https://www.mitcalc.com/doc/plates/help/en/plates.htm . 응력식은 키르히호프 판 모멘트 해로 직접 유도해 검산 | ◐ (Roark 7판 Table 11.2 case 번호는 원서 미열람, TODO) |
| L11 | 구멍 응력집중(판 굽힘) | 단축 굽힘, 구멍 지름 ≫ 판 두께일 때 이론 **Kt = 1.87**, 실측 1.85(총단면 기준) → 초기값 1.87. 등이축 굽힘의 Kt = 2.0은 키르히호프 해에서 직접 유도한 값이라 '계산값'으로 표시. Goodier식 (5+3ν)/(3+ν)는 원문 미확인 | NACA TN-740 (Dumont 1939) https://ntrs.nasa.gov/citations/19930081505 | ✅(초록) |
| L12 | 파동 지배 질량 기준 | 충격체 질량이 판 질량의 약 1/4 미만이면 소질량(파동 지배) 충돌 | Olsson, Compos. Part A 31:879 (2000), 정오표 32:291 | ◐ (초록·인용 수준) |
| L13 | Bruceton / Dixon–Mood | μ = x′ + d(A/N ± ½): 덜 빈번한 사건 기준으로, 반응(파손)이면 −, 무반응이면 +. σ = 1.620·d·((NB − A²)/N² + 0.029). 공개 예제 Wikipedia Example 1은 원자료 44회에서 첫 반전 한 단계 전부터 세면 N = 20, A = 55, 평균 3.45로 집계표와 일치(스크래치 검산). Example 2는 표 내부 불일치(13 vs 12)가 있어 쓰지 않음 | Dixon & Mood, JASA 43:109 (1948, 유료). Chao & Fuh, Statistica Sinica 11:1–21 (2001) 식 5.1·5.4. https://en.wikipedia.org/wiki/Bruceton_analysis | ◐ |
| L14 | ASTM D5420 요약 | 100 mm(4") 원판 권장, Bruceton 계단법, 최적 결과에는 최소 30 시편. 보고값은 평균 파손 높이와 평균 파손 에너지. D5420 본문(식·지지링 치수)은 유료라 미확인 | https://intertek.com/polymers/testlopedia/gardner-impact | ✅ / ❌ 본문 |
| L15 | FAST SF 데이터시트 (Gentex REV.20230306) | 둔탁 충격 **150 g 이하 @ 10 ft/s**. 성능 규격은 "Modified and Abbreviated FTHS (2017-06-30), Ops-Core PS-1228". **EPP 라이너와 성형 통기구**. 셸 두께 5.58 mm, **면밀도 5957 g/m²**. 커버리지 M 884 / **L 955** / XL 1052 / XXL 1103 cm². 셸 무게 M 630 / **L 655** / XL 750 / XXL 780 g(추정값 ±3 %). **헤드폼 질량은 기재 없음** | https://img.trex-arms.com/wp/uploads/2023/09/FAST_SF_Ops-Core_Data_Sheet.pdf | ✅ |
| L16 | FAST SF 사이즈·차세대 무게 | M 53–56, L 56–59, XL 59–62, XXL 62–64.5 cm. **차세대 L 셸 557 g** | https://www.rtstactical.com/products/ops-core-fast-sf-super-high-cut-lightweight-advanced-ballistic-helmet-system | ✅ / ⚠ XXL 상한이 데이터시트(64 cm)와 다름 → 두 값 모두 표시 |
| L17 | 헤드폼 질량 | FAST SF의 FTHS 규격 헤드폼은 공개 자료 없음 → `TODO`. 참고 프리셋으로 FMVSS 218 헤드폼 소 3.4–3.6 / 중 4.9–5.1 / 대 6.0–6.2 kg | 49 CFR 571.218, https://www.law.cornell.edu/cfr/text/49/571.218 | ❌ (FTHS) / ✅ (FMVSS) |
| L18 | 배면 점토 보정 | NIJ 0101.04 Addendum B는 RP1을 지정 배면재로 명시(낙하 수치는 본문 참조). NRC(2012): 63.5 mm 구 5회 낙하, 개별 19±3 mm, 평균 **19±2 mm**. 구 질량 **1043±5 g**, 2.0 m는 검색 요약 수준에서만 확인. Teijin 포스터는 HTTP 403으로 열람 불가 | https://www.ojp.gov/pdffiles1/nij/nlectc/206095.pdf , https://www.nationalacademies.org/read/13390/chapter/6 | ✅ / ◐ / ⚠ 요청서 "1.03 kg" ≠ 1043 g → §9 Q3 |
| L19 | Arduino analogRead | ATmega 보드(UNO 등) 1회 약 100 µs → 최대 약 10,000회/s(단일 채널 기준) | Arduino 공식 reference 저장소 https://github.com/arduino/reference-en (analogRead.adoc). 요청 URL은 docs.arduino.cc로 리다이렉트된 뒤 404 | ✅ |
| L20 | EPP 압축강도 | JSP ARPRO EPP(ARPLANK 표, ASTM D3575, 전형값). 밀도 20/30/45/60 g/L 순으로 @10 %: 11.7/18/32/44 psi, @25 %: 14.5/23.5/42/57, @50 %: 23.5/33.5/54/73, @75 %: 45/64/111/155. 포장재 등급 표이며 준정적 값 | https://www.foam-industries.com/hubfs/Technical%20Documents/TechDataHome_PhysicalPropertyInformation_EPPproducts.pdf | ✅ (헬멧 등급과 같은지는 미확인) |
| L21 | 폼 치밀화 변형률 ε_D | Gibson–Ashby 식을 원문으로 확인하지 못함 → 사용자 입력(`TODO`). 기본 판정은 기하학적 상한(스트로크 ≤ 라이너 두께)으로 한다 | — | ❌ |
| L22 | 체결부 p/d, e/d 기준 | FDM PLA와 열압입 인서트에 대한 표준·문헌 기준을 찾지 못함 → `TODO` + 사용자 입력. CFRP 볼트 연구의 e/D ≥ 3은 재료계가 달라 기본값으로 쓰지 않음 | — | ❌ |
| L23 | 인용 서지 | Connors 외 "Bioinspired design of flexible armor based on chiton scales", Nat. Commun. (2019) doi:10.1038/s41467-019-13215-0 ✅. Li 외 Science 350(6263):952–956 (2015) doi:10.1126/science.aad1246 ✅. NG-IHPS는 셸 무천공("holeless")에 에폭시 접착 받침(Soldier Systems Daily 2023-10-10) ✅. helmets.org/folding: "접어도 충격 폼 부피는 같게 필요하다"는 취지 ✅ | 각 URL | ✅ |
| L25 | Bambu PETG HF TDS V1.0 | 밀도 1.28 g/cm³, 굽힘탄성률 XY 2050±120 / Z 1810±140 MPa, 굽힘강도 XY 64±3 / Z 48±4 MPa, 인장 XY 34±4, 충격 XY 31.5±2.2 kJ/m². 시편 255 °C·인필 100 %·75 °C 8 h 어닐링 | https://store.bblcdn.com/3a230e260a3a47c2b0db0156e07eef91.pdf | ✅ |
| L26 | 아라미드/에폭시 적층판 굽힘 물성 | 100 % 아라미드(에폭시, 섬유부피 73.3 %) ASTM D790-17: 굽힘강도 109.02±10.83 MPa, 굽힘탄성률 10.38±0.60 GPa, 밀도 1.32 g/cm³ | Meliande 외, Polymers 14(18):3749 (2022), doi:10.3390/polym14183749 | ✅ |
| L27 | UHMWPE 적층판 물성 | 밀도 0.97 g/cm³, 면내 E1=E2=30.7 GPa, E3=1.97 GPa, 인장 3.1 GPa (시뮬레이션 입력 물성). **굽힘강도는 제시 없음** → 미확인 처리 | Bian 외, Polymers 16(21):2985 (2024), doi:10.3390/polym16212985 Table 3 (원출처 Hu 외, Compos. Struct. 290:115499) | ◐ |
| L28 | FAST SF 셸 밀도 | 데이터시트 면밀도 5957 g/m² ÷ 두께 5.58 mm = 1068 kg/m³ (계산값). 굽힘 물성은 비공개 | L15 와 동일 | 계산값 |
| L24 | PET병 병목 내경 | 요청서 기재대로 "약 21–22 mm로 추정(도면값 미확인)" 경고만 표시 | — | ❌ |
| L29 | MICH/ACH TC-2000 무게·둔탁 충격 | 공보에 Medium 3.0 lbs, Large 3.25 lbs, XL 3.4 lbs, 'Impact mitigation, less than 150 gs force transmitted to the head at 10 fps'. **셸 단독인지 완성품인지 명시 없음**(구성품에 패드·끈 포함) → 무게는 '완성 헬멧 추정'으로 표시하고 셸 무게와 직접 비교 금지 | MSA ACH TC-2000 Series 제품 공보 ID 3720-23-MC (2006-03) | ◐ |
| L30 | ACH 사이즈 ↔ 머리둘레 | 셸 M: 둘레 22.5 in(573 mm) 이하, L: 573–597 mm, XL: 597 mm 이상. 실제 차트는 둘레·길이·폭 중 최대 치수로 고르며 여기서는 둘레만 쓴다 | US Army PS Magazine 642 (2006-05) ACH Head/Shell Sizing Chart | ✅ |
| L31 | ACH Gen II 면밀도·무게 | 'below 6.9 kg/m² (1.38 lbs/ft²)', 풀컷 하네스·패드 포함 M<1010 g, L<1080 g, XL<1130 g (AR/PD 14-01 요건이라고 제조사가 명시) | ArmorSource Next Generation 제품 페이지 | ◐ |
| L32 | 원본 ACH 셸 면밀도·커버리지 | 공개 규격(AR/PD 10-02 본문)을 구하지 못했다 → **미확인**. 면밀도 등급을 매기지 않는다 | — | ❌ |

스크래치 검산 3건(코드 작성 전, 결과만 기록):
1. **Shivakumar Fig. 7 사례.** 전단 강성을 빼고 판 질량을 무시(SDOF)하면 0.585 ms로 논문값 0.607 ms 대비 −3.7 %다. 판 질량을 넣고 접촉 분리를 허용한 2DOF는 0.499 ms에서 조기 분리된다. 원 모델은 인장 접촉을 허용하므로 이 차이는 모델 차이로 문서화한다.
2. **Thornton.** 수치 적분한 반발계수가 닫힌 해와 0.00 % 일치했다. 3/4" 강구를 6.26 m/s로 강체 지지 PLA에 떨어뜨리면 e ≈ 0.55, 잔류 압흔 ≈ 0.36 mm다.
3. **Bruceton 예제 1.** 원자료가 계단 규칙을 위반하지 않았고, 첫 반전 한 단계 전부터 세면 집계표(N = 20, A = 55)가 그대로 재현된다.

---

## 2. 모듈 구조

요청서의 파일(fall, impact, segments, failure, helmet, calibration, planner, app)은 그대로 두고, 공통 기반 모듈 6개(provenance, units, materials, ball, contact, plate)를 분리한다.

```
(프로젝트 루트)
├─ PLAN.md · README.md · requirements.txt
├─ app.py                     # Streamlit UI (단위 변환은 여기서만)
├─ .streamlit/config.toml     # 그레이 스케일 + 액센트 1색 테마
├─ chiton_sim/
│  ├─ provenance.py  # Quantity(value, unit, label, source, note), 라벨 열거형, ModelWarning, 결과 basis 플래그
│  ├─ units.py       # g↔kg, mm↔m, cm²↔m², 층수×층고+시작높이 → m (UI 전용)
│  ├─ materials.py   # PLA Basic 프리셋(L1), 강구(L2), EPP 프리셋(L20), 사용자 TDS 입력 스키마
│  ├─ ball.py        # 질량↔지름, 규격 강구 스냅, 가이드관·PET 모드 검사
│  ├─ fall.py        # 낙하 ODE (solve_ivp), C_d(Re), K_tube, 벽 손실률
│  ├─ contact.py     # Hertz(참고), Thornton 탄소성 하중·제하·재하중
│  ├─ plate.py       # D, K_b(고정단/단순지지), 유효질량, Roark 응력
│  ├─ impact.py      # 2자유도 스프링-질량 (solve_ivp + 이벤트), 검산, 에너지 분배, 적용범위 경고
│  ├─ segments.py    # 구성×타격위치 처리, knockdown, Kt, 면밀도, 같은두께/같은면밀도 환산
│  ├─ failure.py     # 참고 판정(Roark), 주 판정(E_c = C·tⁿ), 몬테카를로
│  ├─ calibration.py # CSV 스키마, 관 손실·p_y 적합, Bruceton, 로지스틱, 손실률 CI, 접힘 추세, 점토 검사, 보정 전/후 오차표
│  ├─ helmet.py      # 셸 무게·역산, 헤드폼 1자유도, 측정 가능성
│  ├─ planner.py     # 동일 에너지 조합, 판정 기준 저장, 계단법 도우미, 시편 수, 곡면 확인
│  ├─ grading.py     # A~F 등급 (절대 기준선 / 상대 순위)
│  ├─ compare.py     # 재료 비교(같은 두께 / 같은 면밀도), 임계 높이
│  └─ mesh.py        # 3D 메시 → 표면적·투영면적·두께·분할판 면적 (선택 의존성 trimesh)
├─ data/
│  ├─ sample_VIRTUAL_drop_tests.csv   # 가상 데이터(파일명과 첫 줄 주석에 VIRTUAL 명시)
│  └─ criteria.json                   # 파손 판정 기준(실험 전 입력·저장)
└─ tests/  test_provenance.py, test_ball_fall.py, test_contact.py, test_impact.py,
           test_segments.py, test_failure.py, test_calibration.py, test_helmet.py, test_planner.py
```

- 의존 방향: provenance ← materials·units ← ball·fall·contact·plate ← impact ← segments·failure ← calibration·helmet·planner ← app
- 라이브러리 사용처
  - numpy·scipy: `solve_ivp`, `optimize.brentq/minimize_scalar/least_squares`, `stats.linregress/fisher_exact/bootstrap/norm`, `signal.butter/lfilter`
  - pandas: CSV
  - statsmodels: 로지스틱 GLM (§9 Q6)
  - streamlit·plotly: UI
- 직접 구현하는 것
  - 물리 모델: 낙하, Hertz, Thornton, 판, 2DOF, 헤드폼
  - Dixon–Mood 합산식: 표준 공식 몇 줄이고, 유지되는 파이썬 라이브러리가 없다
- 모든 내부 계산은 SI다. `chiton_sim/`에는 g, mm, cm, 층 단위가 나타나지 않는다(테스트로 확인).

---

## 3. 수식

### A. 낙하 (fall.py)
```
m dv/dt = m g₀ − ½ ρ_air C_d(Re) A v|v| K(z)        A = πD²/4,  Re = ρ_air |v| D / μ
K(z) = K_tube   (구슬이 관 안에 있는 구간: 낙하 마지막 L_tube 구간)
     = 1        (관 밖)
C_d = 24/Re + 2.6(Re/5)/(1+(Re/5)^1.52) + 0.411(Re/2.63e5)^-7.94/(1+(Re/2.63e5)^-8.00)
      + 0.25(Re/1e6)/(1+Re/1e6)                                  [Morrison 2013, Re ≤ 1e6]
v_impact = v_ODE(h) · (1 − η_wall)         η_wall: 충돌 속도 손실률 (벽 손실, 보정 대상)
출력: v_impact, 낙하 시간, 손실(%) = 1 − v_impact/√(2 g₀ h)
```
- `solve_ivp`에 z = h 도달 이벤트를 건다.
- 입력 범위는 0.3–20 m이고, 벗어나면 예외로 처리한다.
- v > 10 m/s면 "변형률 속도 효과 미반영" 경고를 띄운다.

### B. 접촉 (contact.py)
```
E* = [(1−ν₁²)/E₁ + (1−ν₂²)/E₂]⁻¹,  R = 구슬 반경 (평판)
Hertz(참고, 강체 지지):
  δmax = (15 m v² / (16 E* √R))^(2/5),  Fmax = (4/3) E* √R δmax^(3/2),  a = √(Rδ),  p₀ = 3F/(2πa²)
  tc = 2.868 (m² / (R v E*²))^(1/5)
  p₀ > 1.6·Y  → 경고 "탄성 모델 무효(국부 항복)" (Y = 굽힘강도 대용값임을 표시)
Thornton 탄성-완전소성:
  δ_y = R (π p_y / (2E*))²,   F_y = (4/3) E* √R δ_y^(3/2)
  하중:  F = (4/3)E*√R δ^(3/2)           (δ ≤ δ_y)
         F = F_y + π p_y R (δ − δ_y)      (δ > δ_y, 하중 중)
  제하:  R_p = (4E*/(3F_max)) · ((2F_max + F_y)/(2π p_y))^(3/2)
         δ_p = δ_max − (3F_max / (4E*√R_p))^(2/3)
         F = (4/3) E* √R_p (δ − δ_p)^(3/2)       (δ_p < δ ≤ δ_max)
  재하중: 제하 곡선을 따라 F_max까지 오르고, 넘으면 소성 하중 식을 이어 간다
  잔류 압흔 깊이 ≈ δ_p (판 쪽 소성으로 귀속, 강구는 탄성)
  p_y 초기값 = 1.6·Y (L6)  → 실측 압흔으로 보정
```

### C. 판 (plate.py)
```
D = E t³ / (12(1−ν²))
K_b,clamped = 16πD/a²,   K_b,SS = 16π(1+ν)D/((3+ν)a²)        [Timoshenko; Shivakumar Table 1]
m_eff = ¼ · ρ π a² t                                          [Shivakumar: Leissa 인용]
Roark 참고 응력 (하중 반경 r₀ = 최대하중 시 접촉 반경):
  r′₀ = √(1.6r₀² + t²) − 0.675t   (r₀ < 0.5t),   그 외에는 r′₀ = r₀
  σ_c = 3P/(2πt²)·[(1+ν)·ln(a/r′₀) + c],  c = 1 (SS), 0 (clamped)
  σ_edge,clamped = 3P/(2πt²);   σ_ref = max(σ_c, σ_edge)
```

### D. 2자유도 충돌 (impact.py)
```
m₁ ẍ₁ = −F_c(δ, 이력)
m₂ ẍ₂ =  F_c(δ, 이력) − K_b x₂          δ = x₁ − x₂,   F_c = 0 (δ ≤ δ_p: 비접촉, 인장 불허)
초기조건: x₁ = x₂ = 0, ẋ₁ = v_impact, ẋ₂ = 0
```
- 하중과 제하의 전환은 이벤트(δ̇ = 0, δ = δ_p)로 구간을 나눠 적분한다.
- 분리 뒤 재접촉을 잡기 위해 t_end(추정 tc의 3배)까지 계속 적분한다.
- 계산 모드는 세 가지다: 2DOF(기본), SDOF 한계(m₂ → 0, F_c = K_b w를 대수적으로 풂), 강체 지지(K_b → ∞).
- 출력: F(t), δ(t), w(t), F_max, 접촉시간(첫 접촉~마지막 분리), v_out, e = −v_out/v_in
- 충격량: J = ∫F dt, 평균력 = J/tc
  - 자동 검산: |J − m₁(v_in − v_out)| / J < 0.5 % (v_out < 0이므로 m₁(v_in − v_out) = m₁v_in(1+e))
- 에너지 분배
  - E_rebound = ½m₁v_out²
  - E_plastic = ∮F dδ (Thornton 소산)
  - E_plate = 판 변형·운동에너지(적분 종료 시점). 합이 E_in과 맞는지 확인한다.
- UI 안내문: "충격량은 공 질량·속도·반발계수로 거의 정해지므로 파손 판정 지표가 아님"
- 적용범위 경고
  - m₁/m_plate < 0.25 → "파동 지배 충돌, 준정적 모델 부정확"(Olsson)
  - 0.25 ≤ m₁/m_plate < 3.5 → 정보 "중간 영역: 판 관성 무시 불가, 2DOF 결과 사용"(Shivakumar)
  - w/t > 0.2 → 정보(Shivakumar), w/t > 0.5 → 경고 "막 효과 누락"(요청서) — §9 Q1
  - v > 10 m/s → "변형률 속도 효과 누락"
  - 인필 < 100 %, 비어닐링 → "TDS 조건과 다름, 실측 보정 필요"

### E. 분할 구조 (segments.py)
| impact_site | 처리 | 보정 전 출력 | 보정 후 출력 |
|---|---|---|---|
| center, monolithic | 사용자가 고른 경계조건 | 수치 (문헌값 기반(보정 전)) | 수치 (실측 보정 후) |
| center, 분할 + lock on | 고정단(상한)~단순지지(하한) 구간 | 구간 | 구간 + 실측값 |
| center, 분할 + lock off | 단순지지를 상한으로 처리 + "잠금 없음" 경고 | ≤ 수치 | 실측값 |
| seam, triple_junction | 해석식 없음. knockdown k = E50(site)/E50(center, 같은 구성) | **`실측 필요`** (수치 없음) | 수치 [해석 불가·실측 보정값] |
| opening, fastener(through_screw·hybrid) | σ_local = Kt·σ_ref, Kt₀ = 1.87 (L11) | 수치 (Kt 문헌값) | Kt_eff = √(E50_center/E50_site) (선형 강성 가정에서 σ ∝ F ∝ √E로 유도한 계산값) |
| fastener(bonded_receiver) | 구멍 없음 → Kt 적용 안 함. "받침 탈락"을 별도 파손 모드로 둠 | 탈락 모드: `실측 필요` | [해석 불가·실측 보정값] |
| vent: liner_vent | 셸 관통 없음 → Kt 없음 | 수치 | — |
| vent: overlap_channel | 겹침 틈 채널 → seam과 같은 방식 | `실측 필요` | 실측값 |
| vent: shell_through | opening과 같은 방식 | 수치 | 보정값 |

```
면밀도 ρ_A = ρ · t · (1 + r_ov),  r_ov = A_overlap / A_projected
       A_overlap = L_seam · overlap_mm   (L_seam: CAD 값 입력. 없으면 r_ov = "미확인")
같은 면밀도 환산: t_mono,eq = t · (1 + r_ov)   (일체형 두께를 겹침 구성의 면밀도에 맞춤)
```
- 모든 비교는 "같은 두께"와 "같은 면밀도" 두 기준으로 출력한다.
- 같은 면밀도 비교에는 E_c(t)의 지수 n이 필요하다. 보정 전에는 `실측 필요`로 표시한다.
- 체결부 검사: p/d, e/d가 기준값 미만이면 경고한다. 기준값은 `TODO`이며 사용자가 입력하고, 입력 전에는 "미확인"으로 표시한다.

### F. 파손 판정과 불확실성 (failure.py)
- **참고 판정**
  - σ_ref(Roark)를 판 반력 최대값 K_b·w_max로 계산해 굽힘강도 σ_f(출력 방향별)와 비교한다.
  - 출력은 여유율(margin)이며, 결과 라벨은 [문헌값 기반(보정 전)]이다.
- **주 판정**
  - E_abs = E_in − E_rebound(모델, p_y 보정 후)를 E_c(t) = C·tⁿ과 비교한다.
  - (C, n)은 구성·타격 위치별로 log E_c,50 = log C + n·log t를 적합해 구한다(`scipy.stats.linregress`).
  - 두께가 하나뿐이면 그 두께의 E_c만 쓰고, n은 `실측 필요`로 둔다.
  - 보정 데이터가 없으면 주 판정 전체가 "미확인·실측 보정 필요"다.
- **몬테카를로(2000회, 시드 고정)**
  - TDS의 ± 값을 1σ 정규분포로 보고 0 이하는 절단한다[가정]. 강구 E와 ν는 L2 범위에서 균등 분포로 뽑는다.
  - 속도 확보를 위해 판 질량을 무시한 에너지 균형 모델(Shivakumar E-B 모델에 Thornton 접촉 에너지를 더한 것)을 numpy 벡터화 이분법으로 푼다.
  - 높이 격자 각 점에서 명목값 2DOF/E-B의 F_max 비를 보정계수로 곱한다[계산값, 하이브리드].
  - 출력은 높이별 P_fail 곡선과 h50(선형 보간)이다. 보정 전 판정은 참고 판정을, 보정 후 판정은 주 판정(C, n의 공분산 포함)을 쓴다.

### G. 보정 (calibration.py)
- **CSV 스키마**: 요청서 스키마 그대로.
  - 선택 열로 `test_date`(점토를 날짜별로 검사할 때)와 `v_rebound_mps`(있으면 반발 실측)를 추가하는 안을 제안한다(§9 Q4).
  - 스키마 오류가 나면 행 번호와 열 이름을 보고한다.
- **차단**: `criteria.json`이 비어 있으면 `CalibrationBlockedError`를 낸다.
- **관 손실**: η_wall을 `minimize_scalar`로 적합해 Σ(v_meas − v_model(η))²를 최소화한다.
  - K_tube는 높이 범위가 충분할 때만 η와 함께 `least_squares`로 적합한다. 식별성이 부족하면 경고한다.
- **p_y**: Σ(dent_meas − δ_p,model(p_y))²를 최소화한다.
- **Bruceton**: 구성×위치별로 높이를 계단 단위로 쓰고, 첫 반전 한 단계 전부터 센다(옵션).
  - Dixon–Mood 평균과 σ를 구하고, 평균 파손 높이는 에너지 ½m v_impact²(보정된 낙하 모델)로 환산한다.
  - M = (NB − A²)/N² < 0.3이면 "σ 추정 신뢰 낮음" 경고를 띄운다.
- **로지스틱**: statsmodels GLM(Binomial, logit)으로 fail ~ E를 적합한다.
  - E50 = −β₀/β₁이고, 95 % CI는 델타법으로 구한다. Bruceton 결과와 나란히 표시한다.
- **분할 손실률**: L = 1 − E50(구성, 위치)/E50(monolithic, center)
  - 95 % CI는 log 비에 대한 델타법(두 그룹 독립)으로 구한다.
  - 참고로 `scipy.stats.bootstrap`(시편 재표본)도 제공한다. 계단법 순서 의존성을 무시한다는 한계를 명시한다.
- **접힘 횟수**: fold_cycles(0/100/500)별 E50을 구하고 `linregress`로 기울기와 95 % CI를 낸다.
- **점토**
  - 기준값과 허용폭은 사용자 설정이다. 참고 프리셋은 RP1 평균 19±2 mm, 개별 19±3 mm(L18)다.
  - 기준을 벗어난 날(또는 행)의 bfd_mm에 경고를 붙인다. bfd는 구성 간 비교 지표로만 쓴다.
- **보정 전/후 오차표**: v_impact, 압흔, h50(참고 판정 예측 vs Bruceton 실측)의 RMSE와 평균 상대오차를 낸다.

### H. 헬멧 (helmet.py)
```
셸 질량  m_shell = ρ · A · t · (1 + r_ov)       A: CAD 실측 (없으면 "미확인", 계산 안 함)
역산     t_allow = m_target / (ρ · A · (1 + r_ov))
비교선   FAST SF L 557 g (차세대, L16) / 655 g (데이터시트, L15), 면밀도 5957 g/m² (L15)
헤드폼   m_h ẍ = −σ(x/t_liner) · A_spread,  v₀ = 10 ft/s = 3.048 m/s (h ≈ 0.474 m)
         σ = σ_plateau (기본, 상수)  |  σ(ε) 곡선 (선택: ARPRO 4점, 준정적)
         출력: a_max(g), 필요 스트로크 s, 펄스 길이, 바닥침 여부(s > t_liner, ε_D 입력 시 s > ε_D·t_liner)
         검산 한계: s_min = v²/(2·a_max) → 150 g에서 3.16 mm
         설계 창: 150 g 이하와 바닥침 없음을 동시에 만족하는
                  A_spread ∈ [m v²/(2 σ s_avail),  150 g₀ m/σ]   (계산값, 가정 없이 도출)
A_spread [가정, UI 표시]
         일체형:  f_mono · A_projected   (f_mono: 사용자 입력, 기본 "미확인")
         분할형:  A_plate · (1 + β·[lock on])  (β: 인접판 기여율, 보정 파라미터, 보정 전 0 = 판 1장 상한)
측정 가능성
  N = T_pulse · f_s,  f_s = 10 kHz / 채널 수 (Arduino UNO, L19)
  반정현 펄스를 N개 샘플로 잡을 때 최악 피크 오차 = 1 − cos(π/(2N))
  센서 대역: 2차 Butterworth 저역통과(데이터시트 대역폭 f_bw 입력, 가정)를 예측 펄스에 적용한 뒤 피크 감쇠율 계산
  두 오차 합 > 허용오차(사용자 설정) → "측정 불가, 장비 변경 필요"
```

### I. 실험 설계 (planner.py)
- **동일 에너지 조합**
  - 목표 E에 대해 규격 강구 중 두 개(가벼운 것·무거운 것)를 골라, 보정된 낙하 모델을 `brentq`로 역산해 각각의 높이를 구한다.
  - 두 높이가 0.3–20 m 범위이고 관 통과가 가능한지 검사한다.
  - 결과 비교에는 `fisher_exact`(pass/fail 비율)나 E50 차이의 CI를 쓴다. 차이가 유의하면 "속도 효과 있음"으로 판정한다.
- **판정 기준**: 관통 균열, 조각 이탈, 잠금 풀림, 받침 탈락, 사용자 정의 기준을 `criteria.json`에 저장하고 작성 시각을 기록한다.
- **계단법 도우미**: pass → h + Δh, fail → h − Δh(Δh는 사용자 설정)로 안내하고, 진행 기록과 현재 N을 보여 준다.
- **시편 수**: 구성 × 위치 × 접힘 조합의 수에 조합당 20–30회를 곱해 출력한다. "계단법은 조합당 20–30회 필요(D5420 요약은 최소 30 권장)" 안내를 붙인다.
- **곡면 헬멧 확인**: 평판 E50 예측과 헬멧 실측(소수 회)을 나란히 표시하고, 차이를 "곡률·형상 효과"로 기록한다.

---

## 4. 가정 목록 (UI의 '가정' 라벨과 1:1로 대응)

| ID | 가정 | 근거·영향 |
|---|---|---|
| A-01 | PLA 푸아송비 0.36 | TDS에 없음(요청서 지정). 1.6Y 계수와 K_b에 영향 |
| A-02 | TDS의 ±값을 1σ로 해석 | TDS에 정의가 없음. MC 분산에 직결 |
| A-03 | TDS 값은 인필 100 %, 어닐링 시편 기준 | 사용자 조건이 다르면 경고하고 보정을 요구 |
| A-04 | 출력 방향: XY(평판 눕혀 출력) → XY 물성, Z(세워 출력) → Z 물성(보수적) | 층간 방향 하중을 단순화 |
| A-05 | Y(항복) 대용값 = 굽힘강도 | 요청서 지정. UI에 "대용값" 표시 |
| A-06 | 강구는 탄성, 소성은 판에서만 일어남 | E*가 PLA에 지배됨 |
| A-07 | 판은 등방성 키르히호프 판, 중앙 집중하중, 전단·막 강성 생략 | Shivakumar 대비 과강성·저강성 요인이 공존함(검산 1) |
| A-08 | 유효 판 질량 = 링 내부 판 질량의 1/4 | L9 |
| A-09 | 판 재료 감쇠 없음 | 에너지 분배에서 판 진동 에너지는 판 흡수로 계산 |
| A-10 | 공기 물성은 해면 표준대기(288.15 K) 고정 | 20 °C 실험실과 밀도 차 약 1.7 %. 3/4" 강구를 2 m에서 떨어뜨리면 충돌 직전 항력이 중량의 약 1 %(계산값)라 영향이 작음 |
| A-11 | K_tube는 관 안 구간에만 적용, 기본값 1.0 | 요청서 지정. 보정 대상 |
| A-12 | 벽 손실 = 충돌 속도 손실률 η 하나, 보정 전 0 | 요청서 지정 |
| A-13 | 분할 + lock on, center 타격: 쿠폰 전체 반경 a를 쓰고 경계조건 구간(고정단~단순지지)으로 이음 불확실성을 표현 | 요청서 문구 해석 → §9 Q2 |
| A-14 | 겹침 면적 = 이음선 길이 × 겹침 폭 | CAD 입력 필요 |
| A-15 | 개구부·체결부 명목응력 ≈ 타격점 중앙 응력(σ_ref) | 개구부가 타격점 근처에 있다고 봄 |
| A-16 | E_abs = E_in − E_rebound(모델) | CSV에 반발 실측이 없음(선택 열로 보완 가능) |
| A-17 | MC 가속: E-B 모델 × 명목 2DOF 보정비 | 판 관성 효과를 높이별 상수비로 근사 |
| A-18 | 헤드폼 1DOF: 라이너 힘 = σ·A_spread, 셸 변형과 목·턱끈 무시 | 요청서 지정 |
| A-19 | 일체형 A_spread = f_mono × 투영면적, 분할형 = 판 1장 면적 × (1 + β) | 요청서 지정. f_mono는 입력 전 "미확인" |
| A-20 | EPP σ는 준정적 표값. 변형률 속도 경화 미반영 | 충격 시 σ가 과소평가될 수 있음 → 경고 |
| A-21 | 센서 응답 = 2차 Butterworth | 데이터시트 곡선 대용 |
| A-22 | 분할판 면적(헬멧) = A/n_segments (CAD 판 면적 미입력 시) | 균등 분할 가정 |
| A-23 | 판의 E 는 굽힘탄성률(ISO 178)을 쓴다 | 판 굽힘이 지배적이라 인장 영률 대신 씀. 접촉 E* 도 같은 값을 쓴다 |
| A-24 | 접촉은 단방향(인장 불허) → 분리·재접촉 허용 | Shivakumar 원 모델은 인장 접촉을 허용(분리 불허). 접촉시간 정의가 달라진다 |
| A-25 | 계단법은 첫 반응 변화 한 단계 전부터 센다 | Dixon–Mood 관행. 공개 예제의 집계표가 이 규칙으로 재현된다 |
| A-26 | 판 강성 실측값이 있으면 경계조건 가정을 쓰지 않는다 | 정적 압입 P = K_b·w + K_m·w³ 적합. 오차 예산의 +78 % 항이 사라진다 |
| A-27 | 막 강성은 Shivakumar Table 1(고정단·이동불가) 식만 쓴다 | 단순지지 식은 원문 스캔에서 확인 실패 → 단순지지에서는 0 |
| A-28 | PETG 푸아송비 0.40 | TDS에 없음 |
| A-30 | A~F 등급 경계 (A 1.5 / B 1.2 / C 1.0 / D 0.85 / E 0.7) | 문헌 근거 없음. C = 기준 충족이며 사용자가 조절한다 |
| A-31 | 종합 등급은 가중치 동일, 4개 중 3개 이상 채점될 때만 |
| A-29 | 복합 적층판 푸아송비 0.30, 면내 등방으로 본다 | 실제로는 직교이방성. K_b 에 주는 영향은 (1−ν²)로 작지만, 파손 방식(층간 박리)은 모델 밖이다 |
| A-32 | 얇은 셸 판정: 부피/바깥면적 < 20 mm | 헬멧 셸 두께 범위를 넉넉히 덮는 경험적 경계 |
| A-33 | 안/바깥 면 한 쌍 판정: 중심 차 < 5 %, 크기 차 < 20 % | 같은 중심·비슷한 크기의 두 면은 분할판이 아니라 한 셸의 양면으로 본다 |
| A-34 | 메시 셸 두께 = 부피/바깥면적 | 두께가 일정하다는 가정. 부위별로 다르면 평균이 된다 |
| A-35 | ACH 무게는 '완성 헬멧'으로 본다 | 공보에 범위 명시가 없다. 셸 무게와 같은 축에 놓지 않고 경고를 붙인다 |
| A-36 | ACH Gen II 사이즈 구분은 ACH 와 같다 | 제조사가 ACH 호환을 명시하나 둘레 표는 따로 주지 않았다 |

---

## 5. 라벨과 경고 체계

- **값 라벨**(모든 수치 옆): `문헌값` · `계산값` · `가정` · `미확인` · `보정 후`
- **결과 기준 라벨**(모든 출력 블록 머리): `문헌값 기반(보정 전)` 또는 `실측 보정 후`
- **특수 라벨**
  - `해석 불가·실측 보정값`: seam, triple_junction, 받침 탈락, overlap_channel, 접힘 효과, joint_type
  - `실측 필요`: 보정 데이터가 없을 때 수치 대신 표시
- **구현 방식**
  - `Quantity`는 `value`, `unit`(SI), `label`, `source`(URL/문헌 또는 None), `note`를 가진다.
  - `source=None`이면 `label=미확인`이어야 한다. 코드에서는 `# TODO(source)` 주석을 달고, UI는 "미확인"으로 표시한다.
  - 경고는 `ModelWarning(code, severity, message)`로 결과 객체에 쌓고, UI가 `st.warning`/`st.info`로 표시한다.

---

## 6. 테스트 계획 (pytest)

| 파일 | 테스트 | 기준 |
|---|---|---|
| test_ball_fall | 항력 0 → v = √(2gh) | 상대오차 < 1e-6 (h = 0.3, 2, 15 m) |
| | 질량↔지름 왕복 | 상대오차 < 1e-12 |
| | 구슬 지름 > 내경 − 여유 | `GuideTubeError` 발생 |
| | PET 모드 경고 문구, 높이 범위 밖 예외, v > 10 m/s 경고 | 문구·예외 확인 |
| test_contact | tc 계수가 He & Wettlaufer 2.8683과 일치 | < 1e-3 |
| | tc·Fmax가 McLaskey & Glaser(2010) 식 4·6과 일치 (출처 주석 명시) | < 0.3 % (문헌 계수 반올림) |
| | Hertz ODE 수치적분 vs 닫힌 해 (tc, Fmax) | < 0.5 % |
| | Thornton 수치 e vs 닫힌 해 (Jackson 외 2010 식 2) | < 0.5 % |
| | V < V_y이면 e = 1, δ_y에서 F 연속 | 확인 |
| test_impact | 무감쇠·무소성 2DOF 에너지 보존 | 오차 < 0.5 % |
| | 강체 지지 또는 SDOF, e = 1 → ∫F dt = 2mv | < 0.5 % |
| | 일반 경우 ∫F dt = m(v_in − v_out) 자동 검산 | < 0.5 % |
| | Shivakumar Fig. 7 (SDOF 한계, 전단 생략)의 접촉시간 vs 0.607 ms | ±10 % (예상 약 −4 %) |
| test_segments | seam·triple_junction 무보정 → `실측 필요` 문자열, 수치 없음 | 확인 |
| | 면밀도 = ρ t (1 + r_ov) | 정확히 일치 |
| | bonded_receiver → Kt 미적용 + 탈락 모드 존재 | 확인 |
| test_failure | Roark: SS − clamped 중앙응력 차 = 3P/(2πt²), r′₀ 전환 조건 | 확인 |
| | MC 재현성(시드), P_fail이 h에 대해 단조 | 확인 |
| test_calibration | Bruceton 예제 1: 원자료 44회 → N = 20, A = 55, 평균 3.45, 원점 이동 불변 (Wikipedia 예제, 출처 주석) | < 1e-9 |
| | 분할 손실률: 알려진 가상 데이터(E50 1.0 J / 0.7 J) → L ≈ 0.30, 95 % CI가 참값 포함 | 확인 |
| | 판정 기준이 비면 보정 차단 | `CalibrationBlockedError` |
| | 관 손실·p_y 적합이 합성 데이터의 참값 복원 | < 2 % |
| | 점토 허용폭 밖 행에 경고 | 확인 |
| test_helmet | 일정 감속 → s = v²/(2a) 재현, 150 g @ 3.048 m/s → 3.16 mm | < 1e-6 |
| | 셸 질량 ↔ 역산 두께 왕복 | < 1e-12 |
| | 0.2 ms 펄스 @ 10 kHz → "측정 불가" | 확인 |
| test_planner | 동일 에너지 조합 두 조건의 E 일치, 계단 다음 높이, 시편 수 산술 | 확인 |
| test_provenance | 모든 프리셋 값에 출처가 있거나 `미확인` 라벨 | 확인 |
| | `chiton_sim/`에 비 SI 변환 상수가 없음 | 확인 |

---

## 7. 성공 기준

1. 모든 출력 블록에 `문헌값 기반(보정 전)` 또는 `실측 보정 후`가 붙는다.
2. 해석할 수 없는 항목에는 `해석 불가·실측 보정값`, 데이터가 없으면 `실측 필요`가 붙는다. 추정 수치는 만들지 않는다.
3. `pytest`가 전부 통과한다(§6).
4. 적용범위를 벗어나면 화면에 경고가 뜬다(§3-D 경고 목록, 가이드관, PET, 높이 범위, 체결부 간격).
5. 모든 물성·계수에 출처 주석이 있다. 출처가 없으면 `TODO`로 남기고 UI에 "미확인"으로 표시한다.
6. UI 하단과 README에 §0 면책 문구를 둔다.
7. CSV 내보내기(`st.download_button`)와 PNG 내보내기(plotly 모드바 카메라 버튼, 브라우저에서 생성)를 지원한다.

---

## 8. 구현 결과 (2026-09-20 기준)

10단계 모두 구현했고, 오차 감축 기능(판 강성 실측·막 강성·예측 밴드)과 UX 개선까지 넣어 `pytest` 129건이 통과한다(약 77초). 단계별 테스트 수는 다음과 같다.

| 단계 | 모듈 | 테스트 | 비고 |
|---|---|---|---|
| 1 | provenance · units · materials | 8 | 라벨 규칙, TDS 값, SI 원칙 검사 |
| 2 | ball · fall | 15 | 항력 0 검증 1e-6, 관 차단, PET 경고 |
| 3 | contact | 21 | McLaskey & Glaser 식과 0.3 % 이내, Thornton 닫힌 해와 0.5 % 이내 |
| 4 | plate · impact | 10 | 에너지 보존 0.5 %, Shivakumar 0.607 ms 재현(−3.7 %) |
| 5 | segments | 9 | seam → `실측 필요`, Kt, 면밀도 |
| 6 | failure | 5 | Roark, E-B 모델 vs SDOF 0.1 %, MC 재현성 |
| 7 | calibration | 9 | Bruceton 공개 예제 3.45, 손실률 참값 복원, 기준 없으면 차단 |
| 8 | helmet | 9 | s = v²/(2a) 재현, 150 g → 3.16 mm, 측정 가능성 |
| 9 | planner | 6 | 동일 에너지, 계단법, 시편 수, 곡면 표 |
| 10 | app.py · README | — | Streamlit AppTest 로 전체 흐름(보정 실행·몬테카를로 포함) 확인 |
| 13 | 등급 (grading) | 9 | 절대 기준선(150 g·면밀도·응력=강도·바닥침)과 상대 순위 분리, 미확인이면 등급 없음 |
| 12 | 재료 비교 (materials·compare) | 7 | 실제 방탄모 계열 3종 추가, 같은 두께/같은 면밀도 비교, 미확인 물성은 계산 제외 |
| 11 | 오차 감축 (plate·impact·failure·calibration) | 7 | 막 강성 식·효과, 실측 강성 적합·적용, 실측 시 경계조건 구간 제거 |
| 15 | 비교 규격 (helmet) | 5 | FAST SF·MICH/ACH·ACH Gen II 기준선, 무게 범위 차이 경고, 미확인이면 등급 없음 |
| 14 | 3D 모델 (mesh) | 8 | 축척 없으면 면적을 `미확인`으로 막음, 머리둘레+라이너·셸 보정, 안/바깥 면 한 쌍 판별, 투영면적 = 삼각형 합집합 |

**오차 예산** (`docs/error_budget.md`, `scripts/error_budget.py`): 보정 전 h50 예측의 파라미터 불확실성은
RSS ±15 %인 반면 모델 형태 오차가 −22 %~+78 %로 더 크다. 가장 큰 항목인 경계조건(+78 %)은 판 강성 실측으로,
막 효과(−10 %)는 막 강성 옵션으로, p_y(−11 %)는 압흔 보정으로 없앨 수 있게 했다.

가상 데이터로 보정을 돌리면 생성 참값을 되찾는다: η 0.0301(참값 0.030), p_y 168 MPa(참값 167),
E50 오차 0.05 J 이내, 속도 RMSE 0.174 → 0.026 m/s, 압흔 RMSE 0.054 → 0.010 mm.

구현하며 새로 드러난 사항:
- 3/4" 강구·2 m·PLA 3 mm·링 반경 40 mm 조건에서 2자유도는 접촉이 6회 끊겼다 이어지고, 판 관성 때문에
  초기 접촉력(1089 N)이 SDOF(482 N)보다 훨씬 크다. w/t = 0.67 이라 막 효과 경고가 뜬다.
- p_y 적합이 조건마다 2자유도 적분을 반복해 느렸다. 적합 전용 저정밀 옵션(rtol 1e-7)과 조건 표본 상한(24개)을
  넣어 전체 보정을 5분 → 49초로 줄였다.
- Windows 경로가 아주 길면 pyarrow DLL 로드가 실패해 Streamlit 표가 그려지지 않는다(계산·테스트는 무관).
  README 에 적어 두었다.

---

## 8b. 구현 순서와 진행 방식

1. 환경: 프로젝트 안에 `.venv`를 만들고 Python 3.14.6에 numpy, scipy, pandas, streamlit, plotly, statsmodels, pytest를 pip로 설치한다.
2. 아래 순서대로 **모듈 하나씩** 구현한다. 각 단계에서 해당 테스트가 통과한 것을 확인한 뒤 다음으로 넘어가고, 단계마다 결과(통과 수, 주요 수치)를 짧게 보고한다.
   1. provenance · units · materials
   2. ball · fall
   3. contact
   4. plate · impact
   5. segments
   6. failure
   7. calibration (+ 가상 샘플 CSV)
   8. helmet
   9. planner
   10. app.py (UI) → README
3. 구현 중 새로운 문헌 확인이 필요하면 먼저 확인하고, 이 문서 §1에 추가한다.

---

## 9. 확인이 필요한 사항

- **Q1. 막 효과 경고 임계값**
  - 문헌(Shivakumar, Timoshenko 인용)은 w/h ≤ 0.2에서 막 효과를 무시할 수 있다고 한다.
  - 제안: w/t > 0.2면 정보(문헌), w/t > 0.5면 경고(요청서)로 두는 2단계 방식.
- **Q2. 분할 구성의 center 타격 해석**
  - 제안: 쿠폰 전체 반경 a를 쓰고, lock on이면 고정단~단순지지 구간으로 이음 불확실성을 표현한다(A-13).
  - center를 "세그먼트 한 장의 중앙"으로 보고 세그먼트 등가반경을 써야 한다면 알려 주세요.
- **Q3. 점토 보정 참고값**
  - 확인된 RP1 기준은 1043±5 g 강구(63.5 mm), 2.0 m, 평균 19±2 mm(개별 19±3)다. 요청서의 "1.03 kg" 대신 1043 g을 참고 프리셋으로 써도 될까요? 사용자 기준값 입력은 그대로 둔다.
- **Q4. CSV 선택 열 추가**
  - `test_date`: "기준을 벗어난 날"을 날짜 단위로 판정하는 데 필요하다. 없으면 행 단위로 판정한다.
  - `v_rebound_mps`: 흡수 에너지를 실측 기반으로 계산할 수 있다.
  - 두 열 모두 선택 사항이며 필수 스키마는 바꾸지 않는다.
- **Q5. 헤드폼 질량**
  - FAST SF 시험 규격(FTHS/PS-1228)의 헤드폼 질량은 공개 자료에서 확인하지 못했다.
  - 제안: 기본값은 `TODO`(입력 필요)로 두고, FMVSS 218 소·중·대(3.5 / 5.0 / 6.1 kg 중앙값)를 "다른 규격 참고값"으로 고를 수 있게 한다.
- **Q6. statsmodels 추가**
  - 로지스틱 GLM과 계수 공분산을 얻는 데 쓴다. 요청서 목록(numpy, scipy, pandas, streamlit, plotly)에는 없다.
  - 허용하지 않으면 로지스틱 우도를 `scipy.optimize`로 최소화하는 방식으로 대체한다.
- **Q7. 몬테카를로 가속 방식(A-17)**
  - 2000회 × 높이 격자를 매번 2DOF로 풀면 수 분이 걸린다. 에너지 균형 모델에 2DOF 보정비를 곱하는 하이브리드 방식으로 해도 될까요?
