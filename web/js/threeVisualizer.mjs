import * as THREE from "three";
import { OrbitControls } from "../vendor/OrbitControls.mjs";
import { GLTFExporter } from "../vendor/GLTFExporter.mjs";
import { OBJExporter } from "../vendor/OBJExporter.mjs";

const SOURCE = "gokayfem.depth-visualization.viewer";
const container = document.querySelector("#canvas-container");
const statusElement = document.querySelector("#status");
const errorElement = document.querySelector("#error");
const batchSelect = document.querySelector("#batch-select");
const depthScale = document.querySelector("#depth-scale");
const depthValue = document.querySelector("#depth-value");
const exportButton = document.querySelector("#export-mesh");

const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
    powerPreference: "high-performance",
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
container.append(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111318);

const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.screenSpacePanning = true;

scene.add(new THREE.HemisphereLight(0xffffff, 0x303040, 2.2));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.5);
keyLight.position.set(4, 6, 8);
scene.add(keyLight);

let channel = null;
let viewUrl = null;
let output = null;
let mesh = null;
let updateVersion = 0;
let animationFrame = null;
let disposed = false;
let contextLost = false;
let inViewport = true;

function setStatus(message) {
    statusElement.textContent = message;
    statusElement.hidden = false;
    errorElement.hidden = true;
}

function setError(error) {
    console.error("[Depth Viewer]", error);
    errorElement.textContent = error instanceof Error ? error.message : String(error);
    errorElement.hidden = false;
    statusElement.hidden = true;
}

function resetCamera() {
    camera.position.set(0, 0, 9);
    controls.target.set(0, 0, 0);
    controls.update();
}

function resize() {
    const width = Math.max(container.clientWidth, 1);
    const height = Math.max(container.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
}

new ResizeObserver(resize).observe(container);
resetCamera();
resize();

function disposeMaterial(material) {
    for (const value of Object.values(material)) {
        if (value?.isTexture) {
            value.dispose();
        }
    }
    material.dispose();
}

function removeMesh() {
    if (!mesh) {
        return;
    }
    scene.remove(mesh);
    mesh.geometry.dispose();
    disposeMaterial(mesh.material);
    mesh = null;
    exportButton.disabled = true;
}

function imageUrl(descriptor) {
    if (!viewUrl) {
        throw new Error("The ComfyUI API URL has not been initialized.");
    }
    const url = new URL(viewUrl, window.location.origin);
    url.search = new URLSearchParams({
        filename: descriptor.filename,
        subfolder: descriptor.subfolder ?? "",
        type: descriptor.type ?? "temp",
    }).toString();
    return url.href;
}

function loadTexture(descriptor, colorTexture) {
    return new Promise((resolve, reject) => {
        new THREE.TextureLoader().load(
            imageUrl(descriptor),
            (texture) => {
                texture.colorSpace = colorTexture
                    ? THREE.SRGBColorSpace
                    : THREE.NoColorSpace;
                texture.anisotropy = Math.min(
                    8,
                    renderer.capabilities.getMaxAnisotropy(),
                );
                resolve(texture);
            },
            undefined,
            () => reject(new Error(`Unable to load ${descriptor.filename}.`)),
        );
    });
}

async function showFrame(index) {
    if (!output) {
        return;
    }
    const reference = output.reference_image[index] ?? output.reference_image[0];
    const depth = output.depth_map[index] ?? output.depth_map[0];
    if (!reference || !depth) {
        setError("The selected frame is missing a reference image or depth map.");
        return;
    }

    const version = ++updateVersion;
    setStatus(`Loading frame ${index + 1}…`);
    try {
        const [referenceTexture, depthTexture] = await Promise.all([
            loadTexture(reference, true),
            loadTexture(depth, false),
        ]);
        if (version !== updateVersion || disposed) {
            referenceTexture.dispose();
            depthTexture.dispose();
            return;
        }

        removeMesh();
        const image = referenceTexture.image;
        const aspect = image.width / Math.max(image.height, 1);
        const width = 7;
        const height = width / aspect;
        const targetSegments = Number(document.querySelector("#mesh-quality").value);
        const segmentsX = Math.max(8, Math.min(targetSegments, image.width - 1));
        const segmentsY = Math.max(8, Math.min(Math.round(targetSegments / aspect), image.height - 1));
        const geometry = new THREE.PlaneGeometry(width, height, segmentsX, segmentsY);
        const material = new THREE.MeshStandardMaterial({
            map: referenceTexture,
            displacementMap: depthTexture,
            displacementScale: Number(depthScale.value),
            displacementBias: -Number(depthScale.value) / 2,
            roughness: 0.95,
            metalness: 0,
            side: THREE.DoubleSide,
            wireframe: document.querySelector("#wireframe").checked,
        });
        mesh = new THREE.Mesh(geometry, material);
        scene.add(mesh);
        resetCamera();
        statusElement.hidden = true;
        exportButton.disabled = false;
    } catch (error) {
        if (version === updateVersion) {
            removeMesh();
            setError(error);
        }
    }
}

function setOutput(nextOutput) {
    const referenceCount = nextOutput?.reference_image?.length ?? 0;
    const depthCount = nextOutput?.depth_map?.length ?? 0;
    const count = Math.max(referenceCount, depthCount);
    if (!count) {
        setError("ComfyUI returned no depth-viewer images.");
        return;
    }

    output = nextOutput;
    batchSelect.replaceChildren();
    for (let index = 0; index < count; index += 1) {
        const option = document.createElement("option");
        option.value = String(index);
        option.textContent = `${index + 1} / ${count}`;
        batchSelect.append(option);
    }
    batchSelect.disabled = count === 1;
    batchSelect.value = "0";
    void showFrame(0);
}

function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function bakedMesh() {
    if (!mesh) {
        throw new Error("Queue the node before exporting a mesh.");
    }
    const clone = new THREE.Mesh(
        mesh.geometry.clone(),
        new THREE.MeshStandardMaterial({
            map: mesh.material.map,
            roughness: mesh.material.roughness,
            metalness: mesh.material.metalness,
            side: THREE.DoubleSide,
        }),
    );

    const depthImage = mesh.material.displacementMap.image;
    const canvas = document.createElement("canvas");
    canvas.width = depthImage.width;
    canvas.height = depthImage.height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(depthImage, 0, 0);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    const positions = clone.geometry.attributes.position;
    const uvs = clone.geometry.attributes.uv;
    const scale = mesh.material.displacementScale;
    const bias = mesh.material.displacementBias;

    for (let index = 0; index < positions.count; index += 1) {
        const x = Math.min(
            canvas.width - 1,
            Math.max(0, Math.round(uvs.getX(index) * (canvas.width - 1))),
        );
        const y = Math.min(
            canvas.height - 1,
            Math.max(0, Math.round((1 - uvs.getY(index)) * (canvas.height - 1))),
        );
        const depth = pixels[(y * canvas.width + x) * 4] / 255;
        positions.setZ(index, depth * scale + bias);
    }
    positions.needsUpdate = true;
    clone.geometry.computeVertexNormals();
    return clone;
}

async function exportMesh() {
    const format = document.querySelector("#export-format").value;
    const exportable = bakedMesh();
    try {
        if (format === "obj") {
            const data = new OBJExporter().parse(exportable);
            download(new Blob([data], { type: "text/plain" }), "depth-mesh.obj");
            return;
        }

        const binary = format === "glb";
        const data = await new GLTFExporter().parseAsync(exportable, { binary });
        const blob = binary
            ? new Blob([data], { type: "model/gltf-binary" })
            : new Blob([JSON.stringify(data, null, 2)], {
                type: "model/gltf+json",
            });
        download(blob, `depth-mesh.${format}`);
    } finally {
        exportable.geometry.dispose();
        exportable.material.dispose();
    }
}

function takeScreenshot() {
    renderer.render(scene, camera);
    renderer.domElement.toBlob((blob) => {
        if (blob) {
            download(blob, "depth-preview.png");
        }
    }, "image/png");
}

function animate() {
    if (disposed) {
        return;
    }
    animationFrame = requestAnimationFrame(animate);
    if (document.visibilityState === "visible" && inViewport && !contextLost) {
        controls.update();
        renderer.render(scene, camera);
    }
}

const intersectionObserver = new IntersectionObserver(([entry]) => {
    inViewport = entry?.isIntersecting ?? true;
});
intersectionObserver.observe(container);
renderer.domElement.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    contextLost = true;
    setError("The browser paused this WebGL context. It will recover automatically.");
});
renderer.domElement.addEventListener("webglcontextrestored", () => {
    contextLost = false;
    setStatus("WebGL restored; rebuilding depth preview…");
    void showFrame(Number(batchSelect.value || 0));
});
animate();

