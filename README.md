# 군부 겹판 접이식 분할 헬멧 — 낙하 충격 시뮬레이터

군부(chiton)의 겹판 구조를 모방한 접이식 분할 헬멧 설계를 검증하기 위한 낙하 충격 시뮬레이터다.
판 수준(원판 쿠폰) 해석, 소규모 낙하 실험 데이터 보정, 구성·타격 위치별 50 % 파손 에너지(E50) 추정,
헬멧 수준 무게·헤드폼 충격 비교를 한다.

---

## 범위와 면책

- 이 시뮬레이터는 **PLA 등 FDM 출력물의 둔탁 충격 거동 모델**이다.
- **방탄 성능은 다루지 않는다.** 용어는 '방탄판'이 아니라 **'충격 분산판'**을 쓴다.
- **IHPS·FAST(UHMWPE 등 복합재 셸)의 성능을 예측하지 않는다.** FAST SF 수치는 치수·무게·시험 조건의
  **비교 기준**으로만 쓴다.
- 모델은 준정적 2자유도 스프링-질량 근사다. 막(membrane) 효과는 선택해서 넣을 수 있고,
  변형률 속도 효과·전단 강성·파동 지배 충돌·곡률 효과는 들어 있지 않다. 해당 영역에서는 화면에 경고가 뜬다.

---

## 실행 방법

**배포된 링크로 보는 경우** — 아무 파일도 열 필요가 없다. 브라우저 주소만 열면 된다.

**내 PC에서 돌리는 경우** — 저장소를 받은 뒤(Code → Download ZIP 또는 `git clone`),

| 운영체제 | 방법 |
|---|---|
| Windows | `run.bat` **더블클릭** |
| macOS / Linux | 터미널에서 `bash run.sh` |

