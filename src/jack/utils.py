# Copyright 2025 edcsnt. All rights reserved.

"""Utility functions."""

import asyncio
import base64
import logging
import mimetypes
import os
import re
import sys
import tempfile
import unicodedata
import urllib.request
from pathlib import Path
from typing import TypeIs

import aiohttp
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

DEBUG = 10
INFO = 20
WARNING = 30
TIMEOUT = 600.0

if sys.stderr.isatty():
    G = '\033[0;32m'
    B = '\033[0;34m'
    Y = '\033[0;33m'
    Z = '\033[0m'
else:
    G = ''
    B = ''
    Y = ''
    Z = ''

logger = logging.getLogger(__name__)


def log(lvl: int, m: str) -> None:
    """Log message with color for terminals that support it.

    :param lvl: Logging level
    :type lvl: int
    :param m: Log message
    :type m: str
    """
    match lvl:
        case 10:
            logger.info(m, extra={'beg': B, 'pre': '+', 'end': Z})
        case 20:
            logger.info(m, extra={'beg': G, 'pre': '*', 'end': Z})
        case 30:
            logger.warning(m, extra={'beg': Y, 'pre': '?', 'end': Z})


def is_str(x: object) -> TypeIs[str]:
    """Test if object is a string.

    :param x: Object to test
    :type x: object
    :return: Whether the object is a string or not
    """
    return isinstance(x, str)


def slugify(s: str) -> str:
    """Generate ASCII filename from Unicode string.

    :param s: Unicode string to transform into filename
    :type s: str
    :return: Slugified ASCII string to serve as a filename
    """
    return re.sub(
        r'[ ][ ]*',
        '_',
        re.sub(
            r'[^ 0-9A-Z_a-z-]',
            '',
            unicodedata.normalize('NFKD', s)
            .encode('ascii', 'ignore')
            .decode('ascii')
            .lower(),
        ),
    )[:32].strip('-_')


def safe_guess_extension(url: str) -> str:
    """Guess filename extension from URL.

    :param url: URL to guess extension from
    :type url: str
    :raises ValueError: Could not determine the media type or extension
        of the URL
    :return: Guessed extension
    """
    pref = {
        # video/MP2T
        '.m2t': '.ts',
        '.m2ts': '.ts',
        '.mts': '.ts',
        '.tts': '.ts',
    }

    if not (typ := mimetypes.guess_type(url)[0]):
        m = f'could not determine the media type of {url}'
        raise ValueError(m)

    if not (ext := mimetypes.guess_extension(typ)):
        m = f'could not determine the extension of {typ}'
        raise ValueError(m)

    try:
        return pref[ext]
    except KeyError:
        return ext


def generate_paths(pn: Path, typ: str) -> list[Path]:
    """Return the list of all possible pathnames for a media type.

    :param pn: Pathname without suffix
    :type pn: Path
    :param typ: Media type with or without subtype
    :type typ: str
    :raises ValueError: An invalid media type was passed
    :return: List of pathnames, each suffixed by the extension of one
        media type
    """
    safetyp = typ.rstrip('/')

    if len(safetyp.split('/')) > 1:
        if not (ext := mimetypes.guess_extension(typ)):
            m = f'{typ} is not a valid media type'
            raise ValueError(m)
        return [pn.with_suffix(ext)]

    # ``mimetypes``' default media types are incomplete:
    # <https://github.com/python/cpython/blob/ebf955df7a89ed0c7968f79faec1de49f61ed7cb/Lib/mimetypes.py#L470-L692>
    if mimetypes._db is None:  # type: ignore[attr-defined]  # noqa: SLF001  # pylint: disable=protected-access
        mimetypes.init()
    mtypes = mimetypes.types_map.items()
    exts = [ext for ext, mtype in mtypes if mtype.startswith(safetyp)]

    return [pn.with_suffix(ext) for ext in exts]


