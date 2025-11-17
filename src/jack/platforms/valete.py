# Copyright 2025 edcsnt. All rights reserved.

"""Functions to scrape content from Valete Plus.

Last confirmed working November 17, 2025.
"""

import asyncio
import json
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from typing import cast
from urllib.parse import unquote

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.relative_locator import locate_with
from selenium.webdriver.support.wait import WebDriverWait

from jack.providers.panda import fetch_segments, fetch_subtitles
from jack.utils import (
    DEBUG,
    INFO,
    WARNING,
    atomic_write,
    fetch_file,
    fetch_video,
    generate_paths,
    get_pseudo_prop,
    is_str,
    log,
    safe_guess_extension,
    slugify,
)

TIMEOUT = 30.0
SEL = {
    'audio': 'audio',
    'avatar': 'img.object-cover',
    'aviews': 'span.opacity-80',
    'blocked': 'a.rounded',
    'body': 'p > span',
    'ccover': 'body > div:first-of-type > div:first-of-type',
    'cdesc': '.md\\:text-sm',
    'cmt': 'li',
    'course': 'h3 > a',
    'cover': 'img.sticky',
    'cshow': 'button.text-blue-400',
    'cuser': 'p.font-semibold',
    'desc': '.prose',
    'doc': 'a[download]',
    'icon': 'img[src="/images/like.svg"]',
    'lesson': 'a.hover\\:scale-105',
    'likes': 'span.text-xs',
    'player': 'iframe[id^="panda"]',
    'plist': 'source',
    'rshow': '//*[contains(text(), "Mostrar")]',
    'ruser': 'p.font-medium',
    'shadow': 'div.py-6 div.hidden > div > div',
    'title': 'h1',
    'vviews': 'span.mt-0\\.5:nth-child(2)',
}


def scrape_course_cover(driver: WebDriver, pn: Path, pre: str = '') -> None:
    """Scrape course cover.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    paths = generate_paths(pn, 'image')
    for path in paths:
        if path.is_file():
            log(WARNING, f'{pre}course cover already ripped. Skipping')
            return

    elem = driver.find_element(By.CSS_SELECTOR, SEL['ccover'])
    url = get_pseudo_prop(driver, elem, '::before', 'background-image').split(
        '"'
    )[1]

    log(DEBUG, f'{pre}ripping course cover')
    f = fetch_file(url)
    ext = safe_guess_extension(url)
    atomic_write(f, pn.with_suffix(ext))


def scrape_course_page(
    driver: WebDriver, pn: Path, title: str, pre: str = ''
) -> None:
    """Scrape course title and description.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param pn: Pathname without suffix
    :type pn: Path
    :param title: Course title
    :type title: str
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    pnws = pn.with_suffix('.json')
    if pnws.is_file():
        log(WARNING, f'{pre}course page already ripped. Skipping')
        return

    page = {'title': title}

    with suppress(NoSuchElementException):
        page['description'] = driver.find_element(
            By.CSS_SELECTOR, SEL['cdesc']
        ).text

    log(DEBUG, f'{pre}ripping course page')
    f = json.dumps(page, ensure_ascii=False, indent=2)
    atomic_write(f, pnws)


