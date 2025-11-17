#!/usr/bin/env python3
# Copyright 2025 edcsnt. All rights reserved.

"""Argument handling and driver code."""

import argparse
import logging
import re

from selenium import webdriver

from jack.browsers import firefox
from jack.platforms import SUPPORTED, valete
from jack.utils import INFO, log

parser = argparse.ArgumentParser(
    description='rip courses off course platforms'
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


def main() -> None:
    """Entry point for the jack script.

    :raises ValueError: Course platform not supported
    :raises RuntimeError: Cookie for host not found in
        ``cookies.sqlite``
    """
    logging.basicConfig(
        format='%(beg)s%(pre)s %(message)s%(end)s', level=logging.INFO
    )

    platform = next((re.search(pf, args.url) for pf in SUPPORTED), None)
    if not platform:
        m = 'course platform not supported'
        raise ValueError(m)

    if not (cookie := firefox.read_cookie(args.cookies, args.url)):
        m = 'cookie not found for URL. Log in and try again'
        raise RuntimeError(m)

    with webdriver.Firefox() as driver:
        driver.get(args.url)
        driver.add_cookie(cookie)

        match platform.re.pattern:
            case 'valete':
                valete.scrape_courses(driver, args.url, args.outdir)

    log(INFO, 'WEBRip complete')


if __name__ == '__main__':
    main()
