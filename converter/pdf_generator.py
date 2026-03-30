import logging
import re
import subprocess
import zipfile
from pathlib import Path

from django.conf import settings
from pypdf import PdfWriter

logger = logging.getLogger(__name__)

OUTPUT_DIR = settings.PDF_OUTPUT_DIR


def _slug(url):
    s = re.sub(r'https?://', '', url)
    s = re.sub(r'[^\w\-]', '_', s)
    return s[:80]


def _find_chrome():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    # try user-level installs
    import os
    local = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    candidates.append(local)

    for p in candidates:
        if Path(p).exists():
            return p

    # try PATH
    try:
        result = subprocess.run(['where', 'chrome'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split('\n')[0]
    except Exception:
        pass

    # try edge as fallback
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in edge_paths:
        if Path(p).exists():
            logger.info(f"Using Edge as Chrome fallback: {p}")
            return p

    return None


def url_to_pdf(url, session_id):
    """Convert URL to PDF using headless Chrome/Edge."""
    slug = _slug(url)
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    out_path = session_dir / f"{slug}.pdf"

    if out_path.exists() and out_path.stat().st_size > 1000:
        return out_path

    browser = _find_chrome()
    if not browser:
        logger.error("No Chrome or Edge found")
        return None

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-background-networking",
        "--run-all-compositor-stages-before-draw",
        "--disable-features=TranslateUI",
        f"--print-to-pdf={out_path}",
        "--print-to-pdf-no-header",
        "--no-pdf-header-footer",
        url,
    ]

    for attempt in range(2):
        try:
            subprocess.run(cmd, capture_output=True, timeout=45, text=True)

            if out_path.exists() and out_path.stat().st_size > 500:
                logger.info(f"PDF ok: {out_path.name} ({out_path.stat().st_size} bytes)")
                return out_path

            logger.warning(f"Attempt {attempt+1}: PDF too small or missing for {url}")
            out_path.unlink(missing_ok=True)

        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout on attempt {attempt+1} for {url}")
            # Kill any lingering chrome processes for this PDF
            out_path.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"PDF error: {e}")
            out_path.unlink(missing_ok=True)
            break

    return None


def merge_pdfs(pdf_paths, output_path):
    """Merge list of PDF paths into a single PDF."""
    valid = [p for p in pdf_paths if p.exists() and p.stat().st_size > 500]
    if not valid:
        return None

    try:
        writer = PdfWriter()
        for path in valid:
            try:
                writer.append(str(path))
            except Exception as e:
                logger.warning(f"Skip {path.name}: {e}")
                continue

        if len(writer.pages) == 0:
            return None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            writer.write(f)

        logger.info(f"Merged {len(valid)} PDFs -> {output_path.name}")
        return output_path

    except Exception as e:
        logger.error(f"Merge failed: {e}")
        return None


def create_zip(named_paths, output_path):
    """Create ZIP from list of (title, path) tuples."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            seen = set()
            for title, path in named_paths:
                if not path.exists() or path.stat().st_size < 500:
                    continue
                name = re.sub(r'[^\w\s\-]', '_', title)[:60] + '.pdf'
                # avoid duplicates
                if name in seen:
                    name = f"{name[:-4]}_{len(seen)}.pdf"
                seen.add(name)
                zf.write(path, name)

        logger.info(f"ZIP created: {output_path.name} ({len(seen)} files)")
        return output_path

    except Exception as e:
        logger.error(f"ZIP failed: {e}")
        return None
