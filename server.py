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

# === Custom Codec Imports ===
from aiortc.rtcrtpsender import RTCRtpSender
from aiortc.rtcrtpreceiver import RTCRtpReceiver
from aiortc.rtcrtpparameters import RTCRtpCodecCapability
import aiortc.codecs
from custom_codecs.h265 import H265Encoder, H265Decoder

import av
from fractions import Fraction
import struct


def register_h265():
    """Registers the custom H.265 codec with aiortc."""
    h265_cap = RTCRtpCodecCapability(
        mimeType="video/custom_h265",
        clockRate=90000,
        parameters={}
    )
    
    sender_codecs = RTCRtpSender.getCapabilities("video").codecs
    if not any(c.mimeType == "video/custom_h265" for c in sender_codecs):
        sender_codecs.append(h265_cap)
    
    receiver_codecs = RTCRtpReceiver.getCapabilities("video").codecs
    if not any(c.mimeType == "video/custom_h265" for c in receiver_codecs):
        receiver_codecs.append(h265_cap)
    
    _orig_get_encoder = aiortc.codecs.get_encoder
    _orig_get_decoder = aiortc.codecs.get_decoder
    
    def get_encoder(codec):
        if codec.mimeType == "video/custom_h265":
            return H265Encoder(crf=23)
        return _orig_get_encoder(codec)
    
    def get_decoder(codec):
        if codec.mimeType == "video/custom_h265":
            return H265Decoder()
        return _orig_get_decoder(codec)
    
    aiortc.codecs.get_encoder = get_encoder
    aiortc.codecs.get_decoder = get_decoder
    
    print(" [Custom Codec] Custom H.265 Registered")


def force_codec(pc, sender, forced_codec):
    kind = forced_codec.split("/")[0]
    codecs = RTCRtpSender.getCapabilities(kind).codecs
    transceiver = next(t for t in pc.getTransceivers() if t.sender == sender)
    transceiver.setCodecPreferences(
        [codec for codec in codecs if codec.mimeType == forced_codec]
    )


async def monitor_bitrate(pc, codec_name):
    """Periodically prints the bitrate of the video track."""
    print(f"Starting stats monitor for {codec_name}...")
    old_bytes = 0
    old_time = time.time()
    
    try:
        while True:
            await asyncio.sleep(1)
            
            if pc.connectionState in ["closed", "failed"]:
                break
            
            stats = await pc.getStats()
            active_codec = codec_name
            
            for report in stats.values():
                if report.type == "outbound-rtp" and report.kind == "video":
                    current_bytes = report.bytesSent
                    now = time.time()
                    
                    # Try to resolve actual codec
                    codec_id = getattr(report, "codecId", getattr(report, "codec_id", None))
                    if codec_id:
                        codec_report = stats.get(codec_id)
                        if codec_report:
                            active_codec = getattr(
                                codec_report, 
                                "mimeType", 
                                getattr(codec_report, "mime_type", active_codec)
                            )
                    
                    if old_bytes > 0:
                        # Calculate Mbps
                        bitrate = ((current_bytes - old_bytes) * 8) / ((now - old_time) * 1_000_000)
                        print(f"[{active_codec}] Bitrate: {bitrate:.2f} Mbps")
                    
                    old_bytes = current_bytes
                    old_time = now
                    break
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in bitrate monitor: {e}")


