"""3D 메시 → 시뮬레이터 입력 치수. 축척이 없으면 값을 쓰지 못하게 막는 것이 핵심이다."""

import math

import pytest

trimesh = pytest.importorskip("trimesh", reason="선택 의존성 (requirements-mesh.txt)")

from chiton_sim.mesh import measure  # noqa: E402
from chiton_sim.provenance import Label  # noqa: E402


def write(mesh, tmp_path, name="helmet.glb"):
    p = tmp_path / name
    mesh.export(p)
    return p


def sphere(radius: float, subdivisions: int = 3):
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


def test_width_scaling_recovers_known_area(tmp_path):
    """단위 없는 메시라도 폭을 주면 면적이 맞아야 한다."""
    p = measure(write(sphere(1.0), tmp_path), target_width=0.200)
    assert p.bbox[0] == pytest.approx(0.2, rel=1e-6)
    # 정이십면체 분할 구는 실제 구보다 면적이 조금 작다(내접) — 2 % 안이면 된다.
    assert p.area_outer == pytest.approx(4 * math.pi * 0.1**2, rel=0.02)
    assert p.projected == pytest.approx(math.pi * 0.1**2, rel=0.03)
    assert p.area_q.label is Label.COMPUTED


def test_no_scale_blocks_use_of_area(tmp_path):
    """생성형 메시에는 치수가 없다. 축척 없이 나온 면적은 '미확인'이어야 한다."""
    p = measure(write(sphere(1.0), tmp_path))
    assert "MESH_NO_SCALE" in p.warnings.codes()
    assert p.area_q.label is Label.UNVERIFIED and p.area_q.value is None
    assert p.scale == 1.0


def test_head_circumference_scaling_adds_liner_and_shell(tmp_path):
    """머리둘레로 축척할 때 바깥 둘레는 2π(라이너+셸)만큼 커진다."""
    p = measure(write(sphere(1.0), tmp_path), target_circumference=0.575,
                liner=0.020, shell=0.004)
    outer = 0.575 + 2 * math.pi * 0.024
    assert p.perimeter == pytest.approx(outer, rel=0.02)
    plain = measure(write(sphere(1.0), tmp_path), target_circumference=0.575)
    assert plain.perimeter < p.perimeter


def test_nested_shells_are_not_counted_as_segments(tmp_path):
    """안/바깥 면 한 쌍을 분할판 2장으로 세면 안 된다. 그 대신 두께가 나온다."""
    outer, inner = sphere(0.100), sphere(0.096)
    inner.invert()                                   # 셸 부피 = 바깥 − 안
    p = measure(write(trimesh.util.concatenate([outer, inner]), tmp_path), scale=1.0)
    assert p.nested and p.n_segments == 1
    assert p.thin_shell and p.watertight
    assert p.area_outer == pytest.approx(4 * math.pi * 0.100**2, rel=0.02)
    assert p.thickness_est == pytest.approx(0.004, rel=0.1)
    assert p.thickness_q.label is Label.COMPUTED
    assert "MESH_NESTED" in p.warnings.codes()


def test_separate_parts_are_segments_sorted_by_area(tmp_path):
    """떨어져 있는 조각은 분할판으로 세고, 큰 것부터 준다."""
    parts = [trimesh.creation.box(extents=(e, e, 0.003)) for e in (0.10, 0.08, 0.06)]
    for i, m in enumerate(parts):
        m.apply_translation([0.5 * i, 0.0, 0.0])
    p = measure(write(trimesh.util.concatenate(parts), tmp_path, "segments.glb"), scale=1.0)
    assert p.n_segments == 3 and not p.nested
    assert list(p.segment_areas) == sorted(p.segment_areas, reverse=True)
    assert p.segment_area_q.value == pytest.approx(p.segment_areas[0])
    assert p.segment_area_q.label is Label.COMPUTED


def test_open_mesh_cannot_give_thickness(tmp_path):
    """열린 메시는 부피가 없다 — 두께를 지어내지 않고 미확인으로 둔다."""
    dome = sphere(0.1)
    dome.update_faces(dome.triangles_center[:, 2] > 0)      # 위쪽 반만 남긴다
    dome.remove_unreferenced_vertices()
    p = measure(write(dome, tmp_path, "dome.glb"), scale=1.0)
    assert not p.watertight
    assert p.thickness_est is None and p.thickness_q.label is Label.UNVERIFIED
    assert p.seam_length > 0.0                               # 열린 테두리가 이음선
    assert "MESH_OPEN" in p.warnings.codes()


def test_curvature_radius_is_reference_only(tmp_path):
    p = measure(write(sphere(0.12), tmp_path), scale=1.0)
    assert p.sphere_radius == pytest.approx(0.12, rel=0.02)
    assert p.curvature_radius_q.label is Label.ASSUMPTION
    assert "곡률 효과는 모델에 없다" in p.curvature_radius_q.note


def test_projected_area_follows_holes_not_the_hull(tmp_path):
    """투영 면적은 그림자다 — 떨어진 조각 사이 빈 공간까지 세면 안 된다."""
    a = trimesh.creation.box(extents=(0.10, 0.10, 0.003))
    b = trimesh.creation.box(extents=(0.10, 0.10, 0.003))
    b.apply_translation([0.30, 0.0, 0.0])
    p = measure(write(trimesh.util.concatenate([a, b]), tmp_path, "two.glb"), scale=1.0)
    assert p.projected == pytest.approx(2 * 0.10 * 0.10, rel=1e-6)   # 볼록껍질이면 0.04 m²
    assert p.projected_method.startswith("정확")
