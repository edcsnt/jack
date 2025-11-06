#!/usr/bin/env python3
# Copyright 2025 edcsnt. All rights reserved.
import argparse
import asyncio
import base64
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import unicodedata
import urllib.request
from urllib.parse import urlsplit

import aiohttp
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.relative_locator import locate_with
from selenium.webdriver.support.wait import WebDriverWait

SUPPORTED = ['valete']
TIMEOUT = 15.0

parser = argparse.ArgumentParser(
    description='rip courses off course platforms',
)
parser.add_argument(
    '-o',
    default='.',
    help='directory to write ripped files to',
    metavar='outdir',
    dest='outdir',
)
parser.add_argument('cookies', help="path to Firefox's cookies.sqlite")
parser.add_argument('url', help='course platform URL')
args = parser.parse_args()

logger = logging.getLogger(__name__)


def log(logger: logging.Logger, lvl: int, m: str) -> None:
    if sys.stderr.isatty():
        r = '\033[1;31m'
        g = '\033[0;32m'
        b = '\033[0;34m'
        y = '\033[0;33m'
        z = '\033[0m'
    else:
        r = ''
        g = ''
        b = ''
        y = ''
        z = ''

    match lvl:
        case 15: logger.info(f'{b}+ {m}{z}')
        case 20: logger.info(f'{g}* {m}{z}')
        case 30: logger.warning(f'{y}? {m}{z}')
        case 50: logger.critical(f'{r}! {m}{z}')


def atomic_write(data: str | bytes, pn: Path) -> None:
    s = isinstance(data, str)
    with tempfile.NamedTemporaryFile(
            'w' if s else 'wb',
            encoding='utf-8' if s else None,
            dir=pn.parent,
            delete=False,
    ) as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    Path(f.name).replace(pn)


def slugify(s: str) -> str:
    return re.sub(
        r'[ ][ ]*',
        '_',
        re.sub(
            r'[^ 0-9A-Z_a-z-]',
            '',
            unicodedata.normalize(
                'NFKD',
                s,
            ).encode('ascii', 'ignore').decode('ascii').lower(),
        ),
    )[:32].strip('-_')


def read_cookie(cookies: str, url: str) -> dict[str, str]:
    cookie = {}
    hvars = []
    sql = 'SELECT name, value FROM moz_cookies WHERE host = ?;'
    host = urlsplit(url).netloc.split('.')

    while len(host) > 1:  # ignore TLDs
        # <https://www.rfc-editor.org/rfc/rfc6265#section-4.1.2.3>
        hvars.append('.'.join(('', *host)))
        hvars.append('.'.join(host))
        del host[0]

    with closing(sqlite3.connect(cookies)) as con:
        while not cookie and len(hvars):
            try:
                cookie['name'], cookie['value'] = con.execute(
                    sql,
                    (hvars[0],),
                ).fetchone()
            except TypeError:  # no cookies for that host variant
                pass
            del hvars[0]

    return cookie


def fetch_binary(driver: WebDriver, url: str) -> bytes:
    fetch_blob = """
        const url = arguments[0];
        const callback = arguments[arguments.length - 1];

        fetch(url).then(res => { return res.bytes(); }).then(
          B => { return B.toBase64(); },
        ).then(callback);
    """

    if url.startswith('blob:'):
        return base64.b64decode(driver.execute_async_script(fetch_blob, url))
    else:
        with urllib.request.urlopen(url) as f: return f.read()


def fetch_segments(url: str, provider: str) -> list[str]:
    segs = []

    with urllib.request.urlopen(url) as f:
        plist = f.read().decode().splitlines()
    for line in plist:
        if 'video.m3u8' in line:
            res = line

    with urllib.request.urlopen(url.replace('playlist.m3u8', res)) as f:
        plist = f.read().decode().splitlines()
    for line in plist:
        if provider in line:
            segs.append(line)

    return segs


async def fetch_video_segment(s: aiohttp.ClientSession, seg: str) -> bytes:
    async with s.get(seg) as r: return await r.read()


