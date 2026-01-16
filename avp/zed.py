import asyncio
from vuer import Vuer, VuerSession
from vuer.schemas import Hands, WebRTCStereoVideoPlane, DefaultScene

# Using cam=True in queries to ensure head tracking works
app = Vuer(
    host="127.0.0.1", 
    port=8000, 
    domain="efference.ngrok.app", 
    queries=dict(grid=False, cam=True)
)

@app.add_handler("CAMERA_MOVE")
async def on_cam_move(event, session):
    if event.key == "ego":
        # Accessing the head matrix directly
        data = event.value.get("camera", event.value)
        matrix = data.get("matrix")
        if matrix:
            print(f"Head Tracking Active - X: {matrix[12]:.2f}", flush=True)

@app.add_handler("HAND_MOVE")
async def on_hand_move(event, session):
    print(f"Hand Moving: {event.key}")

@app.spawn(start=False)
async def main(session: VuerSession):
    # 1. Initialize Scene - frameloop="always" is best for WebRTC
    session.set @ DefaultScene(grid=False, frameloop="always")

    # 2. Add Hands (Invisible, Streaming Data)
    session.upsert @ Hands(
        fps=60, 
        stream=True, 
        key="hands", 
        showLeft=False, 
        showRight=False
    )

    # 3. Add WebRTC Stereo Plane (SBS Format)
    # Ensure this URL matches your ngrok tunnel for the ZED server
    session.upsert @ WebRTCStereoVideoPlane(
        src="https://civilizational-angelia-nonveracious.ngrok-free.dev/offer",
        key="zed-sbs-stream",
        aspect=1.777777,     # Aspect ratio of ONE eye
        height=8,           # Physical size in the virtual world
        position=[0, -1, 3],
        rotation=[0, 0, 0],
    )

    while True:
        # We no longer need to upsert images manually! 
        # WebRTC handles the frame updates automatically.
        await asyncio.sleep(1)

if __name__ == "__main__":
    app.run()
