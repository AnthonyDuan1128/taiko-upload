import os
import sys
import json
import shutil
import pathlib
import requests
import time
import argparse
from urllib.parse import urljoin
from typing import Dict
import re

def _get_basedir():
    try:
        root = pathlib.Path(__file__).resolve().parent
        sys.path.insert(0, str(root / 'taiko-web2'))
        import config  # type: ignore
        base = getattr(config, 'BASEDIR', '/')
        if not isinstance(base, str):
            return '/'
        if not base.endswith('/'):
            base += '/'
        return base
    except Exception:
        return '/'

def _classify_name(name):
    if not name:
        return 2
    c = name[0]
    if '0' <= c <= '9':
        return 0
    if 'A' <= c <= 'Z' or 'a' <= c <= 'z':
        return 1
    return 2

def _find_first_with_ext(dir_path, ext):
    for entry in os.listdir(dir_path):
        p = os.path.join(dir_path, entry)
        if os.path.isfile(p) and entry.lower().endswith(ext):
            return p
    return None

def _upload_song(url, song_type, tja_path, music_path, use_proxy):
    # Retry on connection/proxy/timeout related errors.
    max_attempts = 3
    wait_seconds = 10
    for attempt in range(1, max_attempts + 1):
        try:
            with open(tja_path, 'rb') as ft, open(music_path, 'rb') as fm:
                files = {
                    'file_tja': ('main.tja', ft.read(), 'text/plain'),
                    'file_music': ('music.ogg', fm.read(), 'audio/ogg'),
                }
                data = {'song_type': song_type}
                proxies = _get_proxies() if use_proxy else None
                resp = requests.post(url, files=files, data=data, timeout=60, proxies=proxies)
            if resp.status_code != 200:
                return False, f'http_status_{resp.status_code}'
            try:
                j = resp.json()
            except Exception:
                return False, 'invalid_json'
            if j.get('success') is True:
                return True, 'ok'
            return False, j.get('error') or 'unknown_error'
        except (requests.exceptions.ProxyError,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            # Only retry for these network/proxy/timeout errors
            if attempt < max_attempts:
                print(f'网络错误（{e}），{attempt}/{max_attempts}。等待 {wait_seconds} 秒后重试...')
                time.sleep(wait_seconds)
                continue
            else:
                return False, f'network_error:{e}'
        except Exception as e:
            # Non-network related error — don't retry
            return False, f'error:{e}'

def _get_proxies() -> Dict[str, str]:
    return {
        'http': 'http://127.0.0.1:10808',
        'https': 'http://127.0.0.1:10808',
    }

def _uploaded_file_path():
    return pathlib.Path(__file__).resolve().parent / 'uploaded.json'

def _load_uploaded_set(p: pathlib.Path):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            j = json.load(f)
        items = j.get('uploaded')
        if isinstance(items, list):
            return set(str(x) for x in items)
    except Exception:
        pass
    return set()

def _save_uploaded_set(p: pathlib.Path, s):
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({'uploaded': sorted(list(s))}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _build_upload_url(base_url):
    if not base_url:
        b = _get_basedir()
        return f'http://127.0.0.1{b}api/upload'
    base = base_url.strip()
    if not base.lower().startswith(('http://', 'https://')):
        base = 'http://' + base
    if not base.endswith('/'):
        base += '/'
    return urljoin(base, 'api/upload')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('ese_path', nargs='?', help='ESE目录路径')
    parser.add_argument('site_url', nargs='?', help='站点URL')
    parser.add_argument('proxy', nargs='?', help='是否使用代理(y/n)')
    parser.add_argument('mode', nargs='?', help='模式 (1: 上传, 2: 扫描缺失)')
    args = parser.parse_args()

    if not args.ese_path:
        try:
            ese_input = input('请输入ESE目录路径: ').strip()
        except EOFError:
            ese_input = ''
    else:
        ese_input = args.ese_path

    if not args.site_url:
        try:
            url_input = input('请输入上传站点URL(如https://taiko.asia): ').strip()
        except EOFError:
            url_input = ''
    else:
        url_input = args.site_url

    if not args.proxy:
        try:
            proxy_input = input('是否使用代理(Y/n): ').strip().lower()
        except EOFError:
            proxy_input = ''
    else:
        proxy_input = args.proxy.strip().lower()
    
    use_proxy = (proxy_input != 'n')
    proxies = _get_proxies() if use_proxy else None

    # New: Ask for mode
    if not args.mode:
        try:
            mode_input = input('请选择模式 (1: 上传, 2: 扫描缺失): ').strip()
        except EOFError:
            mode_input = '1'
    else:
        mode_input = args.mode.strip()
    
    is_scan_mode = (mode_input == '2')

    if is_scan_mode:
        print("正在获取服务器歌曲列表...")
        server_songs = _fetch_server_songs(url_input, proxies)
        if server_songs is None:
             print("无法获取服务器列表，扫描终止。")
             return
        print(f"服务器现有歌曲: {len(server_songs)} 首")

    url = _build_upload_url(url_input)
    uploaded_path = _uploaded_file_path()
    uploaded_set = _load_uploaded_set(uploaded_path)
    
    try:
        ese_dir = pathlib.Path(ese_input) if ese_input else pathlib.Path(__file__).resolve().parent / 'ESE'
        if not ese_dir.exists() or not ese_dir.is_dir():
            print('ESE目录不存在')
            return
        
        KNOWN_TYPES = {
            "01 Pop",
            "02 Anime",
            "03 Vocaloid",
            "04 Children and Folk",
            "05 Variety",
            "06 Classical",
            "07 Game Music",
            "08 Live Festival Mode",
            "09 Namco Original",
            "10 Taiko Towers",
            "11 Dan Dojo",
        }
        def _valid_type(name: str) -> bool:
            return bool(re.match(r"^\d{2}\s", name)) or (name in KNOWN_TYPES)
        
        type_dirs = [d for d in ese_dir.iterdir() if d.is_dir() and not d.name.startswith('.') and _valid_type(d.name)]
        if not type_dirs:
            print('ESE目录下没有合法的歌曲类型目录')
            return
            
        missing_count = 0
        for type_dir in type_dirs:
            song_type = type_dir.name
            song_dirs = [d for d in type_dir.iterdir() if d.is_dir()]
            song_dirs.sort(key=lambda p: (_classify_name(p.name), p.name))
            
            for song_dir in song_dirs:
                key = f'{song_type}/{song_dir.name}'
                
                if is_scan_mode:
                    if key not in server_songs:
                        print(f"[缺失] {key}")
                        missing_count += 1
                    continue

                if key in uploaded_set:
                    print(f'已上传跳过：{key}')
                    continue
                
                tja_path = _find_first_with_ext(str(song_dir), '.tja')
                if tja_path is None:
                    print(f'跳过：{key}，未找到TJA')
                    continue
                    
                music_path = _find_first_with_ext(str(song_dir), '.ogg')
                if music_path is None:
                    print(f'跳过：{key}，未找到OGG')
                    continue
                    
                ok, msg = _upload_song(url, song_type, tja_path, music_path, use_proxy)
                if ok:
                    uploaded_set.add(key)
                    print(f'上传完成：{key}')
                else:
                    print(f'上传失败跳过：{key}，原因：{msg}')
        
        if is_scan_mode:
            print(f"扫描完成，共发现 {missing_count} 首缺失歌曲。")

    finally:
        if not is_scan_mode:
             _save_uploaded_set(uploaded_path, uploaded_set)

def _fetch_server_songs(base_url, proxies):
    if not base_url:
        b = _get_basedir()
        api_url = f'http://127.0.0.1{b}api/songs'
    else:
        base = base_url.strip()
        if not base.lower().startswith(('http://', 'https://')):
            base = 'http://' + base
        if not base.endswith('/'):
            base += '/'
        api_url = urljoin(base, 'api/songs')
    
    try:
        resp = requests.get(api_url, proxies=proxies, timeout=30)
        if resp.status_code != 200:
             print(f"获取服务器列表失败: HTTP {resp.status_code}")
             return None
        data = resp.json()
        
        server_set = set()
        for song in data:
            # Construct key from server data to match local key structure
            # Server data has "category" (e.g., "01 Pop") and "title" (e.g., "Song Name")
            # But wait, looking at the user screenshot, the API returns a list of objects.
            # Each object has "category": "05 Variety", "title": "Conflict", etc.
            # Local key structure is "{song_type}/{dirname}".
            # We assume dirname matches title for now, or we might need to be smarter.
            # Let's inspect the API response structure from the screenshot more closely if possible, 
            # or just assume category + "/" + title.
            cat = song.get('category') or song.get('song_type') # api seems to have song_type or category
            title = song.get('title')
            if cat and title:
                 server_set.add(f"{cat}/{title}")
        return server_set
    except Exception as e:
        print(f"获取服务器列表出错: {e}")
        return None

if __name__ == '__main__':
    main()