def scrape_cover(driver: WebDriver, pn: Path, pre: str = '') -> None:
    """Scrape lesson cover.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    paths = generate_paths(pn, 'image')
    for path in paths:
        if path.is_file():
            log(WARNING, f'{pre}cover already ripped. Skipping')
            return

    url = driver.find_element(By.CSS_SELECTOR, SEL['cover']).get_attribute(
        'src'
    )
    if not is_str(url):
        log(WARNING, '{pre}cover image element without source. Skipping')
        return

    log(DEBUG, f'{pre}ripping cover')
    unq = unquote(url.split('url=')[-1].split('&')[0])
    f = fetch_file(unq)
    ext = safe_guess_extension(unq)
    atomic_write(f, pn.with_suffix(ext))


def scrape_avatar(elem: WebElement, outdir: str, user: str) -> None:
    """Scrape user avatar.

    :param elem: An instance of
        ``selenium.webdriver.remote.webelement.WebElement()``
    :type elem: WebElement
    :param outdir: Root directory of the WEBRip
    :type outdir: str
    :param user: Full name of the user
    :type user: str
    """
    try:
        url = elem.find_element(By.CSS_SELECTOR, SEL['avatar']).get_attribute(
            'src'
        )
    except NoSuchElementException:
        return
    if not is_str(url):
        return

    unq = unquote(url.split('url=')[-1].split('&')[0])

    pn = (
        Path(f'{outdir}/avatars/{slugify(user)}')
        if user
        else Path(f'{outdir}/avatars/{unq.split("/")[-1].split(".")[0]}')
    )
    paths = generate_paths(pn, 'image')
    for path in paths:
        if path.is_file():
            return

    f = fetch_file(unq)
    ext = safe_guess_extension(unq)
    atomic_write(f, pn.with_suffix(ext))


def scrape_page(
    driver: WebDriver, outdir: str, pn: Path, pre: str = ''
) -> None:
    """Scrape lesson title, description, and comments.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param outdir: Root directory of the WEBRip
    :type outdir: str
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    pnws = pn.with_suffix('.json')
    if pnws.is_file():
        log(WARNING, f'{pre}page already ripped. Skipping')
        return

    type Reply = dict[str, int | str]
    type Comment = defaultdict[str, int | str | list[Reply]]
    type Page = defaultdict[str, int | str | list[Comment]]

    page: Page = defaultdict(list)

    # scrape lesson title, description, likes, and views
    log(DEBUG, f'{pre}ripping page')
    page['title'] = driver.find_element(By.CSS_SELECTOR, SEL['title']).text
    page['description'] = driver.find_element(
        By.CSS_SELECTOR, SEL['desc']
    ).text
    page['likes'] = int(
        driver.find_element(
            locate_with(By.CSS_SELECTOR, SEL['likes']).below(
                driver.find_element(By.CSS_SELECTOR, SEL['icon'])
            )
        ).text
    )
    try:  # video lesson
        page['views'] = int(
            driver.find_element(By.CSS_SELECTOR, SEL['vviews']).text
        )
    except NoSuchElementException:  # audio lesson
        page['views'] = int(
            WebDriverWait(driver, TIMEOUT)
            .until(
                ec.presence_of_element_located(
                    (By.CSS_SELECTOR, SEL['aviews'])
                )
            )
            .text
        )

    # show all comments
    more = driver.find_elements(By.CSS_SELECTOR, SEL['cshow'])
    while more:  # pylint: disable=while-used
        more[0].click()
        more = driver.find_elements(By.CSS_SELECTOR, SEL['cshow'])

    # scrape lesson comments
    for thd in driver.find_elements(By.CSS_SELECTOR, SEL['cmt']):
        cmt: Comment = defaultdict(list)

        # scrape this comment's user, body, and likes
        cmt['user'] = thd.find_element(By.CSS_SELECTOR, SEL['cuser']).text
        cmt['body'] = thd.find_element(By.CSS_SELECTOR, SEL['body']).text
        cmt['likes'] = int(
            thd.find_element(By.CSS_SELECTOR, SEL['likes']).text
        )
        scrape_avatar(thd, outdir, cast('str', cmt['user']))

        # show all replies to this comment, if any
        with suppress(NoSuchElementException):
            thd.find_element(By.XPATH, SEL['rshow']).click()

        # scrape all replies to this comment, if any
        for shown in thd.find_elements(By.CSS_SELECTOR, SEL['cmt']):
            reply: Reply = {}

            # scrape this reply's user, body, and likes
            reply['user'] = shown.find_element(
                By.CSS_SELECTOR, SEL['ruser']
            ).text
            reply['body'] = shown.find_element(
                By.CSS_SELECTOR, SEL['body']
            ).text
            reply['likes'] = int(
                shown.find_element(By.CSS_SELECTOR, SEL['likes']).text
            )
            scrape_avatar(shown, outdir, cast('str', reply['user']))

            # nested replies are impossible

            cast('list[Reply]', cmt['replies']).append(reply)

        cast('list[Comment]', page['comments']).append(cmt)

    f = json.dumps(page, ensure_ascii=False, indent=2)
    atomic_write(f, pnws)


