import asyncio
import time
import struct
import numpy as np
import av
from fractions import Fraction
from multiprocessing import shared_memory
from constants import SHM_SHAPE

async def run_data_channel_loop(channel, app):
    """Encodes frames and sends them over the Data Channel."""
    print("Starting Data Channel Video Loop...")
    await asyncio.sleep(0.1)
    
    shm = shared_memory.SharedMemory(name=app["shm_name"])
    shared_array = np.ndarray(SHM_SHAPE, dtype=np.uint8, buffer=shm.buf)
    
    codec = None
    try:
        FRAME_WIDTH = 2560
        FRAME_HEIGHT = 720
        
        codec = av.CodecContext.create("libx264", "w")
        codec.width = FRAME_WIDTH
        codec.height = FRAME_HEIGHT
        codec.pix_fmt = "yuv420p"
        codec.time_base = Fraction(1, 60)
        codec.framerate = Fraction(60, 1)
        codec.gop_size = 30
        codec.max_b_frames = 0
        
        codec.options = {
            "preset": "ultrafast",
            "tune": "zerolatency",
            "profile": "baseline",
            "x264-params": "keyint=30:min-keyint=30:scenecut=0:bitrate=4000:vbv-maxrate=4000:vbv-bufsize=4000:nal-hrd=cbr"
        }
        
        codec.open()
        frame_count = 0
        last_frame_time = time.time()
        
        while True:
            if channel.readyState != "open":
                break
            
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
            
            read_slot = app["latest_slot"].value
            frame_data = shared_array[read_slot].copy()
            
            frame = av.VideoFrame(FRAME_WIDTH, FRAME_HEIGHT, "yuv420p")
            y_size = FRAME_WIDTH * FRAME_HEIGHT
            uv_size = (FRAME_WIDTH // 2) * (FRAME_HEIGHT // 2)
            
            flat_data = frame_data.tobytes()
            frame.planes[0].update(flat_data[0:y_size])
            frame.planes[1].update(flat_data[y_size : y_size + uv_size])
            frame.planes[2].update(flat_data[y_size + uv_size : y_size + 2 * uv_size])
            
            
            # Encode
            packets = codec.encode(frame)
            
            for packet in packets:
                data = bytes(packet)
                if len(data) == 0: continue
                
                is_key = 1 if packet.is_keyframe else 0
                ts = int(frame_count * (1_000_000 / 60))
                
                # Check for large frames blocking the channel
                if len(data) > 500_000: # 500KB warning
                    print(f"  Frame {frame_count} is huge! {len(data)} bytes. Keyframe: {is_key}")
                
                header = struct.pack(">BQ", is_key, ts)
                message = header + data
                
                max_buffer_wait = 0
                while channel.bufferedAmount > 4_000_000: # Increase buffer limit to 4MB
                    await asyncio.sleep(0.005) # Check more frequently (5ms)
                    max_buffer_wait += 1
                    if max_buffer_wait > 200: # 1s timeout
                         print("  Buffer FULL, dropping frame")
                         break
                
                if max_buffer_wait <= 200:
                    try:
                        channel.send(message)
                        
                        if frame_count % 60 == 0:
                            current_time = time.time()
                            fps = 60 / (current_time - last_frame_time) if frame_count > 0 else 0
                            print(f"  Frame {frame_count}: size={len(data)}B, fps={fps:.1f}, buf={channel.bufferedAmount}")
                            last_frame_time = current_time
                    except Exception as e:
                        print(f"  Send failed: {e}")
            
            frame_count += 1
            await asyncio.sleep(0)
            
    except Exception as e:
        print(f"Data Channel Loop Error: {e}")
    finally:
        if codec:
            try:
                codec.close()
            except:
                pass
        print("Data Channel Loop Stopped")
