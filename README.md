# TELEHHEAD (GPT generated readme)

This project enables low-latency WebRTC video streaming from a Stereolabs ZED camera hosted on an NVIDIA Jetson (Xavier/Orin). It uses shared memory for efficient frame handling and `aiortc` for the media pipeline.

---

## 🏗️ Jetson Setup

### 1. Install ZED SDK & PyZED
The `pyzed` library is hardware-specific and cannot be installed via `pip`. You must use the official Stereolabs installer.

1.  **Download:** Get the [ZED SDK for JetPack](https://www.stereolabs.com/developers/release/) (ensure the version matches your JetPack 5.x or 6.x).
2.  **Run Installer:**
    ```bash
    chmod +x ZED_SDK_Jetson_JP*.run
    ./ZED_SDK_Jetson_JP*.run
    ```
3.  **Python Wrapper:** During the interactive setup, ensure you say **Yes** to installing the Python Wrapper. If you are using a Python `venv`, activate it **before** running the installer so it detects the correct site-packages path.

### 2. Install Dependencies
Install the remaining Python requirements:
```bash
pip install -r requirements.txt


