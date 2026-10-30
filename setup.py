import os
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel


class NativeDistribution(Distribution):
    def has_ext_modules(self):
        return True


class PlatformWheel(bdist_wheel):
    def get_tag(self):
        _, _, platform = super().get_tag()
        return "py3", "none", platform


class CheckedBuild(build_py):
    def run(self):
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        binary = (
            Path(__file__).parent
            / "src"
            / "audioslim"
            / "_bin"
            / name
        )
        if not binary.is_file():
            raise RuntimeError(
                "Bundled FFmpeg is missing. Run tools/build_ffmpeg.sh first."
            )
        super().run()


setup(
    distclass=NativeDistribution,
    cmdclass={
        "bdist_wheel": PlatformWheel,
        "build_py": CheckedBuild,
    },
    zip_safe=False,
)