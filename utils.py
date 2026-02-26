import os
import re
import requests
from urllib.parse import urljoin

# ─── Sensitive word filter ───────────────────────────────────────────────────

SENSITIVE_WORDS = [
    # 中文常见敏感词（示例）
    '傻逼', '操你', '他妈的', '草泥马', '你妈', '滚蛋', '去死', '白痴', '废物',
    '智障', '脑残', '贱人', '婊子', '混蛋', '王八蛋', '狗屎', '妈的', '尼玛',
    '卧槽', '艹', 'sb', 'nmsl', 'cnm',
    # English profanity
    'fuck', 'shit', 'damn', 'bitch', 'ass', 'dick', 'bastard', 'crap',
    'asshole', 'motherfucker', 'wtf', 'stfu',
]

_compiled_patterns = None


def _get_patterns():
    global _compiled_patterns
    if _compiled_patterns is None:
        _compiled_patterns = []
        for w in SENSITIVE_WORDS:
            escaped = re.escape(w)
            # Use word boundaries for short ASCII words to avoid
            # false positives (e.g. 'ass' in 'class', 'pass')
            if w.isascii() and len(w) <= 5:
                pattern = re.compile(r'\b' + escaped + r'\b', re.IGNORECASE)
            else:
                pattern = re.compile(escaped, re.IGNORECASE)
            _compiled_patterns.append(pattern)
    return _compiled_patterns


def filter_sensitive_words(text):
    """Replace sensitive words with asterisks."""
    if not text:
        return text
    for pattern in _get_patterns():
        text = pattern.sub(lambda m: '*' * len(m.group()), text)
    return text


# ─── Upload to taiko.asia ────────────────────────────────────────────────────

def upload_to_taiko_server(tja_path, ogg_path, song_type, server_url, use_proxy=False, proxy_url=None):
    """
    Upload TJA + OGG to a taiko-web server.
    Returns (success: bool, message: str).
    """
    base = server_url.strip()
    if not base.lower().startswith(('http://', 'https://')):
        base = 'https://' + base
    if not base.endswith('/'):
        base += '/'
    url = urljoin(base, 'api/upload')

    proxies = None
    if use_proxy and proxy_url:
        proxies = {
            'http': proxy_url,
            'https': proxy_url,
        }

    max_attempts = 3
    wait_seconds = 10

    for attempt in range(1, max_attempts + 1):
        try:
            with open(tja_path, 'rb') as ft, open(ogg_path, 'rb') as fm:
                files = {
                    'file_tja': ('main.tja', ft.read(), 'text/plain'),
                    'file_music': ('music.ogg', fm.read(), 'audio/ogg'),
                }
                data = {'song_type': song_type}
                resp = requests.post(url, files=files, data=data, timeout=60, proxies=proxies)

            if resp.status_code != 200:
                return False, f'HTTP {resp.status_code}'
            try:
                j = resp.json()
            except Exception:
                return False, '服务器响应非 JSON'
            if j.get('success') is True:
                return True, 'ok'
            return False, j.get('error') or '未知错误'

        except (requests.exceptions.ProxyError,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout):
            if attempt < max_attempts:
                import time
                time.sleep(wait_seconds)
                continue
            else:
                return False, '网络连接失败，请稍后重试'
        except Exception as e:
            return False, f'上传异常: {e}'

    return False, '上传失败'


# ─── File helpers ─────────────────────────────────────────────────────────────

def allowed_file(filename, allowed_extensions):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions


def ensure_upload_dir(upload_folder, submission_id):
    """Create per-submission upload directory, return the path."""
    path = os.path.join(upload_folder, str(submission_id))
    os.makedirs(path, exist_ok=True)
    return path
