import asyncio
import json
import numpy as np
import av
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack

pcs = set()

class DummyVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, width=320, height=240, eye="left"):
        super().__init__()
        self.width = width
        self.height = height
        self.eye = eye
        self.frame_index = 0

    async def recv(self):
        # Generate random noise frame
        frame = (np.random.randn(self.height, self.width, 3) * 127 + 128).clip(0,255).astype(np.uint8)

        video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = self.frame_index
        video_frame.time_base = 1/30  # 30 FPS
        self.frame_index += 1

        await asyncio.sleep(1/30)  # simulate 30 FPS
        return video_frame

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    pc = RTCPeerConnection()
    pcs.add(pc)

    # Add two dummy video tracks: left/right
    pc.addTrack(DummyVideoTrack(eye="left"))
    pc.addTrack(DummyVideoTrack(eye="right"))

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.json_response({
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    })

async def on_shutdown(app):
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

app = web.Application()
app.on_shutdown.append(on_shutdown)
app.router.add_post("/offer", offer)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8080)

