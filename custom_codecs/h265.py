import math
import av
from av.frame import Frame
from typing import Optional, Iterator, cast
from aiortc.mediastreams import VIDEO_TIME_BASE, convert_timebase
from aiortc.codecs.base import Decoder, Encoder

PACKET_MAX = 1300
NAL_TYPE_FU = 49

class H265PayloadDescriptor:
    @classmethod
    def parse(cls, data: bytes) -> tuple['H265PayloadDescriptor', bytes]:
        if len(data) < 2: raise ValueError("NAL too short")
        nal_type = (data[0] >> 1) & 0x3F
        if nal_type == NAL_TYPE_FU:
            if len(data) < 3: raise ValueError("FU NAL too short")
            first = bool(data[2] & 0x80)
            if first:
                header = bytes([(data[0] & 0x81) | ((data[2] & 0x3F) << 1), data[1]])
                return cls(), bytes([0,0,0,1]) + header + data[3:]
            return cls(), data[3:]
        return cls(), bytes([0,0,0,1]) + data

class H265Decoder(Decoder):
    def __init__(self) -> None:
        self.codec = av.CodecContext.create("hevc", "r")
    def decode(self, encoded_frame) -> list[Frame]:
        try:
            packet = av.Packet(encoded_frame.data)
            packet.pts, packet.time_base = encoded_frame.timestamp, VIDEO_TIME_BASE
            return cast(list[Frame], self.codec.decode(packet))
        except Exception: return []

class H265Encoder(Encoder):
    def __init__(self, crf: int = 23) -> None:
        self.codec: Optional[av.VideoCodecContext] = None
        self.crf = crf

    @staticmethod
    def _packetize_fu(data: bytes) -> list[bytes]:
        original_type = (data[0] >> 1) & 0x3F
        fu_header_base = bytes([(data[0] & 0x81) | (NAL_TYPE_FU << 1), data[1]])
        payload = data[2:]
        num_pkts = math.ceil(len(payload) / (PACKET_MAX - 3))
        size = math.ceil(len(payload) / num_pkts)
        pkts = []
        for i in range(num_pkts):
            start, end = i * size, (i + 1) * size
            chunk = payload[start:end]
            fu_header = original_type | (0x80 if i == 0 else 0x40 if end >= len(payload) else 0)
            pkts.append(fu_header_base + bytes([fu_header]) + chunk)
        return pkts

    @staticmethod
    def _split_bitstream(buf: bytes) -> Iterator[bytes]:
        i = 0
        while True:
            i = buf.find(b"\x00\x00\x01", i)
            if i == -1: return
            i += 3
            start = i
            i = buf.find(b"\x00\x00\x01", i)
            if i == -1: 
                yield buf[start:]
                return
            yield buf[start:i-1] if buf[i-1] == 0 else buf[start:i]

    def _encode_frame(self, frame: av.VideoFrame, force_keyframe: bool) -> Iterator[bytes]:
        if not self.codec or self.codec.width != frame.width or self.codec.height != frame.height:
            self.codec = av.CodecContext.create("libx265", "w")
            self.codec.width, self.codec.height = frame.width, frame.height
            self.codec.pix_fmt, self.codec.framerate = "yuv420p", 60
            self.codec.options = {
                "preset": "ultrafast", "tune": "zerolatency", "crf": str(self.crf),
                "x265-params": "repeat-headers=1:aud=1:keyint=60:min-keyint=60:scenecut=0:bframes=0"
            }
        if force_keyframe: frame.pict_type = 'I'
        for packet in self.codec.encode(frame):
            yield from self._split_bitstream(bytes(packet))

    def encode(self, frame: Frame, force_keyframe: bool = False) -> tuple[list[bytes], int]:
        pkts = []
        for nalu in self._encode_frame(frame, force_keyframe):
            pkts.extend(self._packetize_fu(nalu) if len(nalu) > PACKET_MAX else [nalu])
        return pkts, convert_timebase(frame.pts, frame.time_base, VIDEO_TIME_BASE)

def h265_depayload(payload: bytes) -> bytes:
    _, data = H265PayloadDescriptor.parse(payload)
    return data
