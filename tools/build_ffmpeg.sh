#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 FFMPEG_SOURCE.tar.xz LAME_SOURCE.tar.gz OPUS_SOURCE.tar.gz" >&2
    exit 2
fi

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This build recipe targets native Linux builds." >&2
    exit 1
fi

for tool in cc make pkg-config tar python3; do
    command -v "$tool" >/dev/null || {
        echo "Missing build tool: $tool" >&2
        exit 1
    }
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$ROOT" in
    *[[:space:]]*)
        echo "Use a checkout path without whitespace for the native build." >&2
        exit 1
        ;;
esac

ARCHIVES=()
for archive in "$@"; do
    absolute="$(
        python3 -c \
            'import pathlib, sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve(strict=True))' \
            "$archive"
    )"

    [[ -f "$absolute" ]] || {
        echo "Not a source archive: $absolute" >&2
        exit 1
    }

    ARCHIVES+=("$absolute")
done

mkdir -p "$ROOT/.native"
WORK="$(mktemp -d "$ROOT/.native/build.XXXXXXXX")"
PREFIX="$WORK/prefix"
BIN="$ROOT/src/audioslim/_bin"
NOTICES="$ROOT/src/audioslim/_licenses"

mkdir -p "$PREFIX" "$BIN" "$NOTICES"

JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"
NAMES=(ffmpeg lame opus)

for index in 0 1 2; do
    name="${NAMES[$index]}"
    mkdir -p "$WORK/$name"

    tar --no-same-owner \
        -xf "${ARCHIVES[$index]}" \
        --strip-components=1 \
        -C "$WORK/$name"

    [[ -f "$WORK/$name/configure" ]] || {
        echo "$name archive must be an official release with configure." >&2
        exit 1
    }
done

export CC="${CC:-cc}"
export CFLAGS="${CFLAGS:--O2 -fPIC}"

# Only our locally built codec libraries are visible through pkg-config.
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"

echo "Building static LAME..."
(
    cd "$WORK/lame"
    ./configure \
        --prefix="$PREFIX" \
        --libdir="$PREFIX/lib" \
        --enable-static \
        --disable-shared \
        --disable-frontend \
        --disable-decoder

    make -j"$JOBS"
    make install
)

echo "Building static Opus..."
(
    cd "$WORK/opus"
    ./configure \
        --prefix="$PREFIX" \
        --libdir="$PREFIX/lib" \
        --enable-static \
        --disable-shared \
        --disable-extra-programs \
        --disable-doc

    make -j"$JOBS"
    make install
)

PCM="pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le"
FILTERS="abuffer,abuffersink,aformat,anull,aresample,atrim,asetpts,volume,afade,concat,amix"

echo "Building allow-listed FFmpeg..."
(
    cd "$WORK/ffmpeg"

    ./configure \
        --prefix="$PREFIX" \
        --cc="$CC" \
        --pkg-config-flags=--static \
        --extra-cflags="-I$PREFIX/include" \
        --extra-ldflags="-L$PREFIX/lib" \
        --disable-everything \
        --disable-autodetect \
        --disable-programs \
        --enable-ffmpeg \
        --disable-shared \
        --enable-static \
        --enable-pic \
        --enable-pthreads \
        --enable-small \
        --disable-debug \
        --disable-doc \
        --disable-network \
        --disable-avdevice \
        --disable-postproc \
        --disable-swscale \
        --disable-gpl \
        --disable-version3 \
        --disable-nonfree \
        --enable-avutil \
        --enable-avcodec \
        --enable-avformat \
        --enable-avfilter \
        --enable-swresample \
        --enable-libmp3lame \
        --enable-libopus \
        --enable-protocol=file \
        --enable-demuxer=mp3,wav,mov,flac,ogg \
        --enable-muxer=mp3,wav,ipod,flac,opus \
        --enable-parser=mpegaudio,aac,flac,opus \
        --enable-decoder="mp3float,aac,alac,flac,libopus,$PCM" \
        --enable-encoder="libmp3lame,aac,alac,flac,libopus,$PCM" \
        --enable-filter="$FILTERS"

    make -j"$JOBS"
)

install -m 0755 "$WORK/ffmpeg/ffmpeg" "$BIN/ffmpeg"

# Ship the actual upstream license texts, not summaries.
cp "$WORK/ffmpeg/COPYING.LGPLv2.1" \
    "$NOTICES/FFmpeg-LGPL-2.1.txt"
cp "$WORK/lame/COPYING" \
    "$NOTICES/LAME-COPYING.txt"
cp "$WORK/opus/COPYING" \
    "$NOTICES/Opus-COPYING.txt"

for name in ffmpeg lame opus; do
    if [[ -f "$WORK/$name/AUTHORS" ]]; then
        cp "$WORK/$name/AUTHORS" "$NOTICES/$name-AUTHORS.txt"
    fi
done

cp "$ROOT/tools/build_ffmpeg.sh" "$NOTICES/build_ffmpeg.sh"
cp "$WORK/ffmpeg/ffbuild/config.mak" "$NOTICES/ffmpeg-config.mak"

"$BIN/ffmpeg" -version > "$NOTICES/BUILD.txt" 2>&1

# Record provenance. These hashes are records, not authentication:
# verify source signatures/checksums before running this script.
python3 - "${ARCHIVES[@]}" >> "$NOTICES/BUILD.txt" <<'PY'
import hashlib
import pathlib
import sys

print("\nSource archive SHA-256 values:")
for filename in sys.argv[1:]:
    path = pathlib.Path(filename)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    print(digest.hexdigest(), path.name)
PY

# Capture the actual result, including dependency-selected components.
for capability in encoders decoders muxers demuxers filters protocols; do
    "$BIN/ffmpeg" -hide_banner "-$capability" \
        > "$NOTICES/$capability.txt" 2>&1
done

echo
echo "Bundled executable: $BIN/ffmpeg"
echo "Build records:      $NOTICES"
echo "Native build tree:  $WORK"
echo
echo "The build tree is retained for inspection and relinking."
echo "Keep the exact source archives and satisfy upstream license"
echo "requirements when distributing the executable."