async def fetch_video(segs: list[str]) -> bytes:
    async with aiohttp.ClientSession() as s:
        return b''.join(
            await asyncio.gather(
                *[fetch_video_segment(s, seg) for seg in segs],
            ),
        )


def fetch_page(driver: WebDriver) -> str:
    lesson = {'comments': []}
    lesson['title'] = driver.find_element(By.CSS_SELECTOR, 'h1').text
    article = driver.find_element(By.CSS_SELECTOR, 'article').text
    lesson['description'] = '\n\n'.join(
        [article]
        if article
        else [
            p.text
            for p
            in driver.find_elements(By.CSS_SELECTOR, 'article > p')
        ]
    )
    lesson['likes'] = int(
        driver.find_element(
            locate_with(
                By.CSS_SELECTOR,
                'span.text-xs',
            ).below(
                driver.find_element(
                    By.CSS_SELECTOR,
                    'img[src="/images/like.svg"]',
                ),
            ),
        ).text,
    )
    try:  # video lesson
        lesson['views'] = int(
            driver.find_element(
                By.CSS_SELECTOR,
                'span.mt-0\\.5:nth-child(2)',
            ).text,
        )
    except NoSuchElementException:  # audio lesson
        lesson['views'] = int(
            WebDriverWait(driver, TIMEOUT).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'span.opacity-80'),
                ),
            ).text,
        )

    while True:
        try:
            driver.find_element(
                By.CSS_SELECTOR,
                'button.text-blue-400',
            ).click()
        except NoSuchElementException:
            break

    for thread in driver.find_elements(By.CSS_SELECTOR, 'li'):
        comment = {'replies': []}
        comment['user'] = thread.find_element(
            By.CSS_SELECTOR,
            'p.font-semibold',
        ).text
        comment['body'] = ' '.join(
            [
                span.text
                for span
                in thread.find_elements(By.CSS_SELECTOR, 'p > span')
            ],
        )
        comment['likes'] = int(
            thread.find_element(By.CSS_SELECTOR, 'span.text-xs').text,
        )

        try:
            thread.find_element(
                By.XPATH,
                '//*[contains(text(), "Mostrar")]',
            ).click()
        except NoSuchElementException:
            pass

        for shown in thread.find_elements(By.CSS_SELECTOR, 'li'):
            reply = {}
            reply['user'] = shown.find_element(
                By.CSS_SELECTOR,
                'p.font-medium',
            ).text
            reply['body'] = ' '.join(
                [
                    span.text
                    for span
                    in shown.find_elements(By.CSS_SELECTOR, 'p > span')
                ],
            )
            reply['likes'] = int(
                shown.find_element(By.CSS_SELECTOR, 'span.text-xs').text,
            )
            comment['replies'].append(reply)

        lesson['comments'].append(comment)

    return json.dumps(lesson, ensure_ascii=False, indent=2)


