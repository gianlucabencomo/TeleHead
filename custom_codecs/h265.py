"""
H.265/HEVC Encoder with lossless compression and optimized performance.

This encoder uses x265 with settings optimized for:
- Lossless or near-lossless quality (CRF 0)
- Maximum encoding speed (ultrafast preset)
- Low latency (zero latency tuning)
- Real-time streaming performance
"""

import fractions
import logging
import math
from collections.abc import Iterable, Iterator, Sequence
from itertools import tee
from struct import pack, unpack_from
from typing import Optional, Type, TypeVar, cast

import av
from av.frame import Frame
from av.packet import Packet
from av.video.codeccontext import VideoCodecContext

from aiortc.jitterbuffer import JitterFrame
from aiortc.mediastreams import VIDEO_TIME_BASE, convert_timebase
from aiortc.codecs.base import Decoder, Encoder

logger = logging.getLogger(__name__)

# For lossless, we don't use bitrate control - we use CRF 0
MAX_FRAME_RATE = 60
PACKET_MAX = 1300

# H.265 NAL unit types (different from H.264)
NAL_TYPE_TRAIL_N = 0
NAL_TYPE_TRAIL_R = 1
NAL_TYPE_TSA_N = 2
NAL_TYPE_TSA_R = 3
NAL_TYPE_STSA_N = 4
NAL_TYPE_STSA_R = 5
NAL_TYPE_RADL_N = 6
NAL_TYPE_RADL_R = 7
NAL_TYPE_RASL_N = 8
NAL_TYPE_RASL_R = 9
NAL_TYPE_BLA_W_LP = 16
NAL_TYPE_BLA_W_RADL = 17
NAL_TYPE_BLA_N_LP = 18
NAL_TYPE_IDR_W_RADL = 19
NAL_TYPE_IDR_N_LP = 20
NAL_TYPE_CRA_NUT = 21
NAL_TYPE_VPS = 32
NAL_TYPE_SPS = 33
NAL_TYPE_PPS = 34
NAL_TYPE_AUD = 35
NAL_TYPE_FU = 49  # Fragmentation Unit

NAL_HEADER_SIZE = 2  # H.265 uses 2-byte NAL header
FU_HEADER_SIZE = 3   # 2-byte NAL header + 1-byte FU header

DESCRIPTOR_T = TypeVar("DESCRIPTOR_T", bound="H265PayloadDescriptor")
T = TypeVar("T")


def pairwise(iterable: Sequence[T]) -> Iterator[tuple[T, T]]:
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


class H265PayloadDescriptor:
    def __init__(self, first_fragment: bool) -> None:
        self.first_fragment = first_fragment

    def __repr__(self) -> str:
        return f"H265PayloadDescriptor(FF={self.first_fragment})"

    @classmethod
    def parse(cls: Type[DESCRIPTOR_T], data: bytes) -> tuple[DESCRIPTOR_T, bytes]:
        output = bytes()

        if len(data) < 2:
            raise ValueError("NAL unit is too short")

        # H.265 NAL unit header is 2 bytes
        # First byte: F (1 bit) | Type (6 bits) | LayerId (1 bit)
        # Second byte: LayerId (5 bits) | TID (3 bits)
        nal_type = (data[0] >> 1) & 0x3F

        if nal_type == NAL_TYPE_FU:
            # Fragmentation unit
            if len(data) < 3:
                raise ValueError("FU NAL unit is too short")
            
            fu_header = data[2]
            first_fragment = bool(fu_header & 0x80)
            original_nal_type = fu_header & 0x3F
            
            if first_fragment:
                # Reconstruct original NAL header
                original_header = bytes([
                    (data[0] & 0x81) | (original_nal_type << 1),
                    data[1]
                ])
                output = bytes([0, 0, 0, 1]) + original_header + data[3:]
            else:
                output = data[3:]
            
            obj = cls(first_fragment=first_fragment)
        elif nal_type <= 40:
            # Single NAL unit
            output = bytes([0, 0, 0, 1]) + data
            obj = cls(first_fragment=True)
        else:
            raise ValueError(f"NAL unit type {nal_type} is not supported")

        return obj, output