def get_pseudo_prop(
    driver: WebDriver, elem: WebElement, pseudo: str, prop: str
) -> str:
    """Return CSS property value of pseudo-element.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param elem: An instance of
        ``selenium.webdriver.remote.webelement.WebElement()``
    :type elem: WebElement
    :param pseudo: Pseudo-element to get CSS property value from
    :type pseudo: str
    :param prop: Name of CSS property whose value to get
    :type prop: str
    :raises RuntimeError: The script did not return a string
    :return: CSS property value of pseudo-element
    """
    script = """
        const element = arguments[0];
        const pseudo = arguments[1];
        const property = arguments[2];

        const style = window.getComputedStyle(element, pseudo);
        const value = style.getPropertyValue(property);

        return value;
    """

    val = driver.execute_script(script, elem, f'::{pseudo.lstrip(":")}', prop)
    if not is_str(val):
        m = 'script did not return a string'
        raise RuntimeError(m)

    return val


def atomic_write(buf: str | bytes, pn: Path) -> None:
    """Atomically write buffer to file.

    :param buf: Data buffer to write
    :type buf: str | bytes
    :param pn: Pathname of file to write buffer to
    :type pn: Path
    """
    s = is_str(buf)
    with tempfile.NamedTemporaryFile(
        'w' if s else 'wb',
        encoding='utf-8' if s else None,
        dir=pn.parent,
        delete=False,
    ) as fp:
        fp.write(buf)
        # <https://docs.python.org/3/library/os.html#os.fsync>
        fp.flush()
        os.fsync(fp.fileno())
    # <https://pubs.opengroup.org/onlinepubs/9699919799.2018edition/functions/rename.html#tag_16_487_08>
    Path(fp.name).replace(pn)


def fetch_file(url: str, **kwargs: WebDriver) -> str | bytes:
    """Fetch binary or plain-text file from URL.

    :param url: URL of file to fetch
    :type url: str
    :param kwargs: Additional keyword arguments
    :type **kwargs: WebDriver
    :raises RuntimeError: A blob URL was passed without a WebDriver
    :raises ValueError: A URL with an invalid scheme was passed
    :return: Binary or plain-text file as bytes or string, respectively

    :Keyword Arguments:
        * driver (WebDriver): Selenium WebDriver object
    """
    driver = kwargs.get('driver')
    script = """
        const url = arguments[0];
        const callback = arguments[arguments.length - 1];

        fetch(url).then(res => { return res.bytes(); }).then(
          B => { return B.toBase64(); },
        ).then(callback);
    """
    # <https://github.com/file/file/blob/b310a0c2d3e4a1c12d579ad5c0266f1092a91340/src/encoding.c#L183-L260>
    text_chars = bytes(
        {7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F}
    )

    if url.startswith('blob:https:'):
        if not driver:
            m = "'blob:https:' URLs require a Selenium driver"
            raise RuntimeError(m)
        file = base64.b64decode(driver.execute_async_script(script, url))
    elif url.startswith('https:'):
        with urllib.request.urlopen(url) as f:  # noqa: S310
            file = f.read()
    else:
        m = "URL must start with 'blob:https:' or 'https:'"
        raise ValueError(m)

    if file.translate(None, text_chars):
        return file

    return file.decode()


async def fetch_video_segment(s: aiohttp.ClientSession, seg: str) -> bytes:
    """Fetch video segment.

    :param s: aiohttp client session
    :type s: aiohttp.ClientSession
    :param seg: URL of a video segment
    :type seg: str
    :return: A single video segment
    """
    async with s.get(seg) as r:
        return await r.read()


async def fetch_video(segs: list[str]) -> bytes:
    """Fetch video by joining its segments.

    :param segs: URLs of video segments
    :type segs: list[str]
    :return: The full video
    """
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        video = await asyncio.gather(
            *[fetch_video_segment(s, seg) for seg in segs]
        )
    return b''.join(video)