def scrape_video(url: str, pn: Path, pre: str = '') -> None:
    """Scrape lesson video.

    :param url: Base video URL
    :type url: str
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    # Processing M3U playlists to find the real extension is too costly.
    # Try well-known extensions instead.
    paths = generate_paths(pn, 'video')
    for path in paths:
        if path.is_file():
            log(WARNING, f'{pre}video already ripped. Skipping')
            return

    log(DEBUG, f'{pre}ripping video')
    segs = fetch_segments(url)
    f = asyncio.run(fetch_video(segs))
    ext = safe_guess_extension(segs[0])
    atomic_write(f, pn.with_suffix(ext))


def scrape_subtitles(urls: list[str], pn: Path, pre: str = '') -> None:
    """Scrape subtitles for video lesson.

    :param urls: List of subtitles URLs, one per available language
    :type urls: list[str]
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    for url in urls:
        lang = url.rpartition('/')[-1].partition('.')[0]
        pnwl = pn.with_stem(f'{pn.stem}_{lang.lower()}')

        # SubRip Text is not IANA-approved
        paths = [pnwl.with_suffix('.srt'), pnwl.with_suffix('.vtt')]
        for path in paths:
            if path.is_file():
                log(WARNING, f'{pre}{lang} subtitles already ripped. Skipping')
                return

        log(DEBUG, f'{pre}ripping {lang} subtitles')
        f = fetch_file(url)
        ext = safe_guess_extension(url)
        atomic_write(f, pnwl.with_suffix(ext))


def scrape_video_and_subtitles(
    driver: WebDriver, pn: Path, pre: str = ''
) -> None:
    """Scrape lesson video and subtitles.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    # Try to find the video player before everything else so that if
    # this is an audio lesson ``NoSuchElementException`` is raised
    # early.
    player = driver.find_element(By.CSS_SELECTOR, SEL['player'])

    driver.switch_to.frame(player)
    url = (
        WebDriverWait(driver, TIMEOUT)
        .until(ec.presence_of_element_located((By.CSS_SELECTOR, SEL['plist'])))
        .get_attribute('src')
    )
    driver.switch_to.default_content()

    if not is_str(url):
        log(WARNING, '{pre}video element without source. Skipping')
        return

    base = url.split('/playlist.m3u8')[0]
    scrape_video(base, pn, pre)

    langs = fetch_subtitles(base)
    scrape_subtitles(langs, pn, pre)


def scrape_document(driver: WebDriver, pn: Path, pre: str = '') -> None:
    """Scrape lesson document.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    pnws = pn.with_suffix('.pdf')
    if pnws.is_file():
        log(WARNING, f'{pre}document already ripped. Skipping')
        return

    url = driver.find_element(By.CSS_SELECTOR, SEL['doc']).get_attribute(
        'href'
    )
    if not is_str(url):
        log(
            WARNING,
            '{pre}document anchor without hypertext reference. Skipping',
        )
        return

    log(DEBUG, f'{pre}ripping document')
    f = fetch_file(url, driver=driver)
    atomic_write(f, pnws)