batchSelect.addEventListener("change", () => {
    void showFrame(Number(batchSelect.value));
});
depthScale.addEventListener("input", () => {
    const value = Number(depthScale.value);
    depthValue.value = value.toFixed(2);
    if (mesh) {
        mesh.material.displacementScale = value;
        mesh.material.displacementBias = -value / 2;
    }
});
document.querySelector("#mesh-quality").addEventListener("change", () => {
    void showFrame(Number(batchSelect.value || 0));
});
document.querySelector("#wireframe").addEventListener("change", (event) => {
    if (mesh) {
        mesh.material.wireframe = event.target.checked;
        mesh.material.needsUpdate = true;
    }
});
document.querySelector("#reset-camera").addEventListener("click", resetCamera);
document.querySelector("#screenshot").addEventListener("click", takeScreenshot);
exportButton.addEventListener("click", () => {
    void exportMesh().catch(setError);
});

window.addEventListener("message", (event) => {
    if (
        event.origin !== window.location.origin
        || event.source !== window.parent
        || event.data?.source !== SOURCE
    ) {
        return;
    }
    if (event.data.type === "connect") {
        channel = event.data.channel;
        window.parent.postMessage(
            { source: SOURCE, channel, type: "ready" },
            window.location.origin,
        );
        return;
    }
    if (event.data.channel !== channel) {
        return;
    }
    if (event.data.type === "initialize") {
        viewUrl = event.data.viewUrl;
        setStatus("Viewer connected — queue image and depth inputs to begin.");
    } else if (event.data.type === "update") {
        setOutput(event.data.output);
    } else if (event.data.type === "dispose") {
        disposed = true;
        updateVersion += 1;
        cancelAnimationFrame(animationFrame);
        intersectionObserver.disconnect();
        removeMesh();
        controls.dispose();
        renderer.dispose();
    }
});
