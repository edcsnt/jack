# Copyright 2025 edcsnt. All rights reserved.

"""Functions to extract URLs from a Panda Video player."""

import re
from urllib.error import HTTPError

from jack.utils import fetch_file, is_str


def fetch_segments(url: str) -> list[str]:
    """Fetch video segment URLs in the highest resolution available.

    Panda Video's servers split videos into three-second segments and
    send them to clients. This may be an antipiracy measure.

    Since Panda Video remuxes videos into transport streams, the
    segments' raw bytes can simply be concatenated (or "spliced"), as
    Annex K of ISO/IEC 13818-1:2025 describes.

    :param url: Base video URL
    :type url: str
    :raises ValueError: Got binary data instead of M3U playlist
    :return: Ordered list of URLs, each corresponding to one segment
    """
    segs = []
    rl = (
        '2160p',
        '3840x2160',
        '1440p',
        '2560x1440',
        '1080p',
        '1920x1080',
        '720p',
        '1280x720',
        '480p',
        '842x480',
        '360p',
        '640x360',
    )

    for r in rl:
        res = f'{url}/{r}'
        try:
            plist = fetch_file(f'{res}/video.m3u8')
            break
        except HTTPError:
            pass

    if not is_str(plist):
        m = 'expected M3U playlist but got binary data'
        raise ValueError(m)

    for ln in plist.splitlines():
        if ln.endswith('.ts'):
            seg = f'{res}/{ln.rpartition("/")[-1]}'
            segs.append(seg)

    return segs


def fetch_subtitles(url: str) -> list[str]:
    """Fetch subtitles URLs for all available languages.

    :param url: Base video URL
    :type url: str
    :raises ValueError: Got binary data instead of M3U playlist
    :return: List of URLs, each corresponding to one subtitles file per
        language
    """
    subs: list[str] = []
    iso639 = r'[a-z][a-z](-[A-Z][A-Z]){0,1}'
    pattern = rf'URI="(subtitle_{iso639}\.m3u8)"'
    plist = fetch_file(f'{url}/playlist.m3u8')

    if not is_str(plist):
        msg = 'expected M3U playlist but got binary data'
        raise ValueError(msg)

    for m in re.finditer(pattern, plist):
        fn = m.group(1)
        lang = fetch_file(f'{url}/{fn}')

        if not is_str(lang):
            raise ValueError(msg)

        subs.extend(ln for ln in lang.splitlines() if ln.startswith('http'))

    return subs
