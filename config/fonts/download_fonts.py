"""
Download Poppins TTF files from Google Fonts static CDN into config/fonts/.

Usage:
    python config/fonts/download_fonts.py
"""

import os
import sys

FONTS = {
    "Poppins-Bold.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf",
    "Poppins-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf",
    "Poppins-SemiBold.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-SemiBold.ttf",
}

FONTS_DIR = os.path.dirname(os.path.abspath(__file__))


def download_font(filename: str, url: str) -> bool:
    dest = os.path.join(FONTS_DIR, filename)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        print(f"  [skip] {filename} already downloaded")
        return True
    try:
        import urllib.request
        print(f"  Downloading {filename} ...")
        urllib.request.urlretrieve(url, dest)
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            print(f"  [ok] {filename} ({os.path.getsize(dest) // 1024} KB)")
            return True
        print(f"  [error] {filename} downloaded but appears empty")
        return False
    except Exception as exc:
        print(f"  [failed] {filename}: {exc}")
        return False


def main():
    print(f"Downloading Poppins fonts to: {FONTS_DIR}")
    ok = 0
    for filename, url in FONTS.items():
        if download_font(filename, url):
            ok += 1
    print(f"\nDone: {ok}/{len(FONTS)} fonts downloaded.")
    if ok < len(FONTS):
        print("Some fonts failed — the pipeline will fall back to system fonts.")
        sys.exit(1)


if __name__ == "__main__":
    main()
