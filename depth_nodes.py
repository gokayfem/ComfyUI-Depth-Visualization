"""Zero-download depth processing, analysis, and 3D export nodes for ComfyUI."""

from __future__ import annotations

import json
import os
import re
import struct
from datetime import datetime
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


CATEGORY = "depth/toolkit"
CATEGORY_3D = "depth/3D export"


def _numpy_batch(images: Any) -> np.ndarray:
    array = images.detach().cpu().float().numpy()
    array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
    if array.ndim == 3:
        array = array[None, ...]
    if array.ndim != 4:
        raise ValueError(f"Expected a BHWC image batch, got {array.shape}.")
    if array.shape[-1] == 1:
        array = np.repeat(array, 3, axis=-1)
    elif array.shape[-1] < 3:
        raise ValueError(f"Expected one or at least three channels, got {array.shape}.")
    return np.clip(array[..., :3], 0.0, 1.0).astype(np.float32, copy=False)


def _depth(images: Any) -> np.ndarray:
    rgb = _numpy_batch(images)
    return (rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722).astype(np.float32)


def _torch(array: np.ndarray):
    import torch

    return torch.from_numpy(np.ascontiguousarray(array, dtype=np.float32))


def _depth_image(values: np.ndarray) -> np.ndarray:
    return np.repeat(values[..., None], 3, axis=-1)


def _resize_batch(batch: np.ndarray, height: int, width: int) -> np.ndarray:
    if batch.shape[1:3] == (height, width):
        return batch
    result = []
    for image in batch:
        pil = Image.fromarray((image * 255.0).round().astype(np.uint8), "RGB")
        result.append(np.asarray(pil.resize((width, height), Image.Resampling.LANCZOS), dtype=np.float32) / 255.0)
    return np.stack(result)


def _safe_output_path(prefix: str, extension: str) -> str:
    import folder_paths

    output_root = os.path.realpath(folder_paths.get_output_directory())
    pieces = [re.sub(r"[^A-Za-z0-9._-]+", "_", item).strip("._") for item in str(prefix).replace("\\", "/").split("/")]
    pieces = [item for item in pieces if item] or ["depth_exports", "depth"]
    directory = os.path.realpath(os.path.join(output_root, *pieces[:-1]))
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.realpath(os.path.join(directory, f"{pieces[-1]}_{stamp}.{extension}"))
    if os.path.commonpath((output_root, path)) != output_root:
        raise ValueError("Export path must remain inside the ComfyUI output directory.")
    return path


def _normalize_one(values: np.ndarray, method: str, low: float, high: float) -> tuple[np.ndarray, float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros_like(values), 0.0, 1.0
    if method == "Percentile":
        lo, hi = np.percentile(finite, [low, high])
    elif method == "Fixed range":
        lo, hi = float(low), float(high)
    else:
        lo, hi = float(finite.min()), float(finite.max())
    if hi <= lo + 1e-12:
        return np.zeros_like(values), float(lo), float(hi)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0).astype(np.float32), float(lo), float(hi)


def _median_filter(values: np.ndarray, radius: int) -> np.ndarray:
    """Precision-preserving, bounded-memory 2D median filter for BHW depth."""
    radius = int(radius)
    if radius <= 0:
        return values
    size = radius * 2 + 1
    filtered = np.empty_like(values, dtype=np.float32)
    for batch_index, image in enumerate(values):
        padded = np.pad(image, ((radius, radius), (radius, radius)), mode="edge")
        for row in range(image.shape[0]):
            windows = np.lib.stride_tricks.sliding_window_view(
                padded[row : row + size], (size, size)
            )
            filtered[batch_index, row] = np.median(
                windows[0], axis=(-2, -1)
            ).astype(np.float32)
    return filtered


