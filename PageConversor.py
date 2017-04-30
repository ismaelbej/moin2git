import os
import sys
from MoinMoin import wikiutil
from MoinMoin.web.contexts import ScriptContext as Request
from MoinMoin.Page import Page


class ConversorRequest(Request):
    def __init__(self, *args, **kwargs):
        super(ConversorRequest, self).__init__(*args, **kwargs)
        self._conversor_lines = []

    def write(self, text):
        self._conversor_lines += [text]

    def normalizePagename(self, name):
        return name

    def normalizePageURL(self, name, url):
        return name

    def get_lines(self):
        return self._conversor_lines


class ConversorPage(Page):
    def __init__(self, *args, **kwargs):
        self._conversor_body = None
        if 'conversor_body' in kwargs:
            self._conversor_body = kwargs.pop('conversor_body')
        super(ConversorPage, self).__init__(*args, **kwargs)

    def get_body(self):
        if self._conversor_body is not None:
            return self._conversor_body
        else:
            return super(ConversorPage, self).get_body()
    body = property(fget=get_body, fset=Page.set_body)


def convert(directory, page, body):
    page = page.decode('utf-8')

    old_cwd = os.getcwd()
    old_sys_path = sys.path
    os.chdir(directory)
    sys.path = [ os.getcwd(), ] + sys.path

    request = ConversorRequest(url=page, pagename=page)

    Formatter = wikiutil.importPlugin(request.cfg, "formatter",
                                      "text_x-rst", "Formatter")
    formatter = Formatter(request)
    request.formatter = formatter

    resultPage = ConversorPage(request, page, rev=0, formatter=formatter, conversor_body=body.decode('utf-8'))
    if not resultPage.exists():
        raise RuntimeError("No page named %r" % ( page, ))

    resultPage.send_page()

    os.chdir(old_cwd)
    sys.path = old_sys_path

    return u''.join(request.get_lines()).encode('utf-8')
