#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""moin2git.py

A tool to migrate the content of a MoinMoin wiki to a Git based system
like Waliki, Gollum or similar.

Usage:
  moin2git.py migrate <data_dir> <git_repo> [--convert-to-rst]
  moin2git.py users <data_dir>
  moin2git.py attachments <data_dir> <dest_dir>

Arguments:
    data_dir  Path where your MoinMoin content are
    git_repo  Path to the target repo (created if it doesn't exist)
    dest_dir  Path to copy attachments (created if it doesn't exist)
"""
from sh import git, python, ErrorReturnCode_1
import docopt
import os
import re
import json
from datetime import datetime
from urllib2 import unquote
import shutil

import sys
from distutils.version import LooseVersion
import MoinMoin
import MoinMoin.version
MOIN_VERSION = LooseVersion(MoinMoin.version.release)
if MOIN_VERSION >= "1.9":
    sys.path.append(os.path.join(os.path.dirname(MoinMoin.__file__),
                                 'support'))
from MoinMoin.Page import Page
from MoinMoin import wikiutil


__version__ = "0.1"
PACKAGE_ROOT = os.path.abspath(os.path.dirname(__file__))


if MOIN_VERSION >= "1.9":
    from MoinMoin.web.contexts import ScriptContext as Request
else:
    from MoinMoin.request.request_cli import Request

class MyRequest(Request):
    def __init__(self, *args, **kwargs):
        super(MyRequest, self).__init__(*args, **kwargs)
        self._my_lines = []

    def write(self, text):
        self._my_lines += [text]

    def normalizePagename(self, name):
        return name

    def normalizePageURL(self, name, url):
        return name

class MyPage(Page):
    def __init__(self, *args, **kwargs):
        self._my_body = None
        if 'mybody' in kwargs:
            self._my_body = kwargs.pop('mybody')
        super(MyPage, self).__init__(*args, **kwargs)

    def get_body(self):
        if self._my_body is not None:
            return self._my_body
        else:
            return super(MyPage, self).get_body()
    body = property(fget=get_body, fset=Page.set_body)

def _unquote(encoded):
    """
    >>> _unquote("Tom(c3a1)s(20)S(c3a1)nchez(20)Garc(c3ad)a")
    Tomás Sánchez García
    """
    chunks = re.findall('\(([a-f0-9]{2,4})\)', encoded)
    for chunk in chunks:
        encoded = encoded.replace('(' + chunk + ')', '%' + "%".join(re.findall('..', chunk)))
    return unquote(encoded)


def parse_users(data_dir=None):
    if not data_dir:
        data_dir = arguments['<data_dir>']
    users = {}
    users_dir = os.path.join(data_dir, 'user')
    for autor in os.listdir(users_dir):
        try:
            data = open(os.path.join(users_dir, autor)).read()
        except IOError:
            continue

        users[autor] = dict(re.findall(r'^([a-z_]+)=(.*)$', data, flags=re.MULTILINE))
    return users


def convert_rst(directory, page, body):
    page = page.decode('utf-8')

    old_cwd = os.getcwd()
    old_sys_path = sys.path
    os.chdir(directory)
    sys.path = [ os.getcwd(), ] + sys.path

    request = MyRequest(url=page, pagename=page)

    Formatter = wikiutil.importPlugin(request.cfg, "formatter",
                                      "text_x-rst", "Formatter")
    formatter = Formatter(request)
    request.formatter = formatter

    page = MyPage(request, page, rev=0, formatter=formatter, mybody=body.decode('utf-8'))
    if not page.exists():
        raise RuntimeError("No page named %r" % ( args.page, ))

    page.send_page()

    os.chdir(old_cwd)
    sys.path = old_sys_path

    return u''.join(request._my_lines).encode('utf-8')

def get_versions(page, users=None, data_dir=None, convert=False):
    if not data_dir:
        data_dir = arguments['<data_dir>']
    if not users:
        users = parse_users(data_dir)
    versions = []
    path = os.path.join(data_dir, 'pages', page)
    log = os.path.join(path, 'edit-log')
    if not os.path.exists(log):
        return versions
    log = open(log).read()
    if not log.strip():
        return versions

    basedir = os.path.abspath(os.path.join(data_dir, '..', '..'))

    logs_entries = [l.split('\t') for l in log.split('\n')]
    for entry in logs_entries:
        if len(entry) != 9:
            continue
        try:
            content = open(os.path.join(path, 'revisions', entry[1])).read()
        except IOError:
            continue

        content = convert_rst(basedir, _unquote(page), content)

        date = datetime.fromtimestamp(int(entry[0][:-6]))
        comment = entry[-1]
        email = users.get(entry[-3], {}).get('email', 'an@nymous.com')
        # look for name, username. default to IP
        name = users.get(entry[-3], {}).get('name', None) or users.get(entry[-3], {}).get('username', entry[-5])

        versions.append({'date': date, 'content': content,
                         'author': "%s <%s>" % (name, email),
                         'm': comment,
                         'revision': entry[1]})

    return versions


def migrate_to_git():
    users = parse_users()
    git_repo = arguments['<git_repo>']

    if not os.path.exists(git_repo):
        os.makedirs(git_repo)
    if not os.path.exists(os.path.join(git_repo, '.git')):
        git.init(git_repo)

    data_dir = os.path.abspath(arguments['<data_dir>'])
    root = os.path.join(data_dir, 'pages')
    pages = os.listdir(root)
    os.chdir(git_repo)
    for page in pages:
        versions = get_versions(page, users=users, data_dir=data_dir)
        if not versions:
            print("### ignoring %s (no revisions found)" % page)
            continue
        path = _unquote(page) + '.rst'
        print("### Creating %s\n" % path)
        dirname, basename = os.path.split(path)
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname)

        for version in versions:
            print("revision %s" % version.pop('revision'))
            with open(path, 'w') as f:
                f.write(version.pop('content'))
            try:
                git.add(path)
                git.commit(path, allow_empty_message=True, **version)
            except:
                pass


def copy_attachments():
    dest_dir = arguments['<dest_dir>']

    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)

    root = os.path.abspath(os.path.join(arguments['<data_dir>'], 'pages'))
    pages = os.listdir(root)
    # os.chdir(dest_dir)
    for page in pages:
        attachment_dir = os.path.join(root, page, 'attachments')
        if not os.path.exists(attachment_dir):
            continue
        print("Copying attachments for %s" % page)
        path = _unquote(page)
        dest_path = os.path.join(dest_dir, path)
        if not os.path.exists(dest_path):
            os.makedirs(dest_path)
        for f in os.listdir(attachment_dir):
            print(".. %s" % f)
            full_file_name = os.path.join(attachment_dir, f)
            shutil.copy(full_file_name, dest_path)


if __name__ == '__main__':

    arguments = docopt.docopt(__doc__, version=__version__)

    if arguments['users']:
        print(json.dumps(parse_users(), sort_keys=True, indent=2))
    elif arguments['migrate']:
        migrate_to_git()
    elif arguments['attachments']:
        copy_attachments()
