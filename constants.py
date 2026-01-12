import pyzed.sl as sl

WIDTH, HEIGHT = 1280, 720  # Per eye
FPS = 60
SHM_SHAPE = (2, HEIGHT, WIDTH * 2, 3)  # [Slot 0/1, H, W_SBS, RGB]
RESOLUTION = sl.RESOLUTION.HD720
