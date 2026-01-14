# Camera Workers

This directory contains the multiprocessing workers responsible for capturing and streaming stereo video data into shared memory.

* **`base.py`**: Contains the `BaseWorker` Abstract Base Class, which manages the core shared memory lifecycle, double-buffering logic, and atomic signaling.
* **`zed.py`**: Implementation for the **ZED Mini** (63mm baseline).
* **`efference.py`**: Implementation for the **Efference H1** (65mm baseline).
* **`test.py`**: A diagnostic worker generating random noise to test the pipeline without physical hardware.