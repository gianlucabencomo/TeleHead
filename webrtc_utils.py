import time
import asyncio
from aiortc.rtcrtpsender import RTCRtpSender
from aiortc.rtcrtpreceiver import RTCRtpReceiver
from aiortc.rtcrtpparameters import RTCRtpCodecCapability
import aiortc.codecs
from custom_codecs.h265 import H265Encoder, H265Decoder

def register_h265():
    """Registers the custom H.265 codec with aiortc."""
    h265_cap = RTCRtpCodecCapability(
        mimeType="video/custom_h265",
        clockRate=90000,
        parameters={}
    )
    
    sender_codecs = RTCRtpSender.getCapabilities("video").codecs
    if not any(c.mimeType == "video/custom_h265" for c in sender_codecs):
        sender_codecs.append(h265_cap)
    
    receiver_codecs = RTCRtpReceiver.getCapabilities("video").codecs
    if not any(c.mimeType == "video/custom_h265" for c in receiver_codecs):
        receiver_codecs.append(h265_cap)
    
    _orig_get_encoder = aiortc.codecs.get_encoder
    _orig_get_decoder = aiortc.codecs.get_decoder
    
    def get_encoder(codec):
        if codec.mimeType == "video/custom_h265":
            print(" [Factory] Creating H265Encoder with CRF 18")
            return H265Encoder(crf=18)
        return _orig_get_encoder(codec)
    
    def get_decoder(codec):
        if codec.mimeType == "video/custom_h265":
            return H265Decoder()
        return _orig_get_decoder(codec)
    
    aiortc.codecs.get_encoder = get_encoder
    aiortc.codecs.get_decoder = get_decoder
    
    print(" [Custom Codec] Custom H.265 Registered")

def force_codec(pc, sender, forced_codec):
    kind = forced_codec.split("/")[0]
    codecs = RTCRtpSender.getCapabilities(kind).codecs
    transceiver = next(t for t in pc.getTransceivers() if t.sender == sender)
    transceiver.setCodecPreferences(
        [codec for codec in codecs if codec.mimeType == forced_codec]
    )

async def monitor_bitrate(pc, codec_name):
    """Periodically prints the bitrate of the video track."""
    print(f"Starting stats monitor for {codec_name}...")
    old_bytes = 0
    old_time = time.time()
    
    try:
        while True:
            await asyncio.sleep(1)
            
            if pc.connectionState in ["closed", "failed"]:
                break
            
            stats = await pc.getStats()
            active_codec = codec_name
            
            for report in stats.values():
                if report.type == "outbound-rtp" and report.kind == "video":
                    current_bytes = report.bytesSent
                    now = time.time()
                    
                    codec_id = getattr(report, "codecId", getattr(report, "codec_id", None))
                    if codec_id:
                        codec_report = stats.get(codec_id)
                        if codec_report:
                            active_codec = getattr(
                                codec_report, 
                                "mimeType", 
                                getattr(codec_report, "mime_type", active_codec)
                            )
                    
                    if old_bytes > 0:
                        bitrate = ((current_bytes - old_bytes) * 8) / ((now - old_time) * 1_000_000)
                        print(f"[{active_codec}] Bitrate: {bitrate:.2f} Mbps")
                    
                    old_bytes = current_bytes
                    old_time = now
                    break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in bitrate monitor: {e}")
