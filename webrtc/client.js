const streamBtn = document.getElementById('streamBtn');
const statusText = document.getElementById('status');
const statusContainer = document.getElementById('status-container');
const videoElement = document.getElementById('videoPlayer');
const infoText = document.getElementById('connection-info');
const fpsDisplay = document.getElementById('fps-counter');

let pc = null;
let isStreaming = false;
let statsInterval = null;

// FPS Tracking variables
let lastFramesDecoded = 0;
let lastStatsTime = 0;
let frameCount = 0;
let lastFpsTime = performance.now();

async function startStream() {
    statusText.innerText = "INITIALIZING...";
    
    pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
    });

    pc.onconnectionstatechange = () => {
        console.log("Connection state:", pc.connectionState);
    };

    pc.oniceconnectionstatechange = () => {
        console.log("ICE state:", pc.iceConnectionState);
        if (pc.iceConnectionState === "disconnected" || pc.iceConnectionState === "closed") {
            stopStream();
        }
    };

    pc.ontrack = (event) => {
        console.log("Track received:", event.track.kind);
        const videoEl = document.getElementById('videoPlayer');
        const canvasEl = document.getElementById('videoCanvas');
        
        videoEl.style.display = 'block';
        canvasEl.style.display = 'none';
        
        videoEl.srcObject = event.streams[0];
        statusText.innerText = "LIVE - STREAMING";
        statusContainer.classList.add('live');
        infoText.innerText = "ACTIVE";
        
        startStatsMonitor();
    };

    const codec = document.getElementById('codecSelect').value;
    const useDataChannel = (codec === "datachannel");

    console.log("Requesting codec:", codec, "useDataChannel:", useDataChannel);

    if (!useDataChannel) {
        pc.addTransceiver('video', { direction: 'recvonly' });
    }

    if (useDataChannel) {
        setupDataChannel(pc);
    }

    try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        
        console.log("=== Offer SDP ===");
        const sctpLines = offer.sdp.split('\n').filter(line => 
            line.includes('SCTP') || line.includes('sctp') || line.includes('application')
        );
        console.log("SCTP-related lines:", sctpLines.length > 0 ? sctpLines : "NONE FOUND!");
        console.log("================");

        const response = await fetch('/offer', {
            method: 'POST',
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type,
                codec: codec,
                mode: useDataChannel ? "datachannel" : "track"
            }),
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) throw new Error("Server responded with " + response.status);

        const answer = await response.json();
        await pc.setRemoteDescription(new RTCSessionDescription(answer));

        streamBtn.innerText = "Stop Stream";
        streamBtn.classList.add('stop-mode');
        isStreaming = true;

    } catch (e) {
        console.error("Stream Start Error:", e);
        statusText.innerText = "CONNECTION_FAILED";
        stopStream();
    }
}

function startStatsMonitor() {
    if (statsInterval) clearInterval(statsInterval);
    
    statsInterval = setInterval(async () => {
        if (!pc) return;

        const stats = await pc.getStats();
        stats.forEach(report => {
            if (report.type === 'inbound-rtp' && report.kind === 'video') {
                const now = report.timestamp;
                const frames = report.framesDecoded;

                if (lastStatsTime > 0) {
                    const fps = (frames - lastFramesDecoded) / ((now - lastStatsTime) / 1000);
                    fpsDisplay.innerText = `FPS: ${Math.round(fps)}`;
                    fpsDisplay.style.color = fps < 50 ? "#dc3545" : "#00ff41";
                }

                lastFramesDecoded = frames;
                lastStatsTime = now;
            }
        });
    }, 1000);
}

function stopStream() {
    if (statsInterval) {
        clearInterval(statsInterval);
        statsInterval = null;
    }
    
    if (videoDecoder) {
        try {
            videoDecoder.close();
        } catch (e) {
            console.error("Error closing decoder:", e);
        }
        videoDecoder = null;
    }
    
    if (pc) {
        pc.close();
        pc = null;
    }
    
    videoElement.srcObject = null;
    statusText.innerText = "OFFLINE";
    statusContainer.classList.remove('live');
    streamBtn.innerText = "Connect Stream";
    streamBtn.classList.remove('stop-mode');
    infoText.innerText = "NO_PEER_CONNECTED";
    fpsDisplay.innerText = "FPS: --";
    fpsDisplay.style.color = "#555";
    isStreaming = false;
    
    lastFramesDecoded = 0;
    lastStatsTime = 0;
    frameCount = 0;
    lastFpsTime = performance.now();
    avcConfig = null;
}

