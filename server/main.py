import asyncio
import json
import os
import time
import numpy as np
from aiohttp import web
import aiohttp_cors
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from av import VideoFrame

ROOT = os.path.dirname(__file__)
pcs = set()


class DummyVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, width=320, height=240, fps=30, eye="left"):
        super().__init__()
        self.width = width
        self.height = height
        self.fps = fps
        self.eye = eye
        self.start_time = time.time()
        self.frame_index = 0
        self.timescale = 1000  # milliseconds

    async def recv(self):
        frame = (np.random.randn(self.height, self.width, 3) * 127 + 128).clip(0, 255).astype(np.uint8)
        video_frame = VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = int((time.time() - self.start_time) * self.timescale)
        video_frame.time_base = self.timescale
        self.frame_index += 1
        print(f"[{self.eye}] Sending frame {self.frame_index}")
        await asyncio.sleep(1 / self.fps)
        return video_frame


async def index(request):
    return web.FileResponse(os.path.join(ROOT, "client", "index.html"))


async def client_js(request):
    return web.FileResponse(os.path.join(ROOT, "client", "client.js"))


async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state: {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # Add two dummy tracks for left/right stereo
    left_track = DummyVideoTrack(width=960, height=640, fps=30, eye="left")
    right_track = DummyVideoTrack(width=960, height=640, fps=30, eye="right")
    pc.addTrack(left_track)
    pc.addTrack(right_track)

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


if __name__ == "__main__":
    app = web.Application()
    # Enable CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*",
        )
    })

    cors.add(app.router.add_get("/", index))
    cors.add(app.router.add_get("/client.js", client_js))
    cors.add(app.router.add_post("/offer", offer))

    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=8080)

