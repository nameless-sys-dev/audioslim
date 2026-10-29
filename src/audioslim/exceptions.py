class AudioSlimError(Exception):
    """Base exception for audioslim errors."""


class BinaryNotFoundError(AudioSlimError):
    """Raised when the bundled FFmpeg executable is missing."""


class UnsupportedFormatError(AudioSlimError):
    """Raised when an unsupported audio format or codec is requested."""


class FFmpegExecutionError(AudioSlimError):
    """Raised when the FFmpeg subprocess fails."""
    def __init__(self, message: str, command: list[str], stderr: str):
        super().__init__(f"{message}\nCommand: {' '.join(command)}\nError Output:\n{stderr}")
        self.command = command
        self.stderr = stderr