import argparse
import asyncio
import json
import ssl
import time
from aiohttp import web
import aiohttp_cors
from aiortc import RTCPeerConnection, RTCSessionDescription
from multiprocessing import shared_memory, Value, Event
import numpy as np

try:
    import pyzed.sl as sl
    from camera.zed import ZedWorker as CameraWorker
    print("ZED Camera initialized.")
except ImportError:
    import os
    if os.environ.get("USE_WEBCAM") == "1":
        from camera.webcam import WebcamWorker as CameraWorker
        print("Using Webcam/iPhone as source.")
    else:
        from camera.test import RandomWorker as CameraWorker
        print("Warning: ZED SDK not found. Falling back to RandomWorker (Simulation).")

from track import SharedMemoryTrack
from constants import *
from webrtc_utils import register_h265, force_codec, monitor_bitrate
from datachannel_server import run_data_channel_loop

async def offer(request):
    """Handles the WebRTC handshake."""
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    
    # Allow client to request a specific codec, default to custom_h265
    requested_codec = params.get("codec", "video/custom_h265")
    print(f"Client requested codec: {requested_codec}")
    
    # Debug: Check what codecs the client is actually offering
    print("--- Client SDP Codecs ---")
    for line in params["sdp"].splitlines():
        if line.startswith("a=rtpmap:"):
            print(line)
    print("-------------------------")
    
    # SDP Munging
    if requested_codec == "video/custom_h265" and "H265/90000" in params["sdp"]:
        print(" [Negotiation] Rewriting SDP: H265 -> custom_h265")
        params["sdp"] = params["sdp"].replace("H265/90000", "custom_h265/90000")
    
    pc = RTCPeerConnection()
    request.app["pcs"].add(pc)
    
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state is {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            request.app["pcs"].discard(pc)
    
    # Start the camera hardware on first connection
    request.app["stream_event"].set()
    
    # Determine mode: Track-based or DataChannel-based
    mode = params.get("mode", "track")
    
    if mode == "track":
        # Add the Video Track from Shared Memory
        track = SharedMemoryTrack(
            request.app["shm_name"],
            SHM_SHAPE,
            request.app["latest_slot"],
            request.app["new_frame_event"]
        )
        video_sender = pc.addTrack(track)
        
        try:
            force_codec(pc, video_sender, requested_codec)
        except Exception as e:
            print(f"Error forcing codec {requested_codec}: {e}")
        
        # Start monitoring stats
        asyncio.create_task(monitor_bitrate(pc, requested_codec))
    else:
        print("[Mode] Data Channel Mode activated")
    
    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"[Server] Data channel received: {channel.label}, state: {channel.readyState}")
        print(f"[Server] Channel type: {type(channel)}")
        print(f"[Server] Channel ID: {channel.id if hasattr(channel, 'id') else 'N/A'}")
        
        if channel.label == "video-stream":
            if channel.readyState == "open":
                print(f"[Server] Data channel '{channel.label}' already OPEN, starting loop")
                task = asyncio.create_task(run_data_channel_loop(channel, request.app))
                print(f"[Server] Task created: {task}")
            else:
                print(f"[Server] Waiting for channel to open...")
                @channel.on("open")
                def on_open():
                    print(f"[Server] Data channel '{channel.label}' is now OPEN")
                    task = asyncio.create_task(run_data_channel_loop(channel, request.app))
                    print(f"[Server] Task created: {task}")
    
    # Create Answer
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
    
    # Enable CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })
    
    app.router.add_get('/', index)
    app.router.add_get('/client.js', javascript)
    app.router.add_static('/modules/', './webrtc/modules/')
    
    route = app.router.add_post('/offer', offer)
    cors.add(route)
    
    app.on_shutdown.append(on_shutdown)
    
    return app


if __name__ == "__main__":
    register_h265()
    
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
            print("--- Signaling Server Starting on https://0.0.0.0:8080 ---")
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain("cert.pem", "key.pem")
            web.run_app(app, host="0.0.0.0", port=8080, ssl_context=ssl_context)
        else:
            print("--- Signaling Server Starting on http://127.0.0.1:8080 ---")
            web.run_app(app, host="127.0.0.1", port=8080)
    finally:
        worker.terminate()
        shm.close()
        shm.unlink()