def scrape_audio(driver: WebDriver, pn: Path, pre: str = '') -> None:
    """Scrape lesson audio.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param pn: Pathname without suffix
    :type pn: Path
    :param pre: Optional prefix string to prepend to log messages
    :type pre: str
    """
    paths = generate_paths(pn, 'audio')
    for path in paths:
        if path.is_file():
            log(WARNING, f'{pre}audio already ripped. Skipping')
            return

    with suppress(NoSuchElementException):
        driver.find_element(By.CSS_SELECTOR, SEL['blocked'])
        log(WARNING, f'{pre}audio blocked. Skipping')
        return

    shadow = (
        WebDriverWait(driver, TIMEOUT)
        .until(
            ec.presence_of_element_located((By.CSS_SELECTOR, SEL['shadow']))
        )
        .shadow_root
    )
    # TODO: keep up with
    # <https://github.com/SeleniumHQ/selenium/issues/15697>
    WebDriverWait(shadow, TIMEOUT).until(  # type: ignore[type-var]
        ec.text_to_be_present_in_element_attribute(  # type: ignore[arg-type]
            (By.CSS_SELECTOR, SEL['audio']), 'src', ':'
        )
    )

    url = shadow.find_element(By.CSS_SELECTOR, SEL['audio']).get_attribute(
        'src'
    )
    if not is_str(url):
        log(WARNING, f'{pre}audio element without source. Skipping')

    log(DEBUG, f'{pre}ripping audio')
    f = fetch_file(url, driver=driver)
    try:
        ext = safe_guess_extension(url)
    except ValueError:  # blob
        ext = '.mp3'
    atomic_write(f, pn.with_suffix(ext))


def scrape_courses(driver: WebDriver, url: str, outdir: str) -> None:
    """Scrape all video and audio lessons of all courses.

    :param driver: An instance of
        ``selenium.webdriver.firefox.webdriver.WebDriver()``
    :type driver: WebDriver
    :param url: Course platform base URL
    :type url: str
    :param outdir: Directory to write scraped files to
    :type outdir: str
    """
    driver.get(f'{url}/cursos')
    Path(f'{outdir}/avatars').mkdir(parents=True, exist_ok=True)
    courses = [
        a.get_attribute('href')
        for a in driver.find_elements(By.CSS_SELECTOR, SEL['course'])
    ]

    for i, course in enumerate(courses):
        if not is_str(course):
            log(WARNING, 'course anchor without hypertext reference. Skipping')
            continue

        driver.get(course)
        cprog = f'[{i + 1:02}/{len(courses):02}] '
        ctitle = driver.find_element(By.CSS_SELECTOR, SEL['title']).text
        cpn = Path(f'{outdir}/{course.rpartition("/")[-1]}')
        cpn.mkdir(exist_ok=True)

        log(INFO, f'{cprog}ripping course {ctitle}')
        scrape_course_cover(driver, cpn, cprog)
        scrape_course_page(driver, cpn, ctitle, cprog)

        lessons = [
            a.get_attribute('href')
            for a in driver.find_elements(By.CSS_SELECTOR, SEL['lesson'])
        ]

        for j, lesson in enumerate(lessons):
            if not is_str(lesson):
                log(
                    WARNING,
                    'lesson anchor without hypertext reference. Skipping',
                )
                continue

            driver.get(lesson)
            prog = f'{cprog}[{j + 1:03}/{len(lessons):03}] '
            title = driver.find_element(By.CSS_SELECTOR, SEL['title']).text
            pn = Path(f'{cpn}/{j + 1:03}_{slugify(title)}')

            log(INFO, f'{prog}ripping lesson {title}')
            scrape_cover(driver, pn, prog)
            scrape_page(driver, outdir, pn, prog)

            # Valete Plus has two lesson types: video lessons and audio
            # lessons. Video lessons have a Panda Video player within an
            # iframe, while audio lessons have an audio element within a
            # shadow root. Audio lessons optionally have a document
            # available to download.
            # The audio files are AI-generated text-to-speech versions
            # of the documents.
            try:
                scrape_video_and_subtitles(driver, pn, prog)
            except NoSuchElementException:
                with suppress(NoSuchElementException):
                    scrape_document(driver, pn, prog)
                scrape_audio(driver, pn, prog)
