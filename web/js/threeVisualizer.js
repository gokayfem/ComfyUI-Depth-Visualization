import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

let apiURL = '';

// Listen for messages from the parent window
window.addEventListener('message', function(event) {
    if (event.data.type === 'init') {
        apiURL = event.data.apiURL;
    } else if (event.data.type === 'update') {
        main(event.data.referenceImage, event.data.depthMap);
    }
}, false);

const visualizer = document.getElementById("visualizer");
const container = document.getElementById("container");
const progressDialog = document.getElementById("progress-dialog");
const progressIndicator = document.getElementById("progress-indicator");

const renderer = new THREE.WebGLRenderer({ antialias: true, extensions: {
    derivatives: true
}});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
container.appendChild(renderer.domElement);

const pmremGenerator = new THREE.PMREMGenerator(renderer);

// scene
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);
scene.environment = pmremGenerator.fromScene(new RoomEnvironment(renderer), 0.04).texture;

const ambientLight = new THREE.AmbientLight(0xffffff);

const camera = new THREE.PerspectiveCamera(40, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.set(0, 0, 10);
const pointLight = new THREE.PointLight(0xffffff, 15);
camera.add(pointLight);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 0);
controls.update();
controls.enablePan = true;
controls.enableDamping = true;

// Handle window resize event
window.onresize = function () {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();

    renderer.setSize(window.innerWidth, window.innerHeight);
};

var lastReferenceImage = "";
var lastDepthMap = "";
var needUpdate = false;

function frameUpdate() {
    var referenceImage = visualizer.getAttribute("reference_image");
    var depthMap = visualizer.getAttribute("depth_map");
    if (referenceImage == lastReferenceImage && depthMap == lastDepthMap) {
        if (needUpdate) {
            controls.update();
            renderer.render(scene, camera);
        }
        requestAnimationFrame(frameUpdate);
    } else {
        needUpdate = false;
        scene.clear();
        progressDialog.open = true;
        lastReferenceImage = referenceImage;
        lastDepthMap = depthMap;
        main(JSON.parse(lastReferenceImage), JSON.parse(lastDepthMap));
    }
}

const onProgress = function (xhr) {
    if (xhr.lengthComputable) {
        progressIndicator.value = xhr.loaded / xhr.total * 100;
    }
};

const onError = function (e) {
    console.error(e);
};

async function main(referenceImageParams, depthMapParams) {
    let referenceTexture, depthTexture;
    let imageWidth = 10; // Default width
    let imageHeight = 10; // Default height, will be updated based on the image's aspect ratio

    if (referenceImageParams?.filename) {
        const referenceImageUrl = `${apiURL}/view?` + new URLSearchParams(referenceImageParams).toString();
        const referenceImageExt = referenceImageParams.filename.slice(referenceImageParams.filename.lastIndexOf(".") + 1);

        if (referenceImageExt === "png" || referenceImageExt === "jpg" || referenceImageExt === "jpeg") {
            const referenceImageLoader = new THREE.TextureLoader();
            referenceTexture = await new Promise((resolve, reject) => {
                referenceImageLoader.load(referenceImageUrl, (texture) => {
                    // Once the image is loaded, update the width and height based on the image's aspect ratio
                    imageWidth = 10; // Keep the width as 10
                    imageHeight = texture.image.height / (texture.image.width / 10);
                    resolve(texture);
                }, undefined, reject);
            });
        }
    }

    if (depthMapParams?.filename) {
        const depthMapUrl = `${apiURL}/view?` + new URLSearchParams(depthMapParams).toString();
        const depthMapExt = depthMapParams.filename.slice(depthMapParams.filename.lastIndexOf(".") + 1);

        if (depthMapExt === "png" || depthMapExt === "jpg" || depthMapExt === "jpeg") {
            const depthMapLoader = new THREE.TextureLoader();
            depthTexture = await depthMapLoader.loadAsync(depthMapUrl);
        }
    }

    if (referenceTexture && depthTexture) {
        const depthMaterial = new THREE.ShaderMaterial({
        uniforms: {
            referenceTexture: { value: referenceTexture },
            depthTexture: { value: depthTexture },
            depthScale: { value: 5.0 },
            ambientLightColor: { value: new THREE.Color(0.2, 0.2, 0.2) },
            lightPosition: { value: new THREE.Vector3(2, 2, 2) },
            lightColor: { value: new THREE.Color(1, 1, 1) },
            lightIntensity: { value: 1.0 },
            shininess: { value: 30 },
        },
        vertexShader: `
            uniform sampler2D depthTexture;
            uniform float depthScale;
    
            varying vec2 vUv;
            varying float vDepth;
            varying vec3 vNormal;
            varying vec3 vViewPosition;
    
            void main() {
                vUv = uv;
                
                float depth = texture2D(depthTexture, uv).r;
                vec3 displacement = normal * depth * depthScale;
                vec3 displacedPosition = position + displacement;
                
                vec4 worldPosition = modelMatrix * vec4(displacedPosition, 1.0);
                vNormal = normalize(normalMatrix * normal);
                vViewPosition = (viewMatrix * worldPosition).xyz;
                
                gl_Position = projectionMatrix * viewMatrix * worldPosition;
                
                vDepth = depth;
            }
        `,
        fragmentShader: `
            uniform sampler2D referenceTexture;
    
            varying vec2 vUv;
            varying float vDepth;
    
            void main() {
                vec4 referenceColor = texture2D(referenceTexture, vUv);
                
                // Directly use reference color without fog
                gl_FragColor = referenceColor;
            }
        `
    });
    
        
        const planeGeometry = new THREE.PlaneGeometry(imageWidth, imageHeight, 200, 200);
        const depthMesh = new THREE.Mesh(planeGeometry, depthMaterial);
        scene.add(depthMesh);
    }

    needUpdate = true;

    scene.add(ambientLight);
    scene.add(camera);

    progressDialog.close();

    frameUpdate();
}

document.getElementById('screenshotButton').addEventListener('click', takeScreenshot);

function takeScreenshot() {
    renderer.render(scene, camera);
    const dataURL = renderer.domElement.toDataURL('image/png');
    const link = document.createElement('a');
    link.href = dataURL;
    link.download = "screenshot.png";
    link.click();
    console.log("Screenshot taken");
}
