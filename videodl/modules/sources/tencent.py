'''
Function:
    Implementation of TencentVideoClient
Author:
    Zhenchao Jin
WeChat Official Account (微信公众号):
    Charles的皮卡丘
'''
import os
import re
import time
import copy
import math
import json
import random
import string
import subprocess
import json_repair
from pathlib import Path
from bs4 import BeautifulSoup
from .base import BaseVideoClient
from typing import Dict, Any, List
from urllib.parse import urlencode
from ..utils.domains import TENCENT_SUFFIXES
from ..utils import legalizestring, searchdictbykey, useparseheaderscookies, safeextractfromdict, writevodm3u8fortencent, yieldtimerelatedtitle, FileTypeSniffer, VideoInfo, AESAlgorithmWrapper, SpinWithBackoff


'''TencentVQQVideoClient: https://github.com/Jesseatgao/movie-downloader/blob/master/mdl/sites/vqq.py'''
class TencentVQQVideoClient(BaseVideoClient):
    source = 'TencentVQQVideoClient'
    class QQVideoPlatforms:
        P10901 = '11'; P10801 = '10801'; P10201 = '10201'
    class VideoURLType:
        COVER = 'Playlist'; PAGE = 'EPISODE'
    class VideoTypeCodes:
        MOVIE = 1; TV = 2; CARTOON = 3; SPORTS = 4; ENTMT = 5; GAME = 6; DOCU = 9; VARIETY = 10; MUSIC = 22; NEWS = 23; FINANCE = 24; FASHION = 25
        TRAVEL = 26; EDUCATION = 27; TECH = 28; AUTO = 29; HOUSE = 30; LIFE = 31; FUN = 43; BABY = 60; CHILD = 106; ART = 111
    class VideoTypes:
        MOVIE = "MOV"; TV = "TV"; CARTOON = "Cartoon"; SPORTS = "Sports"; ENTMT = "Ent"; GAME = "Game"; DOCU = "Docu"; VARIETY = "Variety"; MUSIC = "Music"; NEWS = "News"; FINANCE = "Finance"
        FASHION = "Fashion"; TRAVEL = "Travel"; EDUCATION = "Edu"; TECH = "Tech"; AUTO = "Auto"; HOUSE = "House"; LIFE = "Life"; FUN = "Fun"; BABY = "Baby"; CHILD = "Child"; ART = "Art"
    VIDEO_COVER_PREFIX = 'https://v.qq.com/x/cover/'
    VIDEO_CONFIG_URL = 'https://vd.l.qq.com/proxyhttp'
    VIDEO_GETPAGE_URL = "https://pbaccess.video.qq.com/trpc.vector_layout.page_view.PageService/getPage"
    VIDEO_URL_PATS = [{'pat': r'^https?://v\.qq\.com/x/cover/(\w+)\.html', 'eg': 'https://v.qq.com/x/cover/nhtfh14i9y1egge.html'}, {'pat': r'^https?://v\.qq\.com/detail/([a-zA-Z0-9])/((?:\1)\w+)\.html', 'eg': 'https://v.qq.com/detail/n/nhtfh14i9y1egge.html'}, {'pat': r'^https?://v\.qq\.com/x/cover/(\w+)/(\w+)\.html', 'eg': 'https://v.qq.com/x/cover/nhtfh14i9y1egge/d00249ld45q.html'}, {'pat': r'^https?://v\.qq\.com/x/page/(\w+)\.html', 'eg': 'https://v.qq.com/x/page/d00249ld45q.html'}]
    VIDEO_URL_PATS = [re.compile(p['pat'], re.IGNORECASE) for p in VIDEO_URL_PATS]
    ENCRYPTVER_to_APPVER = {'8.1': '3.5.57', '9.1': '3.5.57', '8.5': '1.27.3'}
    VQQ_TYPE_CODES = {
        VideoTypeCodes.MOVIE: VideoTypes.MOVIE, VideoTypeCodes.TV: VideoTypes.TV, VideoTypeCodes.CARTOON: VideoTypes.CARTOON, VideoTypeCodes.SPORTS: VideoTypes.SPORTS, VideoTypeCodes.ENTMT: VideoTypes.ENTMT, 
        VideoTypeCodes.GAME: VideoTypes.GAME, VideoTypeCodes.DOCU: VideoTypes.DOCU, VideoTypeCodes.VARIETY: VideoTypes.VARIETY, VideoTypeCodes.MUSIC: VideoTypes.MUSIC, VideoTypeCodes.NEWS: VideoTypes.NEWS, 
        VideoTypeCodes.CHILD: VideoTypes.CHILD, VideoTypeCodes.ART: VideoTypes.ART, VideoTypeCodes.FINANCE: VideoTypes.FINANCE, VideoTypeCodes.FASHION: VideoTypes.FASHION, VideoTypeCodes.TRAVEL: VideoTypes.TRAVEL, 
        VideoTypeCodes.EDUCATION: VideoTypes.EDUCATION, VideoTypeCodes.TECH: VideoTypes.TECH, VideoTypeCodes.AUTO: VideoTypes.AUTO, VideoTypeCodes.HOUSE: VideoTypes.HOUSE, VideoTypeCodes.LIFE: VideoTypes.LIFE, 
        VideoTypeCodes.FUN: VideoTypes.FUN, VideoTypeCodes.BABY: VideoTypes.BABY,
    }
    VQQ_FORMAT_IDS_DEFAULT = {
        QQVideoPlatforms.P10901: {'uhd': 10208, 'fhd': 10209, 'shd': 10201, 'hd': 10212, 'sd': 10203},
        QQVideoPlatforms.P10801: {'uhd': 321005, 'fhd': 321004, 'shd': 321003, 'hd': 321002, 'sd': 321001},
        QQVideoPlatforms.P10201: {'uhd': 10219, 'fhd': 10218, 'shd': 10217, 'hd': 2, 'sd': 100001}
    }
    VQQ_FMT2DEFN_MAP = {10209: 'fhd', 10201: 'shd', 10212: 'hd', 10203: 'sd', 321004: 'fhd', 321003: 'shd', 321002: 'hd', 321001: 'sd', 320090: 'hd', 320089: 'sd'}
    COVER_PAT_RE = re.compile(r"var\s+COVER_INFO\s*=\s*(.+?);?var\s+COLUMN_INFO" r"|\"coverInfo\"\s*:\s*(.+?),\s*\"videoInfo\"" r"|coverInfoMap\s*:\s*{\s*\w+\s*:\s*(.+?)\s*}\s*,\s*videoInfoMap", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    VIDEO_INFO_RE = re.compile(r"var\s+VIDEO_INFO\s*=\s*(.+?);?</script>" r"|\"episodeSinglePlay\".+?\"item_params\"\s*:\s*({.+?})\s*,\s*\"\s*sub_items" r"|videoInfoMap\s*:\s*{\s*\w+\s*:\s*(.+?)\s*}\s*,\s*initialCid", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    ALL_LOADED_INFO_RE = re.compile(r"window\.__PINIA__\s*=\s*(.+?);?</script>" r"|_piniaState\s*:\s*(.+?)\s*,\s*isHarmonyClient", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    EP_LIST_RE = re.compile(r"(?:\[{\"list\":)?Array\.prototype\.slice\.call\({\"\d+\":(?:{\"list\":\[)?\[(.+?})\]\]?,.*?\"length\":\d+}\)(?=,\"tabs\")", re.MULTILINE | re.DOTALL | re.IGNORECASE)
    PAGE_CONTEXT_RE = re.compile(r"cid=(?P<cid>[^&]+).+episode_begin=(?P<begin>\d+)&episode_end=(?P<end>\d+).+&page_size=(?P<size>\d+)", re.DOTALL | re.IGNORECASE)
    NULLIFY_RE = re.compile(r'new\s+Map\(.*?\]\)|void\s+0|(?<=:)\s*undefined\b|(?<=:)\s*false\b|(?<=:)\s*null\b|(?<=(:|\[))\s*(?<!\\)"([^"]|\\")*?:([^"]|\\")*?(?<!\\)"', re.MULTILINE | re.DOTALL | re.IGNORECASE)
    DOUBLE_QUOTE_VAL_RE = re.compile(r":\s*([^,\[\]{}\"\\\s/]+)", re.DOTALL | re.IGNORECASE)
    DOUBLE_QUOTE_KEY_RE = re.compile(r"(\w+)\s*:", re.DOTALL | re.IGNORECASE)
    MAX_PAGETAB_REQS = 5
    CKEY_FOR_ENCRYPT_VERION = '8.5'
    CKEY_FOR_ENCRYPT_JS_FILE_PATH = Path(__file__).resolve().parents[2] / "modules" / "js" / "tencent" / f'vqq_ckey-{CKEY_FOR_ENCRYPT_VERION}.js'
    APP_VERSION = ENCRYPTVER_to_APPVER[CKEY_FOR_ENCRYPT_VERION]
    DEVICE_ID = "".join([f"{h:x}" for h in [math.floor(random.random() * 16) for _ in range(16)]])
    def __init__(self, **kwargs):
        super(TencentVQQVideoClient, self).__init__(**kwargs)
        self.default_parse_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36', 
            'Accept-Encoding': 'gzip, deflate, br', 'Accept': '*/*', 'Connection': 'keep-alive'
        }
        self.default_download_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        }
        self.default_headers = self.default_parse_headers
        self._initsession()
    '''_getlogintokenfromcookies'''
    @staticmethod
    def _getlogintokenfromcookies(cookies: dict):
        login_token = {'openid': '', 'appid': '', 'access_token': '', 'vuserid': '', 'vusession': ''}
        if cookies:
            for cookie_name in login_token: login_token.update({cookie_name: cookies.get('vqq_' + cookie_name, '')})
        login_token['main_login'] = 'qq'
        return login_token
    '''_getvideourlsp10801'''
    def _getvideourlsp10801(self, vid, definition, vurl, referrer, request_overrides: dict = None):
        urls, ext, format_name, request_overrides = [], None, None, request_overrides or {}
        params = {'vid': vid, 'defn': definition, 'otype': 'json', 'platform': TencentVQQVideoClient.QQVideoPlatforms.P10801, 'fhdswitch': 1, 'show1080p': 1, 'dtype': 3}
        resp = self.get('https://vv.video.qq.com/getinfo', params=params, **request_overrides)
        if (not resp) or (resp.status_code not in {200}): return format_name, ext, urls
        try: data: dict = json.loads(resp.text[len('QZOutputJson='): -1])
        except json.JSONDecodeError: return format_name, ext, urls
        if not (data and data.get('dltype')): return format_name, ext, urls
        url_prefixes: list[str] = [url for d in safeextractfromdict(data, ['vl', 'vi', 0, 'ul', 'ui'], []) if isinstance(d, dict) and (url := d.get('url'))]
        chosen_url_prefixes = [prefix for prefix in url_prefixes if prefix[:prefix.find('/', 8)].endswith('.tc.qq.com')]
        if not chosen_url_prefixes: chosen_url_prefixes = url_prefixes
        chosen_url_prefixes += [prefix for prefix in url_prefixes if prefix not in chosen_url_prefixes]
        drm, preview = safeextractfromdict(data, ['vl', 'vi', 0, 'drm'], None), data.get('preview')
        formats = {str(fmt.get('id')): fmt.get('name') for fmt in safeextractfromdict(data, ['fl', 'fi'], [])}
        keyid = safeextractfromdict(data, ['vl', 'vi', 0, 'keyid'], ''); format_id = keyid.split('.')[-1]; ret_defn = formats.get(format_id)
        ret_defn = ret_defn or (definition if definition in (fmt_names := list(formats.values())) else next((d for d in TencentVQQVideoClient.VQQ_FORMAT_IDS_DEFAULT[TencentVQQVideoClient.QQVideoPlatforms.P10801] if d in fmt_names), definition))
        vfilename = safeextractfromdict(data, ['vl', 'vi', 0, 'fn'], ''); vfn = vfilename.rpartition('.'); ext = vfn[-1]
        fc = safeextractfromdict(data, ['vl', 'vi', 0, 'fc'], None); start = 0 if fc == 0 else 1
        if ext == 'ts':
            if drm == 1 and not preview and not self.default_cookies: return format_name, ext, urls
            urls.extend('\t'.join(f'{prefix}{vfn[0]}.{idx}.ts?sdtfrom=v1010' for prefix in chosen_url_prefixes) for idx in range(start, fc + 1))
        else:
            if drm == 1 and not self.default_cookies: return format_name, ext, urls
            if safeextractfromdict(data, ['vl', 'vi', 0, 'logo'], None) == 0:
                playlist_m3u8, ext = safeextractfromdict(data, ['vl', 'vi', 0, 'ul', 'ui', -1, 'hls', 'pname'], None), 'ts'
                if not playlist_m3u8: return self._getvideourlsp10201(vid, definition, vurl, referrer, request_overrides)
                resp = self.get(chosen_url_prefixes[0] + playlist_m3u8, **request_overrides)
                if resp and resp.status_code in {200}: resp.encoding = 'utf-8'; urls.extend('\t'.join(f'{p}{vfilename}/{line}' for p in chosen_url_prefixes) for line in resp.iter_lines(decode_unicode=True) if line and not str(line).startswith('#'))
            else:
                return self._getvideourlsp10201(vid, definition, vurl, referrer, request_overrides)
        format_name = ret_defn
        return format_name, ext, urls
    '''_getvideourlsp10901'''
    def _getvideourlsp10901(self, vid, definition, request_overrides: dict = None):
        urls, ext, format_name, request_overrides = [], None, None, request_overrides or {}
        params = {'isHLS': False, 'charge': 0, 'vid': vid, 'defn': definition, 'defnpayver': 1, 'otype': 'json', 'platform': TencentVQQVideoClient.QQVideoPlatforms.P10901, 'sdtfrom': 'v1010', 'host': 'v.qq.com', 'fhdswitch': 0, 'show1080p': 1}
        resp = self.get('https://h5vv.video.qq.com/getinfo', params=params, **request_overrides)
        if (not resp) or (resp.status_code not in {200}): return format_name, ext, urls
        try: data: dict = json.loads(resp.text[len('QZOutputJson='):-1])
        except json.JSONDecodeError: return format_name, ext, urls
        if not (data and data.get('dltype')): return format_name, ext, urls
        url_prefixes: list[str] = [url for d in safeextractfromdict(data, ['vl', 'vi', 0, 'ul', 'ui'], []) if isinstance(d, dict) and (url := d.get('url'))]
        chosen_url_prefixes = [prefix for prefix in url_prefixes if prefix[:prefix.find('/', 8)].endswith('.tc.qq.com')]
        if not chosen_url_prefixes: chosen_url_prefixes = url_prefixes
        chosen_url_prefixes += [prefix for prefix in url_prefixes if prefix not in chosen_url_prefixes]
        formats = {fmt.get('name'): fmt.get('id') for fmt in safeextractfromdict(data, ['fl', 'fi'], [])}
        ret_defn = definition if definition in formats else next((d for d in TencentVQQVideoClient.VQQ_FORMAT_IDS_DEFAULT[TencentVQQVideoClient.QQVideoPlatforms.P10901] if d in formats), definition)
        format_id = formats.get(ret_defn) or TencentVQQVideoClient.VQQ_FORMAT_IDS_DEFAULT[TencentVQQVideoClient.QQVideoPlatforms.P10901][ret_defn]
        vfilename = safeextractfromdict(data, ['vl', 'vi', 0, 'fn'], '')
        vfn = vfilename.split('.'); ext = vfn[-1]; vfmt_new = vfn[1][0] + str(format_id % 10000) if len(vfn) == 3 else ''
        fvkey, fc = safeextractfromdict(data, ['vl', 'vi', 0, 'fvkey'], None), safeextractfromdict(data, ['vl', 'vi', 0, 'cl', 'fc'], None)
        keyids: list[str] = [chap.get('keyid') for chap in safeextractfromdict(data, ['vl', 'vi', 0, 'cl', 'ci'], [])] if fc else [safeextractfromdict(data, ['vl', 'vi', 0, 'cl', 'keyid'], [])]
        for keyid in keyids:
            keyid_new = keyid.split('.')
            if len(keyid_new) == 3: keyid_new[1] = vfmt_new; keyid_new = '.'.join(keyid_new)
            else: keyid_new = '.'.join(vfn[:-1])
            resp = self.get('https://h5vv.video.qq.com/getkey', params={'otype': 'json', 'vid': vid, 'format': format_id, 'filename': f"{keyid_new}.{ext}", 'platform': TencentVQQVideoClient.QQVideoPlatforms.P10901, 'vt': 217, 'charge': 0}, **request_overrides)
            if resp and resp.status_code in {200}:
                try: key_data = json.loads(resp.text[len('QZOutputJson='):-1])
                except json.JSONDecodeError: return format_name, ext, urls
                if key_data and isinstance(key_data, dict):
                    vkey = key_data.get('key', fvkey)
                    if not vkey: return format_name, ext, urls
                    url_mirrors = '\t'.join(['%s%s?sdtfrom=v1010&vkey=%s' % (url_prefix, f"{keyid_new}.{ext}", vkey) for url_prefix in chosen_url_prefixes])
                    if url_mirrors: urls.append(url_mirrors)
        if len(keyids) == len(urls): format_name = ret_defn
        return format_name, ext, urls
    '''_getorigformatid'''
    def _getorigformatid(self, data, platform):
        file_format_id, vfilefs = None, safeextractfromdict(data, ['vl', 'vi', 0, 'fs'], None)
        if vfilefs:
            for fmt in safeextractfromdict(data, ['fl', 'fi'], []):
                if not isinstance(fmt, dict): continue
                if vfilefs == fmt.get('fs'): file_format_id = fmt.get('id'); break
        if not file_format_id: file_format_id = safeextractfromdict(data, ['fl', 'fi', 0, 'id'], None) or TencentVQQVideoClient.VQQ_FORMAT_IDS_DEFAULT[platform]['sd']
        return file_format_id
    '''_pickhighestdefinition'''
    def _pickhighestdefinition(self, defns):
        for definition in ('suhd', 'uhd', 'dolby', 'hdr10', 'fhd', 'shd', 'hd', 'sd'):
            if definition in defns: return definition
    '''_sortdefinitions'''
    def _sortdefinitions(self, defns, reverse=True):
        sorted_defns, full_defns = [], ('suhd', 'uhd', 'dolby', 'hdr10', 'fhd', 'shd', 'hd', 'sd') if reverse else ('suhd', 'uhd', 'dolby', 'hdr10', 'fhd', 'shd', 'hd', 'sd')[::-1]
        for defn in full_defns:
            if defn in defns: sorted_defns.append(defn)
        return sorted_defns
    '''_getvideourlsp10201'''
    def _getvideourlsp10201(self, vid, definition, vurl, referrer, request_overrides: dict = None):
        urls, ext, format_name, request_overrides = [], None, None, request_overrides or {}
        cmd_nodejs = ['node', TencentVQQVideoClient.CKEY_FOR_ENCRYPT_JS_FILE_PATH]
        with subprocess.Popen(cmd_nodejs, bufsize=1, universal_newlines=True, encoding='utf-8', stdin=subprocess.PIPE, stdout=subprocess.PIPE) as node_proc:
            ckey_req = ' '.join([TencentVQQVideoClient.QQVideoPlatforms.P10201, TencentVQQVideoClient.APP_VERSION, vid, vurl, referrer])
            node_proc.stdin.write(ckey_req); node_proc.stdin.write(r'\n'); node_proc.stdin.flush()
            ckey_resp = node_proc.stdout.readline().rstrip(r'\r\n'); ckey, tm, guid, flowid = ckey_resp.split()
            vinfoparam = {
                'otype': 'ojson', 'isHLS': 1, 'charge': 0, 'fhdswitch': 0, 'show1080p': 1, 'defnpayver': 7, 'sdtfrom': 'v1010', 'host': 'v.qq.com', 'vid': vid, 'defn': definition, 'platform': TencentVQQVideoClient.QQVideoPlatforms.P10201, 'appVer': TencentVQQVideoClient.APP_VERSION, 
                'refer': referrer, 'ehost': vurl, 'logintoken': json.dumps(self._getlogintokenfromcookies(self.default_cookies), separators=(',', ':')), 'encryptVer': TencentVQQVideoClient.CKEY_FOR_ENCRYPT_VERION, 'guid': guid, 'flowid': flowid, 'tm': tm, 'cKey': ckey, 'dtype': 1,
            }
            params = {'buid': 'vinfoad', 'vinfoparam': urlencode(vinfoparam)}
            try:
                (resp := self.post(TencentVQQVideoClient.VIDEO_CONFIG_URL, json=params, **request_overrides)).raise_for_status()
                try: data: dict = (d := json.loads(resp.text)) and json.loads(d.get('vinfo'))
                except json.JSONDecodeError as e: return format_name, ext, urls
                if not (data and data.get('dltype')): return format_name, ext, urls
                url_prefixes: list[str] = [url for d in safeextractfromdict(data, ['vl', 'vi', 0, 'ul', 'ui'], []) if isinstance(d, dict) and (url := d.get('url'))]
                chosen_url_prefixes = [prefix for prefix in url_prefixes if prefix[:prefix.find('/', 8)].endswith('.tc.qq.com')]
                if not chosen_url_prefixes: chosen_url_prefixes = url_prefixes
                chosen_url_prefixes += [prefix for prefix in url_prefixes if prefix not in chosen_url_prefixes]
                formats = {fmt.get('name'): fmt.get('id') for fmt in safeextractfromdict(data, ['fl', 'fi'], [])}
                ret_defn = definition if definition in formats else self._pickhighestdefinition(formats)
                new_format_id = formats.get(ret_defn) or TencentVQQVideoClient.VQQ_FORMAT_IDS_DEFAULT[TencentVQQVideoClient.QQVideoPlatforms.P10201][ret_defn]
                vfilename = safeextractfromdict(data, ['vl', 'vi', 0, 'fn'], ''); vfn = vfilename.split('.'); ext = vfn[-1]
                fmt_prefix = vfn[1][0] if len(vfn) == 3 else 'p'; vfmt_new = fmt_prefix + str(new_format_id % 10000)
                orig_format_id = self._getorigformatid(data, TencentVQQVideoClient.QQVideoPlatforms.P10201)
                fc = safeextractfromdict(data, ['vl', 'vi', 0, 'cl', 'fc'], None)
                keyid: str = safeextractfromdict(data, ['vl', 'vi', 0, 'cl', 'ci', 0, 'keyid'], None) if fc else safeextractfromdict(data, ['vl', 'vi', 0, 'cl', 'keyid'], None)
                keyid = keyid.split('.'); keyid[1] = str(orig_format_id); keyid = '.'.join(keyid); max_fc = 80
                for idx in range(1, max_fc + 1):
                    keyid_new = keyid.split('.'); keyid_new[0] = vfn[0]
                    if len(keyid_new) == 3: keyid_new = '.'.join([keyid_new[0], vfmt_new, str(idx)])
                    else: (int(keyid_new[1]) != new_format_id) and (vfn.__setitem__(1, vfn[1][0] + str(new_format_id)) if len(vfn) == 3 else vfn.insert(1, vfmt_new)); keyid_new = '.'.join(vfn[:-1])
                    cfilename = f"{keyid_new}.{ext}"; ckey_req = ' '.join([TencentVQQVideoClient.QQVideoPlatforms.P10201, TencentVQQVideoClient.APP_VERSION, vid, vurl, referrer, r'\n'])
                    node_proc.stdin.write(ckey_req); node_proc.stdin.flush()
                    ckey_resp = node_proc.stdout.readline().rstrip(r'\r\n'); ckey, tm, guid, flowid = ckey_resp.split()
                    vkeyparam = {'otype': 'ojson', 'vid': vid, 'format': new_format_id, 'filename': cfilename, 'platform': TencentVQQVideoClient.QQVideoPlatforms.P10201, 'appVer': TencentVQQVideoClient.APP_VERSION, 'sdtfrom': 'v1010', 'guid': guid, 'flowid': flowid, 'tm': tm, 'refer': referrer, 'ehost': vurl, 'logintoken': json.dumps(self._getlogintokenfromcookies(self.default_cookies), separators=(',', ':')), 'encryptVer': TencentVQQVideoClient.CKEY_FOR_ENCRYPT_VERION, 'cKey': ckey}
                    params = {'buid': 'onlyvkey', 'vkeyparam': urlencode(vkeyparam)}
                    try:
                        (resp := self.post(TencentVQQVideoClient.VIDEO_CONFIG_URL, json=params, **request_overrides)).raise_for_status()
                        try: key_data: dict = (d := json.loads(resp.text)) and json.loads(d.get('vkey'))
                        except json.JSONDecodeError: return format_name, ext, urls
                        if key_data and isinstance(key_data, dict):
                            if not key_data.get('key'): break
                            keyid = key_data.get('keyid'); keyid_nseg = len(keyid.split('.'))
                            if (fn := key_data.get('filename')): cfilename = ('.'.join((p := fn.split('.'))[:-1] + [str(idx), p[-1]]) if keyid_nseg == 3 else fn)
                            url_mirrors = '\t'.join(['%s%s?sdtfrom=v1010&vkey=%s' % (url_prefix, cfilename, key_data.get('key')) for url_prefix in chosen_url_prefixes])
                            if url_mirrors: urls.append(url_mirrors)
                            if fc == idx or (not fc and keyid_nseg != 3): break
                    except:
                        return format_name, ext, urls
                if len(urls) > 0: format_name = ret_defn
            except: pass
        return format_name, ext, urls
    '''_getvideourlsp10201ts'''
    def _getvideourlsp10201ts(self, vid, definition, vurl, referrer, request_overrides: dict = None):
        urls, ext, format_name, request_overrides = [], None, None, request_overrides or {}
        cmd_nodejs = ['node', TencentVQQVideoClient.CKEY_FOR_ENCRYPT_JS_FILE_PATH]
        with subprocess.Popen(cmd_nodejs, bufsize=1, universal_newlines=True, encoding='utf-8', stdin=subprocess.PIPE, stdout=subprocess.PIPE) as node_proc:
            ckey_req = ' '.join([TencentVQQVideoClient.QQVideoPlatforms.P10201, TencentVQQVideoClient.APP_VERSION, vid, vurl, referrer])
            node_proc.stdin.write(ckey_req); node_proc.stdin.write(r'\n'); node_proc.stdin.flush()
            ckey_resp = node_proc.stdout.readline().rstrip(r'\r\n'); ckey, tm, guid, flowid = ckey_resp.split()
            vinfoparam = {
                'otype': 'ojson', 'isHLS': 1, 'charge': 0, 'fhdswitch': 0, 'show1080p': 1, 'defnpayver': 7, 'sdtfrom': 'v1010', 'host': 'v.qq.com', 'vid': vid, 'defn': definition, 'platform': TencentVQQVideoClient.QQVideoPlatforms.P10201, 'appVer': TencentVQQVideoClient.APP_VERSION,
                'refer': referrer, 'ehost': vurl, 'logintoken': json.dumps(self._getlogintokenfromcookies(self.default_cookies), separators=(',', ':')), 'encryptVer': TencentVQQVideoClient.CKEY_FOR_ENCRYPT_VERION, 'guid': guid, 'flowid': flowid, 'tm': tm, 'cKey': ckey, 'dtype': 3,
                'spau': 1, 'spaudio': 68, 'spwm': 1, 'sphls': 2, 'sphttps': 1, 'clip': 4, 'spsrt': 2, 'spvvpay': 1, 'spadseg': 3, 'spav1': 15, 'hevclv': 28, 'spsfrhdr': 100, 'spvideo': 1044,
            }
            params = {'buid': 'vinfoad', 'vinfoparam': urlencode(vinfoparam)}
            try:
                (resp := self.post(TencentVQQVideoClient.VIDEO_CONFIG_URL, json=params, **request_overrides)).raise_for_status()
                try: data: dict = (d := json.loads(resp.text)) and json.loads(d.get('vinfo'))
                except json.JSONDecodeError as e: return format_name, ext, urls
                if not (data and data.get('dltype')): return format_name, ext, urls
                url_prefixes = [(u if u.endswith('/') else u[:u.rfind('/') + 1]) for d in safeextractfromdict(data, ['vl', 'vi', 0, 'ul', 'ui'], []) if isinstance(d, dict) and (u := d.get('url'))]
                chosen_url_prefixes = [prefix for prefix in url_prefixes if prefix[:prefix.find('/', 8)].endswith('.tc.qq.com')]
                if not chosen_url_prefixes: chosen_url_prefixes = url_prefixes
                chosen_url_prefixes += [prefix for prefix in url_prefixes if prefix not in chosen_url_prefixes]
                drm, preview = safeextractfromdict(data, ['vl', 'vi', 0, 'drm'], None), data.get('preview')
                formats_id2nm = {fmt.get('id'): fmt.get('name') for fmt in safeextractfromdict(data, ['fl', 'fi'], [])}
                formats_nm2id = {fmt_nm: fmt_id for fmt_id, fmt_nm in formats_id2nm.items()}
                keyid = safeextractfromdict(data, ['vl', 'vi', 0, 'keyid'], ''); vfilename = safeextractfromdict(data, ['vl', 'vi', 0, 'fn'], '')
                vfn = vfilename.rpartition('.'); ext = vfn[-1]; ret_defn = ''
                if ext == 'ts':
                    if drm == 1 and not preview and not self.default_cookies: return format_name, ext, urls
                    key_format_id = keyid.split('.')[-1]
                    try: key_format_id = int(key_format_id); ret_defn = formats_id2nm.get(key_format_id) or ret_defn
                    except ValueError: pass
                    if not ret_defn:
                        for format_defn in self._sortdefinitions(formats_nm2id):
                            format_id = formats_nm2id.get(format_defn)
                            ckey_req = ' '.join([TencentVQQVideoClient.QQVideoPlatforms.P10201, TencentVQQVideoClient.APP_VERSION, vid, vurl, referrer, r'\n'])
                            node_proc.stdin.write(ckey_req); node_proc.stdin.flush()
                            ckey_resp = node_proc.stdout.readline().rstrip(r'\r\n'); ckey, tm, guid, flowid = ckey_resp.split()
                            vkeyparam = {'otype': 'ojson', 'vid': vid, 'format': format_id, 'filename': vfilename, 'platform': TencentVQQVideoClient.QQVideoPlatforms.P10201, 'appVer': TencentVQQVideoClient.APP_VERSION, 'sdtfrom': 'v1010', 'guid': guid, 'flowid': flowid, 'tm': tm, 'refer': referrer, 'ehost': vurl, 'logintoken': json.dumps(self._getlogintokenfromcookies(self.default_cookies), separators=(',', ':')), 'encryptVer': TencentVQQVideoClient.CKEY_FOR_ENCRYPT_VERION, 'cKey': ckey}
                            params = {'buid': 'onlyvkey', 'vkeyparam': urlencode(vkeyparam)}
                            try:
                                (resp := self.post(TencentVQQVideoClient.VIDEO_CONFIG_URL, json=params, **request_overrides)).raise_for_status()
                                try: key_data: dict = (d := json.loads(resp.text)) and json.loads(d.get('vkey'))
                                except json.JSONDecodeError: return format_name, ext, urls
                                if key_data and isinstance(key_data, dict):
                                    if not key_data.get('key'): return format_name, ext, urls
                                    if key_data.get('filename', '') and key_data.get('filename', '') == vfilename: ret_defn = format_defn; break
                            except:
                                return format_name, ext, urls
                    fc = safeextractfromdict(data, ['vl', 'vi', 0, 'fc'], None); start = 1
                    for idx in range(start, fc + 1): vfilename_new = '.'.join([vfn[0], str(idx), 'ts']); url_mirrors = '\t'.join(['%s%s?sdtfrom=v1010' % (prefix, vfilename_new) for prefix in chosen_url_prefixes]); urls.append(url_mirrors)
                else:
                    if drm == 1 and not self.default_cookies: return format_name, ext, urls
                    return self._getvideourlsp10201(vid, definition, vurl, referrer, request_overrides)
                format_name = ret_defn
            except: pass
        return format_name, ext, urls
    '''_getvideourls'''
    def _getvideourls(self, vid, definition, vurl, referrer, request_overrides: dict = None):
        request_overrides = request_overrides or {}
        try: return self._getvideourlsp10201ts(vid, definition, vurl, referrer, request_overrides)
        except: return self._getvideourlsp10201(vid, definition, vurl, referrer, request_overrides)
    '''_normalizeconfinfo'''
    def _normalizeconfinfo(self, text):
        nullified = TencentVQQVideoClient.NULLIFY_RE.sub(r'""', text)
        dquoted_vals = TencentVQQVideoClient.DOUBLE_QUOTE_VAL_RE.sub(r': "\1"', nullified)
        dquoted_keys = TencentVQQVideoClient.DOUBLE_QUOTE_KEY_RE.sub(r'"\1": ', dquoted_vals)
        return dquoted_keys
    '''_extractvideocoverinfo'''
    def _extractvideocoverinfo(self, regex: re.Pattern, text: str):
        result = (None, None); cover_match = regex.search(text)
        if not cover_match: return result
        info, cover_group = {}, self._normalizeconfinfo(cover_match.group(1) or cover_match.group(2) or cover_match.group(3))
        try: cover_info = json.loads(cover_group)
        except json.JSONDecodeError: return result
        if not (cover_info and isinstance(cover_info, dict)): return result
        info['title'] = cover_info.get('title', '') or cover_info.get('title_new', '')
        info['year'] = cover_info.get('year') or (cover_info.get('publish_date') or '').split('-')[0]
        info['cover_id'] = cover_info.get('cover_id', '') or cover_info.get('cid', '')
        info['episode_all'] = int(cover_info.get('episode_all') or 0)
        type_id = int(cover_info.get('type') or TencentVQQVideoClient.VideoTypeCodes.MOVIE)
        info['type'] = TencentVQQVideoClient.VQQ_TYPE_CODES.get(type_id, TencentVQQVideoClient.VideoTypes.MOVIE)
        if cover_info.get('vid') is None: normal_ids = [{'V': vid, 'E': ep, 'defns': {}} for ep, vid in enumerate(cover_info.get('video_ids') or [], start=1)]
        else: normal_ids = [{'V': cover_info.get('vid'), 'E': 1, 'defns': {}}]
        info['normal_ids'] = normal_ids; result = (info, cover_match.end())
        return result
    '''_getallloadedinfo'''
    def _getallloadedinfo(self, r_text):
        conf_info, ep_list, tabs = {}, [], []; match = TencentVQQVideoClient.ALL_LOADED_INFO_RE.search(r_text)
        if not match: return conf_info, ep_list, tabs
        matched = match.group(1) or match.group(2)
        matched_norm = re.sub(TencentVQQVideoClient.EP_LIST_RE, r'[{"list":[[\1]]', matched)
        matched_norm = self._normalizeconfinfo(matched_norm)
        try: conf_info = json.loads(matched_norm)
        except json.JSONDecodeError: return conf_info, ep_list, tabs
        if not conf_info: return conf_info, ep_list, tabs
        ep_list = safeextractfromdict(conf_info, ['episodeMain', 'listData', 0, 'list'], [])
        if ep_list: ep_list = ep_list[0]
        tabs = safeextractfromdict(conf_info, ['episodeMain', 'listData', 0, 'tabs'], [])
        return conf_info, ep_list, tabs
    '''_getpageeplist'''
    def _getpageeplist(self, cid, vid, request_overrides: dict = None):
        conf_info, ep_list, tabs, request_overrides = {}, [], [], request_overrides or {}
        query_params = {'vdevice_guid': TencentVQQVideoClient.DEVICE_ID, 'video_appid': "3000010", 'vversion_name': "8.5.96", 'vversion_platform': "2"}
        json_payload = {'page_params': {'ad_wechat_authorization_status': "0", 'req_from': "web_vsite", 'ad_exp_ids': "", 'pc_sdk_version': "", 'pc_oaid': "", 'new_mark_label_enabled': "1", 'pc_device_info': "", 'support_pc_yyb_mobile_app_engine': "0", 'pc_wegame_version': "", 'cid': cid, 'history_vid': None, 'vid': vid, 'is_pc_new_detail_page': "0", 'is_from_web_flyflow': "1"}, 'page_bypass_params': {'params': {'caller_id': "3000010", 'platform_id': "2"}, 'scene': "desk_detail", 'app_version': "", 'abtest_bypass_id': TencentVQQVideoClient.DEVICE_ID}, 'page_context': {}}
        try:
            (resp := self.post(TencentVQQVideoClient.VIDEO_GETPAGE_URL, json=json_payload, params=query_params)).raise_for_status()
            try: data = json.loads(resp.text)
            except json.JSONDecodeError: return conf_info, ep_list, tabs
            for card in safeextractfromdict(data, ['data', 'CardList'], []):
                if card['type'] == "pc_introduction": conf_info = safeextractfromdict(card, ['children_list', '0', 'cards', 0, 'params'], {})
                elif card['type'] == "pc_web_episode_list": tabs = card['params']['tabs']; tabs = json.loads(tabs) if tabs else []; ep_list = [safeextractfromdict(card, ['cards', 0, 'params'], None) for _, card in sorted(card['children_list'].items(), key=lambda x: int(x[0]))]
                else: continue
        except: pass
        return conf_info, ep_list, tabs
    '''_updatevideocoverinfo'''
    def _updatevideocoverinfo(self, cover_info, r_text, url_type, request_overrides: dict = None):
        update_from_eplist_func = lambda normal_ids, ep_list, vid2idx: [normal_ids[vid2idx[epv['vid']]].__setitem__('E', int(epv['title'])) for epv in ep_list]
        align_eps_func = lambda normal_ids, start, stop, shift: [normal_ids[i].__setitem__('E', normal_ids[i]['E'] + shift) for i in range(start, stop)]
        conf_info = self._getallloadedinfo(r_text)[0]
        if not conf_info: return
        year = safeextractfromdict(conf_info, ['introduction', 'introData', 'list', 0, 'item_params', 'year'], None) or safeextractfromdict(conf_info, ['introduction', 'introData', 'list', 0, 'item_params', 'show_year'], None) or safeextractfromdict(conf_info, ['introductionData', 'introductionData', 'year'], None)
        if year and (not cover_info['year'] or cover_info['year'] != year): cover_info['year'] = year
        current_cid, current_vid = conf_info['globalStore']['currentCid'], conf_info['globalStore']['currentVid']
        conf_info_page, selected_ep_list, tabs = self._getpageeplist(current_cid, current_vid, request_overrides)
        if len(selected_ep_list) >= len(cover_info['normal_ids']): cover_info['normal_ids'] = [{'V': item['vid'], 'E': ep, 'defns': {}, 'title': item.get('play_title') or item.get('union_title', '') if cover_info['type'] not in [TencentVQQVideoClient.VideoTypes.TV, ] else ''} for ep, item in enumerate(selected_ep_list, start=1)]
        if conf_info_page: (not cover_info['year'] and cover_info.__setitem__('year', conf_info_page.get('year') or "")); (not cover_info['title'] and cover_info.__setitem__('title', conf_info_page.get('title') or ""))
        if not cover_info['episode_all'] or cover_info['episode_all'] == len(cover_info['normal_ids']) or not selected_ep_list or not str(selected_ep_list[0].get('title', '')).isdecimal(): return
        v2i = {vi['V']: idx for idx, vi in enumerate(cover_info['normal_ids'])}
        if url_type == TencentVQQVideoClient.VideoURLType.PAGE or not tabs: update_from_eplist_func(cover_info['normal_ids'], selected_ep_list, v2i); return
        delay_request = SpinWithBackoff(); ep, shift = 0, 0
        for tab in sorted(tabs, key=lambda tab: int(tab['begin'])):
            page_context = TencentVQQVideoClient.PAGE_CONTEXT_RE.search(tab['page_context'])
            if not page_context: return
            cid, size = page_context.group('cid'), int(page_context.group('size'))
            if tab['selected']: update_from_eplist_func(cover_info['normal_ids'], selected_ep_list, v2i)
            else:
                if not (url_type == TencentVQQVideoClient.VideoURLType.COVER):
                    align_eps_func(cover_info['normal_ids'], ep, ep + size, shift)
                else:
                    if delay_request.nth > (TencentVQQVideoClient.MAX_PAGETAB_REQS - 1): align_eps_func(cover_info['normal_ids'], ep, len(cover_info['normal_ids']), shift); return
                    delay_request.sleep(); ep_list = self._getpageeplist(cid, cover_info['normal_ids'][ep]['V'], request_overrides)[1]
                    if not ep_list: align_eps_func(cover_info['normal_ids'], ep, len(cover_info['normal_ids']), shift); return
                    update_from_eplist_func(cover_info['normal_ids'], ep_list, v2i)
            ep += size; shift = cover_info['normal_ids'][ep-1]['E'] - ep
    '''_getcoverinfo'''
    def _getcoverinfo(self, cover_url, url_type, request_overrides: dict = None):
        try:
            (resp := self.get(cover_url)).raise_for_status(); resp.encoding = 'utf-8'
            try: image_url = BeautifulSoup(resp.text, 'lxml').find('meta', {'itemprop': 'thumbnailUrl'}).get('content')
            except Exception: image_url = None
            info, pos_end = self._extractvideocoverinfo(TencentVQQVideoClient.COVER_PAT_RE, resp.text)
            if not (info and info['normal_ids']): info, _ = self._extractvideocoverinfo(TencentVQQVideoClient.VIDEO_INFO_RE, resp.text[pos_end:] if info else resp.text)
            if not info: return info
            self._updatevideocoverinfo(info, resp.text, url_type, request_overrides)
            if not info['episode_all']: info['episode_all'] = len(info['normal_ids']) if info['normal_ids'] else 1
            info['referrer'], info['image_url'] = cover_url, image_url
        except: info = None; pass
        return info
    '''_getvideocoverinfo'''
    def _getvideocoverinfo(self, videourl, request_overrides: dict = None):
        for typ, pat in enumerate(TencentVQQVideoClient.VIDEO_URL_PATS, 1):
            match = pat.match(videourl)
            if not match: continue
            if typ in {1, 2}: cover_info = self._getcoverinfo(videourl, url_type=TencentVQQVideoClient.VideoURLType.COVER, request_overrides=request_overrides)
            elif typ in {3}: video_id = match.group(2); (cover_info := self._getcoverinfo(videourl, url_type=TencentVQQVideoClient.VideoURLType.PAGE, request_overrides=request_overrides)) and cover_info.__setitem__('normal_ids', [dic for dic in cover_info['normal_ids'] if dic['V'] == video_id])
            else: video_id = match.group(1); (cover_info := self._getcoverinfo(videourl, url_type=TencentVQQVideoClient.VideoURLType.PAGE, request_overrides=request_overrides)) and cover_info.__setitem__('normal_ids', ([{'V': video_id, 'E': 1, 'defns': {}}] if not cover_info['normal_ids'] else [dic for dic in cover_info['normal_ids'] if dic['V'] == video_id]))
            if cover_info:
                cover_info['url'] = videourl; cover_info['url_type'] = TencentVQQVideoClient.VideoURLType.COVER if typ in {1, 2} else TencentVQQVideoClient.VideoURLType.PAGE
                for vi in cover_info['normal_ids']:
                    if cover_info['cover_id'] and cover_info['cover_id'] != vi['V']: vi['url'] = "https://v.qq.com/x/cover/%s/%s.html" % (cover_info['cover_id'], vi['V']); vi['referrer'] = vi['url']
                    else: vi['url'] = "https://v.qq.com/x/page/%s.html" % vi['V']; vi['referrer'] = cover_info['referrer']
            return cover_info
    '''parsefromurl'''
    @useparseheaderscookies
    def parsefromurl(self, url: str, request_overrides: dict = None):
        # prepare
        request_overrides = request_overrides or {}
        video_info = VideoInfo(source=self.source, enable_nm3u8dlre=True)
        if not self.belongto(url=url): return [video_info]
        null_backup_title = yieldtimerelatedtitle(self.source)
        # try parse
        video_infos = []
        try:
            basic_info = self._getvideocoverinfo(videourl=url, request_overrides=request_overrides)
            video_title = legalizestring(basic_info['title'] or null_backup_title, replace_null_string=null_backup_title).removesuffix('.')
            for normal_id in basic_info['normal_ids']:
                raw_data = copy.deepcopy(basic_info); video_info_page = copy.deepcopy(video_info)
                format_name, ext, urls = self._getvideourls(normal_id['V'], 'uhd', normal_id['url'], normal_id['referrer'])
                if not format_name: continue
                raw_data['download_info'] = {'format_name': format_name, 'ext': ext, 'urls': urls}
                download_url = os.path.join(self.work_dir, self.source, f"{raw_data['cover_id']}-{normal_id['V']}.m3u8")
                writevodm3u8fortencent(segments=urls, out_path=download_url, pick="best", strategy="global_host", probe_timeout=3.0, samples_per_host=2, probe_workers=16, probe_method="head_then_range_get")
                video_info_page.update(dict(raw_data=raw_data, download_url=download_url, title=f'ep{len(video_infos)+1}-{video_title}' if len(basic_info['normal_ids']) > 1 else video_title, file_path=os.path.join(self.work_dir, self.source, f'ep{len(video_infos)+1}-{video_title}' if len(basic_info['normal_ids']) > 1 else video_title), ext=ext, identifier=f"{raw_data['cover_id']}-{normal_id['V']}", enable_nm3u8dlre=True, cover_url=raw_data.get('image_url')))
                video_infos.append(video_info_page)
        except Exception as err:
            err_msg = f'{self.source}.parsefromurl >>> {url} (Error: {err})'
            video_info.update(dict(err_msg=err_msg))
            video_infos.append(video_info)
            self.logger_handle.error(err_msg, disable_print=self.disable_print)
        # return
        return video_infos
    '''belongto'''
    @staticmethod
    def belongto(url: str, valid_domains: list[str] | set[str] = None):
        valid_domains = set(valid_domains or []) | {"v.qq.com"}
        return BaseVideoClient.belongto(url, valid_domains)


'''TencentVideoClient'''
class TencentVideoClient(BaseVideoClient):
    source = 'TencentVideoClient'
    def __init__(self, **kwargs):
        super(TencentVideoClient, self).__init__(**kwargs)
        self.vqq_video_client = TencentVQQVideoClient(**kwargs)
        self.default_parse_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        }
        self.default_download_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        }
        self.default_headers = self.default_parse_headers
        self._initsession()
    '''_getckey'''
    def _getckey(self, video_id, url, guid, app_version, platform):
        ua = self.default_headers['User-Agent']
        payload = (f'{video_id}|{int(time.time())}|mg3c3b04ba|{app_version}|{guid}|{platform}|{url[:48]}|{ua.lower()[:48]}||Mozilla|Netscape|Windows x86_64|00|')
        return AESAlgorithmWrapper.aescbcencryptbytes(bytes(f'|{sum(map(ord, payload))}|{payload}', 'utf-8'), b'Ok\xda\xa3\x9e/\x8c\xb0\x7f^r-\x9e\xde\xf3\x14', b'\x01PJ\xf3V\xe6\x19\xcf.B\xbb\xa6\x8c?p\xf9', padding_mode='whitespace').hex().upper()
    '''_getvinfo'''
    def _getvinfo(self, api_url, video_url, video_id, series_id, subtitle_format, video_format, video_quality, host='v.qq.com', referer='v.qq.com', app_version='3.5.57', platform='10901', request_overrides=None):
        request_overrides = request_overrides or {}
        guid = ''.join(random.choices(string.digits + string.ascii_lowercase, k=16))
        ckey = self._getckey(video_id, video_url, guid, app_version=app_version, platform=platform)
        params = {
            'vid': video_id, 'cid': series_id, 'cKey': ckey, 'encryptVer': '8.1', 'spcaptiontype': '1' if subtitle_format == 'vtt' else '0',
            'sphls': '2' if video_format == 'hls' else '0', 'dtype': '3' if video_format == 'hls' else '0', 'defn': video_quality, 'spsrt': '2',
            'sphttps': '1', 'otype': 'json', 'spwm': '1', 'hevclv': '28', 'drm': '40', 'spvideo': '4', 'spsfrhdr': '100', 'host': host, 'referer': referer,
            'ehost': video_url, 'appVer': app_version, 'platform': platform, 'guid': guid, 'flowid': ''.join(random.choices(string.digits + string.ascii_lowercase, k=32)),
        }
        resp = self.get(api_url, params=params, **request_overrides)
        resp.raise_for_status()
        vinfo = json_repair.loads(resp.text[resp.text.index('QZOutputJson=')+len('QZOutputJson='): -1])
        return vinfo
    '''_extractfromvinfo'''
    def _extractfromvinfo(self, vinfos):
        results: List[Dict[str, Any]] = []
        for api_response in vinfos:
            if not isinstance(api_response, dict): continue
            try: video_response = (api_response.get('vl') or {}).get('vi')[0]
            except Exception: continue
            if not isinstance(video_response, dict): continue
            ul = video_response.get('ul') or {}
            ui_list = ul.get('ui') or []
            if not ui_list: continue
            fl = api_response.get('fl') or {}
            fi_list = fl.get('fi') or []
            identifier = video_response.get('br')
            format_info = None
            for fi in fi_list:
                if not isinstance(fi, dict): continue
                if identifier is not None and fi.get('br') == identifier: format_info = fi; break
            if format_info is None and fi_list: format_info = fi_list[0]
            if format_info is None: format_info = {}
            format_id = format_info.get('name') or format_info.get('formatdefn')
            format_note = format_info.get('resolution') or format_info.get('cname')
            width = format_info.get('width') or video_response.get('vw')
            height = format_info.get('height') or video_response.get('vh')
            vbr = format_info.get('bandwidth')
            abr = format_info.get('audiobandwidth')
            fps = format_info.get('vfps')
            for video_format in ui_list:
                if not isinstance(video_format, dict): continue
                base_url = video_format.get('url') or ''
                if not base_url: continue
                hls: dict = video_format.get('hls')
                if hls: url, ext = base_url + hls.get('pt') or '', 'm3u8'
                elif '.m3u8' in base_url: url, ext = base_url, 'm3u8'
                else:
                    fn, vkey = video_response.get('fn') or '', video_response.get('fvkey') or ''
                    if fn and vkey: url, ext = f'{base_url}{fn}?vkey={vkey}', 'mp4'
                    else: url, ext = base_url, 'mp4'
                if not url: continue
                results.append({'url': url, 'ext': ext, 'format_id': format_id, 'format_note': format_note, 'width': width, 'height': height, 'vbr': vbr, 'abr': abr, 'fps': fps})
        return results
    '''parsefromurl'''
    @useparseheaderscookies
    def parsefromurl(self, url: str, request_overrides: dict = None):
        # prepare
        request_overrides = request_overrides or {}
        video_info = VideoInfo(source=self.source, enable_nm3u8dlre=True)
        if not self.belongto(url=url): return [video_info]
        null_backup_title = yieldtimerelatedtitle(self.source)
        # try parse
        try:
            # --basic info extract with different belong
            if self.belongto(url, {"v.qq.com"}):
                try:
                    video_infos: list[dict] = self.vqq_video_client.parsefromurl(url, request_overrides)
                    if any(((info.get("download_url") or "").upper() not in ("", "NULL")) for info in (video_infos or [])): return video_infos
                except:
                    video_infos = []
                api_url, app_version, platform, host, referer = 'https://h5vv6.video.qq.com/getvinfo', '3.5.57', '10901', 'v.qq.com', 'v.qq.com'
                m = re.match(r'https?://v\.qq\.com/x/(?:page|cover/(?P<series_id>\w+))/(?P<id>\w+)', url)
                video_id, series_id = m.group('id'), m.group('series_id')
                resp = self.get(url, **request_overrides)
                resp.raise_for_status()
                raw_data = re.search(r'window\.__(?:pinia|PINIA__)\s*=\s*({.*?})\s*;?\s*</script>', resp.text, flags=re.S).group(1)
                raw_data = json_repair.loads(raw_data)
            elif self.belongto(url, {"iflix.com"}):
                api_url, app_version, platform, host, referer = 'https://vplay.iflix.com/getvinfo', '3.5.57', '330201', 'www.iflix.com', 'www.iflix.com'
                m = re.match(r'https?://(?:www\.)?iflix\.com/(?:[^?#]+/)?play/(?P<series_id>\w+)(?:-[^?#]+)?/(?P<id>\w+)(?:-[^?#]+)?', url)
                video_id, series_id = m.group('id'), m.group('series_id')
                resp = self.get(url, **request_overrides)
                resp.raise_for_status()
                raw_data = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', resp.text, flags=re.S).group(1)
                raw_data = json_repair.loads(raw_data)
            elif self.belongto(url, {"wetv.vip"}):
                api_url, app_version, platform, host, referer = 'https://play.wetv.vip/getvinfo', '3.5.57', '4830201', 'wetv.vip', 'wetv.vip'
                m = re.match(r'https?://(?:www\.)?wetv\.vip/(?:[^?#]+/)?play/(?P<series_id>\w+)(?:-[^?#]+)?/(?P<id>\w+)(?:-[^?#]+)?', url)
                video_id, series_id = m.group('id'), m.group('series_id')
                resp = self.get(url, **request_overrides)
                resp.raise_for_status()
                raw_data = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', resp.text, flags=re.S).group(1)
                raw_data = json_repair.loads(raw_data)
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "html.parser")
            video_title = soup.title.string.split('_')[0].split('-')[0].strip().strip('“"”') if soup.title else None
            if not video_title:
                video_title = [t for t in searchdictbykey(raw_data, 'title') if t.strip() and len(t.strip()) > 1]
                video_title = video_title[0] if video_title else None
            # --get vinfos
            vinfos = [self._getvinfo(
                api_url=api_url, video_url=url, video_id=video_id, series_id=series_id, subtitle_format='srt', video_format='hls', video_quality='hd', 
                host=host, referer=referer, app_version=app_version, platform=platform, request_overrides=request_overrides
            )]
            qualities = [item.get('name') for item in vinfos[0]['fl']['fi'] if item.get('name')] or ('shd', 'fhd')
            for quality in qualities:
                if quality not in ('ld', 'sd', 'hd'):
                    try:
                        vinfos.append(self._getvinfo(
                            api_url=api_url, video_url=url, video_id=video_id, series_id=series_id, subtitle_format='vtt', video_format='hls', video_quality=quality, 
                            host=host, referer=referer, app_version=app_version, platform=platform, request_overrides=request_overrides
                        ))
                    except:
                        continue
            vinfos = [v for v in vinfos if v]
            raw_data['getvinfo'] = vinfos
            video_info.update(dict(raw_data=raw_data))
            # --reformat vinfos
            formatted_vinfos = self._extractfromvinfo(vinfos=vinfos)
            # --sorted by quality
            def _toint(v, default=0):
                try: return int(v)
                except Exception: return default
            def _inferheight(fmt: Dict[str, Any]):
                h = fmt.get('height')
                if h is not None: return _toint(h, 0)
                note = fmt.get('format_note') or ''
                m = re.search(r'(\d+)[pP]', note)
                if m: return _toint(m.group(1), 0)
                return 0
            def _inferwidth(fmt: Dict[str, Any], height: int):
                w = fmt.get('width')
                if w is not None: return _toint(w, 0)
                if height > 0: return int(height * 16 / 9)
                return 0
            def _qualitykey(fmt: Dict[str, Any]):
                h = _inferheight(fmt)
                w = _inferwidth(fmt, h)
                vbr = _toint(fmt.get('vbr'), 0)
                abr = _toint(fmt.get('abr'), 0)
                return (h, w, vbr, abr)
            sorted_formatted_vinfos: list[dict] = sorted(formatted_vinfos, key=_qualitykey, reverse=True)
            sorted_formatted_vinfos: list[dict] = [item for item in sorted_formatted_vinfos if item.get('url')]
            # --select the best and update video info
            download_url = sorted_formatted_vinfos[0]['url']
            video_info.update(dict(download_url=download_url))
            # --misc
            video_title = legalizestring(video_title or null_backup_title, replace_null_string=null_backup_title).removesuffix('.')
            guess_video_ext_result = FileTypeSniffer.getfileextensionfromurl(
                url=download_url, headers=self.default_download_headers, request_overrides=request_overrides, cookies=self.default_download_cookies,
            )
            ext = guess_video_ext_result['ext'] if guess_video_ext_result['ext'] and guess_video_ext_result['ext'] != 'NULL' else video_info['ext']
            video_info.update(dict(
                title=video_title, file_path=os.path.join(self.work_dir, self.source, f'{video_title}.{ext}'), ext=ext, guess_video_ext_result=guess_video_ext_result, identifier=f'{series_id}-{video_id}'
            ))
        except Exception as err:
            err_msg = f'{self.source}.parsefromurl >>> {url} (Error: {err})'
            video_info.update(dict(err_msg=err_msg))
            self.logger_handle.error(err_msg, disable_print=self.disable_print)
        # construct video infos
        video_infos = [video_info]
        # return
        return video_infos
    '''belongto'''
    @staticmethod
    def belongto(url: str, valid_domains: list[str] | set[str] = None):
        valid_domains = set(valid_domains or []) | TENCENT_SUFFIXES
        return BaseVideoClient.belongto(url, valid_domains)