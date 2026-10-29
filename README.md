# NOTICE ⚠
I haven't been able to build and test this library because I just started developing it today, and FFmpeg's [website](https://www.ffmpeg.org/) is [currently down](https://downforeveryoneorjustme.com/ffmpeg.org). I will build and test it once FFmpeg is back up. This is as of 8:57 a.m. EST on October 29, 2026. - Alex

# Audioslim

A file-based audio manipulation library using a bundled, allow-listed
FFmpeg executable. Python 3.10+ is required. There are no runtime Python
dependencies and no system FFmpeg fallback.

## Supported formats

| Extension | Audio | Default encoding |
|---|---|---|
| `.mp3` | MP3 | LAME, 192 kbit/s |
| `.wav` | PCM WAV | Signed 16-bit little-endian PCM |
| `.m4a` | AAC or ALAC | Native AAC-LC, 192 kbit/s |
| `.flac` | FLAC | Native FLAC |
| `.opus` | Ogg Opus | libopus, 128 kbit/s |

WAV support includes unsigned 8-bit PCM, signed 16/24/32-bit little-endian
PCM, and 32/64-bit floating-point PCM. Arbitrary codecs carried in WAV,
such as ADPCM, are not included.

Opus uses the Ogg container, not WebM. Encrypted/DRM media is not supported.

## Build

The supplied native build recipe targets Linux.

Install build prerequisites, for example on Debian/Ubuntu:

```sh
sudo apt-get update
sudo apt-get install \
    build-essential pkg-config nasm xz-utils python3 python3-venv
```

Obtain and verify official release source archives:

- FFmpeg: https://ffmpeg.org/download.html
- LAME: https://lame.sourceforge.io/
- Opus: https://opus-codec.org/downloads/

Use a maintained patched FFmpeg release with the 7.x configure interface,
LAME 3.100, and an appropriate maintained Opus release. Use release
archives containing `configure`, rather than unprepared source snapshots.

Then run:

```sh
bash tools/build_ffmpeg.sh \
    /path/to/ffmpeg-release.tar.xz \
    /path/to/lame-release.tar.gz \
    /path/to/opus-release.tar.gz

python3 -m venv .venv
. .venv/bin/activate

python -m pip install build
python -m pip install -e .
python -m unittest discover -s tests
python -m build --wheel
```

The build creates `src/audioslim/_bin/ffmpeg`, copies third-party license
texts, and records source hashes and enabled FFmpeg components.

LAME, Opus, and FFmpeg libraries are linked statically into the executable.
The normal operating-system C runtime remains dynamic.

Build on an appropriate baseline system for each supported architecture
and C runtime. The resulting wheel is platform-specific, not
`py3-none-any`. A distributable manylinux wheel requires a compatible
build environment and auditing; do not simply rename the wheel.

## Examples

```python
from audioslim import (
    ExportOptions,
    concatenate,
    convert,
    fade,
    gain,
    mix,
    trim,
)

# Format conversion.
convert("input.wav", "output.mp3")

# Lossy AAC versus lossless ALAC in M4A.
convert("input.flac", "aac.m4a")
convert(
    "input.flac",
    "alac.m4a",
    options=ExportOptions(codec="alac"),
)

# Choose WAV precision explicitly.
convert(
    "input.flac",
    "output.wav",
    options=ExportOptions(codec="pcm_s24le"),
)

# Resample, downmix, and encode.
convert(
    "input.wav",
    "speech.opus",
    options=ExportOptions(
        bitrate=96_000,
        sample_rate=48_000,
        channels=1,
    ),
)

# Trim eight seconds beginning at five seconds.
trim("input.flac", "clip.flac", start=5, duration=8)

# Reduce gain and apply fades.
gain("clip.flac", "quiet.flac", db=-6)
fade(
    "quiet.flac",
    "faded.flac",
    fade_in=0.1,
    fade_out_start=7.5,
    fade_out=0.5,
)

# Join inputs, converting them to a common format first.
concatenate(
    ["first.flac", "second.m4a"],
    "joined.mp3",
    options=ExportOptions(sample_rate=48_000, channels=2),
)

# Simultaneous playback, retaining the longest input duration.
mix(["voice.wav", "music.flac"], "mixed.wav", normalize=True)

# Explicit overwrite and execution timeout.
convert(
    "input.flac",
    "output.mp3",
    options=ExportOptions(overwrite=True, timeout=120),
)
```

## Behavior and limitations

- Operations use the first audio stream from each input.
- Every operation decodes and re-encodes; there is no stream-copy API.
- Artwork, video, subtitles, chapters, and input metadata are not preserved.
- AAC, MP3, and Opus encoding is lossy.
- ALAC and FLAC are lossless codecs, but resampling, channel conversion,
  effects, or reducing PCM precision are not bit-preserving operations.
- WAV defaults to 16-bit PCM. Select a different PCM codec when needed.
- Concatenation and mixing use float32 audio at 48 kHz stereo unless
  sample rate/channels are overridden.
- Encoder-specific sample-rate and channel restrictions still apply.
- Fade-out start time is explicit; FFprobe is deliberately not bundled.
- Destination directories must already exist.
- Output is first written to a temporary file. Failed conversions do not
  replace the destination.
- `overwrite=False` uses atomic hard-link publication and therefore
  requires a filesystem supporting hard links. `overwrite=True` uses
  atomic replacement.
- Positive gain and unnormalized mixing can clip.
- FFmpeg processing of untrusted uploads should still be sandboxed and
  resource-limited. Disabling networking is not a complete sandbox.

## Redistribution

The build avoids GPL-only and nonfree FFmpeg options, but bundled
components still have license obligations:

- FFmpeg: LGPL, as identified by the built executable and copied license.
- LAME: LGPL.
- Opus: BSD-style license and associated notices.

The build copies their actual license texts into `_licenses`.

Those files alone do not necessarily satisfy all redistribution
requirements, particularly for static linking. Retain and provide the
required corresponding source and build/relink materials, and satisfy the
specific terms of the versions distributed. The build script leaves its
native build tree intact for this purpose.