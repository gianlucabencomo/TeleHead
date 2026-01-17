import { updateStatus, updateMetaInfo } from './ui.js';
import { initWebCodecs, decodeChunk } from './webcodecs.js';
import { startStatsMonitor } from './stats.js';

export function setupDataChannel(pc) {
    const dc = pc.createDataChannel("video-stream", { ordered: true, maxRetransmits: 0 });
    dc.binaryType = "arraybuffer";

    dc.onopen = () => {
        updateStatus("WEBCODECS STREAMING", true);
        updateMetaInfo("DATACHANNEL ACTIVE");
        initWebCodecs();
    };

    dc.onmessage = (event) => {
        const data = event.data;
        const view = new DataView(data);
        const isKey = view.getUint8(0) === 1;
        const pts = Number(view.getBigUint64(1));
        const payload = new Uint8Array(data, 9);

        decodeChunk(new EncodedVideoChunk({
            type: isKey ? "key" : "delta",
            timestamp: pts,
            data: payload
        }));
    };

    return dc;
}
