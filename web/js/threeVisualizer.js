import * as THREE from 'three';
import { api } from '../../../scripts/api.js';

import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

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

    if (referenceImageParams?.filename) {
        const referenceImageUrl = api.apiURL('/view?' + new URLSearchParams(referenceImageParams)).replace(/extensions.*\//, "");
        const referenceImageExt = referenceImageParams.filename.slice(referenceImageParams.filename.lastIndexOf(".") + 1);

        if (referenceImageExt === "png" || referenceImageExt === "jpg" || referenceImageExt === "jpeg") {
            const referenceImageLoader = new THREE.TextureLoader();
            referenceTexture = await referenceImageLoader.loadAsync(referenceImageUrl);
        }
    }

    if (depthMapParams?.filename) {
        const depthMapUrl = api.apiURL('/view?' + new URLSearchParams(depthMapParams)).replace(/extensions.*\//, "");
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
    

        const aspect = window.innerWidth / window.innerHeight;
        const planeWidth = 10;
        const planeHeight = planeWidth / aspect;
        
        const planeGeometry = new THREE.PlaneGeometry(planeWidth, planeHeight, 200, 200);
        //add double side three js plane geometry
        const depthMesh = new THREE.Mesh(planeGeometry, depthMaterial);
        scene.add(depthMesh);
    }

    needUpdate = true;

    scene.add(ambientLight);
    scene.add(camera);

    progressDialog.close();

    frameUpdate();
}

main();