def valete(driver: WebDriver, url: str) -> None:
    """Working as of November 4, 2025."""
    sel = {
        'course': 'h3 > a',
        'lesson': 'a.hover\\:scale-105',
        'title': 'h1',
        'iframe': 'iframe[id^="panda"]',
        'shadow': 'div.py-6 div.hidden > div > div',
        'audio': 'audio',
        'document': 'a[download]',
    }

    driver.get(f'{url}/cursos')
    courses = [
        a.get_attribute('href')
        for a
        in driver.find_elements(By.CSS_SELECTOR, sel['course'])
    ]

    for i, course in enumerate(courses):
        driver.get(course)
        log(
            logger,
            logging.INFO,
            (
                f'[{i + 1:02}/{len(courses):02}] ripping course '
                f'{driver.find_element(By.CSS_SELECTOR, "h1").text}...'
            ),
        )
        lessons = [
            a.get_attribute('href')
            for a
            in driver.find_elements(By.CSS_SELECTOR, sel['lesson'])
        ]

        for i, lesson in enumerate(lessons):
            n = f'{i + 1:03}'
            pre = f'        [{n}/{len(lessons):03}]'

            driver.get(lesson)
            log(
                logger,
                logging.INFO,
                (
                    f'{pre} ripping lesson '
                    f'{driver.find_element(By.CSS_SELECTOR, "h1").text}...'
                ),
            )
            pn = Path(
                f'{args.outdir}'
                f'/{course.rpartition("/")[-1]}'
                f'/{n}_{slugify(
                    driver.find_element(By.CSS_SELECTOR, sel["title"]).text,
                )}',
            )
            pn.parent.mkdir(parents=True, exist_ok=True)

            cov = pn.with_suffix('.webp')
            if cov.is_file():
                log(logger, logging.WARNING, f'{pre} cover already ripped')
            else:
                log(logger, 15, f'{pre} ripping cover...')
                atomic_write(
                    fetch_binary(
                        driver,
                        driver.find_element(
                            By.CSS_SELECTOR,
                            'img.sticky',
                        ).get_attribute('src'),
                    ),
                    cov,
                )

            page = pn.with_suffix('.json')
            if page.is_file():
                log(logger, logging.WARNING, f'{pre} page already ripped')
            else:
                log(logger, 15, f'{pre} ripping page...')
                atomic_write(fetch_page(driver), page)

            try:
                driver.switch_to.frame(
                    driver.find_element(By.CSS_SELECTOR, sel['iframe']),
                )
                segs = fetch_segments(
                    WebDriverWait(driver, TIMEOUT).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, 'source'),
                        ),
                    ).get_attribute('src'),
                    'panda',
                )
                driver.switch_to.default_content()

                vid = pn.with_suffix('.ts')
                if vid.is_file():
                    log(logger, logging.WARNING, f'{pre} video already ripped')
                else:
                    log(logger, 15, f'{pre} ripping video...')
                    atomic_write(asyncio.run(fetch_video(segs)), vid)
            except NoSuchElementException:
                shadow = WebDriverWait(driver, TIMEOUT).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, sel['shadow']),
                    ),
                ).shadow_root
                try:
                    doc = pn.with_suffix('.pdf')
                    if doc.is_file():
                        log(
                            logger,
                            logging.WARNING,
                            f'{pre} document already ripped',
                        )
                    else:
                        log(logger, 15, f'{pre} ripping document...')
                        atomic_write(
                            fetch_binary(
                                driver,
                                driver.find_element(
                                    By.CSS_SELECTOR,
                                    sel['document'],
                                ).get_attribute('href'),
                            ),
                            doc,
                        )
                except NoSuchElementException:
                    pass
                WebDriverWait(shadow, TIMEOUT).until(
                    EC.text_to_be_present_in_element_attribute(
                        (By.CSS_SELECTOR, sel['audio']),
                        'src',
                        ':',
                    ),
                )
                aud = pn.with_suffix('.mp3')
                if aud.is_file():
                    log(logger, logging.WARNING, f'{pre} audio already ripped')
                else:
                    log(logger, 15, f'{pre} ripping audio...')
                    atomic_write(
                        fetch_binary(
                            driver,
                            shadow.find_element(
                                By.CSS_SELECTOR,
                                sel['audio'],
                            ).get_attribute('src'),
                        ),
                        aud,
                    )


def main() -> None:
    logging.basicConfig(format='%(message)s', level=logging.INFO)

    platform = None
    while SUPPORTED and not platform:
        platform = re.search(SUPPORTED[0], args.url)
        del SUPPORTED[0]
    if not platform:
        log(logger, logging.CRITICAL, 'course platform not supported')
        sys.exit(1)

    cookie = read_cookie(args.cookies, args.url)
    if not cookie:
        log(
            logger,
            logging.CRITICAL,
            'cookie not found for URL. Log in and try again',
        )
        sys.exit(1)

    with webdriver.Firefox() as driver:
        driver.get(args.url)
        driver.add_cookie(cookie)
        globals()[platform.re.pattern](driver, args.url)
        log(logger, logging.INFO, 'WEBRip complete')


if __name__ == '__main__':
    main()