class DepthNormalize:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "depth_map": ("IMAGE",),
                "method": (["Percentile", "Min-max", "Fixed range"],),
                "low": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1}),
                "high": ("FLOAT", {"default": 99.0, "min": 0.0, "max": 100.0, "step": 0.1}),
                "invert": ("BOOLEAN", {"default": False}),
                "gamma": ("FLOAT", {"default": 1.0, "min": 0.05, "max": 8.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("normalized_depth", "range_report_json")
    FUNCTION = "normalize"
    CATEGORY = CATEGORY
    DESCRIPTION = "Normalizes arbitrary depth ranges per image with percentile clipping, inversion, and gamma."

    def normalize(self, depth_map, method, low, high, invert, gamma):
        if float(high) <= float(low):
            raise ValueError("high must be greater than low.")
        source = _depth(depth_map)
        outputs, ranges = [], []
        for image in source:
            normalized, actual_low, actual_high = _normalize_one(image, method, float(low), float(high))
            if invert:
                normalized = 1.0 - normalized
            normalized = np.power(np.clip(normalized, 0.0, 1.0), 1.0 / float(gamma)).astype(np.float32)
            outputs.append(normalized)
            ranges.append({"low": actual_low, "high": actual_high})
        return (_torch(_depth_image(np.stack(outputs))), json.dumps({"method": method, "invert": bool(invert), "gamma": float(gamma), "ranges": ranges}, indent=2))


_COLORMAPS = {
    "viridis": [(0.0, (68, 1, 84)), (0.25, (59, 82, 139)), (0.5, (33, 145, 140)), (0.75, (94, 201, 98)), (1.0, (253, 231, 37))],
    "magma": [(0.0, (0, 0, 4)), (0.25, (81, 18, 124)), (0.5, (183, 55, 121)), (0.75, (252, 137, 97)), (1.0, (252, 253, 191))],
    "turbo": [(0.0, (48, 18, 59)), (0.2, (65, 105, 225)), (0.4, (52, 205, 166)), (0.6, (190, 233, 51)), (0.8, (249, 126, 32)), (1.0, (122, 4, 3))],
    "plasma": [(0.0, (13, 8, 135)), (0.25, (126, 3, 168)), (0.5, (204, 71, 120)), (0.75, (248, 149, 64)), (1.0, (240, 249, 33))],
    "grayscale": [(0.0, (0, 0, 0)), (1.0, (255, 255, 255))],
}


def _lut(name: str) -> np.ndarray:
    controls = _COLORMAPS[name]
    x = np.linspace(0.0, 1.0, 256)
    xp = np.array([point for point, _ in controls])
    colors = np.array([color for _, color in controls], dtype=np.float32) / 255.0
    return np.stack([np.interp(x, xp, colors[:, channel]) for channel in range(3)], axis=-1).astype(np.float32)


class DepthColormap:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth_map": ("IMAGE",), "colormap": (list(_COLORMAPS),), "invert": ("BOOLEAN", {"default": False}), "show_invalid_magenta": ("BOOLEAN", {"default": True})}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("colored_depth",)
    FUNCTION = "colorize"
    CATEGORY = CATEGORY
    DESCRIPTION = "Applies an embedded perceptual depth colormap without matplotlib or network access."

    def colorize(self, depth_map, colormap, invert, show_invalid_magenta):
        raw = depth_map.detach().cpu().float().numpy()
        invalid = ~np.isfinite(raw[..., 0] if raw.ndim == 4 else raw)
        values = _depth(depth_map)
        if invert:
            values = 1.0 - values
        indices = np.clip(np.rint(values * 255.0), 0, 255).astype(np.uint8)
        output = _lut(colormap)[indices]
        if show_invalid_magenta and invalid.shape == output.shape[:3]:
            output[invalid] = (1.0, 0.0, 1.0)
        return (_torch(output),)


class DepthToNormal:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth_map": ("IMAGE",), "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 20.0, "step": 0.05}), "field_of_view": ("FLOAT", {"default": 60.0, "min": 1.0, "max": 179.0, "step": 1.0}), "convention": (["OpenGL (+Y)", "DirectX (-Y)"],), "invert_depth": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("surface_normal",)
    FUNCTION = "convert"
    CATEGORY = CATEGORY
    DESCRIPTION = "Computes FOV-aware camera-space surface normals from a depth map."

    def convert(self, depth_map, strength, field_of_view, convention, invert_depth):
        values = _depth(depth_map)
        if invert_depth:
            values = 1.0 - values
        h, w = values.shape[1:3]
        focal = 0.5 * w / np.tan(np.deg2rad(float(field_of_view)) * 0.5)
        dy, dx = np.gradient(values, axis=(1, 2))
        scale = float(strength) * focal / max(w, h)
        ny = -dy * scale if convention.startswith("OpenGL") else dy * scale
        vectors = np.stack((-dx * scale, ny, np.ones_like(values)), axis=-1)
        vectors /= np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), 1e-8)
        return (_torch(vectors * 0.5 + 0.5),)


class DepthRangeMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth_map": ("IMAGE",), "near": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}), "far": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 1.0, "step": 0.01}), "feather": ("FLOAT", {"default": 0.02, "min": 0.0, "max": 0.5, "step": 0.005}), "invert_depth": ("BOOLEAN", {"default": False})}}

    RETURN_TYPES = ("MASK", "MASK", "IMAGE")
    RETURN_NAMES = ("inside_range", "outside_range", "masked_depth")
    FUNCTION = "mask"
    CATEGORY = CATEGORY
    DESCRIPTION = "Builds soft near/far masks for compositing, relighting, and depth-conditioned generation."

    def mask(self, depth_map, near, far, feather, invert_depth):
        if float(far) <= float(near):
            raise ValueError("far must be greater than near.")
        values = _depth(depth_map)
        if invert_depth:
            values = 1.0 - values
        f = max(float(feather), 1e-6)
        enter = np.clip((values - (float(near) - f)) / f, 0.0, 1.0)
        leave = np.clip(((float(far) + f) - values) / f, 0.0, 1.0)
        inside = np.minimum(enter, leave).astype(np.float32)
        return (_torch(inside), _torch(1.0 - inside), _torch(_depth_image(values * inside)))


class DepthCleanup:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth_map": ("IMAGE",), "hole_threshold": ("FLOAT", {"default": 0.001, "min": 0.0, "max": 1.0, "step": 0.001}), "fill_iterations": ("INT", {"default": 3, "min": 0, "max": 32}), "median_radius": ("INT", {"default": 1, "min": 0, "max": 5}), "preserve_edges": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 1.0, "step": 0.05})}}

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("clean_depth", "repaired_pixels", "report_json")
    FUNCTION = "clean"
    CATEGORY = CATEGORY
    DESCRIPTION = "Fills zero/invalid holes and suppresses speckle with an edge-preserving blend."

    def clean(self, depth_map, hole_threshold, fill_iterations, median_radius, preserve_edges):
        original = _depth(depth_map)
        result = original.copy()
        holes = result <= float(hole_threshold)
        for _ in range(int(fill_iterations)):
            if not holes.any():
                break
            total = np.zeros_like(result)
            count = np.zeros_like(result)
            for oy, ox in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                neighbor = np.roll(result, (oy, ox), axis=(1, 2))
                valid = neighbor > float(hole_threshold)
                total += neighbor * valid
                count += valid
            can_fill = holes & (count > 0)
            result[can_fill] = total[can_fill] / count[can_fill]
            holes = result <= float(hole_threshold)
        if int(median_radius) > 0:
            filtered = _median_filter(result, int(median_radius))
            gradients = np.hypot(*np.gradient(original, axis=(1, 2)))
            edge_weight = np.clip(gradients * 16.0 * float(preserve_edges), 0.0, 1.0)
            result = filtered * (1.0 - edge_weight) + result * edge_weight
        repaired = (np.abs(result - original) > 1e-6).astype(np.float32)
        report = {"input_hole_fraction": float((original <= float(hole_threshold)).mean()), "unfilled_fraction": float(holes.mean()), "changed_fraction": float(repaired.mean())}
        return (_torch(_depth_image(np.clip(result, 0.0, 1.0))), _torch(repaired), json.dumps(report, indent=2))


class DepthStats:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth_map": ("IMAGE",), "bins": ("INT", {"default": 64, "min": 16, "max": 256, "step": 16})}}

    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("statistics_json", "histogram")
    FUNCTION = "analyze"
    CATEGORY = CATEGORY
    DESCRIPTION = "Reports robust depth statistics and creates a workflow-visible histogram image."

    def analyze(self, depth_map, bins):
        values = _depth(depth_map)
        reports, charts = [], []
        for image in values:
            reports.append({"min": float(image.min()), "max": float(image.max()), "mean": float(image.mean()), "median": float(np.median(image)), "std": float(image.std()), "p01": float(np.percentile(image, 1)), "p99": float(np.percentile(image, 99)), "near_fraction_0_25": float((image <= 0.25).mean()), "far_fraction_0_75": float((image >= 0.75).mean())})
            hist, _ = np.histogram(image, bins=int(bins), range=(0.0, 1.0))
            canvas = Image.new("RGB", (640, 300), (14, 18, 25))
            draw = ImageDraw.Draw(canvas)
            max_count = max(int(hist.max()), 1)
            for index, count in enumerate(hist):
                x0 = 40 + index * 560 / len(hist)
                x1 = 40 + (index + 1) * 560 / len(hist)
                y = 260 - int(count / max_count * 220)
                draw.rectangle((x0, y, x1 + 1, 260), fill=(55, 190, 210))
            draw.line((40, 260, 600, 260), fill=(210, 220, 230), width=2)
            draw.text((40, 270), "near 0", fill=(210, 220, 230))
            draw.text((548, 270), "far 1", fill=(210, 220, 230))
            charts.append(np.asarray(canvas, dtype=np.float32) / 255.0)
        return (json.dumps({"batch": reports}, indent=2), _torch(np.stack(charts)))