class H265Decoder(Decoder):
    def __init__(self) -> None:
        self.codec = av.CodecContext.create("hevc", "r")

    def decode(self, encoded_frame: JitterFrame) -> list[Frame]:
        try:
            packet = av.Packet(encoded_frame.data)
            packet.pts = encoded_frame.timestamp
            packet.time_base = VIDEO_TIME_BASE
            return cast(list[Frame], self.codec.decode(packet))
        except av.FFmpegError as e:
            logger.warning(
                "H265Decoder() failed to decode, skipping package: " + str(e)
            )
            return []


class H265Encoder(Encoder):
    """
    H.265/HEVC encoder optimized for lossless compression with high performance.
    
    Key optimizations for speed on noisy data:
    - ultrafast preset: Minimal computational overhead
    - zerolatency tune: No lookahead, immediate encoding  
    - CRF 0: Lossless quality
    - Disabled features: No B-frames, no SAO, no weighted prediction
    """

    def __init__(self, lossless: bool = True, crf: int = 0) -> None:
        self.buffer_data = b""
        self.buffer_pts: Optional[int] = None
        self.codec: Optional[VideoCodecContext] = None
        self.lossless = lossless
        self.crf = crf  # 0 = lossless, 1-51 = lossy (lower = better quality)

    @staticmethod
    def _packetize_fu(data: bytes) -> list[bytes]:
        """Fragment a large NAL unit into multiple RTP packets."""
        available_size = PACKET_MAX - FU_HEADER_SIZE
        payload_size = len(data) - NAL_HEADER_SIZE
        num_packets = math.ceil(payload_size / available_size)
        package_size = payload_size // num_packets
        num_larger_packets = payload_size % num_packets

        # Extract original NAL unit type from 2-byte header
        original_nal_type = (data[0] >> 1) & 0x3F
        layer_id_tid = data[1]

        # FU NAL header: set type to 49 (FU)
        fu_nal_header = bytes([
            (data[0] & 0x81) | (NAL_TYPE_FU << 1),
            layer_id_tid
        ])

        packages = []
        offset = NAL_HEADER_SIZE
        first = True

        while offset < len(data):
            # Determine payload size for this packet
            if num_larger_packets > 0:
                num_larger_packets -= 1
                current_size = package_size + 1
            else:
                current_size = package_size

            payload = data[offset:offset + current_size]
            offset += current_size

            # FU header: S (start), E (end), FuType
            if first:
                fu_header = 0x80 | original_nal_type  # Start bit set
                first = False
            elif offset >= len(data):
                fu_header = 0x40 | original_nal_type  # End bit set
            else:
                fu_header = original_nal_type  # Middle fragment

            packages.append(fu_nal_header + bytes([fu_header]) + payload)

        return packages

    @staticmethod
    def _split_bitstream(buf: bytes) -> Iterator[bytes]:
        """Split H.265 bitstream into individual NAL units."""
        i = 0
        while True:
            # Find start code (0x000001 or 0x00000001)
            i = buf.find(b"\x00\x00\x01", i)
            if i == -1:
                return

            # Skip start code
            i += 3
            nal_start = i

            # Find next start code or end of buffer
            i = buf.find(b"\x00\x00\x01", i)
            if i == -1:
                yield buf[nal_start:]
                return
            elif i > 0 and buf[i - 1] == 0:
                # 4-byte start code
                yield buf[nal_start:i - 1]
            else:
                yield buf[nal_start:i]

    @classmethod
    def _packetize(cls, packages: Iterable[bytes]) -> list[bytes]:
        """Packetize NAL units for RTP transmission."""
        packetized = []
        for package in packages:
            if len(package) > PACKET_MAX:
                packetized.extend(cls._packetize_fu(package))
            else:
                packetized.append(package)
        return packetized

    def _encode_frame(
        self, frame: av.VideoFrame, force_keyframe: bool
    ) -> Iterator[bytes]:
        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
        ):
            self.buffer_data = b""
            self.buffer_pts = None
            self.codec = None

        if force_keyframe:
            frame.pict_type = av.video.frame.PictureType.I
        else:
            frame.pict_type = av.video.frame.PictureType.NONE

        if self.codec is None:
            self.codec = av.CodecContext.create("libx265", "w")
            self.codec.width = frame.width
            self.codec.height = frame.height
            self.codec.pix_fmt = "yuv420p"
            self.codec.framerate = fractions.Fraction(MAX_FRAME_RATE, 1)
            self.codec.time_base = fractions.Fraction(1, MAX_FRAME_RATE)
            
            # Build x265 params for maximum speed with lossless quality
            # These settings prioritize encoding speed for noisy data
            x265_params = [
                "log-level=warning",
                "repeat-headers=1",      # Include VPS/SPS/PPS with each keyframe
                "aud=1",                  # Access unit delimiters
                
                # Speed optimizations (critical for performance)
                "no-sao=1",              # Disable Sample Adaptive Offset (big speedup)
                "no-weightp=1",          # Disable weighted prediction
                "no-weightb=1",          # Disable weighted B prediction  
                "bframes=0",             # No B-frames (lower latency + faster)
                "ref=1",                 # Single reference frame (faster)
                "me=dia",                # Diamond motion estimation (fastest)
                "subme=0",               # No subpel motion refinement
                "no-rect=1",             # Disable rectangular partitions
                "no-amp=1",              # Disable asymmetric motion partitions
                "rd=1",                  # Fast RD level
                "no-early-skip=1",       # Disable early skip
                "fast-intra=1",          # Fast intra analysis
                "no-tskip-fast=1",       # Disable transform skip fast mode
                "no-cu-lossless=1",      # Disable CU-level lossless coding mode
                
                # Additional speed optimizations for noisy content
                "no-cutree=1",           # Disable cutree (faster)
                "no-scenecut=1",         # Disable scenecut detection
                "keyint=60",             # GOP size
                "min-keyint=60",         # Minimum keyframe interval
                "ctu=32",                # Smaller CTU for faster encoding
                "max-tu-size=16",        # Smaller max TU size
                "qg-size=32",            # QP granularity
                
                # Parallel processing
                "frame-threads=0",       # Auto frame threads
                "pools=*",               # Use all CPU pools
                
                # Rate control for lossless
                "rc-lookahead=0",        # No lookahead (immediate encoding)
            ]
            
            if self.lossless:
                x265_params.append("lossless=1")
            
            self.codec.options = {
                "preset": "superfast",
                "tune": "zerolatency",
                "x265-params": ":".join(x265_params),
                "crf": "23" if self.lossless else str(self.crf),
                "threads": "4",
                "keyint": "60",
            }
            
            # Only set CRF if not lossless (lossless mode ignores CRF)
            if not self.lossless:
                self.codec.options["crf"] = str(self.crf)

        data_to_send = b""
        for package in self.codec.encode(frame):
            data_to_send += bytes(package)

        if data_to_send:
            yield from self._split_bitstream(data_to_send)

    def encode(
        self, frame: Frame, force_keyframe: bool = False
    ) -> tuple[list[bytes], int]:
        assert isinstance(frame, av.VideoFrame)
        packages = self._encode_frame(frame, force_keyframe)
        timestamp = convert_timebase(frame.pts, frame.time_base, VIDEO_TIME_BASE)
        return self._packetize(packages), timestamp

    def pack(self, packet: Packet) -> tuple[list[bytes], int]:
        assert isinstance(packet, av.Packet)
        packages = self._split_bitstream(bytes(packet))
        timestamp = convert_timebase(packet.pts, packet.time_base, VIDEO_TIME_BASE)
        return self._packetize(packages), timestamp

    @property
    def target_bitrate(self) -> int:
        """Not used for lossless encoding, but required by interface."""
        return 0

    @target_bitrate.setter
    def target_bitrate(self, bitrate: int) -> None:
        """Not used for lossless encoding."""
        pass


def h265_depayload(payload: bytes) -> bytes:
    """Extract H.265 NAL unit data from RTP payload."""
    descriptor, data = H265PayloadDescriptor.parse(payload)
    return data
