import cv2
import time
import numpy as np

import sys
from pathlib import Path

camera_path = Path(__file__).resolve(strict=True).parent # camera dir
root_path = camera_path.parent # repo dir
sys.path.append(str(camera_path))
sys.path.append(str(root_path)) # add to path

# import safely
from base import BaseWorker
from constants import *

class RandomWorker(BaseWorker):
    def on_start(self):
        pass

    def capture_frame(self):
        time.sleep(1. / 120.)
        sample = np.random.randint(0, 256, size=(2, HEIGHT, WIDTH, 3), dtype=np.uint8)
        left, right = sample[0], sample[1]
        return left, right

    def on_stop(self):
        pass

def test():
    from multiprocessing import shared_memory, Event, Value

    size = np.prod(SHM_SHAPE) * np.uint8().itemsize
    shm = shared_memory.SharedMemory(create=True, size=size)
    
    latest_slot = Value('i', 0)
    stream_event = Event()
    new_frame_event = Event()

    worker = RandomWorker(shm.name, SHM_SHAPE, latest_slot, stream_event, new_frame_event, debug=True)
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
                cv2.imshow("Random Shared Memory Test", display_frame)           
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