from __future__ import annotations

import copy
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Sequence, Union

from .exceptions import (
    BinaryNotFoundError,
    FFmpegExecutionError,
    AudioSlimError,
    UnsupportedFormatError,
)

SupportedFormat = Literal["mp3", "wav", "m4a", "flac", "opus"]
PathLike = Union[str, Path]


@dataclass(frozen=True)
class AudioMetadata:
    duration: float
    codec: str
    sample_rate: int
    channels: int
    bitrate_kbps: Optional[int]


def get_ffmpeg_binary() -> Path:
    """Locates the bundled custom FFmpeg executable."""
    exe_name = "ffmpeg.exe" if platform.system().lower() == "windows" else "ffmpeg"
    bin_path = Path(__file__).parent / "bin" / exe_name

    if not bin_path.is_file():
        raise BinaryNotFoundError(
            f"Bundled FFmpeg binary not found at '{bin_path}'. "
            "Please run './build_ffmpeg.sh' before using audioslim."
        )
    if not os.access(bin_path, os.X_OK):
        os.chmod(bin_path, 0o755)

    return bin_path


class AudioTrack:
    """
    Represents an audio file and a lazy chain of manipulations.
    All operations return a new AudioTrack instance and execute in a single pass upon .export().
    """

    SUPPORTED_FORMATS = {"mp3", "wav", "m4a", "flac", "opus"}

    def __init__(
        self,
        inputs: list[Path],
        metadata: AudioMetadata,
        filters: Optional[list[str]] = None,
        is_concat: bool = False,
        target_sample_rate: Optional[int] = None,
        target_channels: Optional[int] = None,
    ):
        self._inputs = inputs
        self._metadata = metadata
        self._filters = filters or []
        self._is_concat = is_concat
        self._target_sample_rate = target_sample_rate
        self._target_channels = target_channels

    @classmethod
    def from_file(cls, path: PathLike) -> AudioTrack:
        """Loads an audio file and probes its metadata."""
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        ext = file_path.suffix.lower().lstrip(".")
        if ext not in cls.SUPPORTED_FORMATS:
            raise UnsupportedFormatError(
                f"Input extension '.{ext}' is not supported. Supported: {cls.SUPPORTED_FORMATS}"
            )

        metadata = cls._probe(file_path)
        return cls(inputs=[file_path], metadata=metadata)

    @classmethod
    def concat(cls, tracks: Sequence[AudioTrack]) -> AudioTrack:
        """
        Concatenates multiple AudioTracks sequentially.
        Note: Any existing filters on the individual tracks must be exported first
        or applied after concatenation.
        """
        if len(tracks) < 2:
            raise AudioSlimError("At least two AudioTracks are required for concatenation.")

        inputs: list[Path] = []
        total_duration = 0.0

        for t in tracks:
            if t._filters or t._is_concat:
                raise AudioSlimError(
                    "Cannot directly concatenate tracks with unrendered filters. "
                    "Export intermediate tracks or apply manipulations after concat()."
                )
            inputs.extend(t._inputs)
            total_duration += t.duration

        base_meta = tracks[0].metadata
        combined_meta = AudioMetadata(
            duration=total_duration,
            codec=base_meta.codec,
            sample_rate=base_meta.sample_rate,
            channels=base_meta.channels,
            bitrate_kbps=base_meta.bitrate_kbps,
        )
        return cls(inputs=inputs, metadata=combined_meta, is_concat=True)

    @staticmethod
    def _probe(file_path: Path) -> AudioMetadata:
        """Uses `ffmpeg -i` stderr output to extract metadata without requiring ffprobe."""
        ffmpeg = get_ffmpeg_binary()
        cmd = [str(ffmpeg), "-hide_banner", "-i", str(file_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        output = proc.stderr

        # Parse Duration: 00:03:12.45
        dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        if not dur_match:
            raise FFmpegExecutionError("Failed to parse audio duration.", cmd, output)
        hours, mins, secs = map(float, dur_match.groups())
        duration = (hours * 3600.0) + (mins * 60.0) + secs

        # Parse Audio Stream info: Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 192 kb/s
        stream_match = re.search(
            r"Stream #\d+:\d+.*?: Audio:\s*([a-zA-Z0-9_]+).*?,\s*(\d+)\s*Hz,\s*([^,]+)",
            output,
        )
        if not stream_match:
            raise FFmpegExecutionError("No valid audio stream found in file.", cmd, output)

        codec = stream_match.group(1)
        sample_rate = int(stream_match.group(2))
        channel_str = stream_match.group(3).strip()

        if channel_str in ("mono", "1 channels", "1.0"):
            channels = 1
        elif channel_str in ("stereo", "2 channels", "2.0"):
            channels = 2
        else:
            ch_num = re.search(r"(\d+)", channel_str)
            channels = int(ch_num.group(1)) if ch_num else 2

        # Parse Bitrate
        br_match = re.search(r"bitrate:\s*(\d+)\s*kb/s", output)
        bitrate_kbps = int(br_match.group(1)) if br_match else None

        return AudioMetadata(
            duration=duration,
            codec=codec,
            sample_rate=sample_rate,
            channels=channels,
            bitrate_kbps=bitrate_kbps,
        )

    def _clone(
        self,
        new_filter: Optional[str] = None,
        new_duration: Optional[float] = None,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
    ) -> AudioTrack:
        """Creates a new AudioTrack instance with updated filter state."""
        filters = copy.copy(self._filters)
        if new_filter:
            filters.append(new_filter)

        meta = AudioMetadata(
            duration=new_duration if new_duration is not None else self._metadata.duration,
            codec=self._metadata.codec,
            sample_rate=sample_rate or self._metadata.sample_rate,
            channels=channels or self._metadata.channels,
            bitrate_kbps=self._metadata.bitrate_kbps,
        )
        return AudioTrack(
            inputs=copy.copy(self._inputs),
            metadata=meta,
            filters=filters,
            is_concat=self._is_concat,
            target_sample_rate=sample_rate or self._target_sample_rate,
            target_channels=channels or self._target_channels,
        )

    @property
    def metadata(self) -> AudioMetadata:
        return self._metadata

    @property
    def duration(self) -> float:
        return self._metadata.duration

    # -------------------------------------------------------------------------
    # Audio Manipulations
    # -------------------------------------------------------------------------

    def trim(self, start: float = 0.0, end: Optional[float] = None) -> AudioTrack:
        """Trims the audio between `start` and `end` (in seconds)."""
        if start < 0:
            raise ValueError("start time cannot be negative.")
        if end is not None and end <= start:
            raise ValueError("end time must be greater than start time.")

        actual_end = min(end, self.duration) if end is not None else self.duration
        new_duration = max(0.0, actual_end - start)

        if end is not None:
            f_str = f"atrim=start={start}:end={actual_end},asetpts=PTS-STARTPTS"
        else:
            f_str = f"atrim=start={start},asetpts=PTS-STARTPTS"

        return self._clone(new_filter=f_str, new_duration=new_duration)

    def volume_db(self, db: float) -> AudioTrack:
        """Adjusts volume by decibels (e.g., +3.5 or -6.0)."""
        return self._clone(new_filter=f"volume={db}dB")

    def volume_factor(self, factor: float) -> AudioTrack:
        """Adjusts volume by a linear multiplier (e.g., 0.5 for 50%, 2.0 for 200%)."""
        if factor < 0:
            raise ValueError("Volume factor cannot be negative.")
        return self._clone(new_filter=f"volume={factor}")

    def fade_in(self, duration: float) -> AudioTrack:
        """Applies a fade-in effect over `duration` seconds from the start."""
        if duration <= 0:
            raise ValueError("Fade duration must be positive.")
        return self._clone(new_filter=f"afade=t=in:st=0:d={duration}")

    def fade_out(self, duration: float) -> AudioTrack:
        """Applies a fade-out effect over the last `duration` seconds of the track."""
        if duration <= 0:
            raise ValueError("Fade duration must be positive.")
        start_time = max(0.0, self.duration - duration)
        return self._clone(new_filter=f"afade=t=out:st={start_time:.4f}:d={duration}")

    def speed(self, factor: float) -> AudioTrack:
        """
        Changes playback speed without altering pitch using the `atempo` filter.
        Automatically chains filters if factor is outside [0.5, 2.0].
        """
        if factor <= 0:
            raise ValueError("Speed factor must be strictly positive.")

        # Decompose factor into multiples within [0.5, 2.0] for maximum compatibility
        tempos = []
        rem = factor
        while rem > 2.0:
            tempos.append(2.0)
            rem /= 2.0
        while rem < 0.5:
            tempos.append(0.5)
            rem /= 0.5
        tempos.append(rem)

        filter_chain = ",".join(f"atempo={t:.4f}" for t in tempos)
        new_duration = self.duration / factor
        return self._clone(new_filter=filter_chain, new_duration=new_duration)

    def resample(self, sample_rate: int) -> AudioTrack:
        """Changes the audio sample rate (in Hz, e.g., 44100, 48000)."""
        if sample_rate <= 0:
            raise ValueError("Sample rate must be positive.")
        return self._clone(new_filter=f"aresample={sample_rate}", sample_rate=sample_rate)

    def set_channels(self, channels: int) -> AudioTrack:
        """Sets the number of audio channels (e.g., 1 for mono, 2 for stereo)."""
        if channels < 1 or channels > 8:
            raise ValueError("Channels must be between 1 and 8.")
        return self._clone(channels=channels)

    # -------------------------------------------------------------------------
    # Export & Encoding
    # -------------------------------------------------------------------------

    def export(
        self,
        output_path: PathLike,
        format: Optional[SupportedFormat] = None,
        bitrate: Optional[str] = None,
        lossless: bool = False,
        pcm_bit_depth: Literal[16, 24, 32] = 16,
    ) -> Path:
        """
        Executes the manipulation pipeline and writes the output file.

        :param output_path: Destination file path.
        :param format: Explicit format ('mp3', 'wav', 'm4a', 'flac', 'opus'). Inferred from extension if omitted.
        :param bitrate: Target bitrate for lossy formats (e.g., '192k', '128k', '320k').
        :param lossless: When format is 'm4a', setting lossless=True encodes using ALAC instead of AAC.
        :param pcm_bit_depth: Bit depth when exporting to 'wav' (16, 24, or 32).
        """
        out_path = Path(output_path).resolve()
        fmt = (format or out_path.suffix.lstrip(".")).lower()

        if fmt not in self.SUPPORTED_FORMATS:
            raise UnsupportedFormatError(
                f"Unsupported export format '{fmt}'. Supported: {self.SUPPORTED_FORMATS}"
            )

        ffmpeg = get_ffmpeg_binary()
        cmd = [str(ffmpeg), "-hide_banner", "-y"]

        # 1. Add Input(s)
        for inp in self._inputs:
            cmd.extend(["-i", str(inp)])

        # 2. Construct Filter Graph
        if self._is_concat:
            n = len(self._inputs)
            in_streams = "".join(f"[{i}:a]" for i in range(n))
            concat_filter = f"{in_streams}concat=n={n}:v=0:a=1"
            if self._filters:
                full_graph = f"{concat_filter}[cat];[cat]{','.join(self._filters)}[outa]"
            else:
                full_graph = f"{concat_filter}[outa]"
            cmd.extend(["-filter_complex", full_graph, "-map", "[outa]"])
        elif self._filters:
            cmd.extend(["-af", ",".join(self._filters)])

        # 3. Channel & Sample Rate Overrides
        if self._target_channels:
            cmd.extend(["-ac", str(self._target_channels)])
        if self._target_sample_rate:
            cmd.extend(["-ar", str(self._target_sample_rate)])

        # 4. Codec & Container Mapping
        if fmt == "mp3":
            cmd.extend(["-f", "mp3", "-c:a", "libmp3lame", "-b:a", bitrate or "192k"])

        elif fmt == "wav":
            pcm_map = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_s32le"}
            if pcm_bit_depth not in pcm_map:
                raise ValueError("pcm_bit_depth must be 16, 24, or 32.")
            cmd.extend(["-f", "wav", "-c:a", pcm_map[pcm_bit_depth]])

        elif fmt == "m4a":
            if lossless:
                cmd.extend(["-f", "ipod", "-c:a", "alac"])
            else:
                cmd.extend(["-f", "ipod", "-c:a", "aac", "-b:a", bitrate or "192k"])

        elif fmt == "flac":
            cmd.extend(["-f", "flac", "-c:a", "flac"])

        elif fmt == "opus":
            # libopus requires specific sample rates (48000, 24000, 16000, 12000, 8000)
            if not self._target_sample_rate:
                cmd.extend(["-ar", "48000"])
            cmd.extend(["-f", "opus", "-c:a", "libopus", "-b:a", bitrate or "128k"])

        # Disable video/data streams explicitly
        cmd.extend(["-vn", "-dn", "-sn", str(out_path)])

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise FFmpegExecutionError(
                f"Failed to export audio to '{out_path}'.", cmd, proc.stderr
            )

        return out_path