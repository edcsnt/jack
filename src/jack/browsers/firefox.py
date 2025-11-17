# Copyright 2025 edcsnt. All rights reserved.

"""Firefox-specific functions."""

import sqlite3
from contextlib import closing
from urllib.parse import urlsplit


def read_cookie(cookies: str, url: str) -> dict[str, str]:
    """Read ``cookies.sqlite`` and return cookie for specific host.

    :param cookies: Pathname of Firefox's ``cookies.sqlite``
    :type cookies: str
    :param url: Course platform URL
    :type url: str
    :return: Cookie dictionary to be consumed by WebDriver.add_cookie()
    """
    hvars = []
    sql = 'SELECT name, value FROM moz_cookies WHERE host = ?;'
    host = urlsplit(url).netloc.split('.')

    # generate host variants from most to least specific
    for offset in range(len(host) - 1):  # ignore TLDs
        subdom = '.'.join(host[offset:])
        # <https://www.rfc-editor.org/rfc/rfc6265#section-4.1.2.3>
        hvars.append(f'.{subdom}')
        hvars.append(subdom)

    with closing(sqlite3.connect(cookies)) as con:
        for hvar in hvars:
            if res := con.execute(sql, (hvar,)).fetchone():
                return {'name': res[0], 'value': res[1]}

    return {}
