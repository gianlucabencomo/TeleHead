try:
    import pyzed.sl as sl
    ZED_AVAILABLE = True
except ImportError:
    ZED_AVAILABLE = False
    print("Warning: ZED SDK (pyzed) not found. Camera features will be disabled.")

WIDTH, HEIGHT = 1280, 720  # Per eye
FPS = 30
SHM_SHAPE = (2, int(HEIGHT * 1.5), WIDTH * 2,) # YUV420 height is HEIGHT * 1.5
RESOLUTION = sl.RESOLUTION.HD720 if ZED_AVAILABLE else None