let videoDecoder = null;
let canvasCtx = null;

function setupDataChannel(pc) {
    console.log("Setting up Data Channel...");
    
    const dc = pc.createDataChannel("video-stream", { 
        ordered: true,
        maxRetransmits: 0
    });
    
    dc.binaryType = "arraybuffer";
    
    console.log("Data channel created:", {
        label: dc.label,
        id: dc.id,
        readyState: dc.readyState,
        maxPacketLifeTime: dc.maxPacketLifeTime,
        maxRetransmits: dc.maxRetransmits,
        ordered: dc.ordered
    });

    dc.onopen = () => {
        console.log("✓ Data Channel OPEN");
        console.log("  readyState:", dc.readyState);
        console.log("  bufferedAmount:", dc.bufferedAmount);
        console.log("  bufferedAmountLowThreshold:", dc.bufferedAmountLowThreshold);
        console.log("  label:", dc.label);
        console.log("  id:", dc.id);
        
        dc.bufferedAmountLowThreshold = 65536;
        
        statusText.innerText = "WEBCODECS STREAMING";
        statusContainer.classList.add('live');
        infoText.innerText = "DATACHANNEL ACTIVE";
        
        initWebCodecs();
        startStatsMonitor();
    };
    
    dc.onerror = (e) => {
        console.error("✗ Data Channel Error:", e);
    };
    
    dc.onclose = () => {
        console.log("✗ Data Channel CLOSED");
        stopStream();
    };
    
    let messageCount = 0;
    dc.onmessage = (event) => {
        messageCount++;
        console.log(`📦 RAW Message #${messageCount}, size: ${event.data?.byteLength || 'unknown'}, type: ${typeof event.data}`);
        try {
            handleDataChannelMessage(event.data);
        } catch (e) {
            console.error("✗ Error in message handler:", e);
            console.error("Stack:", e.stack);
        }
    };
    
    setInterval(() => {
        if (dc.readyState === "open") {
            console.log(`DC Stats: msgs=${messageCount}, buffer=${dc.bufferedAmount}, state=${dc.readyState}`);
        }
    }, 5000);
}

function initWebCodecs() {
    console.log("Initializing WebCodecs decoder...");
    const canvas = document.getElementById('videoCanvas');
    
    canvas.width = 2560;
    canvas.height = 720;
    
    canvasCtx = canvas.getContext('2d', {
        alpha: false,
        desynchronized: true
    });
    
    canvas.style.display = 'block';
    document.getElementById('videoPlayer').style.display = 'none';
    
    console.log("Canvas configured:", canvas.width, "x", canvas.height);

    videoDecoder = new VideoDecoder({
        output: (frame) => {
            console.log(`✓ Frame decoded: ${frame.codedWidth}x${frame.codedHeight}, format=${frame.format}, ts=${frame.timestamp}`);
            
            try {
                canvasCtx.fillStyle = '#000';
                canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
                canvasCtx.drawImage(frame, 0, 0, canvas.width, canvas.height);
                
                console.log("✓ Frame rendered to canvas");
                
                frameCount++;
                const now = performance.now();
                const elapsed = now - lastFpsTime;
                
                if (elapsed >= 1000) {
                    const fps = Math.round((frameCount * 1000) / elapsed);
                    fpsDisplay.innerText = `FPS: ${fps}`;
                    fpsDisplay.style.color = fps < 50 ? "#dc3545" : "#00ff41";
                    
                    frameCount = 0;
                    lastFpsTime = now;
                }
                
            } catch (e) {
                console.error("✗ Error rendering frame:", e);
            } finally {
                frame.close();
            }
        },
        error: (e) => {
            console.error("✗ Decoder Error:", e);
            statusText.innerText = "DECODER_ERROR";
        },
    });

    try {
        videoDecoder.configure({
            codec: "avc1.42E028",
            codedWidth: 2560,
            codedHeight: 720,
            optimizeForLatency: true,
            hardwareAcceleration: "prefer-hardware"
        });
        console.log("VideoDecoder configured:", videoDecoder.state);
    } catch (e) {
        console.error("Failed to configure decoder:", e);
        statusText.innerText = "CODEC_ERROR";
    }
}

