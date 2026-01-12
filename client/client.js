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

    // Add two recvonly transceivers for left/right video
    pc.addTransceiver('video', { direction: 'recvonly' }); // left
    pc.addTransceiver('video', { direction: 'recvonly' }); // right

    pc.ontrack = (event) => {
        if (!event.streams || !event.streams[0]) return;

        // Simple assignment: first track -> left, second -> right
        const videoEls = [document.getElementById('left_video'), document.getElementById('right_video')];

        if (!videoEls[0].srcObject) {
            videoEls[0].srcObject = event.streams[0];
        } else if (!videoEls[1].srcObject) {
            videoEls[1].srcObject = event.streams[0];
        }
    };

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

