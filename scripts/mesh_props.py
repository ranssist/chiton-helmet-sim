"""3D 헬멧 메시(Meshy 등)에서 시뮬레이터 입력값을 뽑는다.

뽑는 것: 셸 표면적 A, 투영 면적, 분할판 개수·면적, 이음선(열린 모서리) 길이, 셸 두께 추정,
곡률 반경(구 근사). 이 값들은 '헬멧' 탭의 A, 분할판 면적, 겹침 면적비 계산에 그대로 쓴다.

주의
- 생성형 3D 메시는 실제 치수가 없다. --target-circumference-cm 또는 --target-width-mm 로 반드시 축척을 맞춘다.
- 이 스크립트는 형상 치수만 뽑는다. 메시 위에서 응력을 푸는 FEA 가 아니다.
- 곡률 효과는 모델에 없다(평판 가정). 곡률 반경은 참고로만 출력한다.

사용법
  .venv/Scripts/python scripts/mesh_props.py helmet.glb --target-circumference-cm 57.5
  .venv/Scripts/python scripts/mesh_props.py helmet.obj --scale 0.001 --json out.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import trimesh

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_meshes(path: Path) -> list[trimesh.Trimesh]:
    """장면이면 부품별로, 단일 메시면 연결 요소별로 나눈다(분할판 개수 파악)."""
    obj = trimesh.load(path, force="scene")
    parts: list[trimesh.Trimesh] = []
    for g in obj.geometry.values():
        if isinstance(g, trimesh.Trimesh) and len(g.faces):
            parts.append(g)
    if len(parts) == 1:
        split = parts[0].split(only_watertight=False)
        if len(split) > 1:
            parts = [m for m in split if len(m.faces) > 10]
    return parts


def max_horizontal_perimeter(mesh: trimesh.Trimesh, n: int = 40) -> tuple[float, float]:
    """수평 단면 둘레의 최대값과 그 높이 (머리둘레 축척용)."""
    zmin, zmax = mesh.bounds[0][2], mesh.bounds[1][2]
    best, best_z = 0.0, zmin
    for z in np.linspace(zmin + 0.02 * (zmax - zmin), zmax - 0.02 * (zmax - zmin), n):
        try:
            sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        except Exception:
            sec = None
        if sec is None:
            continue
        length = float(np.sum(sec.length)) if np.ndim(sec.length) else float(sec.length)
        if length > best:
            best, best_z = length, float(z)
    return best, best_z


def projected_area(mesh: trimesh.Trimesh) -> tuple[float, str]:
    """위에서 본 투영 면적. shapely 가 있으면 정확히, 없으면 볼록껍질 근사."""
    try:
        from trimesh.path import polygons
        poly = polygons.projected(mesh, normal=[0, 0, 1])
        if poly is not None:
            return float(poly.area), "정확(윤곽 합집합)"
    except Exception:
        pass
    from scipy.spatial import ConvexHull
    hull = ConvexHull(mesh.vertices[:, :2])
    return float(hull.volume), "근사(볼록껍질 — 실제보다 크게 나온다)"


def open_edge_length(mesh: trimesh.Trimesh) -> float:
    """열린 모서리(경계) 길이 합 — 분할판 테두리·이음선 길이의 대용값."""
    edges = mesh.edges_sorted
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = uniq[counts == 1]
    if not len(boundary):
        return 0.0
    v = mesh.vertices
    return float(np.linalg.norm(v[boundary[:, 0]] - v[boundary[:, 1]], axis=1).sum())


def nested_shells(parts: list[trimesh.Trimesh]) -> bool:
    """조각들이 같은 중심을 공유하는 안/바깥 면인지(= 분할판이 아닌지) 판단한다."""
    if len(parts) < 2:
        return False
    cents = np.array([m.bounds.mean(axis=0) for m in parts])
    sizes = np.array([m.extents.max() for m in parts])
    spread = np.linalg.norm(cents - cents.mean(axis=0), axis=1).max()
    return spread < 0.05 * sizes.max() and (sizes.max() - sizes.min()) < 0.2 * sizes.max()


def fit_sphere_radius(mesh: trimesh.Trimesh) -> float:
    """정점에 구를 최소제곱으로 맞춘 반경 (곡률 참고값)."""
    p = np.asarray(mesh.vertices, float)
    A = np.column_stack([2 * p, np.ones(len(p))])
    b = (p**2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:3]
    return float(math.sqrt(max(sol[3] + (c**2).sum(), 0.0)))


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

    parts = load_meshes(args.mesh)
    if not parts:
        raise SystemExit("메시를 읽지 못했다")
    whole = trimesh.util.concatenate(parts)

    # --- 축척 ---------------------------------------------------------------
    scale, how = 1.0, "축척 미지정 — 파일 단위를 m 로 가정했다(결과가 틀릴 수 있다)"
    if args.scale:
        scale, how = args.scale, f"직접 지정 ×{args.scale}"
    elif args.target_width_mm:
        w = float(whole.extents[:2].max())
        scale = (args.target_width_mm / 1000.0) / w
        how = f"좌우 폭 {args.target_width_mm:.0f} mm 기준 ×{scale:.5g}"
    elif args.target_circumference_cm:
        per, _z = max_horizontal_perimeter(whole)
        if per <= 0:
            raise SystemExit("수평 단면 둘레를 재지 못했다 — --target-width-mm 나 --scale 을 쓴다")
        offset = 2.0 * math.pi * (args.liner_mm + args.shell_mm) / 1000.0
        target = args.target_circumference_cm / 100.0 + offset
        scale = target / per
        how = (f"바깥 둘레 {target*100:.1f} cm 기준 ×{scale:.5g}"
               + (f" (머리둘레 {args.target_circumference_cm:.1f} cm + 라이너·셸 {offset*100:.1f} cm)"
                  if offset > 0 else ""))
    if scale != 1.0:
        for m in parts:
            m.apply_scale(scale)
        whole = trimesh.util.concatenate(parts)

    # --- 측정 ---------------------------------------------------------------
    area_total = float(whole.area)
    vol = float(abs(whole.volume)) if whole.is_watertight else float("nan")
    thin_shell = whole.is_watertight and not math.isnan(vol) and (vol / area_total) < 0.02
    shell_pair = nested_shells(parts)      # 안/바깥 면이 따로 있는 메시인가
    if shell_pair:
        area_outer = max(float(m.area) for m in parts)     # 바깥 면만 센다
    elif thin_shell:
        area_outer = area_total / 2.0                       # 한 덩어리 셸: 절반이 바깥면
    else:
        area_outer = area_total
    proj, proj_how = projected_area(whole)
    per, per_z = max_horizontal_perimeter(whole)
    t_est = vol / area_outer if (thin_shell and area_outer > 0) else float("nan")
    seam = sum(open_edge_length(m) for m in parts)
    radius = fit_sphere_radius(whole)
    n_seg = 1 if shell_pair else len(parts)
    seg_areas = ([area_outer] if shell_pair
                 else sorted((float(m.area) / (2.0 if thin_shell else 1.0) for m in parts), reverse=True))

    print(f"파일: {args.mesh.name} · 부품/조각 {len(parts)}개"
          + (" (안/바깥 면 한 쌍으로 판단 — 분할판이 아니다)" if shell_pair else "")
          + f" · 삼각형 {len(whole.faces):,}개")
    print(f"축척: {how}")
    print(f"경계 상자: {whole.extents[0]*100:.1f} × {whole.extents[1]*100:.1f} × {whole.extents[2]*100:.1f} cm")
    print(f"최대 수평 둘레: {per*100:.1f} cm (높이 z = {per_z*100:.1f} cm)")
    print(f"닫힌(watertight) 메시: {whole.is_watertight} · 얇은 셸로 판단: {thin_shell}")
    print()
    print("시뮬레이터 입력값")
    print(f"  셸 표면적 A        : {area_outer*1e4:.0f} cm²   ('헬멧' 탭의 A 에 입력)"
          + ("  ← 안·바깥 양면 중 바깥면" if thin_shell else "  ← 열린 면이라 한 면 기준"))
    print(f"  투영 면적          : {proj*1e4:.0f} cm²   [{proj_how}]  (A_spread 의 f 기준면)")
    if not math.isnan(t_est):
        print(f"  셸 두께 추정       : {t_est*1000:.2f} mm   (= 부피/바깥면적)")
    else:
        print("  셸 두께 추정       : 불가(닫힌 메시가 아니다) — 두께는 직접 입력한다")
    if n_seg > 1:
        print(f"  분할판 1장 면적    : 최대 {seg_areas[0]*1e4:.0f} cm², 최소 {seg_areas[-1]*1e4:.0f} cm² "
              f"(조각 {n_seg}개)")
    print(f"  이음선(열린 모서리): {seam*100:.1f} cm   (겹침 면적비 계산에 쓴다)")
    print(f"  곡률 반경(구 근사) : {radius*100:.1f} cm   [참고 — 곡률 효과는 모델에 없다]")
    print()
    print("FAST SF L 비교: 커버리지 955 cm² · 면밀도 5957 g/m² · 셸 557 g(차세대)/655 g(데이터시트)")
    if scale == 1.0 and not (args.scale or args.target_width_mm or args.target_circumference_cm):
        print("⚠ 축척을 지정하지 않았다. 생성형 메시는 실제 치수가 없으므로 면적 수치를 그대로 믿으면 안 된다.")

    if args.json:
        args.json.write_text(json.dumps({
            "file": str(args.mesh), "scale": scale, "scale_how": how,
            "area_m2": area_outer, "area_total_m2": area_total, "projected_m2": proj,
            "projected_method": proj_how, "thin_shell": bool(thin_shell),
            "thickness_m_est": None if math.isnan(t_est) else t_est,
            "n_parts": len(parts), "n_segments": n_seg, "segment_areas_m2": seg_areas,
            "seam_length_m": seam, "sphere_radius_m": radius,
            "bbox_m": whole.extents.tolist(), "watertight": bool(whole.is_watertight),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 저장: {args.json}")


if __name__ == "__main__":
    main()
