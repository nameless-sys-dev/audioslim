from .core import AudioMetadata, AudioTrack, get_ffmpeg_binary
from .exceptions import (
    BinaryNotFoundError,
    FFmpegExecutionError,
    AudioSlimError,
    UnsupportedFormatError,
)

__all__ = [
    "AudioTrack",
    "AudioMetadata",
    "get_ffmpeg_binary",
    "AudioSlimError",
    "BinaryNotFoundError",
    "UnsupportedFormatError",
    "FFmpegExecutionError",
]

__version__ = "0.1.0"