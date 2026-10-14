"""System binary locator for ffmpeg, ffprobe, tesseract with WinGet / standard Windows path fallback."""
import os
import shutil
from pathlib import Path


def find_system_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        # Check WinGet packages if PATH has not been reloaded in the current process
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            winget_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if winget_dir.exists():
                for candidate in winget_dir.glob(f"**/{name}.exe"):
                    bin_dir = str(candidate.parent)
                    current_path = os.environ.get("PATH", "")
                    if bin_dir not in current_path:
                        os.environ["PATH"] = bin_dir + os.pathsep + current_path
                    return str(candidate)
        # Check standard installation directories
        common_paths = [
            Path("C:/Program Files/Tesseract-OCR"),
            Path("C:/Program Files/ffmpeg/bin"),
            Path("C:/ffmpeg/bin"),
            Path("C:/ProgramData/chocolatey/bin"),
        ]
        for c in common_paths:
            exe = c / f"{name}.exe"
            if exe.exists():
                bin_dir = str(c)
                current_path = os.environ.get("PATH", "")
                if bin_dir not in current_path:
                    os.environ["PATH"] = bin_dir + os.pathsep + current_path
                return str(exe)
    return None

