import math, av
from typing import Optional, Iterator, cast
from aiortc.mediastreams import VIDEO_TIME_BASE, convert_timebase
from aiortc.codecs.base import Decoder, Encoder

PACKET_MAX = 1300
NAL_TYPE_FU = 49

class H265PayloadDescriptor:
    @classmethod
    def parse(cls, data: bytes) -> tuple['H265PayloadDescriptor', bytes]:
        if len(data) < 2: raise ValueError("NAL too short")
        if (data[0] >> 1) & 0x3F == NAL_TYPE_FU:
            if len(data) < 3: raise ValueError("FU too short")
            if data[2] & 0x80:
                hdr = bytes([(data[0] & 0x81) | ((data[2] & 0x3F) << 1), data[1]])
                return cls(), b"\x00\x00\x00\x01" + hdr + data[3:]
            return cls(), data[3:]
        return cls(), b"\x00\x00\x00\x01" + data

class H265Decoder(Decoder):
    def __init__(self): self.codec = av.CodecContext.create("hevc", "r")
    def decode(self, frame):
        try:
            p = av.Packet(frame.data)
            p.pts, p.time_base = frame.timestamp, VIDEO_TIME_BASE
            return cast(list[av.VideoFrame], self.codec.decode(p))
        except: return []

class H265Encoder(Encoder):
    def __init__(self, crf=35):
        print(" [DEBUG] Using Custom H265 Encoder")
        self.codec = None
        self.crf = crf

    def _packetize(self, data: bytes) -> list[bytes]:
        if len(data) <= PACKET_MAX: return [data]
        out, o_type, hdr = [], (data[0] >> 1) & 0x3F, bytes([(data[0] & 0x81) | (NAL_TYPE_FU << 1), data[1]])
        payload = data[2:]
        size = PACKET_MAX - 3
        for i in range(0, len(payload), size):
            chunk = payload[i:i+size]
            flag = o_type | (0x80 if i == 0 else 0x40 if i+size >= len(payload) else 0)
            out.append(hdr + bytes([flag]) + chunk)
        return out

    def _encode_frame(self, frame: av.VideoFrame, force_keyframe: bool) -> Iterator[bytes]:
        if not self.codec or self.codec.width != frame.width or self.codec.height != frame.height:
            print(f" [Encoder Init] Res: {frame.width}x{frame.height}, Force CBR: 2Mbps")
            self.codec = av.CodecContext.create("libx265", "w")
            self.codec.width, self.codec.height = frame.width, frame.height
            self.codec.pix_fmt, self.codec.framerate = "yuv420p", 30
            
            # FORCE CBR (Constant Bitrate) - No CRF
            self.codec.bit_rate = 2_000_000
            self.codec.rc_max_rate = 2_000_000
            self.codec.rc_min_rate = 2_000_000
            self.codec.rc_buffer_size = 2_000_000
            
            self.codec.options = {
                "preset": "ultrafast", 
                "tune": "zerolatency",
                # vital: removing 'crf' forces ABR/CBR mode
                "x265-params": "bitrate=2000:vbv-maxrate=2000:vbv-bufsize=2000:strict-cbr=1:keyint=30:min-keyint=30:scenecut=0:bframes=0:repeat-headers=1:aud=1:no-sao=1"
            }
        if force_keyframe: frame.pict_type = 'I'
        for p in self.codec.encode(frame):
            buf, i = bytes(p), 0
            while True:
                i = buf.find(b"\x00\x00\x01", i)
                if i == -1: break
                i += 3
                start = i
                i = buf.find(b"\x00\x00\x01", i)
                yield buf[start:i-1] if i != -1 and buf[i-1] == 0 else buf[start:i] if i != -1 else buf[start:]

    def encode(self, frame, force_keyframe=False):
        pkts = []
        for nalu in self._encode_frame(frame, force_keyframe):
            pkts.extend(self._packetize(nalu))
        return pkts, convert_timebase(frame.pts, frame.time_base, VIDEO_TIME_BASE)

def h265_depayload(payload: bytes) -> bytes:
    _, data = H265PayloadDescriptor.parse(payload)
    return data
