from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest


class FakeTensor:
    def __init__(self, array):
        self.array = np.asarray(array, dtype=np.float32)

    def detach(self):
        return self

    def cpu(self):
        return self

    def float(self):
        return self

    def numpy(self):
        return self.array


class FakeBatch:
    def __init__(self, arrays):
        self.items = [FakeTensor(array) for array in arrays]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]


@pytest.fixture()
def depth_module(tmp_path, monkeypatch):
    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_temp_directory = lambda: str(tmp_path)

    def get_save_image_path(prefix, output_dir, width, height):
        assert width > 0 and height > 0
        return output_dir, f"{prefix}_%batch_num%", 1, "", prefix

    folder_paths.get_save_image_path = get_save_image_path
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)

    module_path = Path(__file__).parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("depth_viewer_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module, tmp_path


def test_processes_full_batch_and_broadcasts_single_depth(depth_module):
    module, output_dir = depth_module
    reference = FakeBatch(
        [
            np.zeros((8, 12, 3)),
            np.ones((8, 12, 3)),
        ]
    )
    depth = FakeBatch([np.full((8, 12, 1), 0.5)])

    result = module.DepthViewer().process_images(reference, depth)["ui"]

    assert len(result["reference_image"]) == 2
    assert len(result["depth_map"]) == 2
    for descriptor in result["reference_image"] + result["depth_map"]:
        assert descriptor["type"] == "temp"
        assert (output_dir / descriptor["filename"]).is_file()


def test_rejects_incompatible_batch_sizes(depth_module):
    module, _ = depth_module
    reference = FakeBatch([np.zeros((4, 4, 3)) for _ in range(2)])
    depth = FakeBatch([np.zeros((4, 4, 1)) for _ in range(3)])

    with pytest.raises(ValueError, match="Batch sizes must match"):
        module.DepthViewer().process_images(reference, depth)


def test_sanitizes_non_finite_pixels(depth_module):
    module, _ = depth_module
    image = FakeTensor([[[np.nan, np.inf, -np.inf]]])

    converted = np.asarray(module._as_pil(image))

    assert converted.tolist() == [[[0, 255, 0]]]
