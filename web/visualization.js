import { app } from "../../scripts/app.js"

class Visualizer {
    constructor(node, container, visualSrc) {
        this.node = node

        this.iframe = document.createElement('iframe')
        Object.assign(this.iframe, {
            scrolling: "no",
            overflow: "hidden",
        })
        this.iframe.src = "/extensions/ComfyUI-Depth-Visualization/html/" + visualSrc + ".html"
        container.appendChild(this.iframe)

        // Wait for the iframe to load, then initialize it with the API URL
        this.iframe.onload = () => {
            this.iframe.contentWindow.postMessage({
                type: 'init',
                apiURL: app.getApiUrl() // Assuming app.getApiUrl() exists and returns the API URL
            }, '*')
        }
    }

    updateVisual(params) {
        const iframeDocument = this.iframe.contentWindow.document;
        const previewScript = iframeDocument.getElementById('visualizer');
        previewScript.setAttribute("reference_image", JSON.stringify(params.reference_image));
        previewScript.setAttribute("depth_map", JSON.stringify(params.depth_map));
        // Trigger the update in the iframe
        this.iframe.contentWindow.postMessage({
            type: 'update',
            referenceImage: params.reference_image,
            depthMap: params.depth_map
        }, '*')
    }

    remove() {
        this.container.remove()
    }
}

function createVisualizer(node, inputName, typeName, inputData, app) {
    node.name = inputName

    const widget = {
        type: typeName,
        name: "preview3d",
        callback: () => {},
        draw : function(ctx, node, widgetWidth, widgetY, widgetHeight) {
            const margin = 10
            const top_offset = 5
            const visible = app.canvas.ds.scale > 0.5 && this.type === typeName
            const w = widgetWidth - margin * 4
            const clientRectBound = ctx.canvas.getBoundingClientRect()
            const transform = new DOMMatrix()
                .scaleSelf(
                    clientRectBound.width / ctx.canvas.width,
                    clientRectBound.height / ctx.canvas.height
                )
                .multiplySelf(ctx.getTransform())
                .translateSelf(margin, margin + widgetY)
            
            Object.assign(this.visualizer.style, {
                left: `${transform.a * margin + transform.e}px`,
                top: `${transform.d + transform.f + top_offset}px`,
                width: `${(w * transform.a)}px`,
                height: `${(w * transform.d - widgetHeight - (margin * 15) * transform.d)}px`,
                position: "absolute",
                overflow: "hidden",
                zIndex: app.graph._nodes.indexOf(node),
            })

            Object.assign(this.visualizer.children[0].style, {
                transformOrigin: "50% 50%",
                width: '100%',
                height: '100%',
                border: '0 none',
            })

            this.visualizer.hidden = !visible
        },
    }

    const container = document.createElement('div')
    container.id = `Comfy3D_${inputName}`

    node.visualizer = new Visualizer(node, container, typeName)
    widget.visualizer = container
    widget.parent = node

    document.body.appendChild(widget.visualizer)

    node.addCustomWidget(widget)

    node.updateParameters = (params) => {
        node.visualizer.updateVisual(params);
    }


    // Events for drawing backgound
    node.onDrawBackground = function (ctx) {
        if (!this.flags.collapsed) {
            node.visualizer.iframe.hidden = false
        } else {
            node.visualizer.iframe.hidden = true
        }
    }

    // Make sure visualization iframe is always inside the node when resize the node
    node.onResize = function () {
        let [w, h] = this.size
        if (w <= 600) w = 600
        if (h <= 500) h = 500

        if (w > 600) {
            h = w - 100
        }

        this.size = [w, h]
    }

    // Events for remove nodes
    node.onRemoved = () => {
        for (let w in node.widgets) {
            if (node.widgets[w].visualizer) {
                node.widgets[w].visualizer.remove()
            }
        }
    }

    return {
        widget: widget,
    }
}

function registerVisualizer(nodeType, nodeData, nodeClassName, typeName) {
    if (nodeData.name == nodeClassName) {
        console.log("[3D Visualizer] Registering node: " + nodeData.name)

        const onNodeCreated = nodeType.prototype.onNodeCreated

        nodeType.prototype.onNodeCreated = async function() {
            const r = onNodeCreated
                ? onNodeCreated.apply(this, arguments)
                : undefined

            let Preview3DNode = app.graph._nodes.filter(
                (wi) => wi.type == nodeClassName
            )
            let nodeName = `Preview3DNode_${Preview3DNode.length}`

            console.log(`[Comfy3D] Create: ${nodeName}`)

            const result = await createVisualizer.apply(this, [this, nodeName, typeName, {}, app])

            this.setSize([600, 500])

            return r
        }

        nodeType.prototype.onExecuted = async function(message) { 
                // Check if reference image and depth map are available
            if (message.reference_image && message.depth_map) {
                const params = {}
                params.reference_image = message.reference_image[0];
                params.depth_map = message.depth_map[0];
                this.updateParameters(params);
            }
                
            }
    }
}

app.registerExtension({
    name: "Mr.ForExample.Visualizer.GS",

    async init (app) {

    },

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        registerVisualizer(nodeType, nodeData, "DepthViewer", "threeVisualizer")
    },
})
