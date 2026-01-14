from abc import ABC, abstractmethod
from multiprocessing import Process, shared_memory, Event, Value
import numpy as np
import time

class BaseWorker(Process, ABC):
    def __init__(
        self, 
        shm_name: str, 
        shm_shape: tuple,
        latest_slot: Value,
        stream_event: Event, 
        new_frame_event: Event, 
        debug: bool = False
    ):
        super().__init__()
        self.shm_name = shm_name
        self.shm_shape = shm_shape
        self.latest_slot = latest_slot
        self.stream_event = stream_event
        self.new_frame_event = new_frame_event
        self.debug = debug
        
        self.frame_count = 0
        self.start_time = 0.0

    @abstractmethod
    def on_start(self):
        """Hardware initialization (e.g., zed.open())"""
        pass

    @abstractmethod
    def capture_frame(self):
        """Should return a tuple (left_img, right_img) or a single SBS image"""
        pass

    @abstractmethod
    def on_stop(self):
        """Hardware cleanup (e.g., zed.close())"""
        pass

    def run(self):
        existing_shm = shared_memory.SharedMemory(name=self.shm_name)
        shared_array = np.ndarray(self.shm_shape, dtype=np.uint8, buffer=existing_shm.buf)

        self.on_start()
        
        write_slot = 0
        print(f"{self.__class__.__name__}: Ready. Waiting for client...")
        self.stream_event.wait()
        self.start_time = time.time()
        try:
            while True:
                frames = self.capture_frame()
                if frames is None:
                    continue
                
                left, right = frames
                
                # Write to SHM (Assuming Stereo Split)
                # Note: WIDTH is half of SHM_SHAPE[2] if SBS
                h, total_w, _ = shared_array.shape[1:]
                half_w = total_w // 2
                
                shared_array[write_slot, :, :half_w, :] = left
                shared_array[write_slot, :, half_w:, :] = right

                with self.latest_slot.get_lock():
                    self.latest_slot.value = write_slot
                self.new_frame_event.set()

                write_slot = 1 - write_slot
                
                if self.debug:
                    self._handle_debug()
        finally:
            self.on_stop()
            existing_shm.close()

    def _handle_debug(self):
        self.frame_count += 1
        if self.frame_count % 60 == 0:
            fps = self.frame_count / (time.time() - self.start_time)
            print(f" [{self.__class__.__name__}] {fps:.2f} fps")
            self.frame_count = 0
            self.start_time = time.time()