def _camera_points(depth: np.ndarray, fov: float, depth_scale: float, stride: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h, w = depth.shape
    ys = np.arange(0, h, stride, dtype=np.int32)
    xs = np.arange(0, w, stride, dtype=np.int32)
    xx, yy = np.meshgrid(xs, ys)
    z = depth[yy, xx] * float(depth_scale)
    focal = 0.5 * w / np.tan(np.deg2rad(float(fov)) * 0.5)
    x = (xx - (w - 1) * 0.5) * z / focal
    y = -((yy - (h - 1) * 0.5) * z / focal)
    return np.stack((x, y, z), axis=-1).astype(np.float32), xs, ys


class DepthToPointCloud:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth_map": ("IMAGE",), "field_of_view": ("FLOAT", {"default": 60.0, "min": 1.0, "max": 179.0, "step": 1.0}), "depth_scale": ("FLOAT", {"default": 1.0, "min": 0.001, "max": 1000.0, "step": 0.01}), "stride": ("INT", {"default": 4, "min": 1, "max": 64}), "drop_zero_depth": ("BOOLEAN", {"default": True}), "filename_prefix": ("STRING", {"default": "depth_exports/point_cloud"})}, "optional": {"color_image": ("IMAGE",)}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("ply_paths", "manifest_json")
    FUNCTION = "export"
    CATEGORY = CATEGORY_3D
    OUTPUT_NODE = True
    DESCRIPTION = "Exports binary PLY point clouds with camera-space coordinates and optional RGB color."

    def export(self, depth_map, field_of_view, depth_scale, stride, drop_zero_depth, filename_prefix, color_image=None):
        depths = _depth(depth_map)
        colors = _resize_batch(_numpy_batch(color_image), depths.shape[1], depths.shape[2]) if color_image is not None else None
        paths, counts = [], []
        for batch_index, depth in enumerate(depths):
            points, xs, ys = _camera_points(depth, field_of_view, depth_scale, int(stride))
            points = points.reshape(-1, 3)
            valid = np.isfinite(points).all(axis=1)
            if drop_zero_depth:
                valid &= points[:, 2] > 1e-8
            points = points[valid]
            rgb = None
            if colors is not None:
                color = colors[min(batch_index, len(colors) - 1)][np.ix_(ys, xs)].reshape(-1, 3)
                rgb = (color[valid] * 255.0).round().astype(np.uint8)
            path = _safe_output_path(f"{filename_prefix}_{batch_index:03d}", "ply")
            properties = "property float x\nproperty float y\nproperty float z\n"
            if rgb is not None:
                properties += "property uchar red\nproperty uchar green\nproperty uchar blue\n"
            header = f"ply\nformat binary_little_endian 1.0\ncomment ComfyUI Depth Visualization\nelement vertex {len(points)}\n{properties}end_header\n".encode("ascii")
            with open(path, "xb") as handle:
                handle.write(header)
                if rgb is None:
                    handle.write(points.astype("<f4", copy=False).tobytes())
                else:
                    dtype = np.dtype([("xyz", "<f4", (3,)), ("rgb", "u1", (3,))])
                    packed = np.empty(len(points), dtype=dtype)
                    packed["xyz"], packed["rgb"] = points, rgb
                    handle.write(packed.tobytes())
            paths.append(path)
            counts.append(len(points))
        return ("\n".join(paths), json.dumps({"format": "binary_little_endian PLY", "paths": paths, "point_counts": counts, "fov_degrees": float(field_of_view), "depth_scale": float(depth_scale), "stride": int(stride)}, indent=2))


def _aligned(blob: bytearray, alignment: int = 4) -> None:
    while len(blob) % alignment:
        blob.append(0)


def _write_glb(path: str, positions: np.ndarray, colors: np.ndarray, indices: np.ndarray) -> None:
    binary = bytearray()
    pos_offset = len(binary)
    binary.extend(positions.astype("<f4", copy=False).tobytes())
    _aligned(binary)
    color_offset = len(binary)
    binary.extend(colors.astype(np.uint8, copy=False).tobytes())
    _aligned(binary)
    index_offset = len(binary)
    binary.extend(indices.astype("<u4", copy=False).tobytes())
    _aligned(binary)
    gltf = {
        "asset": {"version": "2.0", "generator": "ComfyUI-Depth-Visualization"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2, "mode": 4}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": pos_offset, "byteLength": int(positions.nbytes), "target": 34962},
            {"buffer": 0, "byteOffset": color_offset, "byteLength": int(colors.nbytes), "target": 34962},
            {"buffer": 0, "byteOffset": index_offset, "byteLength": int(indices.nbytes), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3", "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5121, "normalized": True, "count": len(colors), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": len(indices), "type": "SCALAR", "min": [int(indices.min())], "max": [int(indices.max())]},
        ],
    }
    json_chunk = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_chunk) % 4:
        json_chunk += b" "
    total = 12 + 8 + len(json_chunk) + 8 + len(binary)
    with open(path, "xb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", 2, total))
        handle.write(struct.pack("<I4s", len(json_chunk), b"JSON"))
        handle.write(json_chunk)
        handle.write(struct.pack("<I4s", len(binary), b"BIN\0"))
        handle.write(binary)


