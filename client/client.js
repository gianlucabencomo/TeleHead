let pc = null;

async function negotiate() {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // Wait for ICE gathering
    await new Promise(resolve => {
        if (pc.iceGatheringState === 'complete') {
            resolve();
        } else {
            pc.addEventListener('icegatheringstatechange', function check() {
                if (pc.iceGatheringState === 'complete') {
                    pc.removeEventListener('icegatheringstatechange', check);
                    resolve();
                }
            });
        }
    });

    // Send offer to server
    const res = await fetch('/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pc.localDescription)
    });

    const answer = await res.json();
    await pc.setRemoteDescription(answer);
}

function start() {
    pc = new RTCPeerConnection({ sdpSemantics: 'unified-plan' });

    // Two recvonly transceivers
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('video', { direction: 'recvonly' });

    pc.ontrack = (event) => {
        if (!event.streams || !event.streams[0]) return;

        const leftVideo = document.getElementById('left_video');
        const rightVideo = document.getElementById('right_video');

        if (!leftVideo.srcObject) {
            leftVideo.srcObject = event.streams[0];
            console.log("Assigned first track to left");
        } else if (!rightVideo.srcObject) {
            rightVideo.srcObject = event.streams[0];
            console.log("Assigned second track to right");
        }
    };

    pc.oniceconnectionstatechange = () => console.log("ICE state:", pc.iceConnectionState);
    pc.onconnectionstatechange = () => console.log("Connection state:", pc.connectionState);

    document.getElementById('start').style.display = 'none';
    document.getElementById('stop').style.display = 'inline-block';

    negotiate();
}

function stop() {
    if (pc) pc.close();
    pc = null;
    document.getElementById('stop').style.display = 'none';
    document.getElementById('start').style.display = 'inline-block';
}

document.getElementById('start').addEventListener('click', start);
document.getElementById('stop').addEventListener('click', stop);

