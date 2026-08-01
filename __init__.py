"""Depth-map preview node for ComfyUI."""

from __future__ import annotations

import os
from typing import Any

import folder_paths
import numpy as np
from PIL import Image

try:
    from .depth_nodes import (
        NODE_CLASS_MAPPINGS as TOOL_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as TOOL_NODE_DISPLAY_NAME_MAPPINGS,
    )
except (ImportError, ModuleNotFoundError):  # Standalone import used by pytest.
    from depth_nodes import (  # type: ignore[no-redef]
        NODE_CLASS_MAPPINGS as TOOL_NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as TOOL_NODE_DISPLAY_NAME_MAPPINGS,
    )


def _as_pil(
    image: Any,
    *,
    grayscale: bool = False,
    bit_depth: int = 8,
) -> Image.Image:
    """Convert one ComfyUI IMAGE tensor to a web-safe PIL image."""
    array = image.detach().cpu().float().numpy()
    array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
    array = np.clip(array, 0.0, 1.0)

    if array.ndim == 2:
        mode = "L"
    elif array.ndim == 3 and array.shape[-1] == 1:
        array = array[..., 0]
        mode = "L"
    elif array.ndim == 3 and array.shape[-1] >= 3:
        array = array[..., :3]
        mode = "RGB"
    else:
        raise ValueError(f"Expected an HxW, HxWx1, or HxWx3+ image, got {array.shape}.")

    if grayscale and bit_depth == 16:
        if mode == "RGB":
            array = array[..., 0] * 0.2126 + array[..., 1] * 0.7152 + array[..., 2] * 0.0722
        return Image.fromarray((array * 65535.0).round().astype(np.uint16))
    converted = Image.fromarray((array * 255.0).round().astype(np.uint8), mode=mode)
    return converted.convert("L" if grayscale else "RGB")


def _batch_item(batch: Any, index: int, target_count: int, name: str) -> Any:
    count = len(batch)
    if count == target_count:
        return batch[index]
    if count == 1:
        return batch[0]
    raise ValueError(
        f"{name} has {count} images but the other input has {target_count}. "
        "Batch sizes must match, or one input must contain a single image."
    )


def _save_image(
    image: Image.Image,
    *,
    prefix: str,
    suffix: str,
    batch_number: int,
) -> dict[str, str]:
    output_dir = folder_paths.get_temp_directory()
    full_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
        prefix,
        output_dir,
        image.width,
        image.height,
    )
    filename = filename.replace("%batch_num%", str(batch_number))
    image_name = f"{filename}_{counter:05}_{suffix}.png"
    image.save(os.path.join(full_folder, image_name), compress_level=1)
    return {"filename": image_name, "subfolder": subfolder, "type": "temp"}


class DepthViewer:
    """Preview an image displaced by a matching depth map in an interactive 3D view."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_image": ("IMAGE",),
                "depth_map": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("reference_passthrough", "depth_passthrough")
    OUTPUT_NODE = True
    FUNCTION = "process_images"
    CATEGORY = "visualization/3D"
    DESCRIPTION = (
        "Interactively previews an image as a depth-displaced mesh. "
        "Supports image batches and browser-side PNG, OBJ, GLTF, and GLB export."
    )

    def process_images(self, reference_image, depth_map):
        reference_count = len(reference_image)
        depth_count = len(depth_map)
        batch_count = max(reference_count, depth_count)

        references: list[dict[str, str]] = []
        depths: list[dict[str, str]] = []
        for index in range(batch_count):
            reference = _as_pil(
                _batch_item(reference_image, index, batch_count, "reference_image")
            )
            depth = _as_pil(
                _batch_item(depth_map, index, batch_count, "depth_map"),
                grayscale=True,
                bit_depth=16,
            )
            references.append(
                _save_image(
                    reference,
                    prefix="depth_viewer",
                    suffix="reference",
                    batch_number=index,
                )
            )
            depths.append(
                _save_image(
                    depth,
                    prefix="depth_viewer",
                    suffix="depth",
                    batch_number=index,
                )
            )

        return {
            "ui": {"reference_image": references, "depth_map": depths},
            "result": (reference_image, depth_map),
        }


NODE_CLASS_MAPPINGS = {"DepthViewer": DepthViewer, **TOOL_NODE_CLASS_MAPPINGS}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DepthViewer": "Depth Viewer Pro",
    **TOOL_NODE_DISPLAY_NAME_MAPPINGS,
}
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