class DepthToMesh:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"depth_map": ("IMAGE",), "field_of_view": ("FLOAT", {"default": 60.0, "min": 1.0, "max": 179.0, "step": 1.0}), "depth_scale": ("FLOAT", {"default": 1.0, "min": 0.001, "max": 1000.0, "step": 0.01}), "stride": ("INT", {"default": 4, "min": 1, "max": 64}), "max_edge_length": ("FLOAT", {"default": 0.15, "min": 0.0, "max": 1000.0, "step": 0.01}), "filename_prefix": ("STRING", {"default": "depth_exports/depth_mesh"})}, "optional": {"color_image": ("IMAGE",)}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("glb_paths", "manifest_json")
    FUNCTION = "export"
    CATEGORY = CATEGORY_3D
    OUTPUT_NODE = True
    DESCRIPTION = "Exports colorized camera-space depth meshes as standards-compliant GLB without extra packages."

    def export(self, depth_map, field_of_view, depth_scale, stride, max_edge_length, filename_prefix, color_image=None):
        depths = _depth(depth_map)
        colors = _resize_batch(_numpy_batch(color_image), depths.shape[1], depths.shape[2]) if color_image is not None else _depth_image(depths)
        paths, triangle_counts = [], []
        for batch_index, depth in enumerate(depths):
            grid, xs, ys = _camera_points(depth, field_of_view, depth_scale, int(stride))
            rows, cols = grid.shape[:2]
            if rows < 2 or cols < 2:
                raise ValueError("stride is too large for this depth-map resolution.")
            positions = grid.reshape(-1, 3)
            rgb = (colors[min(batch_index, len(colors) - 1)][np.ix_(ys, xs)].reshape(-1, 3) * 255.0).round().astype(np.uint8)
            indices = []
            threshold = float(max_edge_length)
            for row in range(rows - 1):
                base = row * cols
                next_base = (row + 1) * cols
                for col in range(cols - 1):
                    for tri in ((base + col, next_base + col, base + col + 1), (base + col + 1, next_base + col, next_base + col + 1)):
                        vertices = positions[list(tri)]
                        if not np.isfinite(vertices).all() or np.any(vertices[:, 2] <= 1e-8):
                            continue
                        if threshold > 0:
                            edges = (np.linalg.norm(vertices[0] - vertices[1]), np.linalg.norm(vertices[1] - vertices[2]), np.linalg.norm(vertices[2] - vertices[0]))
                            if max(edges) > threshold:
                                continue
                        indices.extend(tri)
            index_array = np.asarray(indices, dtype=np.uint32)
            if len(index_array) < 3:
                raise ValueError("No valid mesh triangles remain; increase max_edge_length or reduce stride.")
            path = _safe_output_path(f"{filename_prefix}_{batch_index:03d}", "glb")
            _write_glb(path, positions, rgb, index_array)
            paths.append(path)
            triangle_counts.append(len(index_array) // 3)
        return ("\n".join(paths), json.dumps({"format": "glTF 2.0 binary", "paths": paths, "triangle_counts": triangle_counts, "fov_degrees": float(field_of_view), "depth_scale": float(depth_scale), "stride": int(stride), "max_edge_length": float(max_edge_length)}, indent=2))


def _bilinear_clamp(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = image.shape[:2]
    valid = (x >= 0.0) & (x <= w - 1.0) & (y >= 0.0) & (y <= h - 1.0)
    x = np.clip(x, 0.0, w - 1.0)
    y = np.clip(y, 0.0, h - 1.0)
    x0, y0 = np.floor(x).astype(np.int32), np.floor(y).astype(np.int32)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    wx, wy = (x - x0)[..., None], (y - y0)[..., None]
    top = image[y0, x0] * (1 - wx) + image[y0, x1] * wx
    bottom = image[y1, x0] * (1 - wx) + image[y1, x1] * wx
    return top * (1 - wy) + bottom * wy, valid.astype(np.float32)


class DepthParallaxFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "depth_map": ("IMAGE",), "frames": ("INT", {"default": 24, "min": 2, "max": 240}), "amplitude_px": ("FLOAT", {"default": 24.0, "min": 0.0, "max": 512.0, "step": 1.0}), "path": (["horizontal sway", "vertical sway", "ellipse", "dolly"],), "loop": ("BOOLEAN", {"default": True}), "depth_center": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01})}}

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("frames", "validity_masks", "manifest_json")
    FUNCTION = "animate"
    CATEGORY = CATEGORY
    DESCRIPTION = "Creates video-ready depth parallax frames plus validity masks for inpainting exposed edges."

    def animate(self, image, depth_map, frames, amplitude_px, path, loop, depth_center):
        colors = _numpy_batch(image)
        depths = _depth(depth_map)
        count = max(len(colors), len(depths))
        if len(colors) not in (1, count) or len(depths) not in (1, count):
            raise ValueError("image and depth_map batches must match or contain one image.")
        depths = _resize_batch(_depth_image(depths), colors.shape[1], colors.shape[2])[..., 0]
        h, w = colors.shape[1:3]
        yy, xx = np.mgrid[0:h, 0:w]
        outputs, masks = [], []
        frame_count = int(frames)
        denominator = frame_count if loop else max(frame_count - 1, 1)
        for batch_index in range(count):
            color = colors[min(batch_index, len(colors) - 1)]
            depth = depths[min(batch_index, len(depths) - 1)]
            relative = (depth - float(depth_center)) * float(amplitude_px)
            for frame in range(frame_count):
                phase = 2.0 * np.pi * frame / denominator
                sx = sy = 0.0
                scale = 0.0
                if path == "horizontal sway":
                    sx = np.sin(phase)
                elif path == "vertical sway":
                    sy = np.sin(phase)
                elif path == "ellipse":
                    sx, sy = np.cos(phase), np.sin(phase) * 0.55
                else:
                    scale = np.sin(phase)
                sample_x = xx - relative * sx - (xx - (w - 1) * 0.5) * relative * scale / max(w, 1)
                sample_y = yy - relative * sy - (yy - (h - 1) * 0.5) * relative * scale / max(h, 1)
                warped, valid = _bilinear_clamp(color, sample_x, sample_y)
                outputs.append(warped)
                masks.append(valid)
        manifest = {"source_batches": count, "frames_per_source": frame_count, "total_frames": len(outputs), "path": path, "loop": bool(loop), "amplitude_px": float(amplitude_px), "mask_semantics": "1 = sampled inside source; 0 = exposed edge requiring fill"}
        return (_torch(np.stack(outputs)), _torch(np.stack(masks)), json.dumps(manifest, indent=2))


NODE_CLASS_MAPPINGS = {
    "DepthNormalize": DepthNormalize,
    "DepthColormap": DepthColormap,
    "DepthToNormal": DepthToNormal,
    "DepthRangeMask": DepthRangeMask,
    "DepthCleanup": DepthCleanup,
    "DepthStats": DepthStats,
    "DepthToPointCloud": DepthToPointCloud,
    "DepthToMesh": DepthToMesh,
    "DepthParallaxFrames": DepthParallaxFrames,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DepthNormalize": "Normalize Depth",
    "DepthColormap": "Depth Colormap",
    "DepthToNormal": "Depth to Surface Normal",
    "DepthRangeMask": "Depth Range Masks",
    "DepthCleanup": "Clean & Repair Depth",
    "DepthStats": "Analyze Depth",
    "DepthToPointCloud": "Export Depth Point Cloud (PLY)",
    "DepthToMesh": "Export Depth Mesh (GLB)",
    "DepthParallaxFrames": "Depth Parallax Frames",
}
