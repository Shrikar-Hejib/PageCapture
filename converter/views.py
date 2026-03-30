import json
import re
import logging

import requests as http_requests
from urllib.parse import urlparse

from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse, HttpResponse, Http404
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .crawler import crawl
from .pdf_generator import url_to_pdf, merge_pdfs, create_zip

logger = logging.getLogger(__name__)


def _domain_slug(url):
    """Convert URL to a clean folder name like 'example_com'."""
    host = urlparse(url).netloc.lower()
    host = re.sub(r'^www\.', '', host)
    return re.sub(r'[^\w]', '_', host)[:60]


def index(request):
    return render(request, 'converter/index.html')


def workspace(request):
    pages = request.session.get('pages')
    if not pages:
        return redirect('index')
    
    domain = request.session.get('session_id', 'website')
    return render(request, 'converter/workspace.html', {
        'pages': pages,
        'domain': domain
    })


@csrf_exempt
@require_POST
def start_crawl(request):
    try:
        data = json.loads(request.body)
        url = data.get('url', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid request.'}, status=400)

    if not url:
        return JsonResponse({'error': 'URL is required.'}, status=400)

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        pages = crawl(url, max_pages=settings.CRAWLER_MAX_PAGES, timeout=settings.CRAWLER_TIMEOUT)
    except Exception as e:
        logger.error(f"Crawl error: {e}")
        return JsonResponse({'error': f'Crawl failed: {str(e)[:200]}'}, status=500)

    if not pages:
        return JsonResponse({'error': 'No pages found. Check the URL and try again.'}, status=404)

    # Use domain name as folder name
    session_id = _domain_slug(url)
    request.session['session_id'] = session_id
    request.session['pages'] = pages
    request.session['results'] = []
    request.session.modified = True

    return JsonResponse({'session_id': session_id, 'pages': pages})


@csrf_exempt
def proxy_page(request):
    """Proxy a page to bypass X-Frame-Options restrictions for preview."""
    url = request.GET.get('url', '').strip()
    if not url:
        return HttpResponse('URL required', status=400)

    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        }
        resp = http_requests.get(url, headers=headers, timeout=15, allow_redirects=True, verify=False)
        ct = resp.headers.get('Content-Type', 'text/html')

        if 'text/html' not in ct:
            return HttpResponse(f'Non-HTML content: {ct}', status=400)

        html = resp.text

        # Inject <base> tag so relative URLs resolve correctly
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        base_tag = f'<base href="{base_url}/" target="_blank">'

        if '<head>' in html.lower():
            html = re.sub(r'(<head[^>]*>)', r'\1' + base_tag, html, count=1, flags=re.IGNORECASE)
        elif '<html' in html.lower():
            html = re.sub(r'(<html[^>]*>)', r'\1<head>' + base_tag + '</head>', html, count=1, flags=re.IGNORECASE)
        else:
            html = base_tag + html

        response = HttpResponse(html, content_type='text/html; charset=utf-8')
        # Remove headers that block iframe embedding
        response['X-Frame-Options'] = 'ALLOWALL'
        response['Content-Security-Policy'] = ''
        return response

    except Exception as e:
        return HttpResponse(f'''
            <html><body style="display:flex;align-items:center;justify-content:center;height:100vh;
            font-family:sans-serif;color:#666;background:#f8f8f8;margin:0;">
            <div style="text-align:center;">
                <p style="font-size:1.2rem;">Preview unavailable</p>
                <p style="font-size:0.85rem;color:#999;">{str(e)[:100]}</p>
                <a href="{url}" target="_blank" style="color:#6366f1;">Open in new tab →</a>
            </div></body></html>
        ''', content_type='text/html')


@csrf_exempt
@require_POST
def generate_single_pdf(request):
    try:
        data = json.loads(request.body)
        url = data.get('url', '').strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid request.'}, status=400)

    session_id = request.session.get('session_id')
    if not session_id or not url:
        return JsonResponse({'error': 'No active session or URL missing.'}, status=400)

    pages = request.session.get('pages', [])
    page_info = next((p for p in pages if p['url'] == url), {'title': url, 'has_video': False})

    pdf_path = url_to_pdf(url, session_id)

    if not pdf_path:
        return JsonResponse({
            'url': url,
            'title': page_info.get('title', url),
            'has_video': page_info.get('has_video', False),
            'pdf_url': None,
            'status': 'failed',
        })

    rel = str(pdf_path.relative_to(settings.MEDIA_ROOT))
    pdf_url = f'/media/{rel}'

    results = request.session.get('results', [])
    results = [r for r in results if r.get('url') != url]
    results.append({
        'url': url,
        'title': page_info.get('title', url),
        'has_video': page_info.get('has_video', False),
        'pdf_url': pdf_url,
        'status': 'done',
    })
    request.session['results'] = results
    request.session.modified = True

    return JsonResponse({
        'url': url,
        'title': page_info.get('title', url),
        'has_video': page_info.get('has_video', False),
        'pdf_url': pdf_url,
        'status': 'done',
    })


@csrf_exempt
def download_merged(request):
    session_id = request.session.get('session_id')
    results = request.session.get('results', [])

    if not session_id or not results:
        raise Http404

    pdf_paths = []
    for r in results:
        if r.get('status') == 'done' and r.get('pdf_url'):
            rel = r['pdf_url'].replace('/media/', '')
            path = settings.MEDIA_ROOT / rel
            if path.exists():
                pdf_paths.append(path)

    if not pdf_paths:
        raise Http404

    merged_path = settings.PDF_OUTPUT_DIR / session_id / 'merged.pdf'
    result = merge_pdfs(pdf_paths, merged_path)
    if not result:
        raise Http404

    return FileResponse(
        open(result, 'rb'),
        content_type='application/pdf',
        as_attachment=True,
        filename='pages_merged.pdf',
    )


@csrf_exempt
def download_zip(request):
    session_id = request.session.get('session_id')
    results = request.session.get('results', [])

    if not session_id or not results:
        raise Http404

    named_paths = []
    for r in results:
        if r.get('status') == 'done' and r.get('pdf_url'):
            rel = r['pdf_url'].replace('/media/', '')
            path = settings.MEDIA_ROOT / rel
            if path.exists():
                named_paths.append((r.get('title', 'page'), path))

    if not named_paths:
        raise Http404

    zip_path = settings.PDF_OUTPUT_DIR / session_id / 'pages.zip'
    create_zip(named_paths, zip_path)

    if not zip_path.exists():
        raise Http404

    return FileResponse(
        open(zip_path, 'rb'),
        content_type='application/zip',
        as_attachment=True,
        filename='pages.zip',
    )
