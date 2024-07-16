from enum import Enum


class CodeDisplayLevel(Enum):
    """Enum to represent the display level"""
    SIGNATURE = "signature"
    MINIMAL = "minimal"
    MODERATE = "moderate"
    FULL = "full"

class LineNumberMode(Enum):
    """Enum to represent the line number mode"""
    ENABLED = "enabled"
    DISABLED = "disabled"