async def run_data_channel_loop(channel, app):
    """Encodes frames and sends them over the Data Channel."""
    print("Starting Data Channel Video Loop...")
    print(f"  Channel readyState: {channel.readyState}")
    print(f"  Channel type: {type(channel)}")
    
    # Wait a moment for channel to be fully ready
    await asyncio.sleep(0.1)
    
    # Connect to Shared Memory
    shm = shared_memory.SharedMemory(name=app["shm_name"])
    shared_array = np.ndarray(SHM_SHAPE, dtype=np.uint8, buffer=shm.buf)
    
    codec = None
    
    try:
        # WIDTH * 2 (stereo) = 2560
        FRAME_WIDTH = 2560
        FRAME_HEIGHT = 720
        
        codec = av.CodecContext.create("libx264", "w")
        codec.width = FRAME_WIDTH
        codec.height = FRAME_HEIGHT
        codec.pix_fmt = "yuv420p"
        codec.time_base = Fraction(1, 60)  # 60 fps
        codec.framerate = Fraction(60, 1)
        codec.gop_size = 30  # Keyframe every 30 frames
        codec.max_b_frames = 0  # No B-frames for low latency
        
        # Use CRF for quality-based encoding with reasonable compression
        # CRF 28 = decent quality, much smaller files
        # Also set a max bitrate to prevent huge frames
        codec.options = {
            "preset": "ultrafast",
            "tune": "zerolatency",
            "profile": "baseline",
            "crf": "28",
            "maxrate": "4M",
            "bufsize": "8M",
            "x264-params": "keyint=30:min-keyint=30:scenecut=0"
        }
        
        codec.open()
        print(f"  Encoder opened: {codec.name}, gop={codec.gop_size}, crf=28")
        
        frame_count = 0
        last_frame_time = time.time()
        
        while True:
            # Check if channel is still open
            if channel.readyState != "open":
                print(f"Channel closed, state: {channel.readyState}")
                break
            
            # Wait for new frame with timeout
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, 
                        app["new_frame_event"].wait
                    ), 
                    timeout=0.1
                )
                app["new_frame_event"].clear()
            except asyncio.TimeoutError:
                continue
            
            # Read the frame from shared memory (copy to avoid race condition)
            read_slot = app["latest_slot"].value
            frame_data = shared_array[read_slot].copy()
            
            # Create frame and copy YUV data
            frame = av.VideoFrame(FRAME_WIDTH, FRAME_HEIGHT, "yuv420p")
            
            # YUV420p Layout: Y = W*H, U = W/2 * H/2, V = W/2 * H/2
            y_size = FRAME_WIDTH * FRAME_HEIGHT
            uv_size = (FRAME_WIDTH // 2) * (FRAME_HEIGHT // 2)
            
            flat_data = frame_data.tobytes()
            frame.planes[0].update(flat_data[0:y_size])
            frame.planes[1].update(flat_data[y_size : y_size + uv_size])
            frame.planes[2].update(flat_data[y_size + uv_size : y_size + 2 * uv_size])
            
            frame.pts = frame_count
            
            # Encode
            packets = codec.encode(frame)
            
            for packet in packets:
                data = bytes(packet)
                is_key = 1 if packet.is_keyframe else 0
                
                # Timestamp in microseconds
                ts = frame_count * (1_000_000 // 60)
                
                header = struct.pack(">BQ", is_key, ts)
                message = header + data
                
                # Check if we can send (respect buffer limits)
                # DataChannel typically has 16MB buffer, but we should stay well below
                max_wait = 0
                while channel.bufferedAmount > 1_000_000:  # Wait if buffer > 1MB
                    await asyncio.sleep(0.01)
                    max_wait += 1
                    if max_wait > 100:  # 1 second timeout
                        print(f"  ⚠ Buffer stuck at {channel.bufferedAmount}, skipping frame")
                        break
                
                try:
                    channel.send(message)
                    
                    # Verify send
                    if frame_count == 0:
                        print(f"  ✓ First frame sent: {len(message)} bytes (header=9, payload={len(data)})")
                    
                    # Log periodically
                    if frame_count % 60 == 0:
                        current_time = time.time()
                        fps = 60 / (current_time - last_frame_time) if frame_count > 0 else 0
                        print(f"  Frame {frame_count}: size={len(data)}B, key={is_key}, fps={fps:.1f}, buffer={channel.bufferedAmount}")
                        last_frame_time = current_time
                        
                except Exception as e:
                    print(f"  Send error: {e}")
                    break
            
            frame_count += 1
            await asyncio.sleep(0)  # Yield control
            
    except asyncio.CancelledError:
        print("Data Channel Loop Cancelled")
    except Exception as e:
        import traceback
        print(f"Data Channel Loop Error: {e}")
        traceback.print_exc()
    finally:
        if codec:
            try:
                # Flush any remaining packets
                packets = codec.encode(None)
                for packet in packets:
                    try:
                        data = bytes(packet)
                        is_key = 1 if packet.is_keyframe else 0
                        ts = frame_count * (1_000_000 // 60)
                        header = struct.pack(">BQ", is_key, ts)
                        channel.send(header + data)
                    except:
                        pass
            except:
                pass
            
            try:
                codec.close()
            except Exception as e:
                print(f"Error closing codec: {e}")
        
        print("Data Channel Loop Stopped")


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