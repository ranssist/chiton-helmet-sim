"""3D 헬멧 메시(Meshy 등)에서 시뮬레이터 입력값을 뽑는다 (chiton_sim.mesh 의 CLI).

앱에서 바로 하려면 '헬멧' 탭의 "3D 모델에서 치수 불러오기"에 파일을 올리면 된다.
이 스크립트는 같은 계산을 터미널에서 하고 JSON 으로 저장할 때 쓴다.

주의
- 생성형 3D 메시는 실제 치수가 없다. --target-circumference-cm 또는 --target-width-mm 로 반드시 축척을 맞춘다.
- 형상 치수만 뽑는다. 메시 위에서 응력을 푸는 FEA 가 아니다.
- 곡률 효과는 모델에 없다(평판 가정). 곡률 반경은 참고로만 출력한다.

사용법
  .venv/Scripts/python scripts/mesh_props.py helmet.glb --target-circumference-cm 57.5
  .venv/Scripts/python scripts/mesh_props.py helmet.obj --scale 0.001 --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chiton_sim import units  # noqa: E402
from chiton_sim.mesh import measure, to_dict  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser(description="헬멧 메시 → 시뮬레이터 입력값")
    ap.add_argument("mesh", type=Path, help="glb / gltf / obj / stl / ply (FBX·USDZ 는 GLB 로 내보낸다)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--target-circumference-cm", type=float, help="머리둘레 기준 축척 (FAST SF L = 56–59)")
    g.add_argument("--target-width-mm", type=float, help="좌우 최대 폭 기준 축척")
    g.add_argument("--scale", type=float, help="직접 곱할 축척 (예: mm 단위 메시면 0.001)")
    ap.add_argument("--liner-mm", type=float, default=0.0,
                    help="--target-circumference-cm 를 '머리둘레'로 줄 때 라이너 두께 [mm]")
    ap.add_argument("--shell-mm", type=float, default=0.0,
                    help="같은 경우의 셸 두께 [mm] — 둘레는 2π(라이너+셸)만큼 커진다")
    ap.add_argument("--json", type=Path, help="결과를 JSON 으로 저장")
    args = ap.parse_args()

    p = measure(
        args.mesh, scale=args.scale,
        target_width=units.mm_to_m(args.target_width_mm) if args.target_width_mm else None,
        target_circumference=(units.cm_to_m(args.target_circumference_cm)
                              if args.target_circumference_cm else None),
        liner=units.mm_to_m(args.liner_mm), shell=units.mm_to_m(args.shell_mm))

    print(f"파일: {p.name} · 부품/조각 {p.n_parts}개"
          + (" (안/바깥 면 한 쌍으로 판단 — 분할판이 아니다)" if p.nested else "")
          + f" · 삼각형 {p.n_faces:,}개")
    print(f"축척: {p.scale_how}")
    print(f"경계 상자: {units.m_to_cm(p.bbox[0]):.1f} × {units.m_to_cm(p.bbox[1]):.1f} × {units.m_to_cm(p.bbox[2]):.1f} cm")
    print(f"최대 수평 둘레: {units.m_to_cm(p.perimeter):.1f} cm (높이 z = {units.m_to_cm(p.perimeter_z):.1f} cm)")
    print(f"닫힌(watertight) 메시: {p.watertight} · 얇은 셸로 판단: {p.thin_shell}")
    print()
    print("시뮬레이터 입력값")
    print(f"  셸 표면적 A        : {units.m2_to_cm2(p.area_outer):.0f} cm²   ('헬멧' 탭의 A 에 입력)"
          + ("  ← 안·바깥 양면 중 바깥면" if p.thin_shell else "  ← 열린 면이라 한 면 기준"))
    print(f"  투영 면적          : {units.m2_to_cm2(p.projected):.0f} cm²   [{p.projected_method}]  (A_spread 의 f 기준면)")
    if p.thickness_est is not None:
        print(f"  셸 두께 추정       : {units.m_to_mm(p.thickness_est):.2f} mm   (= 부피/바깥면적)")
    else:
        print("  셸 두께 추정       : 불가(닫힌 메시가 아니다) — 두께는 직접 입력한다")
    if p.n_segments > 1:
        print(f"  분할판 1장 면적    : 최대 {units.m2_to_cm2(p.segment_areas[0]):.0f} cm², "
              f"최소 {units.m2_to_cm2(p.segment_areas[-1]):.0f} cm² (조각 {p.n_segments}개)")
    print(f"  이음선(열린 모서리): {units.m_to_cm(p.seam_length):.1f} cm   (겹침 면적비 계산에 쓴다)")
    print(f"  곡률 반경(구 근사) : {units.m_to_cm(p.sphere_radius):.1f} cm   [참고 — 곡률 효과는 모델에 없다]")
    print()
    print("FAST SF L 비교: 커버리지 955 cm² · 면밀도 5957 g/m² · 셸 557 g(차세대)/655 g(데이터시트)")
    for w in p.warnings:
        print(f"⚠ [{w.severity.value}] {w.message}")

    if args.json:
        args.json.write_text(json.dumps(to_dict(p), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 저장: {args.json}")


if __name__ == "__main__":
    main()
