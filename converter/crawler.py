import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque
import re
import logging

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

SKIP_EXT = {
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.webp',
    '.zip', '.tar', '.gz', '.mp4', '.mp3', '.avi', '.mov', '.wmv',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
    '.xml', '.json', '.txt', '.csv', '.xlsx', '.docx', '.pptx',
}

VIDEO_RE = re.compile(
    r'('
    # HTML5 video element
    r'<video[\s>]'
    r'|<source[^>]+type=["\']video/'
    # YouTube embeds
    r'|youtube\.com/embed/[a-zA-Z0-9_-]'
    r'|youtube\.com/watch\?v='
    r'|youtu\.be/[a-zA-Z0-9_-]'
    # Vimeo embeds
    r'|player\.vimeo\.com/video/\d'
    # Wistia embeds
    r'|fast\.wistia\.(com|net)/embed'
    r'|wistia\.com/medias/[a-zA-Z0-9]'
    # Loom embeds
    r'|loom\.com/(share|embed)/[a-zA-Z0-9]'
    # Other platforms 
    r'|dailymotion\.com/embed/video/'
    r'|player\.twitch\.tv/\?'
    r'|tiktok\.com/embed/v'
    r'|facebook\.com/plugins/video\.php'
    r'|play\.vidyard\.com/[a-zA-Z0-9]'
    r'|players\.brightcove\.(com|net)/[0-9]'
    # Video files linked in src attributes
    r'|src=["\'][^"\']*\.(mp4|webm|m3u8)["\']'
    # Iframes with video platform domains
    r'|<iframe[^>]+src=["\'][^"\']*(?:youtube\.com/embed|player\.vimeo\.com|fast\.wistia)'
    r')',
    re.IGNORECASE
)


def _normalize(url):
    p = urlparse(url)
    path = p.path.rstrip('/') or '/'
    return p._replace(fragment='', path=path).geturl()


def _same_domain(url, base_domain):
    host = urlparse(url).netloc.lower()
    base = base_domain.lower()
    return host == base or host == f'www.{base}' or f'www.{host}' == base


def _is_crawlable(url, base_domain):
    parsed = urlparse(url)
    if parsed.netloc and not _same_domain(url, base_domain):
        return False
    ext = parsed.path.rsplit('.', 1)[-1].lower() if '.' in parsed.path.split('/')[-1] else ''
    if f'.{ext}' in SKIP_EXT:
        return False
    if parsed.fragment and not parsed.path:
        return False
    return True


def _page_title(soup, url):
    if soup.title and soup.title.string:
        return soup.title.string.strip()[:120]
    h1 = soup.find('h1')
    if h1:
        return h1.get_text(strip=True)[:120]
    return urlparse(url).path or url


def crawl(start_url, max_pages=50, timeout=10):
    parsed = urlparse(start_url)
    base_domain = parsed.netloc
    
    visited = set()
    queue = deque([_normalize(start_url)])
    pages = []

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            except requests.exceptions.SSLError:
                resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True, verify=False)

            if resp.status_code != 200:
                continue

            ct = resp.headers.get('Content-Type', '')
            if ct and 'text/html' not in ct:
                continue

        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as e:
            logger.warning(f"Skip {url}: {str(e)[:80]}")
            continue

        try:
            html = resp.text
            soup = BeautifulSoup(html, 'lxml')

            depth = urlparse(url).path.count('/')
            pages.append({
                'url': url,
                'title': _page_title(soup, url),
                'has_video': bool(VIDEO_RE.search(html)),
                'depth': depth,
            })
            logger.info(f"Crawled ({len(pages)}/{max_pages}): {url}")

            # Extract links - resolve relative to current page URL
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                if not href or href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                    continue
                full = _normalize(urljoin(url, href))
                if full not in visited and _is_crawlable(full, base_domain):
                    queue.append(full)

        except Exception as e:
            logger.error(f"Parse error {url}: {e}")
            continue

    pages.sort(key=lambda p: (p['depth'], p['url']))
    logger.info(f"Crawl done: {len(pages)} pages")
    return pages
