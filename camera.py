import numpy as np
import pyzed.sl as sl
from multiprocessing import Process, shared_memory, Event, Value
import cv2
import time

from constants import *

class CameraWorker(Process):
    """Double-Buffered Shared Memory with Atomic Signaling"""
    def __init__(self, shm_name, latest_slot, stream_event, new_frame_event, debug: bool = False):
        super().__init__()
        self.shm_name = shm_name
        self.latest_slot = latest_slot
        self.stream_event = stream_event
        self.new_frame_event = new_frame_event
        self.debug = debug
        if self.debug:
            self.frame_count = 0
            self.start_time = time.time()

    def run(self):
        existing_shm = shared_memory.SharedMemory(name=self.shm_name)
        shared_array = np.ndarray(SHM_SHAPE, dtype=np.uint8, buffer=existing_shm.buf)

        zed = sl.Camera()
        init_params = sl.InitParameters()
        init_params.camera_resolution = RESOLUTION
        init_params.camera_fps = FPS
        init_params.depth_mode = sl.DEPTH_MODE.NONE

        e = zed.open(init_params)
        if e != sl.ERROR_CODE.SUCCESS:
            raise ValueError(f"ZED SDK raise the following error while attempting to open the camera: {e}")

        runtime_parameters = sl.RuntimeParameters()
        left, right = sl.Mat(), sl.Mat()
        write_slot = 0 # Toggle between 0 and 1
        
        print("Worker: Ready. Waiting for client...")
        self.stream_event.wait()
        try:
            while True:
                if zed.grab(runtime_parameters) == sl.ERROR_CODE.SUCCESS:
                    zed.retrieve_image(left, sl.VIEW.LEFT)
                    zed.retrieve_image(right, sl.VIEW.RIGHT)
                    
                    shared_array[write_slot, :, :WIDTH, :] = cv2.cvtColor(left.get_data(), cv2.COLOR_BGRA2RGB)
                    shared_array[write_slot, :, WIDTH:, :] = cv2.cvtColor(right.get_data(), cv2.COLOR_BGRA2RGB)

                    with self.latest_slot.get_lock():
                        self.latest_slot.value = write_slot
                    self.new_frame_event.set()

                    # Switch slots for the next grab
                    write_slot = 1 - write_slot
                    
                    if self.debug:
                        if (self.frame_count + 1) % 30 == 0:
                            print(f" [{self.frame_count / (time.time() - self.start_time)}] fps]")
                            self.frame_count = 0
                            self.start_time = time.time()
                        else:
                            self.frame_count += 1

        finally:
            zed.close()
            existing_shm.close()

if __name__ == "__main__":
    size = np.prod(SHM_SHAPE) * np.uint8().itemsize
    shm = shared_memory.SharedMemory(create=True, size=size)
    
    latest_slot = Value('i', 0)
    stream_event = Event()
    new_frame_event = Event()

    worker = CameraWorker(shm.name, latest_slot, stream_event, new_frame_event)
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

                display_frame = frame[:, :, ::-1]

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
