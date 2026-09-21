"""3D 헬멧 메시(Meshy 등) → 시뮬레이터 입력 치수.

이 모듈은 '형상 치수만' 뽑는다. 메시 위에서 응력을 푸는 FEA 가 아니고, 곡률 효과도
모델에 없다(평판 가정). 그래서 여기서 나오는 값은 헬멧 탭의 표면적 A, 분할판 1장 면적,
셸 두께 같은 '입력'으로만 쓰인다.

생성형 3D 모델(Meshy·Tripo 등)에는 실제 치수가 없다. 축척을 지정하지 않으면 면적·두께는
의미가 없으므로 경고(MESH_NO_SCALE)를 남긴다.

trimesh 는 선택 의존성이다(requirements-mesh.txt). 없으면 MeshDependencyError 를 던진다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .provenance import Quantity, Severity, WarningLog, assumed, computed, unverified

# 읽을 수 있는 확장자. FBX·USDZ 는 Meshy 에서 GLB 로 내보내면 된다.
SUPPORTED_SUFFIXES = (".glb", ".gltf", ".obj", ".stl", ".ply", ".off", ".3mf")

# 얇은 셸 판정: 부피/바깥면적 < 2 cm 이면 판재로 본다(두께 20 mm 이하). [가정 A-32]
THIN_SHELL_RATIO = 0.02

# 조각들이 '안/바깥 면 한 쌍'인지 보는 기준 — 중심 차이 5 %, 크기 차이 20 % 이내. [가정 A-33]
NESTED_CENTER_TOL = 0.05
NESTED_SIZE_TOL = 0.20


class MeshDependencyError(ImportError):
    """trimesh 가 설치되지 않았다."""


def _trimesh():
    try:
        import trimesh  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 설치 환경에 따라 다름
        raise MeshDependencyError(
            "trimesh 가 없다. .venv/Scripts/pip install -r requirements-mesh.txt") from exc
    return trimesh


@dataclass(frozen=True)
class MeshProps:
    """메시에서 잰 값. 길이 m, 면적 m²."""

    name: str
    scale: float
    scale_how: str
    area_outer: float
    area_total: float
    projected: float
    projected_method: str
    thin_shell: bool
    nested: bool
    watertight: bool
    thickness_est: float | None
    n_parts: int
    n_segments: int
    segment_areas: tuple[float, ...]
    seam_length: float
    sphere_radius: float
    bbox: tuple[float, float, float]
    perimeter: float
    perimeter_z: float
    n_faces: int
    warnings: WarningLog = field(default_factory=WarningLog)

    # --- 시뮬레이터 입력으로 꺼낼 때 ---------------------------------------
    @property
    def area_q(self) -> Quantity:
        """헬멧 탭의 셸 표면적 A. 축척이 없으면 미확인으로 준다."""
        if self.scale_how.startswith("축척 미지정"):
            return unverified("m^2", "메시 축척 미지정 — 면적을 신뢰할 수 없다")
        return computed(self.area_outer, "m^2", f"메시 {self.name} ({self.scale_how})")

    @property
    def thickness_q(self) -> Quantity:
        """부피/바깥면적으로 추정한 셸 두께. 닫힌 메시가 아니면 미확인."""
        if self.thickness_est is None:
            return unverified("m", "닫힌(watertight) 메시가 아니라 두께를 잴 수 없다")
        return computed(self.thickness_est, "m", f"메시 부피/바깥면적 ({self.name})")

    @property
    def segment_area_q(self) -> Quantity:
        """분할판 1장 면적(가장 큰 조각). 조각이 하나면 미확인."""
        if self.n_segments < 2 or not self.segment_areas:
            return unverified("m^2", "분할 조각이 하나라 판 1장 면적을 잴 수 없다")
        return computed(self.segment_areas[0], "m^2", f"메시 최대 조각 ({self.name})")

    @property
    def curvature_radius_q(self) -> Quantity:
        """구 근사 곡률 반경 — 참고값. 모델은 평판 가정이라 계산에 쓰지 않는다."""
        return assumed(self.sphere_radius, "m", "구 최소제곱 근사 [참고 — 곡률 효과는 모델에 없다]")


def load_parts(path: Path):
    """장면이면 부품별로, 단일 메시면 연결 요소별로 나눈다(분할판 개수 파악)."""
    trimesh = _trimesh()
    obj = trimesh.load(path, force="scene")
    parts = [g for g in obj.geometry.values()
             if isinstance(g, trimesh.Trimesh) and len(g.faces)]
    if len(parts) == 1:
        split = parts[0].split(only_watertight=False)
        if len(split) > 1:
            parts = [m for m in split if len(m.faces) > 10]
    return parts


def max_horizontal_perimeter(mesh, n: int = 40) -> tuple[float, float]:
    """수평 단면 둘레의 최대값과 그 높이 (머리둘레 축척용)."""
    zmin, zmax = mesh.bounds[0][2], mesh.bounds[1][2]
    best, best_z = 0.0, float(zmin)
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


def projected_area(mesh) -> tuple[float, str]:
    """위에서 본 투영(그림자) 면적.

    삼각형을 xy 평면에 내리고 합집합을 잡는다. 열린 메시·떨어진 조각·구멍(통풍구)을
    그대로 반영한다. shapely 가 없으면 볼록껍질로 근사하는데, 그 값은 구멍을 메우므로
    실제보다 크게 나온다.
    """
    tri = np.asarray(mesh.triangles)[:, :, :2]
    x, y = tri[:, :, 0], tri[:, :, 1]
    a = 0.5 * np.abs(x[:, 0] * (y[:, 1] - y[:, 2]) + x[:, 1] * (y[:, 2] - y[:, 0])
                     + x[:, 2] * (y[:, 0] - y[:, 1]))
    tri = tri[a > 1e-12]                       # 옆에서 본 삼각형(선으로 뭉개진 것)은 뺀다
    try:
        from shapely.geometry import Polygon  # noqa: PLC0415
        from shapely.ops import unary_union  # noqa: PLC0415
        return float(unary_union([Polygon(t) for t in tri]).area), "정확(삼각형 합집합)"
    except Exception:
        pass
    from scipy.spatial import ConvexHull  # noqa: PLC0415
    hull = ConvexHull(mesh.vertices[:, :2])
    return float(hull.volume), "근사(볼록껍질 — 구멍을 메우므로 실제보다 크게 나온다)"


def open_edge_length(mesh) -> float:
    """열린 모서리(경계) 길이 합 — 분할판 테두리·이음선 길이의 대용값."""
    uniq, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    boundary = uniq[counts == 1]
    if not len(boundary):
        return 0.0
    v = mesh.vertices
    return float(np.linalg.norm(v[boundary[:, 0]] - v[boundary[:, 1]], axis=1).sum())


def nested_shells(parts) -> bool:
    """조각들이 같은 중심을 공유하는 안/바깥 면인지(= 분할판이 아닌지) 판단한다."""
    if len(parts) < 2:
        return False
    cents = np.array([m.bounds.mean(axis=0) for m in parts])
    sizes = np.array([m.extents.max() for m in parts])
    spread = float(np.linalg.norm(cents - cents.mean(axis=0), axis=1).max())
    return (spread < NESTED_CENTER_TOL * sizes.max()
            and (sizes.max() - sizes.min()) < NESTED_SIZE_TOL * sizes.max())


def fit_sphere_radius(mesh) -> float:
    """정점에 구를 최소제곱으로 맞춘 반경 (곡률 참고값)."""
    p = np.asarray(mesh.vertices, float)
    A = np.column_stack([2 * p, np.ones(len(p))])
    b = (p**2).sum(axis=1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:3]
    return float(math.sqrt(max(sol[3] + (c**2).sum(), 0.0)))


def measure(path: str | Path, *, scale: float | None = None,
            target_width: float | None = None,
            target_circumference: float | None = None,
            liner: float = 0.0, shell: float = 0.0) -> MeshProps:
    """메시 파일에서 시뮬레이터 입력 치수를 뽑는다. 길이 인자는 전부 m 다.

    축척은 셋 중 하나로 준다(우선순위: scale > target_width > target_circumference).
    target_circumference 를 '머리둘레'로 줄 때는 liner·shell 을 같이 준다.
    바깥 둘레는 머리둘레보다 2π(라이너+셸)만큼 크다.
    """
    trimesh = _trimesh()
    path = Path(path)
    log = WarningLog()
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        log.add("MESH_SUFFIX", Severity.WARNING,
                f"{path.suffix} 는 확인된 형식이 아니다. 지원: {', '.join(SUPPORTED_SUFFIXES)}")

    parts = load_parts(path)
    if not parts:
        raise ValueError("메시를 읽지 못했다 (면이 있는 형상이 없다)")
    whole = trimesh.util.concatenate(parts)

    # --- 축척 ---------------------------------------------------------------
    factor, how = 1.0, "축척 미지정 — 파일 단위를 m 로 가정했다(결과가 틀릴 수 있다)"
    if scale:
        factor, how = float(scale), f"직접 지정 ×{scale}"
    elif target_width:
        w = float(whole.extents[:2].max())
        factor = target_width / w
        how = f"좌우 폭 {target_width:.4g} m 기준 ×{factor:.5g}"
    elif target_circumference:
        per0, _z = max_horizontal_perimeter(whole)
        if per0 <= 0:
            raise ValueError("수평 단면 둘레를 재지 못했다 — 폭이나 배율로 축척을 지정한다")
        offset = 2.0 * math.pi * (liner + shell)
        target = target_circumference + offset
        factor = target / per0
        how = (f"바깥 둘레 {target:.4g} m 기준 ×{factor:.5g}"
               + (f" (머리둘레 {target_circumference:.4g} m + 라이너·셸 {offset:.4g} m)"
                  if offset > 0 else ""))
    else:
        log.add("MESH_NO_SCALE", Severity.BLOCK,
                "축척을 지정하지 않았다. 생성형 메시에는 실제 치수가 없으므로 "
                "면적·두께 수치를 그대로 쓰면 안 된다.")
    if factor != 1.0:
        for m in parts:
            m.apply_scale(factor)
        whole = trimesh.util.concatenate(parts)

    # --- 측정 ---------------------------------------------------------------
    area_total = float(whole.area)
    vol = float(abs(whole.volume)) if whole.is_watertight else float("nan")
    thin = bool(whole.is_watertight and not math.isnan(vol) and (vol / area_total) < THIN_SHELL_RATIO)
    pair = nested_shells(parts)
    if pair:
        area_outer = max(float(m.area) for m in parts)      # 바깥 면만 센다
    elif thin:
        area_outer = area_total / 2.0                        # 한 덩어리 셸: 절반이 바깥면
    else:
        area_outer = area_total
    proj, proj_how = projected_area(whole)
    per, per_z = max_horizontal_perimeter(whole)
    t_est = vol / area_outer if (thin and area_outer > 0) else None
    seam = sum(open_edge_length(m) for m in parts)
    n_seg = 1 if pair else len(parts)
    seg_areas = tuple([area_outer] if pair else sorted(
        (float(m.area) / (2.0 if thin else 1.0) for m in parts), reverse=True))

    if not whole.is_watertight:
        log.add("MESH_OPEN", Severity.INFO,
                "닫힌 메시가 아니다 — 두께를 잴 수 없으니 직접 입력한다. "
                "표면적도 한쪽 면 기준으로 센다.")
    if pair:
        log.add("MESH_NESTED", Severity.INFO,
                "조각들이 안/바깥 면 한 쌍으로 보인다 — 분할판 개수로 세지 않았다.")
    if proj_how.startswith("근사"):
        log.add("MESH_PROJ_HULL", Severity.WARNING,
                "투영 면적을 볼록껍질로 근사했다(실제보다 크게 나온다). shapely 를 설치하면 정확해진다.")
    if factor != 1.0 and not (0.2 < whole.extents.max() < 0.45):
        log.add("MESH_SIZE_ODD", Severity.WARNING,
                f"축척 후 최대 치수가 {whole.extents.max():.3g} m 다. "
                "사람 머리(대략 0.20–0.30 m)와 크게 다르면 축척 기준을 다시 본다.")

    return MeshProps(
        name=path.name, scale=factor, scale_how=how,
        area_outer=area_outer, area_total=area_total,
        projected=proj, projected_method=proj_how,
        thin_shell=thin, nested=pair, watertight=bool(whole.is_watertight),
        thickness_est=t_est, n_parts=len(parts), n_segments=n_seg,
        segment_areas=seg_areas, seam_length=seam,
        sphere_radius=fit_sphere_radius(whole),
        bbox=tuple(float(x) for x in whole.extents), perimeter=per, perimeter_z=per_z,
        n_faces=int(len(whole.faces)), warnings=log,
    )


def to_dict(p: MeshProps) -> dict:
    """JSON 저장용."""
    return {
        "file": p.name, "scale": p.scale, "scale_how": p.scale_how,
        "area_m2": p.area_outer, "area_total_m2": p.area_total, "projected_m2": p.projected,
        "projected_method": p.projected_method, "thin_shell": p.thin_shell, "nested": p.nested,
        "thickness_m_est": p.thickness_est, "n_parts": p.n_parts, "n_segments": p.n_segments,
        "segment_areas_m2": list(p.segment_areas), "seam_length_m": p.seam_length,
        "sphere_radius_m": p.sphere_radius, "bbox_m": list(p.bbox),
        "watertight": p.watertight, "n_faces": p.n_faces,
        "warnings": [f"[{w.severity.value}] {w.message}" for w in p.warnings],
    }