처음 한 번은 파이썬 환경을 만드느라 1~3분 걸리고, 그다음부터는 바로 켜진다.
브라우저가 자동으로 열리지 않으면 `http://localhost:8501` 로 들어가면 된다. 종료는 창에서 Ctrl+C.
파이썬이 없으면 [python.org](https://www.python.org/downloads/) 에서 설치하고,
설치 화면의 "Add python.exe to PATH" 를 체크한다.

**직접 명령으로 실행·시험하는 경우** (PowerShell은 `&&` 대신 `;` 를 쓴다)

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows (Linux/macOS: .venv/bin/pip)
.venv/Scripts/python -m pytest -q                 # 테스트
.venv/Scripts/streamlit run app.py                # UI
```

`app.py` 는 더블클릭으로 열리는 파일이 아니라 Streamlit 진입점이다. 반드시 `streamlit run` 으로 실행한다.

가상 데이터를 다시 만들려면:

```bash
PYTHONPATH=. .venv/Scripts/python scripts/make_virtual_data.py
```

> **Windows 경로 길이 주의.** 프로젝트 경로가 아주 길면(약 200자 이상) pyarrow DLL 로드가 실패해
> Streamlit 표가 그려지지 않는다. 계산과 pytest 는 영향을 받지 않는다. 짧은 경로(예: `C:\work\chiton-sim`)에
> 두거나 Windows 긴 경로 지원을 켜면 된다.

---

## 구조

| 파일 | 역할 |
|---|---|
| `chiton_sim/provenance.py` | 값 라벨(문헌값·계산값·가정·미확인·보정 후), 출처, 경고, 예외 |
| `chiton_sim/units.py` | UI 전용 단위 변환(g, mm, cm, 층, CSV → SI) |
| `chiton_sim/materials.py` | 재료·물리 상수 프리셋(PLA TDS, 크롬강, EPP, 표준대기) |
| `chiton_sim/ball.py` | 구슬 질량↔지름, 규격 강구, 가이드관 검사 |
| `chiton_sim/fall.py` | 낙하 ODE, 구 항력 상관식, 관 폐색·벽 손실 |
| `chiton_sim/contact.py` | 탄성 Hertz(참고), Thornton 탄소성 접촉 |
| `chiton_sim/plate.py` | 원판 굽힘 강성, 유효질량, Roark 참고 응력 |
| `chiton_sim/impact.py` | 2자유도 스프링-질량 충돌, 에너지 분배, 적용범위 경고 |
| `chiton_sim/segments.py` | 구성×타격 위치, 응력집중, 면밀도, 같은 두께/같은 면밀도 |
| `chiton_sim/failure.py` | 참고 판정, 주 판정 E_c(t) = C·tⁿ, 몬테카를로 |
| `chiton_sim/calibration.py` | CSV 스키마, 관 손실·p_y 적합, Bruceton, 로지스틱, 손실률, 점토 검사 |
| `chiton_sim/helmet.py` | 셸 무게·면밀도, 헤드폼 1자유도, 측정 가능성 |
| `chiton_sim/planner.py` | 동일 에너지 조합, 계단법 도우미, 시편 수, 곡면 확인 |
| `chiton_sim/compare.py` | 재료 비교(같은 두께/같은 면밀도), 순위 |
| `chiton_sim/grading.py` | A~F 등급 (절대 기준선 / 상대 순위) |
| `chiton_sim/mesh.py` | 3D 헬멧 메시 → 표면적·투영면적·두께·분할판 면적 (선택 의존성) |
| `app.py` | Streamlit UI (판 충돌 / 분할 비교 / 헬멧 / 보정 / 실험 계획) |
| `run.bat` · `run.sh` | 더블클릭(또는 한 줄) 실행 — 가상환경 생성·설치·실행까지 |
| `scripts/error_budget.py` | 오차 예산 재계산 |
| `scripts/mesh_props.py` | 위 모듈의 터미널 버전(JSON 저장용) |
| `docs/error_budget.md` | 예측과 실험의 오차 분석 |
| `data/sample_VIRTUAL_drop_tests.csv` | **가상** 시험 데이터 (실측 아님) |

내부 계산은 전부 SI 단위다. g, mm, cm, 층 단위 변환은 `units.py`와 `app.py`에서만 한다(테스트로 확인).

---

## 라벨 규칙

- 모든 값 옆: `문헌값` · `계산값` · `가정` · `미확인` · `보정 후`
- 모든 결과 블록 머리: `문헌값 기반(보정 전)` 또는 `실측 보정 후`
- 해석식이 없는 항목: `해석 불가·실측 보정값`
- 보정 데이터가 없을 때: 숫자 대신 `실측 필요`

출처를 찾지 못한 값은 추정해서 넣지 않았다. 코드에는 `TODO(source)` 주석이 있고 UI에는 "미확인"으로 나온다.
현재 미확인 항목은 아래와 같다.

| 항목 | 상태 |
|---|---|
| FTHS(FAST SF 시험 규격) 헤드폼 질량 | 공개 자료 없음 → 사용자 입력. FMVSS 218 값(3.5/5.0/6.1 kg)은 '다른 규격 참고값'으로만 제공 |
| FDM PLA 체결부 p/d, e/d 기준 | 표준·문헌을 찾지 못함 → 사용자 입력, 미입력 시 비교만 표시 |
| 폼 치밀화 변형률 ε_D | Gibson–Ashby 식 원문 확인 실패 → 사용자 입력, 미입력 시 기하학적 상한(스트로크 ≤ 라이너 두께) 사용 |
| ASTM D5420 본문(지지링·타구 치수, 규격 고유 식) | 유료 표준 → Dixon–Mood 식으로 대체 구현 |
| PET병 병목 내경 | 도면값 미확인 → 21 mm 가정 + 경고 |
| PLA 푸아송비 | TDS에 없음 → 0.36 가정 (PETG 0.40, 복합재 0.30 도 가정) |
| UHMWPE 적층판 굽힘강도 | 문헌은 면내 인장(3.1 GPa)만 제시 → 굽힘 파손 기준 아님, 실측 입력 필요 |
| FAST SF 셸 굽힘 물성 | 제조사 비공개 → 무게·면밀도 비교만 가능 |

---

## 모델과 가정

### 낙하
`m dv/dt = m g − ½ ρ C_d(Re) A v|v| K_tube`, 충돌 속도에 벽 손실률 η를 곱한다.
`C_d(Re)`는 Morrison(2013) 상관식(Re ≤ 10⁶)이고, K_tube(기본 1.0)와 η(기본 0)는 실측 보정 대상이다.

### 접촉
Thornton(1997) 탄성-완전소성. 항복 전 Hertz, 항복 후 `F = F_y + π p_y R (δ − δ_y)`, 제하는 반경 R_p 의
Hertz 곡선이다. `p_y` 초기값은 1.6·Y(Y는 굽힘강도 대용값)이고 실측 압흔으로 보정한다.

### 판과 충돌
고정단 `K_b = 16πD/a²`, 단순지지 `K_b = 16π(1+ν)D/((3+ν)a²)`, 유효 판 질량은 판 질량의 1/4이다.
2자유도 모델을 `solve_ivp`로 풀고, `∫F dt = m v(1+e)` 와 에너지 수지를 자동 검산한다.
접촉은 단방향(인장 불허)이라 분리·재접촉이 일어날 수 있다.

### 주요 가정
| ID | 가정 |
|---|---|
| A-01 | PLA 푸아송비 0.36 (TDS에 없음) |
| A-02 | TDS의 ± 값을 1σ로 해석(몬테카를로) |
| A-03 | TDS 값은 인필 100 %·어닐링 시편 기준 — 다르면 경고 |
| A-04 | 출력 방향 XY=눕혀 출력, Z=세워 출력(보수적) |
| A-05 | 항복강도 Y 대용값 = 굽힘강도 |
| A-06 | 강구는 탄성, 소성은 판에서만 |
| A-07 | 전단 강성 생략. 막 강성은 선택(기본 '자동': w/t > 0.2면 포함) |
| A-08 | 유효 판 질량 = 링 내부 판 질량의 1/4 |
| A-13 | 분할+잠금 center 타격은 고정단~단순지지 구간으로 표현 |
| A-14 | 겹침 면적 = 이음선 길이 × 겹침 폭(CAD 입력) |
| A-16 | 흡수 에너지 = 입력 − 반발(모델) |
| A-17 | 몬테카를로는 에너지 균형 모델 × 2자유도 보정비 |
| A-18 | 헤드폼 1자유도, 라이너 힘 = σ·A_spread |
| A-19 | A_spread: 일체형 = 투영면적 × f, 분할형 = 판 1장 면적 ×(1+β) |
| A-21 | 가속도계 응답을 2차 Butterworth로 근사 |
| A-26 | 판 강성을 실측하면 경계조건 가정을 쓰지 않는다(실측값이 이론값에 우선) |

전체 목록과 근거는 `PLAN.md` §1(문헌 확인 결과)과 §4(가정 목록)에 있다.

### 재료 라이브러리

출력해서 실제로 시험할 필라멘트와, 비교 기준으로 쓰는 실제 방탄모 계열 셸 재질이 함께 들어 있다.
'재료 비교' 탭에서 **같은 두께 / 같은 면밀도** 기준으로 면밀도·셸 무게·판 강성·굽힘응력·여유율·
흡수 에너지·h50 을 나란히 본다.

| 재료 | 분류 | 밀도 | 굽힘탄성률 | 굽힘강도 | 출처 |
|---|---|---|---|---|---|
| Bambu PLA Basic | 출력 가능 | 1.24 g/cm³ | 2.75 GPa | 76 MPa | TDS V3.0 |
| Bambu PETG HF | 출력 가능 | 1.28 g/cm³ | 2.05 GPa | 64 MPa | TDS V1.0 |
| 아라미드/에폭시 적층판 | 비교용 | 1.32 g/cm³ | 10.38 GPa | 109 MPa | Polymers 14:3749 (2022) |
| UHMWPE 적층판 | 비교용 | 0.97 g/cm³ | 30.7 GPa(면내) | **미확인** | Polymers 16:2985 (2024) |
| FAST SF 하이브리드 셸 | 비교용 | 1.07 g/cm³(계산) | **미확인** | **미확인** | Ops-Core 데이터시트 |

> **이 비교는 방탄 성능 비교가 아니다.** 복합 적층판은 층간 박리·섬유 파단·변형률 속도로 파손하는데
> 이 모델은 등방성 평판 가정이라 그 파손 방식을 보지 못한다. 실제로 계산 결과를 보면 뻣뻣한 아라미드
> 적층판이 하중을 더 끌어와 굽힘응력 여유율은 오히려 낮게 나온다. **여유율이 높다 = 더 안전하다가 아니다.**
> 지표별로 따로 보고, 최종 판단은 실측 E50 으로 한다.

### 등급 (A~F)

"어떤 수치가 나와야 좋은가"를 등급으로 보여 준다. 두 종류를 구분한다.

**절대 등급** — 기준선이 있는 지표. 점수 = 기준선 대비 여유이고 **점수 1.0 = 기준 충족 = C** 다.

| 지표 | 기준선 | 출처 |
|---|---|---|
| 헤드폼 최대 가속도 | 150 g @ 10 ft/s | FAST SF 데이터시트 [문헌값] |
| 굽힘응력 여유율 | 1.0 (응력 = 굽힘강도) | 물리적 경계 [계산값] |
| 필요 스트로크 | 라이너가 쓸 수 있는 스트로크 | 물리적 경계(바닥침) [계산값] |
| 면밀도 | 5957 g/m² | FAST SF 데이터시트 [문헌값] |
| 셸 무게 | 목표값(기본 557 g = FAST SF L 차세대) | [가정·사용자] |
| 임계 높이 h50 | 목표 높이(기본 2 m) | [가정·사용자] |
| 측정 피크 오차 | 허용오차(기본 5 %) | [가정·사용자] |

**상대 등급** — 기준선이 없는 지표(판 강성 등)는 비교 대상 안의 **순위**로만 매기고 그렇게 표시한다.

- **A~F 경계는 문헌 근거가 없는 가정이다.** 기본값은 A ≥ 1.5, B ≥ 1.2, C ≥ 1.0, D ≥ 0.85, E ≥ 0.7이며
  사이드바 '등급 기준'에서 바꿀 수 있다. 등급 옆에는 항상 원래 수치와 기준선을 함께 보여 준다.
- **기준선이나 값이 미확인이면 등급을 만들지 않고 `-` 로 둔다.**
- 종합 등급은 4개 지표 중 3개 이상 채점될 때만 낸다. 그러지 않으면 굽힘 물성이 미확인인 재료가
  '모르는 항목을 빼서' 좋은 등급을 받는 일이 생긴다(UHMWPE·FAST SF 셸이 그런 경우다).

### 오차를 줄이는 장치

예측이 실제 실험과 얼마나 어긋나는지는 [docs/error_budget.md](docs/error_budget.md) 에 계산해 뒀다.
요약하면 **보정 전 예측은 2배 이내** 수준이고, 가장 큰 항목은 물성 산포(±15 %)가 아니라
**경계조건 가정(+78 %)** 이다. 이를 줄이려고 아래를 넣었다.

| 장치 | 없애는 오차 | 쓰는 곳 |
|---|---|---|
| **판 강성 실측** (정적 압입 P = K_b·w + K_m·w³ 적합) | 경계조건 가정 +78 % | 보정 탭 0번 |
| **막(membrane) 강성** (Shivakumar Table 1, 고정단) | 막 효과 누락 −10 % | 사이드바 '모델 옵션', 기본 '자동'(w/t > 0.2면 포함) |
| **p_y 보정** (압흔 실측) 또는 p_y/Y 슬라이더 | p_y 가정 −11 % | 보정 탭 / 사이드바 |
| **2자유도 기본 사용** | 판 관성 무시 −22 % | 기본값 |
| **예측 밴드** | 남은 가정을 한눈에 | 판 충돌 탭 상단 |

예측 밴드는 시나리오(경계조건·p_y·막 효과)를 한 번에 계산해 응력 범위를 보여 주고,
**무엇을 재면 밴드가 좁아지는지** 화면에 같이 적는다.

### 조작 (UX)

- **빠른 설정 버튼**: 낙하탑 1.5 m / 2 m / PET병 관 / 5층 낙하를 한 번에 적용
- **기본 / 접힌 고급**: 자주 만지는 높이·구슬·두께·구성은 위에, 나머지는 접어 둔다
- **설정 저장·불러오기**: 현재 설정을 JSON 으로 내려받아 친구에게 보내면 같은 조건이 그대로 재현된다
- 모든 값 옆에 라벨이 붙고, 적용범위를 벗어나면 경고가 뜬다

### 3D 모델(Meshy 등) 적용

헬멧 탭 맨 위 **"3D 모델에서 치수 불러오기"** 에 파일을 올리면 시뮬레이터 입력이 채워진다.

1. 설치(한 번만): `.venv/Scripts/pip install -r requirements-mesh.txt`
2. 파일 형식: `glb` · `gltf` · `obj` · `stl` · `ply` · `off` · `3mf`  (Meshy 는 **GLB 로 내보내기**가 제일 무난하다. FBX·USDZ 는 GLB 로 변환한다.)
3. **축척을 반드시 지정한다.** 생성형 3D 모델에는 실제 치수가 없다.
   - 머리둘레 기준(권장): 머리둘레 + 라이너 두께 + 셸 두께 → 셸 바깥 둘레 = 머리둘레 + 2π(라이너+셸)
   - 좌우 폭 기준 / 직접 배율(파일 단위가 mm 면 0.001)
   - 축척을 지정하지 않으면 면적은 `미확인`으로 두고 **적용 버튼이 잠긴다**
4. "치수 읽기" → 표를 확인 → "이 값을 헬멧 입력에 적용"

| 읽는 값 | 쓰이는 곳 | 비고 |
|---|---|---|
| 셸 표면적 A | 셸 무게·면밀도·무게 등급 | 안/바깥 두 면이 있으면 바깥 면만 센다 |
| 투영 면적 | `A_spread = 투영면적 × f` | 삼각형 그림자 합집합 — 통풍구·조각 사이 빈 공간을 반영한다 |
| 셸 두께 | 무게·면밀도 | 부피/바깥면적. **닫힌 메시일 때만** 나오고, 아니면 직접 입력한다 |
| 분할판 1장 면적 | 분할형 `A_spread` | 떨어져 있는 조각을 분할판으로 센다 |
| 이음선 길이 | 겹침 면적비 참고 | 열린 모서리 길이의 합 |
| 곡률 반경 | **참고만** | 모델은 평판 가정이라 곡률 효과가 없다 |

한계: 이 기능은 **형상 치수만** 읽는다. 메시 위에서 응력을 푸는 FEA 가 아니다. 판 충돌 계산은 여전히
원판(반지름 `a`, 두께 `t`) 모델이고, 헬멧 탭은 그 결과에 메시에서 읽은 면적·두께를 넣는 것이다.
안/바깥 면이 한 쌍으로 들어오면 분할판 2장으로 세지 않고 두께 계산에 쓴다.

### 적용범위 경고
- 구슬/판 질량비 < 0.25 → 파동 지배 충돌(준정적 모델 부정확)
- 질량비 0.25–3.5 → 중간 영역, 판 관성 무시 불가
- w/t > 0.2 → 막 효과 시작 가능(문헌), w/t > 0.5 → 막 효과 누락 경고 (막 강성을 켜면 '포함' 안내로 바뀐다)
- 충돌 속도 > 10 m/s → 변형률 속도 효과 누락
- p₀ > 1.6Y → 탄성 Hertz 모델 무효(국부 항복)
- 구슬 지름 > 관 내경 − 여유 → 계산 차단

---

## 실험 절차 요약

1. **판정 기준을 먼저 정한다.** 관통 균열·조각 이탈·잠금 풀림·받침 탈락 등. 기준이 비어 있으면 보정이 차단된다.
2. **시편 수를 계획한다.** 구성 × 타격 위치 × 접힘 횟수 조합마다 계단법 20–30회.
3. **계단법으로 시험한다.** 시작 높이는 예상 평균 근처, 파손이면 한 단계 낮추고 아니면 높인다.
4. **속도를 실측한다(광센서).** 관 손실률 η 보정에 쓴다.
5. **압흔을 측정한다.** p_y 보정에 쓴다.
6. **배면 점토를 매일 보정한다.** 기준을 벗어난 날의 bfd 에는 경고가 붙는다. bfd 는 합불 기준이 아니라 구성 간 비교 지표다.
7. **동일 에너지 2조합**(가벼운 공·높은 높이 / 무거운 공·낮은 높이)으로 속도 효과를 확인한다.
8. **CSV를 올려 보정한다.** 보정 전/후 오차표, E50, 분할 손실률, 접힘 추세가 나온다.
9. **곡면 헬멧으로 소수 회 확인한다.** 평판 예측과의 차이는 '곡률·형상 효과'로 기록한다.

### CSV 스키마

필수: `specimen_id, config_type, overlap_mm, n_segments, lock, joint_type, thickness_mm, orientation,
infill_pct, fastener_type, vent_type, impact_site, fold_cycles, ball_g, height_m, v_measured_mps,
result, failure_mode, dent_mm, bfd_mm, clay_cal_mm`

선택: `test_date`(날짜별 점토 검사), `v_rebound_mps`

- `result` 는 `pass`/`fail`, `lock` 은 `on`/`off`, 값이 없는 칸은 비워 둔다.
- 단위는 실험 기록 단위(mm, g, %)이며 프로그램이 SI로 바꾼다.
- 샘플: `data/sample_VIRTUAL_drop_tests.csv` (**가상 데이터**, 참값 η = 0.030, p_y = 167 MPa로 생성)

---

## 검증

`pytest`로 다음을 확인한다.

- 항력 0이면 v = √(2gh) (상대오차 < 1e-6)
- 질량↔지름 왕복, 관 내경 초과 시 예외
- Hertz 구현이 McLaskey & Glaser(2010) 식 (4)·(6)과 0.3 % 이내로 일치, He & Wettlaufer(2013)의 계수 2.8683 확인
- Thornton 수치 적분이 Thornton(1997) 반발계수 닫힌 해와 0.5 % 이내로 일치
- 무감쇠·무소성 2자유도 에너지 보존 오차 < 0.5 %, e = 1일 때 ∫F dt = 2mv
- Shivakumar 외 NASA TM-85703 Fig. 7 사례(0.607 ms) 재현 ±10 %
- Bruceton 계산이 공개 예제(50 % 수준 3.45)를 재현
- 분할 손실률이 알려진 가상 데이터(참값 0.30)를 복원하고 CI가 참값을 포함
- 판정 기준이 비면 보정 차단
- 면밀도 환산, 헤드폼 s_min = v²/(2a), seam·triple_junction 무보정 시 `실측 필요`

---

## 참고문헌

- Bambu Lab, PLA Basic Technical Data Sheet V3.0 — https://wiki.bambulab.com/filament-acc/abs-asa-pc/bambu_pla_basic_technical_data_sheet.pdf
- F.A. Morrison, *Data Correlation for Drag Coefficient for Sphere* (2016) / *An Introduction to Fluid Mechanics*, Cambridge UP (2013) — https://pages.mtu.edu/~fmorriso/DataCorrelationForSphereDrag2016.pdf
- A. He & J.S. Wettlaufer, *Hertz beyond expectations*, arXiv:1306.4952 (2013)
- G.C. McLaskey & S.D. Glaser, *Hertzian impact*, J. Acoust. Soc. Am. 128(3):1087 (2010) — https://courses.cit.cornell.edu/mclaskey/pubs/JASA2010.pdf
- H.A. Burgoyne & C. Daraio, Phys. Rev. E 89, 032203 (2014) — 항복 시작 p₀ = 1.6Y
- C. Thornton, J. Appl. Mech. 64(2):383 (1997) — 탄성-완전소성 접촉 (원문 유료. 식은 arXiv:2104.00344, 반발계수는 Jackson, Green & Marghitu, Nonlinear Dyn. 60:217 (2010)에서 확인)
- K.N. Shivakumar, W. Elber, W. Illg, NASA TM-85703 (1983) / J. Appl. Mech. 52:674 (1985), doi:10.1115/1.3169120
- S. Timoshenko & S. Woinowsky-Krieger, *Theory of Plates and Shells*, McGraw-Hill (1959)
- Roark's Formulas for Stress and Strain — 소면적 하중 등가반경
- C. Dumont, NACA TN-740 (1939) — 구멍이 있는 판의 굽힘 응력집중
- R. Olsson, Compos. Part A 31:879 (2000) — 파동 지배 충돌 질량 기준
- W.J. Dixon & A.M. Mood, JASA 43:109 (1948); M.T. Chao & C.D. Fuh, Statistica Sinica 11:1 (2001)
- ASTM D5420 요약(Intertek) — https://intertek.com/polymers/testlopedia/gardner-impact
- Ops-Core FAST SF Data Sheet (Gentex, REV.20230306) — https://img.trex-arms.com/wp/uploads/2023/09/FAST_SF_Ops-Core_Data_Sheet.pdf
- RTS Tactical, FAST SF 제품 페이지 — 차세대 L 셸 557 g
- 49 CFR 571.218 (FMVSS No. 218) — 헤드폼 질량
- NIJ Standard-0101.04 Addendum B — https://www.ojp.gov/pdffiles1/nij/nlectc/206095.pdf ; NRC, *Testing of Body Armor Materials: Phase III* (2012) — 점토 낙하 보정
- JSP ARPRO EPP 물성표(ASTM D3575) — https://www.foam-industries.com/hubfs/Technical%20Documents/TechDataHome_PhysicalPropertyInformation_EPPproducts.pdf
- Arduino 공식 레퍼런스 `analogRead()` — 약 10,000회/s
- M.J. Connors 외, *Bioinspired design of flexible armor based on chiton scales*, Nat. Commun. (2019), doi:10.1038/s41467-019-13215-0
- L. Li 외, *Multifunctionality of chiton biomineralized armor with an integrated visual system*, Science 350(6263):952 (2015), doi:10.1126/science.aad1246
- Soldier Systems Daily (2023-10-10) — NG-IHPS 무천공(holeless) 설계
- Bicycle Helmet Safety Institute, 접이식 헬멧 — https://helmets.org/folding/
