export const elements = {
    streamBtn: document.getElementById('streamBtn'),
    statusText: document.getElementById('status'),
    statusContainer: document.getElementById('status-container'),
    videoElement: document.getElementById('videoPlayer'),
    infoText: document.getElementById('connection-info'),
    fpsDisplay: document.getElementById('fps-counter'),
    codecSelect: document.getElementById('codecSelect'),
    videoCanvas: document.getElementById('videoCanvas')
};

export function updateStatus(text, isLive = false) {
    elements.statusText.innerText = text;
    if (isLive) {
        elements.statusContainer.classList.add('live');
    } else {
        elements.statusContainer.classList.remove('live');
    }
}

export function updateMetaInfo(text) {
    elements.infoText.innerText = text;
}
