"""Download the two public datasets used by the case study (raw files are gitignored).

1. Online Retail II (CC BY 4.0), UCI ML Repository - no login needed
   https://archive.ics.uci.edu/dataset/502/online+retail+ii
   (same data on Kaggle: mashlyn/online-retail-ii-uci)
2. Brazilian E-Commerce Public Dataset by Olist (CC BY-NC-SA 4.0), Kaggle
   https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
   Needs the Kaggle CLI (pip install kaggle) and YOUR Kaggle API token in
   ~/.kaggle (the CLI reads it; this script never touches it).

Only the small derived extracts in data/legacy/ (built by src/extract.py) are
committed, so tests and CI need neither download.

Usage:  python -m src.download [uci|olist|all]
"""

import shutil
import subprocess
import sys
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


OLIST_DIR = RAW_DIR.parent / "olist"


def download_olist() -> Path:
    """Fetch the Olist CSVs with the Kaggle CLI (credentials handled by the CLI itself)."""
    if (OLIST_DIR / "olist_customers_dataset.csv").exists():
        print(f"Already present: {OLIST_DIR}")
        return OLIST_DIR
    kaggle = shutil.which("kaggle") or str(Path(sys.executable).parent / "kaggle")
    OLIST_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([kaggle, "datasets", "download", "-d", "olistbr/brazilian-ecommerce",
                    "-p", str(OLIST_DIR), "--unzip"], check=True)
    return OLIST_DIR


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("uci", "all"):
        download()
    if what in ("olist", "all"):
        download_olist()
