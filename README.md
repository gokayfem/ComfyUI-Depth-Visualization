# ComfyUI Depth Visualization

An interactive, in-node 3D preview for any ComfyUI reference image and depth
map. The current implementation is compatible with the modern ComfyUI
frontend, works offline, supports batches, and cleans up its WebGL resources
when a node is removed.

![Depth Visualization](https://github.com/gokayfem/ComfyUI-Depth-Visualization/assets/88277926/0b63c2ed-60d4-44a6-9d44-b3548ec58d48)

## Features

- Interactive orbit, pan, and zoom controls
- Adjustable positive or negative displacement
- Batch frame selector with single-image broadcasting
- PNG screenshots
- Baked depth-mesh export as GLB, GLTF, or OBJ
- Local, pinned Three.js assets with no runtime CDN dependency
- Correct copy/paste, collapse, resize, and node-removal behavior
- Stale-load cancellation and visible error reporting

## Installation

Install with ComfyUI Manager, or clone the repository manually:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/gokayfem/ComfyUI-Depth-Visualization.git
python -m pip install -r ComfyUI-Depth-Visualization/requirements.txt
```

Restart ComfyUI after installation.

## Usage

1. Add **Depth Viewer** from `visualization/3D`.
2. Connect a reference `IMAGE` and a depth-map `IMAGE`.
3. Queue the workflow.
4. Drag to orbit, scroll to zoom, or right-drag to pan.

When one input contains a single image and the other contains a batch, the
single image is reused for every frame. Other unequal batch sizes produce a
clear validation error instead of silently dropping images.

Mesh export bakes the current depth slider value into the vertices. GLB is the
recommended portable format; OBJ contains geometry only.

## Development

```bash
python -m pip install pytest
pytest -q
```

The browser assets are vendored from Three.js 0.185.1. Its MIT license is in
`web/vendor/THREE-LICENSE.txt`.

## Acknowledgements

The original viewer was inspired by
[ComfyUI-Flowty-TripoSR](https://github.com/flowtyone/ComfyUI-Flowty-TripoSR).
