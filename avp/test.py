import asyncio
from vuer import Vuer, VuerSession
from vuer.schemas import Scene, Hands, ImageBackground, DefaultScene

app = Vuer(host="127.0.0.1", port=8000, domain="efference.ngrok.app", queries=dict(grid=False, cam=True))

@app.add_handler("CAMERA_MOVE")
async def on_cam_move(event, session):
    print(f"Camera Move Detected! Key: {event.key}")

@app.add_handler("HAND_MOVE")
async def on_hand_move(event, session):
    print(f"Hand Moving: {event.key}")

@app.spawn(start=False)
async def main(session: VuerSession):
    # 1. Initialize Scene without grid. 
    # DefaultScene ensures the ego-camera (head) starts tracking immediately.
    session.set @ DefaultScene(grid=False)

    # 2. Configure Hands: Invisible but streaming data
    session.upsert @ Hands(
        fps=60,
        stream=True,
        key="hands",
        showLeft=False,
        showRight=False,
        )

    while True:
        session.upsert(
            [
                ImageBackground(
                    "./stereo/left/1.jpeg",
                    key="left-image",
                    layers=1,
                    aspect=1.66667,
                    height=8,
                    position=[0, -1, 3],
                    interpolate=True,
                    format="jpeg",
                    quality=80,
                ),
                ImageBackground(
                    "./stereo/right/1.jpeg",
                    key="right-image",
                    layers=2,
                    aspect=1.66667,
                    height=8,
                    position=[0, -1, 3],
                    interpolate=True,
                    format="jpeg",
                    quality=80,
                )
            ],
            to="bgChildren"
        )
        await asyncio.sleep(0.03) # ~30 FPS for smoother updates

if __name__ == "__main__":
    app.run()

