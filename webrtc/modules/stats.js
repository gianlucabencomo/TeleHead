import { elements } from './ui.js';

let statsInterval = null;
let lastFramesDecoded = 0;
let lastStatsTime = 0;

export function startStatsMonitor(pc) {
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
                    updateFpsDisplay(fps);
                }

                lastFramesDecoded = frames;
                lastStatsTime = now;
            }
        });
    }, 1000);
}

export function stopStatsMonitor() {
    if (statsInterval) {
        clearInterval(statsInterval);
        statsInterval = null;
    }
    lastFramesDecoded = 0;
    lastStatsTime = 0;
    updateFpsDisplay(0);
}

export function updateFpsDisplay(fps) {
    elements.fpsDisplay.innerText = `FPS: ${Math.round(fps) || '--'}`;
    elements.fpsDisplay.style.color = fps < 50 ? "#dc3545" : "#00ff41";
}
