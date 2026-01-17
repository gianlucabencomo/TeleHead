import { elements, updateStatus, updateMetaInfo } from './modules/ui.js';
import { startStatsMonitor, stopStatsMonitor } from './modules/stats.js';
import { setupDataChannel } from './modules/datachannel.js';
import { closeWebCodecs } from './modules/webcodecs.js';

let pc = null;

async function startStream() {
    updateStatus("INITIALIZING...");
    
    pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
    });

    pc.ontrack = (event) => {
        elements.videoElement.style.display = 'block';
        elements.videoCanvas.style.display = 'none';
        elements.videoElement.srcObject = event.streams[0];
        updateStatus("LIVE - STREAMING", true);
        updateMetaInfo("ACTIVE");
        startStatsMonitor(pc);
    };

    const codec = elements.codecSelect.value;
    const useDataChannel = (codec === "datachannel");

    if (!useDataChannel) {
        pc.addTransceiver('video', { direction: 'recvonly' });
    } else {
        setupDataChannel(pc);
    }

    try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        const response = await fetch('/offer', {
            method: 'POST',
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type,
                codec: codec,
                mode: useDataChannel ? "datachannel" : "track"
            }),
            headers: { 'Content-Type': 'application/json' }
        });

        const answer = await response.json();
        await pc.setRemoteDescription(new RTCSessionDescription(answer));

        elements.streamBtn.innerText = "Stop Stream";
        elements.streamBtn.classList.add('stop-mode');

    } catch (e) {
        console.error("Stream Start Error:", e);
        stopStream();
    }
}

function stopStream() {
    stopStatsMonitor();
    closeWebCodecs();
    if (pc) {
        pc.close();
        pc = null;
    }
    elements.videoElement.srcObject = null;
    updateStatus("OFFLINE");
    elements.streamBtn.innerText = "Connect Stream";
    elements.streamBtn.classList.remove('stop-mode');
    updateMetaInfo("NO_PEER_CONNECTED");
}

elements.streamBtn.onclick = () => {
    if (pc) stopStream();
    else startStream();
};
