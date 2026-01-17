import cv2
import numpy as np
from camera.base import BaseWorker
from constants import WIDTH, HEIGHT, SHM_SHAPE

class WebcamWorker(BaseWorker):
    def on_start(self):
        # On macOS, index 0 is built-in, 1+ are external/iPhone
        # We loop to find the first working camera
        self.cap = None
        for i in range(3):
            print(f"WebcamWorker: Checking camera index {i}...")
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                # Test read to ensure permissions are actually granted
                ret, _ = cap.read()
                if ret:
                    self.cap = cap
                    print(f"WebcamWorker: Successfully opened camera {i}")
                    break
            cap.release()
        
        if not self.cap:
            print("Error: Could not open any Webcam/iPhone camera index (0-2)")
            print("TIP: If on macOS, ensure your Terminal/VS Code has 'Camera' permissions in System Settings.")
            return

        # Set resolution to match what the system expects (720p)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    def capture_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return None
        
        # Current system expects Stereo (2560x720). 
        # iPhone is Mono (1280x720).
        # We will duplicate the frame side-by-side to "fake" stereo.
        
        # 1. Resize iPhone frame to exactly 1280x720 if needed
        if frame.shape[1] != WIDTH or frame.shape[0] != HEIGHT:
            frame = cv2.resize(frame, (WIDTH, HEIGHT))
        
        # 2. Stack left and right (identical) to create side-by-side stereo
        stereo_frame = np.hstack((frame, frame)) 
        
        # 3. Convert to YUV420p (I420)
        # Resulting shape will be (HEIGHT * 1.5, WIDTH * 2)
        yuv = cv2.cvtColor(stereo_frame, cv2.COLOR_BGR2YUV_I420)
        return yuv

    def on_stop(self):
        if hasattr(self, 'cap') and self.cap:
            self.cap.release()
