const streamBtn = document.getElementById('streamBtn');
const statusText = document.getElementById('status');
const statusContainer = document.getElementById('status-container');
const videoElement = document.getElementById('videoPlayer');
const infoText = document.getElementById('connection-info');
const fpsDisplay = document.getElementById('fps-counter'); // New element

let pc = null;
let isStreaming = false;
let statsInterval = null; // To hold our timer

// FPS Tracking variables
let lastFramesDecoded = 0;
let lastStatsTime = 0;

async function startStream() {
    statusText.innerText = "INITIALIZING...";
    
    pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
    });

    pc.ontrack = (event) => {
        videoElement.srcObject = event.streams[0];
        statusText.innerText = "LIVE - STREAMING";
        statusContainer.classList.add('live');
        infoText.innerText = "ACTIVE";
        
        // Start monitoring FPS when the track arrives
        startStatsMonitor();
    };

    pc.oniceconnectionstatechange = () => {
        if (pc.iceConnectionState === "disconnected" || pc.iceConnectionState === "closed") {
            stopStream();
        }
    };

    pc.addTransceiver('video', { direction: 'recvonly' });

    try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const response = await fetch('/offer', {
            method: 'POST',
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type,
            }),
            headers: { 'Content-Type': 'application/json' }
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
            // We are looking for the inbound-rtp stats for video
            if (report.type === 'inbound-rtp' && report.kind === 'video') {
                const now = report.timestamp;
                const frames = report.framesDecoded;

                if (lastStatsTime > 0) {
                    // Calculate FPS: (CurrentFrames - LastFrames) / (TimeDelta in seconds)
                    const fps = (frames - lastFramesDecoded) / ((now - lastStatsTime) / 1000);
                    fpsDisplay.innerText = `FPS: ${Math.round(fps)}`;
                    
                    // Optional: Change color if FPS drops below 50
                    fpsDisplay.style.color = fps < 50 ? "#dc3545" : "#00ff41";
                }

                lastFramesDecoded = frames;
                lastStatsTime = now;
            }
        });
    }, 1000); // Update every second
}

function stopStream() {
    if (statsInterval) {
        clearInterval(statsInterval);
        statsInterval = null;
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
}

streamBtn.addEventListener('click', () => {
    if (!isStreaming) {
        startStream();
    } else {
        stopStream();
    }
});