function handleDataChannelMessage(data) {
    if (data.byteLength <= 6) {
        const text = new TextDecoder().decode(data);
        if (text.startsWith("TEST")) {
            console.log(`✓ ${text} message received - channel is working!`);
            return;
        }
    }
    
    if (data.byteLength < 9) {
        console.warn("⚠ Received unexpected small packet:", data.byteLength);
        return;
    }
    
    try {
        const view = new DataView(data);
        const isKey = (view.getUint8(0) === 1);
        const ts = Number(view.getBigUint64(1, false));
        
        const chunkData = new Uint8Array(data, 9);
        
        if (!videoDecoder || videoDecoder.state !== "configured") {
            console.warn("⚠ Decoder not ready, state:", videoDecoder?.state);
            return;
        }
        
        // Just decode directly without trying to extract description
        const chunk = new EncodedVideoChunk({
            type: isKey ? 'key' : 'delta',
            timestamp: ts,
            data: chunkData
        });
        
        videoDecoder.decode(chunk);
        
    } catch (e) {
        console.error("✗ Error decoding:", e);
    }
}

function extractAVCDescription(annexBData) {
    try {
        const nalUnits = [];
        let i = 0;
        
        while (i < annexBData.length - 4) {
            if (annexBData[i] === 0 && annexBData[i+1] === 0) {
                let startCodeLen = 0;
                if (annexBData[i+2] === 0 && annexBData[i+3] === 1) {
                    startCodeLen = 4;
                } else if (annexBData[i+2] === 1) {
                    startCodeLen = 3;
                }
                
                if (startCodeLen > 0) {
                    let nextStart = i + startCodeLen;
                    let found = false;
                    
                    for (let j = nextStart; j < annexBData.length - 4; j++) {
                        if (annexBData[j] === 0 && annexBData[j+1] === 0 &&
                            (annexBData[j+2] === 1 || (annexBData[j+2] === 0 && annexBData[j+3] === 1))) {
                            nalUnits.push(annexBData.slice(i + startCodeLen, j));
                            i = j;
                            found = true;
                            break;
                        }
                    }
                    
                    if (!found) {
                        nalUnits.push(annexBData.slice(i + startCodeLen));
                        break;
                    }
                } else {
                    i++;
                }
            } else {
                i++;
            }
        }
        
        let sps = null, pps = null;
        for (const nal of nalUnits) {
            if (nal.length === 0) continue;
            const nalType = nal[0] & 0x1F;
            if (nalType === 7) sps = nal;
            if (nalType === 8) pps = nal;
        }
        
        if (sps && pps) {
            const description = new Uint8Array(sps.length + pps.length + 11);
            let offset = 0;
            
            description[offset++] = 1;
            description[offset++] = sps[1];
            description[offset++] = sps[2];
            description[offset++] = sps[3];
            description[offset++] = 0xFF;
            
            description[offset++] = 0xE1;
            description[offset++] = (sps.length >> 8) & 0xFF;
            description[offset++] = sps.length & 0xFF;
            description.set(sps, offset);
            offset += sps.length;
            
            description[offset++] = 1;
            description[offset++] = (pps.length >> 8) & 0xFF;
            description[offset++] = pps.length & 0xFF;
            description.set(pps, offset);
            
            console.log("✓ Created AVCC description:", description.length, "bytes");
            return description;
        }
        
        console.warn("⚠ Could not find SPS/PPS in keyframe");
        return null;
        
    } catch (e) {
        console.error("✗ Error extracting AVC description:", e);
        return null;
    }
}

streamBtn.addEventListener('click', () => {
    if (!isStreaming) {
        startStream();
    } else {
        stopStream();
    }
});