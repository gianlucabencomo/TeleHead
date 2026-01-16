import numpy as np
import time
import asyncio
from aiortc import MediaStreamTrack
from av import VideoFrame
from multiprocessing import shared_memory

class SharedMemoryTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, shm_name, shm_shape, latest_slot, new_frame_event):
        super().__init__()
        self.shm = shared_memory.SharedMemory(name=shm_name)
        self.shared_array = np.ndarray(shm_shape, dtype=np.uint8, buffer=self.shm.buf)
        self.latest_slot = latest_slot
        self.new_frame_event = new_frame_event
        self.start_time = None

    async def recv(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.new_frame_event.wait, 0.1)
        self.new_frame_event.clear()

        if self.start_time is None:
            self.start_time = time.time()

        read_slot = self.latest_slot.value
       
        frame = VideoFrame.from_ndarray(self.shared_array[read_slot], format="yuv420p")

        pts = int((time.time() - self.start_time) * 90000)
        frame.pts = pts
        frame.time_base = 90000
        
        return frame
