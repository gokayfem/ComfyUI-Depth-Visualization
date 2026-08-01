from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import torch

import depth_nodes as nodes


def depth(height=24, width=32):
    x = torch.linspace(0.05, 1, width).view(1, 1, width, 1)
    return x.repeat(1, height, 1, 3)


def color(height=24, width=32):
    image = torch.zeros((1, height, width, 3))
    image[..., 0] = torch.linspace(0, 1, width)
    image[..., 1] = torch.linspace(0, 1, height).view(height, 1)
    image[..., 2] = 0.4
    return image


def test_normalize_colormap_normal_and_masks():
    normalized, report = nodes.DepthNormalize().normalize(depth(), "Percentile", 1, 99, False, 1)
    colored, = nodes.DepthColormap().colorize(normalized, "turbo", False, True)
    normal, = nodes.DepthToNormal().convert(normalized, 1.0, 60, "OpenGL (+Y)", False)
    inside, outside, masked = nodes.DepthRangeMask().mask(normalized, 0.2, 0.8, 0.05, False)
    assert normalized.min() == 0 and normalized.max() == 1
    assert json.loads(report)["method"] == "Percentile"
    assert colored.shape == normal.shape == masked.shape == (1, 24, 32, 3)
    assert torch.allclose(inside + outside, torch.ones_like(inside), atol=1e-6)


def test_cleanup_and_stats_emit_inspectable_outputs():
    source = depth()
    source[:, 8:12, 10:15] = 0
    cleaned, repaired, report = nodes.DepthCleanup().clean(source, 0.001, 8, 1, 0.8)
    stats, histogram = nodes.DepthStats().analyze(cleaned, 32)
    assert repaired[:, 8:12, 10:15].max() == 1
    assert json.loads(report)["changed_fraction"] > 0
    assert json.loads(stats)["batch"][0]["max"] <= 1
    assert histogram.shape == (1, 300, 640, 3)


def test_median_filter_preserves_sub_8_bit_depth_precision():
    values = np.array(
        [[[0.5001, 0.5002, 0.5003], [0.5004, 0.5005, 0.5006], [0.5007, 0.5008, 0.5009]]],
        dtype=np.float32,
    )
    filtered = nodes._median_filter(values, 1)
    assert np.isclose(filtered[0, 1, 1], 0.5005, atol=1e-6)
    assert not np.isclose(filtered[0, 1, 1] * 255, round(filtered[0, 1, 1] * 255))


def test_binary_ply_and_glb_exports(monkeypatch, tmp_path):
    import folder_paths

    monkeypatch.setattr(folder_paths, "get_output_directory", lambda: str(tmp_path), raising=False)
    ply_paths, ply_manifest = nodes.DepthToPointCloud().export(
        depth(), 60, 2, 4, True, "depth_exports/cloud", color()
    )
    glb_paths, glb_manifest = nodes.DepthToMesh().export(
        depth(), 60, 2, 4, 100, "depth_exports/mesh", color()
    )
    ply = Path(ply_paths)
    glb = Path(glb_paths)
    assert ply.read_bytes().startswith(b"ply\nformat binary_little_endian")
    magic, version, total = struct.unpack("<4sII", glb.read_bytes()[:12])
    assert (magic, version, total) == (b"glTF", 2, glb.stat().st_size)
    assert json.loads(ply_manifest)["point_counts"][0] > 0
    assert json.loads(glb_manifest)["triangle_counts"][0] > 0


def test_parallax_frames_and_validity_masks():
    frames, masks, manifest = nodes.DepthParallaxFrames().animate(
        color(), depth(), 8, 12, "ellipse", True, 0.5
    )
    assert frames.shape == (8, 24, 32, 3)
    assert masks.shape == (8, 24, 32)
    assert json.loads(manifest)["total_frames"] == 8
    assert masks.min() == 0 and masks.max() == 1
