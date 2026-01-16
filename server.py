import argparse
import asyncio
import json
import ssl
from aiohttp import web
import aiohttp_cors
from aiortc import RTCPeerConnection, RTCSessionDescription
from multiprocessing import shared_memory, Value, Event
import numpy as np
import ssl

try:
    import pyzed.sl as sl
    from camera.zed import ZedWorker as CameraWorker
except ImportError:
    from camera.test import RandomWorker as CameraWorker
    print("Warning: ZED SDK (pyzed) not found. Falling back to RandomWorker (Simulation).")

from track import SharedMemoryTrack
from constants import *

from aiortc.rtcrtpsender import RTCRtpSender

def force_codec(pc, sender, forced_codec):
    kind = forced_codec.split("/")[0]
    codecs = RTCRtpSender.getCapabilities(kind).codecs
    transceiver = next(t for t in pc.getTransceivers() if t.sender == sender)
    transceiver.setCodecPreferences(
        [codec for codec in codecs if codec.mimeType == forced_codec]
    )

async def offer(request):
    """Handles the WebRTC handshake."""
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    request.app["pcs"].add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            request.app["pcs"].discard(pc)

    # 1. Start the camera hardware on first connection
    request.app["stream_event"].set()

    # 2. Add the Video Track from Shared Memory
    track = SharedMemoryTrack(
        request.app["shm_name"], 
        SHM_SHAPE,
        request.app["latest_slot"], 
        request.app["new_frame_event"]
    )
    video_sender = pc.addTrack(track)

    force_codec(pc, video_sender, "video/H264")

    # 3. Create Answer
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.json_response({
        "sdp": pc.localDescription.sdp, 
        "type": pc.localDescription.type
    })

async def on_shutdown(app):
    # Close all peer connections
    coros = [pc.close() for pc in app["pcs"]]
    await asyncio.gather(*coros)
    app["pcs"].clear()

async def index(request):
    return web.FileResponse('./webrtc/index.html')

async def javascript(request):
    return web.FileResponse('./webrtc/client.js')

def create_app(shm_name, latest_slot, stream_event, new_frame_event):
    app = web.Application()
    app["pcs"] = set()
    app["shm_name"] = shm_name
    app["latest_slot"] = latest_slot
    app["stream_event"] = stream_event
    app["new_frame_event"] = new_frame_event

    # Enable CORS so Vuer/Browsers can connect
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*"
        )
    })
    
    app.router.add_get('/', index)
    app.router.add_get('/client.js', javascript) # Add this
   
    route = app.router.add_post('/offer', offer)
    cors.add(route)
    
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Server script.")
    parser.add_argument("--local", action="store_true", help="Run in local SSL mode")
    args = parser.parse_args()

    size = np.prod(SHM_SHAPE) * np.uint8().itemsize
    shm = shared_memory.SharedMemory(create=True, size=size)
    
    latest_slot = Value('i', 0)
    stream_event = Event()
    new_frame_event = Event()

    worker = CameraWorker(shm.name, SHM_SHAPE, latest_slot, stream_event, new_frame_event)
    worker.start()

    app = create_app(shm.name, latest_slot, stream_event, new_frame_event)

    try:
        if args.local:
            # LOCAL MODE: Needs SSL and a specific IP/Host
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain("cert.pem", "key.pem")
            web.run_app(app, host="0.0.0.0", port=8080, ssl_context=ssl_context)
            print("--- Signaling Server Running on http://0.0.0.0:8080 ---")
        else:
            # NGROK MODE: Standard HTTP on localhost
            web.run_app(app, host="127.0.0.1", port=8080) 
            print("--- Signaling Server Running on http://127.0.0.1:8080 ---")

    finally:
        worker.terminate()
        shm.close()
        shm.unlink()
