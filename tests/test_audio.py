import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from audioslim import (
    AudioError,
    ExportOptions,
    concatenate,
    convert,
    fade,
    gain,
    mix,
    trim,
)


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.root = Path(self.temporary.name)
        self.source = self.root / "source with spaces.wav"
        self.rate = 48_000

        self.pcm = b"".join(
            struct.pack(
                "<h",
                int(12_000 * math.sin(2 * math.pi * 440 * i / self.rate)),
            )
            for i in range(self.rate)
        )

        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.rate)
            output.writeframes(self.pcm)

    def read_wav(self, path):
        with wave.open(str(path), "rb") as source:
            return (
                source.getframerate(),
                source.getnchannels(),
                source.getnframes(),
                source.readframes(source.getnframes()),
            )

    def test_formats(self):
        cases = [
            ("audio.mp3", ExportOptions(), False),
            ("audio.wav", ExportOptions(), True),
            ("pcm24.wav", ExportOptions(codec="pcm_s24le"), True),
            ("float.wav", ExportOptions(codec="pcm_f32le"), True),
            ("aac.m4a", ExportOptions(codec="aac"), False),
            ("alac.m4a", ExportOptions(codec="alac"), True),
            ("audio.flac", ExportOptions(), True),
            ("audio.opus", ExportOptions(), False),
        ]

        for index, (filename, options, lossless) in enumerate(cases):
            with self.subTest(filename=filename):
                encoded = self.root / filename
                decoded = self.root / f"decoded-{index}.wav"

                convert(self.source, encoded, options=options)
                convert(
                    encoded,
                    decoded,
                    options=ExportOptions(
                        sample_rate=self.rate,
                        channels=1,
                    ),
                )

                rate, channels, frames, pcm = self.read_wav(decoded)
                self.assertEqual((rate, channels), (self.rate, 1))
                self.assertGreater(frames, 0)

                if lossless:
                    self.assertEqual(pcm, self.pcm)

    def test_manipulation(self):
        cut = trim(
            self.source,
            self.root / "cut.wav",
            start=0.1,
            duration=0.25,
        )
        quiet = gain(cut, self.root / "quiet.wav", db=-6)
        faded = fade(
            quiet,
            self.root / "faded.wav",
            fade_in=0.02,
            fade_out_start=0.20,
            fade_out=0.05,
        )

        options = ExportOptions(sample_rate=self.rate, channels=1)

        joined = concatenate(
            [faded, faded],
            self.root / "joined.wav",
            options=options,
        )
        mixed = mix(
            [faded, faded],
            self.root / "mixed.wav",
            options=options,
        )

        self.assertAlmostEqual(self.read_wav(cut)[2], 12_000, delta=1)
        self.assertAlmostEqual(self.read_wav(joined)[2], 24_000, delta=1)
        self.assertAlmostEqual(self.read_wav(mixed)[2], 12_000, delta=1)

    def test_no_overwrite(self):
        original = self.source.read_bytes()

        with self.assertRaises(FileExistsError):
            convert(self.source, self.source)

        self.assertEqual(self.source.read_bytes(), original)

    def test_failed_conversion_does_not_publish_output(self):
        broken = self.root / "broken.bin"
        destination = self.root / "bad.wav"
        broken.write_bytes(b"not an audio file")

        with self.assertRaises(AudioError):
            convert(broken, destination)

        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()