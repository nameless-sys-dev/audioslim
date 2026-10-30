from __future__ import annotations

import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PathLike = str | os.PathLike[str]


class AudioError(RuntimeError):
    """Bundled FFmpeg could not start or could not process the audio."""


def _number(value: float, name: str, minimum: float | None = None) -> float:
    value = float(value)

    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")

    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")

    return value


@dataclass(frozen=True)
class ExportOptions:
    """
    Output settings.

    codec:
        Normally inferred from the destination extension.
        Use "alac" for lossless M4A, or a PCM codec for WAV.

    bitrate:
        Bits per second, for MP3, AAC, or Opus only.

    sample_rate/channels:
        None leaves selection to FFmpeg and the encoder.
        Explicit channel conversion supports mono or stereo.

    overwrite:
        False prevents replacing an existing destination.

    timeout:
        Maximum FFmpeg execution time in seconds; None means no limit.
    """

    codec: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    overwrite: bool = False
    timeout: float | None = None

    def __post_init__(self):
        for name in ("bitrate", "sample_rate"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not int or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")

        if self.channels is not None and (
            type(self.channels) is not int or self.channels not in (1, 2)
        ):
            raise ValueError("channels must be None, 1, or 2")

        if type(self.overwrite) is not bool:
            raise ValueError("overwrite must be a boolean")

        if self.timeout is not None:
            timeout = _number(self.timeout, "timeout", 0)
            if timeout == 0:
                raise ValueError("timeout must be positive")
            object.__setattr__(self, "timeout", timeout)


_DEFAULT = ExportOptions()

_PCM_CODECS = {
    name: name
    for name in (
        "pcm_u8",
        "pcm_s16le",
        "pcm_s24le",
        "pcm_s32le",
        "pcm_f32le",
        "pcm_f64le",
    )
}

# extension -> (muxer, default public codec name, allowed encoder mappings)
_FORMATS = {
    ".mp3": ("mp3", "mp3", {"mp3": "libmp3lame"}),
    ".wav": ("wav", "pcm_s16le", _PCM_CODECS),
    ".m4a": ("ipod", "aac", {"aac": "aac", "alac": "alac"}),
    ".flac": ("flac", "flac", {"flac": "flac"}),
    ".opus": ("opus", "opus", {"opus": "libopus"}),
}

_DEFAULT_BITRATES = {
    "mp3": 192_000,
    "aac": 192_000,
    "opus": 128_000,
}


def ffmpeg_path() -> Path:
    """Return the bundled executable, without searching PATH."""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    binary = Path(__file__).resolve().parent / "_bin" / name

    if not binary.is_file():
        raise AudioError(
            "Bundled FFmpeg is missing. Run tools/build_ffmpeg.sh "
            "before installing or building the package."
        )

    if os.name != "nt" and not os.access(binary, os.X_OK):
        raise AudioError(f"Bundled FFmpeg is not executable: {binary}")

    return binary


def _encoding_args(destination: Path, options: ExportOptions) -> list[str]:
    extension = destination.suffix.lower()

    if extension not in _FORMATS:
        raise ValueError(
            f"Unsupported output extension {extension!r}; "
            f"choose one of {', '.join(_FORMATS)}"
        )

    muxer, default_codec, encoders = _FORMATS[extension]
    codec = default_codec if options.codec is None else options.codec

    if codec not in encoders:
        raise ValueError(
            f"Codec {codec!r} is not supported for {extension}; "
            f"choose one of {', '.join(encoders)}"
        )

    args = ["-c:a", encoders[codec]]

    if codec in _DEFAULT_BITRATES:
        bitrate = options.bitrate or _DEFAULT_BITRATES[codec]
        args += ["-b:a", str(bitrate)]
    elif options.bitrate is not None:
        raise ValueError("bitrate applies only to MP3, AAC, and Opus")

    if options.sample_rate is not None:
        args += ["-ar", str(options.sample_rate)]

    if options.channels is not None:
        args += ["-ac", str(options.channels)]

    if muxer == "ipod":
        args += ["-movflags", "+faststart"]

    # The temporary output does not have the destination's extension,
    # so the muxer must always be explicit.
    args += ["-f", muxer]
    return args


def _render(
    sources: Iterable[PathLike],
    destination: PathLike,
    options: ExportOptions,
    *,
    audio_filter: str | None = None,
    graph: str | None = None,
) -> Path:
    inputs = [
        Path(source).expanduser().resolve(strict=True)
        for source in sources
    ]

    if not inputs:
        raise ValueError("At least one input is required")

    for source in inputs:
        if not source.is_file():
            raise ValueError(f"Input is not a regular file: {source}")

    # Do not resolve the final filename: replacing an output symlink
    # should replace the link, rather than overwrite its target.
    output = Path(destination).expanduser().absolute()
    encoding_args = _encoding_args(output, options)

    if not output.parent.is_dir():
        raise FileNotFoundError(f"Output directory does not exist: {output.parent}")

    if not options.overwrite and os.path.lexists(output):
        raise FileExistsError(f"Destination already exists: {output}")

    command = [
        str(ffmpeg_path()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",  # Only overwrites our private temporary file.
    ]

    for source in inputs:
        command += ["-protocol_whitelist", "file", "-i", str(source)]

    if graph is not None:
        command += ["-filter_complex", graph, "-map", "[out]"]
    else:
        command += ["-map", "0:a:0"]
        if audio_filter is not None:
            command += ["-af", audio_filter]

    command += [
        "-vn",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_metadata:s:a",
        "-1",
        "-map_chapters",
        "-1",
    ]
    command += encoding_args

    # Write beside the destination so publication stays on one filesystem.
    fd, temporary_name = tempfile.mkstemp(
        prefix=".audioslim-",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)

    try:
        try:
            result = subprocess.run(
                command + [str(temporary)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=options.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AudioError("FFmpeg exceeded the configured timeout") from exc
        except OSError as exc:
            raise AudioError(
                "Could not execute bundled FFmpeg. Check its architecture, "
                "permissions, and operating-system runtime requirements."
            ) from exc

        if result.returncode != 0:
            details = result.stderr[-8000:].strip()
            raise AudioError(
                f"FFmpeg exited with status {result.returncode}:\n{details}"
            )

        if options.overwrite:
            os.replace(temporary, output)
        else:
            # Atomic no-clobber publication: also handles another process
            # creating the destination while FFmpeg was running.
            os.link(temporary, output)

        return output
    finally:
        temporary.unlink(missing_ok=True)


def convert(
    source: PathLike,
    destination: PathLike,
    *,
    options: ExportOptions = _DEFAULT,
) -> Path:
    """Decode and encode the first audio stream."""
    return _render([source], destination, options)


def trim(
    source: PathLike,
    destination: PathLike,
    *,
    start: float = 0,
    duration: float | None = None,
    options: ExportOptions = _DEFAULT,
) -> Path:
    """Trim by seconds; duration=None retains everything after start."""
    start = _number(start, "start", 0)
    settings = [f"start={start:.9f}"]

    if duration is not None:
        duration = _number(duration, "duration", 0)
        if duration == 0:
            raise ValueError("duration must be positive")
        settings.append(f"duration={duration:.9f}")

    audio_filter = (
        "atrim=" + ":".join(settings) + ",asetpts=PTS-STARTPTS"
    )
    return _render(
        [source], destination, options, audio_filter=audio_filter
    )


def gain(
    source: PathLike,
    destination: PathLike,
    *,
    db: float,
    options: ExportOptions = _DEFAULT,
) -> Path:
    """Apply gain in decibels. Positive gain can cause clipping."""
    db = _number(db, "db")
    return _render(
        [source],
        destination,
        options,
        audio_filter=f"volume={db:.9f}dB",
    )


def fade(
    source: PathLike,
    destination: PathLike,
    *,
    fade_in: float = 0,
    fade_out_start: float | None = None,
    fade_out: float = 0,
    options: ExportOptions = _DEFAULT,
) -> Path:
    """
    Apply linear fades, with all times in seconds.

    fade_out_start is explicit because this library does not bundle
    FFprobe or perform a separate duration-probing pass.
    """
    fade_in = _number(fade_in, "fade_in", 0)
    fade_out = _number(fade_out, "fade_out", 0)
    filters = ["asetpts=PTS-STARTPTS"]

    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.9f}")

    if fade_out > 0:
        if fade_out_start is None:
            raise ValueError("fade_out_start is required for a fade-out")

        start = _number(fade_out_start, "fade_out_start", 0)
        filters.append(
            f"afade=t=out:st={start:.9f}:d={fade_out:.9f}"
        )
    elif fade_out_start is not None:
        raise ValueError("fade_out must be positive when fade_out_start is set")

    return _render(
        [source],
        destination,
        options,
        audio_filter=",".join(filters),
    )


def _combine(
    sources: Iterable[PathLike],
    destination: PathLike,
    options: ExportOptions,
    *,
    mixing: bool,
    normalize: bool = True,
) -> Path:
    if isinstance(sources, (str, os.PathLike)):
        raise TypeError("Pass an iterable of input paths, not one path")

    sources = tuple(sources)
    if not sources:
        raise ValueError("At least one input is required")

    # All inputs must have matching audio parameters before concat/amix.
    rate = options.sample_rate or 48_000
    channels = options.channels or 2
    layout = "mono" if channels == 1 else "stereo"

    chains = []
    for index in range(len(sources)):
        chains.append(
            f"[{index}:a:0]"
            f"aresample={rate},"
            f"aformat=sample_fmts=fltp:"
            f"sample_rates={rate}:channel_layouts={layout},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )

    labels = "".join(f"[a{index}]" for index in range(len(sources)))

    if mixing:
        operation = (
            f"amix=inputs={len(sources)}:"
            f"duration=longest:dropout_transition=0:"
            f"normalize={int(normalize)}"
        )
    else:
        operation = f"concat=n={len(sources)}:v=0:a=1"

    chains.append(f"{labels}{operation}[out]")

    return _render(
        sources,
        destination,
        options,
        graph=";".join(chains),
    )


def concatenate(
    sources: Iterable[PathLike],
    destination: PathLike,
    *,
    options: ExportOptions = _DEFAULT,
) -> Path:
    """Join inputs end-to-end, using 48 kHz stereo unless overridden."""
    return _combine(
        sources, destination, options, mixing=False
    )


def mix(
    sources: Iterable[PathLike],
    destination: PathLike,
    *,
    normalize: bool = True,
    options: ExportOptions = _DEFAULT,
) -> Path:
    """
    Mix inputs from time zero and retain the longest duration.

    normalize=True scales the mix by the active input weights.
    normalize=False sums inputs directly and can cause clipping.
    """
    if type(normalize) is not bool:
        raise ValueError("normalize must be a boolean")

    return _combine(
        sources,
        destination,
        options,
        mixing=True,
        normalize=normalize,
    )