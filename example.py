import math
import struct
import tempfile
import wave
from pathlib import Path

from slim_audio import AudioTrack, get_ffmpeg_binary


def create_test_sine_wav(filepath: Path, duration_sec: float = 5.0, freq: float = 440.0):
    """Generates a standard 16-bit 44.1kHz stereo sine wave WAV file for testing."""
    sample_rate = 44100
    num_samples = int(duration_sec * sample_rate)
    with wave.open(str(filepath), "w") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(num_samples):
            val = int(16000.0 * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
            data = struct.pack("<hh", val, val)
            wav_file.writeframesraw(data)


def main():
    print(f"Using custom FFmpeg binary at: {get_ffmpeg_binary()}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        source_wav = tmp / "input.wav"
        create_test_sine_wav(source_wav, duration_sec=6.0)

        # 1. Load and inspect metadata
        track = AudioTrack.from_file(source_wav)
        print(f"Loaded Input: {track.metadata}")

        # 2. Chain Manipulations (Single-pass lazy evaluation)
        edited = (
            track.trim(start=1.0, end=5.0)  # 4.0s duration
            .speed(1.25)                    # 3.2s duration
            .volume_db(-3.0)                # Reduce volume by 3dB
            .fade_in(0.5)                   # 0.5s fade in
            .fade_out(0.5)                  # 0.5s fade out (automatically starts at 2.7s)
            .resample(48000)                # Resample to 48kHz
            .set_channels(1)                # Downmix to Mono
        )

        # 3. Export across all supported formats
        outputs = {
            "MP3": edited.export(tmp / "out.mp3", bitrate="192k"),
            "WAV (24-bit)": edited.export(tmp / "out.wav", pcm_bit_depth=24),
            "M4A (Lossy AAC)": edited.export(tmp / "out_aac.m4a", bitrate="160k", lossless=False),
            "M4A (Lossless ALAC)": edited.export(tmp / "out_alac.m4a", lossless=True),
            "FLAC": edited.export(tmp / "out.flac"),
            "OPUS": edited.export(tmp / "out.opus", bitrate="96k"),
        }

        print("\n--- Exported Formats Verification ---")
        for label, out_path in outputs.items():
            reprobed = AudioTrack.from_file(out_path)
            print(
                f"{label:<22} | Size: {out_path.stat().st_size:>6} B | "
                f"Codec: {reprobed.metadata.codec:<10} | "
                f"Dur: {reprobed.duration:.2f}s | "
                f"SR: {reprobed.metadata.sample_rate}Hz | "
                f"Ch: {reprobed.metadata.channels}"
            )

        # 4. Test Concatenation
        part1 = AudioTrack.from_file(outputs["FLAC"])
        part2 = AudioTrack.from_file(outputs["WAV (24-bit)"])
        merged = AudioTrack.concat([part1, part2]).fade_out(1.0)
        merged_path = merged.export(tmp / "merged.mp3")
        merged_probed = AudioTrack.from_file(merged_path)
        print(f"\nMerged Track Duration: {merged_probed.duration:.2f}s (Expected ~6.40s)")


if __name__ == "__main__":
    main()