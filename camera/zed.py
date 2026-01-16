import pyzed.sl as sl
import cv2

import sys
from pathlib import Path

camera_path = Path(__file__).resolve(strict=True).parent # camera dir
root_path = camera_path.parent # repo dir
sys.path.append(str(camera_path))
sys.path.append(str(root_path)) # add to path

# import safely
from base import BaseWorker
from constants import *

class ZedWorker(BaseWorker):
    def on_start(self):
        self.zed = sl.Camera()
        init_params = sl.InitParameters()
        init_params.camera_resolution = RESOLUTION
        init_params.camera_fps = FPS
        init_params.depth_mode = sl.DEPTH_MODE.NONE

        e = self.zed.open(init_params)
        if e != sl.ERROR_CODE.SUCCESS:
            raise ValueError(f"ZED SDK raise the following error while attempting to open the camera: {e}")
        
        self.sbs = sl.Mat()
        self.runtime = sl.RuntimeParameters()

    def capture_frame(self):
        if self.zed.grab(self.runtime) == sl.ERROR_CODE.SUCCESS:
            self.zed.retrieve_image(self.sbs, sl.VIEW.SIDE_BY_SIDE)
            
            # Convert
            sbs = cv2.cvtColor(self.sbs.get_data(), cv2.COLOR_BGRA2YUV_I420)
            return sbs
        return None

    def on_stop(self):
        self.zed.close()

def test():
    import numpy as np
    from multiprocessing import shared_memory, Event, Value

    size = np.prod(SHM_SHAPE) * np.uint8().itemsize
    shm = shared_memory.SharedMemory(create=True, size=size)
    
    latest_slot = Value('i', 0)
    stream_event = Event()
    new_frame_event = Event()

    worker = ZedWorker(shm.name, SHM_SHAPE, latest_slot, stream_event, new_frame_event)
    worker.start()

    print("Testing Worker... Press 'q' to stop.")
    stream_event.set() # Wake up the camera

    # Create a local view of the shared memory
    shared_array = np.ndarray(SHM_SHAPE, dtype=np.uint8, buffer=shm.buf)

    try:
        while True:
            if new_frame_event.wait(timeout=1.0):
                new_frame_event.clear()
                read_slot = latest_slot.value
                frame = shared_array[read_slot]
                display_frame = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
                cv2.imshow("ZED Shared Memory Test", display_frame)           
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        pass
    finally:
        print("Cleaning up...")
        cv2.destroyAllWindows()
        worker.terminate()
        shm.close()
        shm.unlink()

if __name__ == "__main__":
    test()
