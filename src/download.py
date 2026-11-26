"""Download the public Online Retail II dataset (CC BY 4.0) from the UCI ML Repository.

Source : https://archive.ics.uci.edu/dataset/502/online+retail+ii  (no login needed)
Mirror : https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci (same data, needs login)

The raw .xlsx (~45 MB) is gitignored. Only the small derived legacy material
master (data/legacy/mara_legacy.csv, built by src/extract.py) is committed.

Usage:  python -m src.download
"""

import time
import urllib.request
import zipfile
from pathlib import Path

URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "online_retail_ii"
ZIP_PATH = RAW_DIR / "online_retail_ii.zip"
XLSX_NAME = "online_retail_II.xlsx"


def _download_with_resume(url: str, target: Path, attempts: int = 10) -> None:
    """Download url to target, resuming a partial file if the connection drops."""
    for attempt in range(1, attempts + 1):
        have = target.stat().st_size if target.exists() else 0
        request = urllib.request.Request(url, headers={"User-Agent": "migrateright-downloader"})
        if have:
            # Ask the server for the remaining bytes only (HTTP Range request).
            request.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                # 206 = partial content (resume worked); 200 = server sent the whole file again.
                mode = "ab" if response.status == 206 else "wb"
                with open(target, mode) as out:
                    while chunk := response.read(1024 * 256):
                        out.write(chunk)
            return
        except Exception as exc:  # network hiccup -> wait and resume
            print(f"  attempt {attempt} failed ({exc}); retrying...")
            time.sleep(3)
    raise RuntimeError(f"Could not download {url}")


def download() -> Path:
    """Fetch and unzip the dataset. Returns the path of the .xlsx file."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    xlsx = RAW_DIR / XLSX_NAME
    if xlsx.exists():
        print(f"Already present: {xlsx}")
        return xlsx

    print(f"Downloading {URL}")
    _download_with_resume(URL, ZIP_PATH)

    with zipfile.ZipFile(ZIP_PATH) as zf:
        zf.extractall(RAW_DIR)
    print(f"Extracted to {RAW_DIR}")
    return xlsx


if __name__ == "__main__":
    download()
