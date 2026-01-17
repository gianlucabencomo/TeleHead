import { elements, updateStatus } from './ui.js';
import { updateFpsDisplay } from './stats.js';

let videoDecoder = null;
let canvasCtx = null;
let frameCount = 0;
let lastFpsTime = performance.now();

export function initWebCodecs() {
    const canvas = elements.videoCanvas;
    canvas.width = 2560;
    canvas.height = 720;
    canvasCtx = canvas.getContext('2d', { alpha: false, desynchronized: true });
    
    canvas.style.display = 'block';
    elements.videoElement.style.display = 'none';

    videoDecoder = new VideoDecoder({
        output: handleDecodedFrame,
        error: (e) => {
            console.error("Decoder Error:", e);
            updateStatus("DECODER_ERROR");
        }
    });

    videoDecoder.configure({
        codec: "avc1.42E028",
        codedWidth: 2560,
        codedHeight: 720,
        optimizeForLatency: true,
        hardwareAcceleration: "prefer-hardware"
    });
}

function handleDecodedFrame(frame) {
    canvasCtx.drawImage(frame, 0, 0, elements.videoCanvas.width, elements.videoCanvas.height);
    frame.close();

    frameCount++;
    const now = performance.now();
    const elapsed = now - lastFpsTime;
    if (elapsed >= 1000) {
        updateFpsDisplay((frameCount * 1000) / elapsed);
        frameCount = 0;
        lastFpsTime = now;
    }
}

export function decodeChunk(chunk) {
    if (videoDecoder && videoDecoder.state === "configured") {
        videoDecoder.decode(chunk);
    }
}

export function closeWebCodecs() {
    if (videoDecoder) {
        videoDecoder.close();
        videoDecoder = null;
    }
}
