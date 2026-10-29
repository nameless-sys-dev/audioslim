#!/usr/bin/env bash
set -euo pipefail

# Directories
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${ROOT_DIR}/ffmpeg_build"
SOURCES_DIR="${BUILD_DIR}/sources"
PREFIX_DIR="${BUILD_DIR}/prefix"
TARGET_BIN_DIR="${ROOT_DIR}/src/audioslim/bin"

# Versions
LAME_VERSION="3.100"
OPUS_VERSION="1.5.2"
FFMPEG_VERSION="7.0.2"

# Detect CPU cores for parallel compilation
if command -v nproc >/dev/null 2>&1; then
    CORES=$(nproc)
elif command -v sysctl >/dev/null 2>&1; then
    CORES=$(sysctl -n hw.ncpu)
else
    CORES=4
fi

mkdir -p "${SOURCES_DIR}" "${PREFIX_DIR}" "${TARGET_BIN_DIR}"

export PATH="${PREFIX_DIR}/bin:${PATH}"
export PKG_CONFIG_PATH="${PREFIX_DIR}/lib/pkgconfig"

echo "=== [1/3] Building libmp3lame ${LAME_VERSION} (Static) ==="
cd "${SOURCES_DIR}"
if [ ! -f "lame-${LAME_VERSION}.tar.gz" ]; then
    curl -L -o "lame-${LAME_VERSION}.tar.gz" \
        "https://downloads.sourceforge.net/project/lame/lame/${LAME_VERSION}/lame-${LAME_VERSION}.tar.gz"
fi
tar -xzf "lame-${LAME_VERSION}.tar.gz"
cd "lame-${LAME_VERSION}"
./configure \
    --prefix="${PREFIX_DIR}" \
    --enable-static \
    --disable-shared \
    --disable-frontend \
    --disable-decoder \
    --with-pic
make -j"${CORES}"
make install

echo "=== [2/3] Building libopus ${OPUS_VERSION} (Static) ==="
cd "${SOURCES_DIR}"
if [ ! -f "opus-${OPUS_VERSION}.tar.gz" ]; then
    curl -L -o "opus-${OPUS_VERSION}.tar.gz" \
        "https://downloads.xiph.org/releases/opus/opus-${OPUS_VERSION}.tar.gz"
fi
tar -xzf "opus-${OPUS_VERSION}.tar.gz"
cd "opus-${OPUS_VERSION}"
./configure \
    --prefix="${PREFIX_DIR}" \
    --enable-static \
    --disable-shared \
    --disable-doc \
    --disable-extra-programs \
    --with-pic
make -j"${CORES}"
make install

echo "=== [3/3] Building Custom Audio-Only FFmpeg ${FFMPEG_VERSION} ==="
cd "${SOURCES_DIR}"
if [ ! -f "ffmpeg-${FFMPEG_VERSION}.tar.xz" ]; then
    curl -L -o "ffmpeg-${FFMPEG_VERSION}.tar.xz" \
        "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz"
fi
tar -xJf "ffmpeg-${FFMPEG_VERSION}.tar.xz"
cd "ffmpeg-${FFMPEG_VERSION}"

./configure \
    --prefix="${PREFIX_DIR}" \
    --pkg-config-flags="--static" \
    --extra-cflags="-I${PREFIX_DIR}/include -O3" \
    --extra-ldflags="-L${PREFIX_DIR}/lib" \
    --extra-libs="-lm -lpthread" \
    --enable-static \
    --disable-shared \
    --enable-small \
    \
    --disable-everything \
    --disable-autodetect \
    --disable-network \
    --disable-doc \
    --disable-htmlpages \
    --disable-manpages \
    --disable-podpages \
    --disable-txtpages \
    --disable-ffplay \
    --disable-ffprobe \
    --disable-avdevice \
    --disable-swscale \
    --disable-postproc \
    --disable-pixelutils \
    \
    --enable-ffmpeg \
    --enable-avcodec \
    --enable-avformat \
    --enable-avfilter \
    --enable-swresample \
    --enable-libmp3lame \
    --enable-libopus \
    \
    --enable-protocol=file,pipe \
    \
    --enable-demuxer=mp3,wav,mov,flac,ogg,concat \
    --enable-muxer=mp3,wav,ipod,mp4,flac,ogg,opus,null \
    \
    --enable-decoder=mp3,mp3float,aac,alac,flac,opus,libopus,pcm_s8,pcm_u8,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f64le \
    --enable-encoder=libmp3lame,aac,alac,flac,opus,libopus,pcm_s8,pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le \
    \
    --enable-parser=mpegaudio,aac,flac,opus \
    --enable-bsf=aac_adtstoasc \
    \
    --enable-filter=aresample,aformat,anull,atrim,asetpts,volume,afade,concat,amerge,pan,atempo,acrossfade

make -j"${CORES}"
make install

# Strip symbols to minimize binary size and copy to Python package
strip "${PREFIX_DIR}/bin/ffmpeg"
cp "${PREFIX_DIR}/bin/ffmpeg" "${TARGET_BIN_DIR}/ffmpeg"
chmod +x "${TARGET_BIN_DIR}/ffmpeg"

echo "=== Build Complete! ==="
ls -lh "${TARGET_BIN_DIR}/ffmpeg"