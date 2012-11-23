"""
This script is a hack.  It's an absolute mess.  Thankfully, it works.
And you just need to run this once, so who cares!

This will import a Sycamore dump, as provided by export.py, into sapling.

To use:

  0. Get localwiki up and running.  THIS SCRIPT WILL **WIPE ALL DATA** in the localwiki
     install its run against, so DO NOT run this script against a site with real content
     in it!
  1. Add django_extensions to your LOCAL_INSTALLED_APPS in localsettings.py.
     And install django_extensions (pip install django-extensions in your virtualenv)
  2. Make a directory called "scripts" inside the sapling/ project directory and move
     this file into it.
  3. Find the directory your "Sycamore" code directory lives inside of.  Change
     SYCAMORE_CODE_PATH to point there.
  4. Copy sycamore_scripts/export.py and sycamore_scripts/user_export.py into
     your Sycamore/ directory.
  5. From your Sycamore/ directory, run python export.py.  Do the admin dump.  You'll now
     have an XML file in the Sycamore/ directory containing a Sycamore XML export.
  6. From your Sycamore/ directory, run python user_export.py.  You'll now have an XML
     file in the Sycamore/ directory containing a Sycamore XML user export.
       Note: Change EXPORT_ENC_PASSWORD = True if you want to export passwords, too
  7. Run localwiki-manage runscript syc_import --script-args=/path/to/the/dump.xml /path/to/the/user.dump.xml

You'll then have an import of the old Sycamore site!  User accounts are moved over
but passwords aren't.  Users will have to reset their password in order to sign in
for now.  We could fix this.

=== For faster import/export (large site) ===

Export using:

   python export.py --just_pages
   python export.py --just_files
   python export.py --just_maps

which will give you three different content export files.

Then run syc_import with:

  localwiki-manage runscript syc_import --script-args=/path/to/the/page_dump.xml /path/to/the/user.dump.xml /path/to/the/files_dump.xml /path/to/the/map_dump.xml
"""

from multiprocessing import Process

import os
import sys
import site
import gc

import re
import datetime
import urllib
import copy
from lxml import etree
from base64 import b64decode

from pages.models import Page, slugify, PageFile, clean_name
from maps.models import MapData
from redirects.models import Redirect
from haystack import site as haystack_site
from django.contrib.gis.geos import Point, MultiPoint
from django.core.files.base import ContentFile
from django.db import transaction

#################################
# CHANGE THIS
SYCAMORE_CODE_PATH = '/home/philip/sycamore'
#################################
sys.path.append(SYCAMORE_CODE_PATH)

from Sycamore import security as sycamore_security
from Sycamore.formatter.text_html import Formatter as sycamore_HTMLFormatter
from Sycamore.formatter.base import FormatterBase
from Sycamore import wikiutil
from Sycamore.parser.wiki_simple import Parser as sycamore_SimpleParser
from Sycamore.parser.wiki import Parser as sycamore_Parser

redirects = []


def replace_baseline_table_color(hex):
    if hex.lower() == '#e0e0ff':
        return '#e8ecef'

    return hex


def normalize_pagename(pagename):
    return clean_name(pagename)


class AllPermissions(sycamore_security.Permissions):
    def read(self, page, **kws):
        return True

    def edit(self, page, **kws):
        return True

    def delete(self, page, **kws):
        return True

    def admin(self, page, **kws):
        return True


class SimpleWikiParser(sycamore_SimpleParser):
    def print_br(self):
        # For now, don't emit <br/> b/c we don't support it.
        return False

    #def print_br(self):
    #    # We inhibit br in lists, unlike the sycamore default.

    #    # is the next line a table?
    #    next_line = self.lines[self.lineno-1].strip()
    #    if next_line[:2] == "||" and next_line[-2:] == "||":
    #      return False

    #    return not (self.inhibit_br > 0 or self.formatter.in_list or self.in_table or self.lineno <= 1 or
    #                self.line_was_empty)


class WikiParser(sycamore_Parser):
    def print_br(self):
        # For now, don't emit <br/> b/c we don't support it.
        return False

    #def print_br(self):
    #    # We inhibit br in lists, unlike the sycamore default.

    #    # is the next line a table?
    #    next_line = self.lines[self.lineno-1].strip()
    #    if next_line[:2] == "||" and next_line[-2:] == "||":
    #      return False

    #    return not (self.inhibit_br > 0 or self.formatter.in_list or self.in_table or self.lineno <= 1 or
    #                self.line_was_empty)


IMAGE_MACRO = re.compile(r'^(\s*(\[\[image((\(.*\))|())\]\])\s*)+$')


def line_has_just_macro(macro, args, formatter):
    line = macro.parser.lines[macro.parser.lineno - 1].lower().strip()
    if IMAGE_MACRO.match(line):
        return True
    return False


def next_line_has_just_macro(macro, args, formatter):
    try:
       line = macro.parser.lines[macro.parser.lineno].lower().strip()
    except IndexError:
        return False
    if IMAGE_MACRO.match(line):
        return True
    return False


def parse_include_args(args):
    # This grossness pulled from moinmoin include macro.
    re_args = re.match('('
        '('
            '(?P<name1>.+?)(\s*,\s*)((".*")|(left|right)|([0-9]{1,2}%)))|'
        '(?P<name2>.+))', args)

    have_more_args = re_args.group('name1')
    page_name = re_args.group('name1') or re_args.group('name2')

    if have_more_args:
        args = args[re_args.end('name1'):]
    else:
        args = ''
    re_args = re.search('"(?P<heading>.*)"', args)
    if re_args:
        heading = re_args.group('heading')
    else:
        heading = None

    if heading:
        before_heading = args[:re_args.start('heading')-1].strip()
        after_heading = args[re_args.end('heading')+1:].strip()
        args = before_heading + after_heading[1:]

    args_elements = args.split(',')
    align = None
    was_given_width = False
    width = None
    for arg in args_elements:
        arg = arg.strip()
        if arg == 'left' or arg == 'right':
            align = arg
        elif arg.endswith('%'):
            try:
                arg = str(int(arg[:-1])) + '%'
            except:
                continue
            width = arg
        was_given_width = True

    return (page_name, heading, width, align)


class Formatter(sycamore_HTMLFormatter):
    """
    A modified version of the text_html formatter from Sycamore.

    We turn off certain things to have a cleaner output.  Most
    of the big blocks of code here are copied from text_html.
    """

    def __init__(self, *args, **kwargs):
        if 'page_slug' in kwargs:
            self.page_slug = kwargs.pop('page_slug')
        sycamore_HTMLFormatter.__init__(self, *args, **kwargs)

    def setPage(self, page):
        val = sycamore_HTMLFormatter.setPage(self, page)
        self.page.proper_name = lambda: self.page.page_name
        return val

    def url(self, url, text=None, css=None, show_image=True, **kw):
        # Turn off classes on links -- we don't need them
        css = None
        return sycamore_HTMLFormatter.url(self, url, text, css, show_image, **kw)

    def paragraph(self, on, id=None):
        FormatterBase.paragraph(self, on)
        if self._in_li:
            self._in_li = self._in_li + 1
        attr = self._langAttr()
        if self.inline_edit_force_state is not None:
            self.inline_edit = self.inline_edit_force_state
        if self.inline_edit and on:
            dummy = '%s id="%s"' % (attr, id or self.inline_edit_id())
        result = ['<p%s>' % attr, '\n</p>'][not on]
        return '%s\n' % result

    def definition_list(self, on):
        attrs = ''
        if self.inline_edit_force_state is not None:
            self.inline_edit = self.inline_edit_force_state
        if self.inline_edit:
            dummy = '%s id="%s"' % (attrs, self.inline_edit_id())
        result = ['<dl%s>' % attrs, '</dl>'][not on]
        return '%s\n' % result

    def heading(self, depth, title, id = None, **kw):
        # remember depth of first heading, and adapt counting depth accordingly
        if not self._base_depth:
            self._base_depth = depth
        count_depth = max(depth - (self._base_depth - 1), 1)

        number = ''

        id_text = ''
        if id:
            id_text = ' id="%s"' % id

        heading_depth = depth + 1
        link_to_heading = False
        if kw.has_key('link_to_heading') and kw['link_to_heading']:
            link_to_heading = True
        if kw.has_key('on'):
            if kw['on']:
                attrs = ''
                if self.inline_edit_force_state is not None:
                    self.inline_edit = self.inline_edit_force_state
                if self.inline_edit:
                    dummy = '%s id="%s"' % (attrs, self.inline_edit_id())

                result = '<span%s><h%d%s></span>' % (id_text, heading_depth,
                                                     attrs)
            else:
                result = '</h%d>' % heading_depth
        else:
            if link_to_heading:
                title = Page(kw.get('pagename') or title,
                             self.request).link_to(know_status=True,
                                                   know_status_exists=True,
                                                   text=title)
            attrs = ''
            if self.inline_edit_force_state is not None:
                self.inline_edit = self.inline_edit_force_state
            if self.inline_edit:
                    dummy = '%s id="%s"' % (attrs, self.inline_edit_id())

            result = '<h%d%s%s>%s%s%s</h%d>\n' % (
                heading_depth, self._langAttr(), attrs,
                kw.get('icons', ''), number, title, heading_depth)

        self.just_printed_heading = True
        return result

    def rule(self, size=0):
        return '<hr />'

    def table_row(self, on, attrs={}):
        if on:
            attrs = self._checkTableAttr(attrs, 'row')
            if self.inline_edit_force_state is not None:
                self.inline_edit = self.inline_edit_force_state
            if self.inline_edit:
                dummy = '%s id="%s"' % (attrs, self.inline_edit_id())

            result = '<tr%s>' % attrs
        else:
            result = '</tr>'
        return '%s\n' % result

    allowed_table_attrs = {
        'table': ['class', 'width', 'height', 'bgcolor', 'border',
                  'cellpadding', 'bordercolor'],
        'row': ['class', 'width', 'align', 'valign', 'bgcolor'],
        '': ['colspan', 'rowspan', 'class', 'width', 'align', 'valign',
             'bgcolor'],
    }

    def _checkTableAttr(self, attrs, prefix):
        CSS_COLORS = {
            'aqua': '#00FFFF',
            'black': '#000000',
            'blue': '#0000FF',
            'fuchsia': '#FF00FF',
            'gray': '#808080',
            'grey': '#808080',
            'green': '#008000',
            'lime': '#00FF00',
            'maroon': '#800000',
            'navy': '#000080',
            'olive': '#808000',
            'purple': '#800080',
            'red': '#FF0000',
            'silver': '#C0C0C0',
            'teal': '#008080',
            'white': '#FFFFFF',
            'yellow': '#FFFF00',
        }
        def toRGB(hex):
            if hex.lower() in CSS_COLORS:
                hex = CSS_COLORS[hex.lower()]
            hex = replace_baseline_table_color(hex)
            value = hex.replace('#', '')
            try:
                lv = len(value)
                r, g, b = tuple(int(value[i:i+lv/3], 16) for i in range(0, lv, lv/3))
                return 'rgb(%s, %s, %s)' % (r, g, b)
            except:
                return hex
        if not attrs:
            return ''

        result = ''
        style = ''
        for key, val in attrs.items():
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            if prefix and key[:len(prefix)] != prefix:
                continue
            key = key[len(prefix):]
            if key not in self.allowed_table_attrs[prefix]:
                continue
            if prefix == 'table':
                if key in ['width', 'height', 'bgcolor', 'border', 'cellpadding', 'bordercolor']:
                    if key == 'bgcolor':
                        newstyle = 'background-color: %s;' % toRGB(val)
                        if style:
                            style += " %s" % newstyle
                        else:
                            style = newstyle
                    elif key == 'border':
                        # XXX TODO skipping table border for now. Maybe
                        # re-add when we support it in sapling.
                        continue
                    elif key == 'cellpadding':
                        # XXX TODO skipping table cellpadding for now.  Maybe re-add when we
                        # support it in sapling.
                        continue
                    elif key == 'bordercolor':
                        # XXX TODO skipping table bordercolor for now.  Maybe re-add when we
                        # support it in sapling.
                        continue
                    elif key == 'width':
                        width = val
                        if not (width.endswith('%') or width.endswith('px')):
                            width = '%spx' % width
                        newstyle = 'width: %s;' % width

                        if style:
                            style += " %s" % newstyle
                        else:
                            style = newstyle
                    elif key == 'height':
                        height = val
                        if not (height.endswith('%') or height.endswith('px')):
                            height = '%spx' % height
                        newstyle = 'height: %s;' % height

                        if style:
                            style += " %s" % newstyle
                        else:
                            style = newstyle
                else:
                    # Regular attribute
                    result = '%s %s=%s' % (result, key, val)
                    continue

            elif prefix == 'row':
                # We ignore all row properties.
                continue

            elif prefix == '':
                # Ignore class attribute on table cells.
                if key == 'class':
                    continue
                if key == 'bgcolor':
                    newstyle = 'background-color: %s;' % toRGB(val)
                    if style:
                        style += " %s" % newstyle
                    else:
                        style = newstyle
                elif key == 'width':
                    width = val
                    if not (width.endswith('%') or width.endswith('px')):
                        width = '%spx' % width
                    newstyle = 'width: %s;' % width

                    if style:
                        style += " %s" % newstyle
                    else:
                        style = newstyle
                elif key == 'align':
                    newstyle = 'text-align: %s;' % val
                    if style:
                        style += " %s" % newstyle
                    else:
                        style = newstyle
                elif key == 'valign':
                    newstyle = 'vertical-align: %s;' % val
                    if style:
                        style += " %s" % newstyle
                    else:
                        style = newstyle
                else:
                    # Regular attribute
                    result = '%s %s=%s' % (result, key, val)
                    continue

            if style:
                result = '%s style="%s"' % (result, style)

        return result

    def table(self, on, attrs={}):
        if on:
            attrs = attrs and attrs.copy() or {}
            result = '\n<table%(tableAttr)s>' % {
                'tableAttr': self._checkTableAttr(attrs, 'table'),
            }
        else:
            result = '</table>'
        return '%s\n' % result

    ###########################################################################

    def process_file_macro(self, macro_obj, name, args):
        filename = args
	try:
            file = PageFile.objects.get(slug=self.page_slug, name=filename)
        except:
            # File doesn't exist, was just a macro reference to an
            # un-uploaded file.
            return ''
        html = '<a href="_files/%s">%s</a>' % (filename, filename)
        return html

    def process_image_macro(self, macro_obj, name, args):
        from Sycamore.macro.image import getArguments
        from django.core.files.images import get_image_dimensions
        image_name, caption, is_thumbnail, px_size, alignment, has_border = \
            getArguments(args)

        if line_has_just_macro(macro_obj, args, macro_obj.formatter):
            macro_obj.parser.inhibit_br = 2
            if next_line_has_just_macro(macro_obj, args, macro_obj.formatter):
                macro_obj.parser.inhibit_p = 1

        try:
            img = PageFile.objects.get(slug=self.page_slug, name=image_name)
        except:
            # Image doesn't exist, was just a macro reference to an
            # un-uploaded image.
            return ''
        attrs = {
            'total_style': '',
            'img_style': '',
            'caption_html': '',
            'img_frame_classes': 'image_frame',
            'img_src': '_files/%s' % image_name,
        }
        width, height = None, None
        total_style_value, img_style_value = '', ''
        # Calculate correct width, height for thumbnail.
        if not img.file:
            return ''
        try:
            width, height = get_image_dimensions(img.file)
        except TypeError:
            return ''
        if is_thumbnail and not px_size:
            # Set default px_size
            px_size = 192
        if is_thumbnail and px_size:
            if width > height:
                # px_size is width
                ratio = ((px_size * 1.0) / width)
                height = int(height * ratio)
                width = px_size
            else:
                # px_size is height
                ratio = ((px_size * 1.0) / height)
                width = int(width * ratio)
                height = px_size
            #total_style_value += 'width: %spx' % width
            img_style_value += 'width: %spx; height:%spx;' % (width, height)

        if has_border:
            attrs['img_frame_classes'] += " image_frame_border"

        if alignment:
            attrs['img_frame_classes'] += " image_%s" % alignment

        if total_style_value:
            attrs['total_style'] = 'style="%s"' % total_style_value
        if img_style_value:
            attrs['img_style'] = 'style="%s"' % img_style_value
        if caption:
            caption_html = render_wikitext(caption, strong=False, page_slug=self.page_slug)
            # remove surrounding <p> tag
            caption_html = '\n'.join(caption_html.strip().split('\n')[1:-1])
            caption_style = ''
            if width:
                caption_style = ' style="width:%spx;"' % width
            attrs['caption_html'] = '<span class="image_caption"%s>%s</span>' \
                % (caption_style, caption_html)

        html = ('<span %(total_style)s class="%(img_frame_classes)s">'
                  '<img src="%(img_src)s" %(img_style)s/>'
                  '%(caption_html)s'
                '</span>' % attrs)
        return html

    def process_flickr_macro(self, macro_obj, name, args):
        try:
            from Sycamore.macro.flickr import getArguments, licenses_getInfo
            from Sycamore.support import flickr
        except ImportError:
            return ''

        image_name, caption, is_thumbnail, size, alignment, has_border = \
            getArguments(args)

        url_image_name = urllib.quote(image_name.encode('utf-8'))
        photohandle = flickr.Photo(image_name)
        licensename = licenses_getInfo(photohandle.license)
        oklicenses = ['1','2','3','4','5','6','7','8']

        if (photohandle.license not in oklicenses) or (not photohandle.ispublic):
            return ("<!-- Don't have permissions for Flickr image here.\n"
                    "        Image_name %s\n"
                    "        Caption %s\n"
                    "        Is_Thumbnail %s\n"
                    "        Size %s\n"
                    "        Alignment %s\n"
                    "        Has_Border %s -->\n") % getArguments(args)

        ownername = photohandle.owner.username
        imageurl = photohandle.getURL(urlType='source', size=size)
        linkurl = photohandle.getURL(urlType='url', size=size)

        if caption:
            caption += ' (by Flickr user %s: [%s license info], [%s link to original])' % (
                        ownername, licensename[1], linkurl)

        if line_has_just_macro(macro_obj, args, macro_obj.formatter):
            macro_obj.parser.inhibit_br = 2
            if next_line_has_just_macro(macro_obj, args, macro_obj.formatter):
                macro_obj.parser.inhibit_p = 1

        attrs = {
            'total_style': '',
            'img_style': '',
            'caption_html': '',
            'img_frame_classes': 'image_frame',
            'img_src': imageurl,
        }
        width, height = None, None
        total_style_value, img_style_value = '', ''

        sizedata = photohandle.getSizes()
        for i in sizedata:
            if i['label'].lower() == size.lower():
                width, height = i['width'], i['height']

        img_style_value += 'width: %spx; height:%spx;' % (width, height)

        if has_border:
            attrs['img_frame_classes'] += " image_frame_border"

        if alignment:
            attrs['img_frame_classes'] += " image_%s" % alignment

        if total_style_value:
            attrs['total_style'] = 'style="%s"' % total_style_value
        if img_style_value:
            attrs['img_style'] = 'style="%s"' % img_style_value
        if caption:
            caption_html = render_wikitext(caption, strong=False, page_slug=self.page_slug)
            # remove surrounding <p> tag
            caption_html = '\n'.join(caption_html.strip().split('\n')[1:-1])
            caption_style = ''
            if width:
                caption_style = ' style="width:%spx;"' % width
            attrs['caption_html'] = '<span class="image_caption"%s>%s</span>' \
                % (caption_style, caption_html)

        html = ('<span %(total_style)s class="%(img_frame_classes)s">'
                  '<img src="%(img_src)s" %(img_style)s/>'
                  '%(caption_html)s'
                '</span>' % attrs)
        return html

    def process_comments_macro(self, macro_obj, name, args):
        title = (args and args.strip()) or "Comments"
        return "<h2>%s</h2>" % title

    def process_nbsp_macro(self, macro_obj, name, args):
        return '&nbsp;'

    def process_include_macro(self, macro_obj, name, args):
        page_name, heading, width, align = parse_include_args(args)
        # The old behavior was: align w/o set width -> width is 50%. So
        # let's preserve that.
        if (align == 'left' or align == 'right') and not width:
            width = '50%'

        width_style = ''
        include_classes = ''
        if width:
            width_style = ' style="width: %s;"' % width
        if align == 'left':
            include_classes += ' includepage_left'
        if align == 'right':
            include_classes += ' includepage_right'
        if heading and heading.strip():
            include_classes += ' includepage_showtitle'
        quoted_pagename = urllib.quote(page_name.encode('utf-8'))
        d = {
            'width_style': width_style,
            'quoted_pagename': quoted_pagename,
            'include_classes': include_classes,
            'pagename': page_name,
        }
        include_html = """<a%(width_style)s href="%(quoted_pagename)s" class="plugin includepage%(include_classes)s">Include page %(pagename)s</a></p>""" % d
        return include_html

    def process_mailto_macro(self, macro_obj, name, args):
        from Sycamore.util.mail import decodeSpamSafeEmail

        args = args or ''
        if args.find(',') == -1:
            email = args
            text = ''
        else:
            email, text = args.split(',', 1)

        email, text = email.strip(), text.strip()

        # decode address and generate mailto: link
        email = decodeSpamSafeEmail(email)

        return '<a href="mailto:%s">%s</a>' % (email, email)

    def process_address_macro(self, macro_obj, name, args):
        address = render_wikitext(args.strip('"'), strong=False, page_slug=self.page_slug)
        # remove surrounding <p> tag
        return '\n'.join(address.strip().split('\n')[1:-1])

    def process_footnote_macro(self, macro_obj, name, args):
        if not args or not args.strip():
            return ""
        args = args.strip()
        html = strip_outer_para(render_wikitext(args, strong=False))
        if not hasattr(self, '_footnotes'):
            self._footnotes = []
        idx = len(self._footnotes) + 1
        self._footnotes.append((html, idx))
        return "<sup>%s</sup>" % idx

    def macro(self, macro_obj, name, args):
        macro_processors = {
            'image': self.process_image_macro,
            'file': self.process_file_macro,
            'comments': self.process_comments_macro,
            'include': self.process_include_macro,
            'nbsp': self.process_nbsp_macro,
            'address': self.process_address_macro,
            'mailto': self.process_mailto_macro,
            'footnote': self.process_footnote_macro,
            'flickr': self.process_flickr_macro,
        }
        if name.lower() in macro_processors:
            try:
                return macro_processors[name.lower()](macro_obj, name, args)
            except Exception, e:
                print "\t ERROR failed macro processing on", name, args
        return ''

    def pagelink(self, pagename, text=None, **kw):
        import urllib
        if not text:
            text = pagename

        if type(pagename) == str:
            pagename = pagename.decode('utf-8')
        if type(text) == str:
            text = text.decode('utf-8')
        if text.lower().startswith('users/'):
            text = text[len('users/'):]
        return u'<a href="%s">%s</a>' % (
            urllib.quote(pagename.encode('utf-8')), text)

    def interwikilink(self, wikiurl, text, **kw):
        from Sycamore.wikiutil import split_wiki
        map = {
            'davis': 'http://daviswiki.org/',
            'santacruz': 'http://scruzwiki.org/',
            'chico': 'http://chicowiki.org/',
            'sacramento': 'http://sacwiki.org/',
            'westsac': 'http://westsacwiki.org/',
            'wikipedia': 'http://en.wikipedia.org/wiki/',
            'rocwiki': 'http://rocwiki.org/',
            'roc': 'http://rocwiki.org/',
            'wiki': 'http://c2.com/cgi/wiki?',
            'wikinews': 'http://en.wikinews.org/wiki/',
            'wikisource': 'http://en.wikisource.org/wiki/',
            'wiktionary': 'http://en.wiktionary.org/wiki/',
            'c2': 'http://c2.com/cgi/wiki?',
            'uncyclopedia': 'http://uncyclopedia.org/wiki/',
            'drama': 'http://www.encyclopediadramatica.com/index.php/',
            'meatball': 'http://www.usemod.com/cgi-bin/mb.pl?',
            'webster': 'http://www.m-w.com/?',
            'wikitravel': 'http://www.wikitravel.org/en/',
            'musicguide': 'http://www.wikimusicguide.com',
            'wikimapia': 'http://www.wikimapia.org/',
            'tvtropes': 'http://tvtropes.org/pmwiki/pmwiki.php/Main/',
            '@': 'http://twitter.com/',
            'pubmed': 'http://www.ncbi.nlm.nih.gov/pubmed/',
            'calbar': 'http://members.calbar.ca.gov/search/member_detail.aspx?x=',
        }

        tag, tail = split_wiki(wikiurl)
        external_url = map.get(tag.lower(), None)
        if not external_url:
            if tag != 'wikispot':
                external_url = 'http://%s.wikispot.org/' % tag
            else:
                external_url = 'http://wikispot.org/'
        url = external_url + tail
        if not text:
            text = tag
        return '<a href="%s">%s</a>' % (url, text)


def return_empty_string(*args, **kwargs):
    return ''


def return_none(*args, **kwargs):
    return None


def sycamore_wikifyString(text, request, page, doCache=True, formatter=None,
        delays=None, strong=False):
    "This is an exact copy of wikiutil.wikifyString, with argument to parser.format() changed"
    import cStringIO
    # back up attributes we might want before doing simple parsing

    if formatter:
        orig_inline_edit = formatter.inline_edit
        orig_inline_edit_force_state = formatter.inline_edit_force_state
    
    # find out what type of formatter we're using
    if hasattr(formatter, 'assemble_code'):
        from Sycamore.formatter.text_html import Formatter
        html_formatter = Formatter(request) 
        py_formatter = formatter
    else:
        doCache = False
        from Sycamore.formatter.text_python import Formatter
        if formatter:
            html_formatter = formatter
        else:
            from Sycamore.formatter.text_html import Formatter
            html_formatter = Formatter(request)
        doCache = False
        py_formatter = Formatter(request)

    if strong:
        Parser = WikiParser
    else:
        Parser = SimpleWikiParser

    html_formatter.setPage(page)
    buffer = cStringIO.StringIO()
    request.redirect(buffer)
    html_parser = Parser(text, request)
    html_parser.format(html_formatter)
    request.redirect()
    
    if doCache:
        buffer.close()
        buffer = cStringIO.StringIO()
        request.redirect(buffer)
        parser = Parser(text, request)
        py_formatter.delays = delays
        parser.format(py_formatter)
        request.redirect()
        text = buffer.getvalue().decode('utf-8')
        buffer.close()
    else:
        text = buffer.getvalue()
        buffer.close()
        text = text.decode('utf-8')

    # restore attributes
    if formatter:
        formatter.inline_edit = orig_inline_edit
        formatter.inline_edit_force_state = orig_inline_edit_force_state

    return text


def wikifyString(text, request, page, **kwargs):
    if not text:
        return ''

    import cStringIO
    from Sycamore.request import RequestDummy
    from Sycamore.user import User

    request = RequestDummy(process_config=False)

    request.user = User(request)
    request.user.may = AllPermissions(request.user)
    request.theme.make_icon = return_empty_string

    html_formatter = Formatter(request)
    html_formatter.setPage(page)
    buffer = cStringIO.StringIO()
    request.redirect(buffer)
    html_parser = SimpleWikiParser(text, request)
    html_parser.format(html_formatter, inline_edit_default_state=False)
    text = buffer.getvalue()

    buffer.close()
    text = text.decode('utf-8')

    return text

wikiutil.wikifyString = wikifyString


def wrap_top_level_images(s):
    """
    Make sure all top-level images are wrapped in a paragraph.
    """
    import html5lib

    p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
    top_level_elems = p.parseFragment(s, encoding='UTF-8')
    l = []
    to_wrap = []
    for e in top_level_elems:
        if isinstance(e, basestring):
            continue
        if e.tag == 'span' and e.attrib.get('class', '').find('image_frame') != -1:
            # This is an image that isn't contained in a paragraph tag but it's in
            # the top-level, so let's wrap it in a paragraph.
            to_wrap.append(e)
            para = etree.Element("p")
            para.append(e)
            l.append(para)
        else:
            if to_wrap:
                para = etree.Element("p")
                for item in to_wrap:
                    para.append(item)
                l.append(para)
                to_wrap = []
            l.append(e)
    if to_wrap:
        para = etree.Element("p")
        for item in to_wrap:
            para.append(item)
        l.append(para)

    top_level_elems = l
    s = ''
    for e in top_level_elems:
        if isinstance(e, basestring):
            s += e
        else:
            s += etree.tostring(e, encoding='UTF-8')
    return s


def _convert_to_string(l):
    s = ''
    for e in l:
        if isinstance(e, basestring):
            s += e
        elif isinstance(e, list):
            s += _convert_to_string(e)
        else:
            s += etree.tostring(e, encoding='UTF-8')
    return s


def strip_outer_para(quote):
    quote = quote.strip()
    return quote[quote.find('>')+1: len(quote)-len('</p>')].strip()


def fix_threaded_indents(s):
    """
    Convert the totally invalid and silly <ul><p>..</p>..</ul> to
    <ul><p class="ident[N]">..</p>..</ul>
    """
    import html5lib
    def _fix_threading_in_ul(e, level=1):
        def _accumulate_list(list_items):
            # Add accumulated <ul> and <li>'s to new tree.
            if list_items:
                if list_items[0].tag == 'li' or list_items[0].tag == 'ul':
                    ul = etree.Element("ul")
                    if level > 3:
                        ul.attrib['class'] = 'indent%s' % (level-1)
                    for elem in list_items:
                        ul.append(elem)
                    return [ul]
            return list_items
        new_tree_list = []
        list_items = []
        for child in e.iterchildren():
            if child.tag == 'p':
                child.attrib['class'] = 'indent%s' % level
                new_list = _accumulate_list(list_items)
                if new_list:
                    new_tree_list += new_list
                    list_items = []
                new_tree_list.append(child)
            elif child.tag == 'li':
                list_items.append(child)
            elif child.tag == 'ul':
                fixed_sub_list = _fix_threading_in_ul(child, level=level+1)
                #if fixed_sub_list[0].tag == 'li':
                #    ul = etree.Element("ul")
                #    if level > 3:
                #        ul.attrib['class'] = 'indent%s' % (level-1)
                #    for elem in fixed_sub_list:
                #        ul.append(elem)
                #    list_items.append(ul)
                #else:
                #    for elem in fixed_sub_list:
                #        list_items.append(elem)
                for elem in fixed_sub_list:
                    list_items.append(elem)

        # Iterate through remaining list items, adding them to the new
        # tree.  Break off groups of <li> and wrap them in <ul>.
        if list_items:
            ul = None
            for item in list_items:
                if item.tag == 'li':
                    if ul is None:
                        ul = etree.Element("ul")
                        #if level >= 3:
                        #    ul.attrib['class'] = 'indent%s' % (level-1)
                    ul.append(item)
                elif item.tag == 'ul':
                    if ul is None:
                        ul = etree.Element("ul")
                    ul.append(item)
                else:
                    if ul is not None:
                        new_tree_list.append(ul)
                        ul = None
                    new_tree_list.append(item)
            if ul is not None:
                new_tree_list.append(ul)

        return new_tree_list

    def _kill_p_in_li(elem):
        children = list(elem.iterchildren())
        if elem.tag == 'li':
            if len(children) == 1 and children[0].tag == 'p':
                # Break out the content of <p> if that's all there is inside of the li.
                new_elem = etree.Element("li")
                for i in children[0].iterchildren():
                    new_elem.append(i)
                new_elem.text = children[0].text
                return new_elem

        new_elem = etree.Element(elem.tag)
        for k, v in elem.attrib.iteritems():
            new_elem.attrib[k] = v
        new_elem.text = elem.text
        for child in children:
            new_child = _kill_p_in_li(child)
            new_child.tail = child.tail
            new_elem.append(new_child)
        return new_elem

    def _fix_repeated_ul(elem, level=0):
        # We take <ul><ul><ul>..</ul></ul></ul> ->
        # <ul class="indent3">..</ul>
        children = list(elem.iterchildren())
        if (elem.tag == 'ul' and len(children) == 1 and
            children[0].tag == 'ul'):
            return _fix_repeated_ul(children[0], level+1)
        elif elem.tag == 'ul':
            if level:
                elem.attrib['class'] = 'indent%s' % level
        return elem

    def _fix_ul(e):
        items = _fix_threading_in_ul(e)

        new_items = []
        for item in items:
            new_items.append(_fix_repeated_ul(item))
        items = new_items

        new_items = []
        for item in items:
            new_items.append(_kill_p_in_li(item))
        return new_items

    p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
    top_level_elems = p.parseFragment(s, encoding='UTF-8')
    l = []
    for e in top_level_elems:
        if e.tag == 'ul':
            for item in _fix_ul(e):
                l.append(item)
        else:
            l.append(e)

    return _convert_to_string(l) 

HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'h9']


def kill_empty_headings(s):
    s = re.sub('<h1>\s*</h1>\n?', '', s)
    s = re.sub('<h2>\s*</h2>\n?', '', s)
    s = re.sub('<h3>\s*</h3>\n?', '', s)
    s = re.sub('<h4>\s*</h4>\n?', '', s)
    s = re.sub('<h5>\s*</h5>\n?', '', s)
    s = re.sub('<h6>\s*</h6>\n?', '', s)
    s = re.sub('<h7>\s*</h7>\n?', '', s)
    s = re.sub('<h8>\s*</h8>\n?', '', s)
    return s


def remove_ridicilous_indents(s):
    # remove <ul> that surrounds anything that isn't
    # an <li> or a <p>
    import html5lib
    p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
    top_level_elems = p.parseFragment(s, encoding='UTF-8')
    new_top_level = []
    for e in top_level_elems:
        if isinstance(e, basestring):
            new_top_level.append(e)
            continue
        if e.tag == 'ul':
            children = list(e.iterchildren())
            if children and children[0].tag != 'li' and children[0].tag != 'p':
                # push everything to the top-level
                new_top_level += children
                continue
        new_top_level.append(e)
    return _convert_to_string(new_top_level)


def tidy_html(s):
    # Kill empty p tags.
    s = re.sub('<p>\s*</p>\n?', '', s)
    # Kill p tags with just &nbsp in them.
    s = re.sub('<p>\s*&nbsp;\s*</p>\n?', '', s)

    # Kill empty strong, em tags.
    s = re.sub('<strong>\s*</strong>\n?', '', s)
    s = re.sub('<em>\s*</em>\n?', '', s)

    s = wrap_top_level_images(s)
    s = remove_ridicilous_indents(s)
    s = fix_threaded_indents(s)
    s = kill_empty_headings(s)

    return s


def reformat_wikitext(s):
    if not s:
        return s
    # Remove comments macro when it's the last thing on the page.
    # TODO: remove this if/when we have a comments function.
    r = re.compile('\s{0,2}\[\[comments\]\]\s*$', re.IGNORECASE)
    s = r.sub('', s)
    r = re.compile('\s{0,2}\[\[comments(.*)\]\]\s*$', re.IGNORECASE)
    s = r.sub('', s)
    return s


def render_wikitext(text, strong=True, page_slug=None):
    from Sycamore.request import RequestDummy
    from Sycamore.Page import Page
    from Sycamore.user import User
    from Sycamore import user

    if not text:
        return ''

    user.unify_userpage = return_none

    request = RequestDummy(process_config=False)
    request.user = User(request)
    request.user.may = AllPermissions(request.user)
    request.theme.make_icon = return_empty_string
    formatter = Formatter(request, page_slug=page_slug)
    page = Page("PAGENAME", request)

    try:
      wiki_html = sycamore_wikifyString(text, request, page,
          formatter=formatter, strong=strong, doCache=False)
    except Exception, e:
      print "\tERROR render_wikitext (page %s): %s" % (page_slug, e)
      return ''

    if strong and hasattr(formatter, '_footnotes'):
        items = ["%s. %s" % (id, note) for (note, id) in formatter._footnotes]
        footnotes = "\n<h2>Footnotes</h2>\n<p>%s</p>" % ('<br/>'.join(items))
        wiki_html += footnotes

    return wiki_html


def create_page(page_elem, text_elem):
    # We import a page in a few different phases.
    # We first pull in the raw wiki text, then we render it using the
    # Sycamore parser and a modified Sycamore formatter (which does the HTML
    # output).  Some fixes we need to make are easier to do after the
    # HTML is generated (like fixing empty paragraphs), while other
    # fixes are easier to do by modifying our custom Formatter.  So we
    # mix and match to get the best result.
    global redirects

    name = normalize_pagename(page_elem.attrib['propercased_name'])
    if Page.objects.filter(slug=slugify(name)).exists():
        return
    wikitext = text_elem.text
    try:
        wikitext = reformat_wikitext(wikitext)
    except Exception, e:
        # render error
        print "\t ERROR rendering wikitext for %s (%s)" % (name, e)
        return
    html = render_wikitext(wikitext, page_slug=slugify(name))
    if wikitext and wikitext.strip().lower().startswith('#redirect'):
        # Page is a redirect
        line = wikitext.strip()
    	from_page = name
    	to_page = line[line.find('#redirect')+10:]
        redirects.append((from_page, to_page))
        # skip page creation
        print "\tQueued page redirect %s" % name
        return
    if not html or not html.strip():
        print "\t ERROR empty page %s" % name
        return
    p = Page(name=name, content=html)
    try:
        p.clean_fields()
    except Exception, e:
        print "\t ERROR importing HTML for %s (%s)" % (name, e)
        return
    p.content = tidy_html(p.content)
    p.save(track_changes=False)
    print "\tImported page %s" % name


def convert_edit_type(s):
    d = {
        'SAVE': 1,
        'SAVENEW': 0,
        'ATTNEW': 0,
        'ATTDEL': 2,
        # XXX TODO deal with renames here
        'RENAME': 1,
        'NEWEVENT': 0,
        'COMMENT_MACRO': 1,
        'SAVE/REVERT': 4,
        'DELETE': 2,
    }
    return d[s]


def create_page_version(version_elem, text_elem):
    from django.contrib.auth.models import User

    name = normalize_pagename(version_elem.attrib['propercased_name'])
    edit_time_epoch = float(version_elem.attrib['edit_time'])
    username_edited = version_elem.attrib['user_edited']
    edit_type = version_elem.attrib['edit_type']
    history_comment = version_elem.attrib['comment']
    history_user_ip = version_elem.attrib['user_ip']
    if not history_user_ip.strip():
        history_user_ip = None

    user = User.objects.filter(username=username_edited)
    if user:
        user = user[0]
        history_user_id = user.id
    else:
        history_user_id = None
    
    history_type = convert_edit_type(edit_type)
    history_date = datetime.datetime.fromtimestamp(edit_time_epoch)

    # If we already have a version exactly like this, skip
    if Page.versions.filter(name=name, history_comment=history_comment, history_type=history_type).exists():
        return

    # Set id to 0 because we create historical versions in
    # parallel.  We fix this in fix_historical_ids().
    id = 0

    wikitext = text_elem.text
    wikitext = reformat_wikitext(wikitext)
    try:
        html = render_wikitext(wikitext, page_slug=slugify(name))
    except Exception, e:
        # render error
        print "\t ERROR rendering wikitext for %s (%s)" % (name, e)
        return
    if wikitext and wikitext.strip().startswith('#redirect'):
        # Page is a redirect
        line = wikitext.strip()
    	to_page = line[line.find('#redirect')+10:]
        html = '<p>This version of the page was a redirect.  See <a href="%s">%s</a>.</p>' % (to_page, to_page)
    if not html or not html.strip():
        print "\t ERROR empty page version %s (%s)" % (name, history_date)
        return

    # Create a dummy Page object to get the correct cleaning behavior
    p = Page(name=name, content=html)
    try:
        p.clean_fields()
    except Exception, e:
        print "\t ERROR importing HTML for %s (%s)" % (name, e)
        return
    html = tidy_html(p.content)

    p_h = Page.versions.model(
        id=id,
        name=name,
        slug=slugify(name),
        content=html,
        history_comment=history_comment,
        history_date=history_date,
        history_type=history_type,
        history_user_id=history_user_id,
        history_user_ip=history_user_ip
    )
    p_h.save()
    print "\tImported historical page %s at %s" % (name, history_date)


def is_image(filename):
    import mimetypes
    try:
        file_type = mimetypes.guess_type('filename.gif')[0]
        return file_type.startswith('image/')
    except:
        return False


def process_user_element(element):
    from django.contrib.auth.models import User

    parent = element.getparent()
    if parent is None:
        return
    if parent.tag == 'users' and element.tag == 'user':
        username = element.attrib['name']
        email = element.attrib['email']
        disabled = element.attrib['disabled']
        if disabled == '1':
            return
        if User.objects.filter(email=email) or User.objects.filter(username=username):
            # skip import if user already exists
            return
        User.objects.create_user(username, email)
        print 'created user: %s %s' % (username, email)

def process_element(element, parent, parent_parent, just_pages, exclude_pages, just_maps):
    from django.contrib.auth.models import User
    if parent is None:
        return

    if not just_maps and not exclude_pages:
        if parent.tag == 'page':
            if element.tag == 'text':
                create_page(parent, element)
        elif parent.tag == 'version' and element.tag == 'text' and parent_parent.tag == 'page':
            create_page_version(parent, element)
    if just_pages:
        return
    if parent.tag == 'current' or parent.tag == 'old':
        if element.tag == 'point':
            if parent.tag == 'current':
                try:
                    p = Page.objects.get(slug=slugify(normalize_pagename(element.attrib['pagename'])))
                except Page.DoesNotExist:
                    return
                else:
                    mapdata = MapData.objects.filter(page=p)
                    x = float(element.attrib['x'])
                    y = float(element.attrib['y'])
                    point = Point(y, x)
                    if mapdata:
                        m = mapdata[0]
                        points = m.points
                        points.append(point)
                        m.points = points
                    else:
                        points = MultiPoint(point)
                        m = MapData(page=p, points=points)

                    m.save()

                    # Save historical version - with editor info, etc
                    m_h = m.versions.most_recent()

                    try:
                        edit_time_epoch = float(element.attrib['created_time'])
                    except ValueError:
                        edit_time_epoch = -1
                    username_edited = element.attrib['created_by']
                    history_user_ip = element.attrib['created_by_ip']
                    if not history_user_ip.strip():
                        history_user_ip = None

                    user = User.objects.filter(username=username_edited)
                    if user:
                        user = user[0]
                        history_user_id = user.id
                    else:
                        history_user_id = None
                    
                    history_type = 0
                    history_date = datetime.datetime.fromtimestamp(edit_time_epoch)
                    m_h.history_date = history_date
                    m_h.history_type = history_type
                    m_h.history_user_id = history_user_id
                    m_h.history_user_ip = history_user_ip
                    m_h.save()

            elif parent.tag == 'old':
                # Skip import of historical map point data - not really
                # interesting and it'd be weird because the points are
                # kept separately in the XML dump.  People weren't
                # thinking about map data being independently versioned
                # at the time.
                return
    if just_maps:
        return
    if parent.tag == 'files':
        # Current version of a file for a page.
        if (element.tag == 'file' and
            element.attrib.get('deleted', 'False') != 'True'):
            if not element.text:
                return
            filename = element.attrib.get('name')
            file_content = ContentFile(b64decode(element.text))
            slug = slugify(normalize_pagename(element.attrib.get('attached_to_pagename')))
            # XXX TODO generic files
            if is_image(filename):
                if PageFile.objects.filter(name=filename, slug=slug):
                    return
                pfile = PageFile(name=filename, slug=slug)

                pfile.file.save(filename, file_content, save=False)
                pfile.save()

                # Save historical version - with editor info, etc
                m_h = pfile.versions.most_recent()

                edit_time_epoch = float(element.attrib['uploaded_time'])
                username_edited = element.attrib['uploaded_by']
                history_user_ip = element.attrib['uploaded_by_ip']
                if not history_user_ip.strip():
                    history_user_ip = None

                user = User.objects.filter(username=username_edited)
                if user:
                    user = user[0]
                    history_user_id = user.id
                else:
                    history_user_id = None
                
                history_type = 0 # Will fix in historical version if needed
                history_date = datetime.datetime.fromtimestamp(edit_time_epoch)
                m_h.history_date = history_date
                m_h.history_type = history_type
                m_h.history_user_id = history_user_id
                m_h.history_user_ip = history_user_ip
                m_h.save()


                print "\timported image %s on page %s" % (filename.encode('utf-8'), element.attrib.get('attached_to_pagename').encode('utf-8'))
        # Old version of a file for a page.
        elif (element.tag == 'file' and
            element.attrib.get('deleted', 'False') == 'True'):
            if not element.text:
                return
            filename = element.attrib.get('name')
            file_content = ContentFile(b64decode(element.text))
            slug = slugify(normalize_pagename(element.attrib.get('attached_to_pagename')))
            edit_time_epoch = float(element.attrib['uploaded_time'])
            username_edited = element.attrib['uploaded_by']
            history_user_ip = element.attrib['uploaded_by_ip']
            if not history_user_ip.strip():
                history_user_ip = None

            user = User.objects.filter(username=username_edited)
            if user:
                user = user[0]
                history_user_id = user.id
            else:
                history_user_id = None
            
            if PageFile.versions.filter(name=filename, slug=slug):
                history_type = 1
            else:
                history_type = 0
            history_date = datetime.datetime.fromtimestamp(edit_time_epoch)
            
            # Set id to 0 because we create historical versions in
            # parallel.  We fix this in fix_historical_ids().
            id = 0

            pfile_h = PageFile.versions.model(
                id=id,
                name=filename,
                slug=slug,
                history_date=history_date,
                history_type=history_type,
                history_user_id=history_user_id,
                history_user_ip=history_user_ip
            )
            pfile_h.file.save(filename, file_content, save=False)
            pfile_h.save()

            # Change most recent historical version to be 'saved'
            # rather than 'added'.
            pfile_h = pfile_h.version_info._object.versions.most_recent()
            pfile_h.history_type = 1
            pfile_h.save()

            print "\timported historical file %s on page %s" % (filename.encode('utf-8'), normalize_pagename(element.attrib.get('attached_to_pagename')).encode('utf-8'))


@transaction.commit_on_success
def import_process(items, just_pages, exclude_pages, just_maps):
    from django.db import close_connection, connection
    close_connection()
    connection.connection = None

    for element, parent, parent_parent in items:
        process_element(element, parent, parent_parent, just_pages, exclude_pages, just_maps)


def import_from_export_file(f, just_pages=False, exclude_pages=False, just_maps=False):
    jobs = []
    to_start = []
    items = []
    max_jobs = 10
    n = 0
    parsing = True

    parser = etree.iterparse(f, events=("start", "end"), encoding='utf-8', huge_tree=True)
    while parsing:
        try:
            event, element = parser.next()
        except StopIteration:
            parsing = False
        except Exception, s:
            print "\t ERROR import_from_export_file at", n, s
    
        n += 1

        if n % 1000 == 0:
            print "Processed", n

        for p in to_start:
            # Clean up address space before fork()
            gc.collect()
            p.start()
            jobs.append(p)
            to_start.remove(p)
            print "Starting job", len(jobs)

        while len(jobs) >= max_jobs:
            for p in jobs:
                p.join(0.05)
                if not p.is_alive():
                    jobs.remove(p)
                    break
        
        if event != 'end':
            continue

        parent = element.getparent()
        parent_parent = parent.getparent() if (parent is not None) else None
        items.append((copy.deepcopy(element), copy.deepcopy(parent), copy.deepcopy(parent_parent)))

        if not exclude_pages:
            max_jobs = 20
            process_every = 40
        else:
            # File imports use way more memory, so we send less elements
            # to the process.
            max_jobs = 4
            process_every = 20

        import_process(items, just_pages, exclude_pages, just_maps)
        items = []
        if len(items) > process_every:
            p = Process(target=import_process, args=(items, just_pages, exclude_pages, just_maps))
            p.daemon = True
            to_start.append(p)
            items = []

        # Remove all previous siblings to keep the in-memory tree small.
        element.clear()
        parent = element.getparent()
        previous_sibling = element.getprevious()
        while previous_sibling is not None:
            parent.remove(previous_sibling)
            previous_sibling = element.getprevious()

        gc.collect()


    gc.collect()
    p = Process(target=import_process, args=(items, just_pages, exclude_pages, just_maps))
    p.daemon = True
    to_start.append(p)

    for p in to_start:
        p.start()
        jobs.append(p)
        to_start.remove(p)
        print "Starting job", len(jobs)
    for p in jobs:
        p.join()


def users_import_from_export_file(f):
    print 'importing users'
    for event, element in etree.iterparse(f, events=("start", "end"), encoding='utf-8', huge_tree=True):
        if event == 'start':
            pass
        elif event == 'end':
            process_user_element(element)
            element.clear()

            # Remove all previous siblings to keep the in-memory tree small.
            parent = element.getparent()
            previous_sibling = element.getprevious()
            while previous_sibling is not None:
                parent.remove(previous_sibling)
                previous_sibling = element.getprevious()


def clear_out_everything():
    from django.db import connection
    from django.contrib.auth.models import User
    #for p in User.objects.all():
    #    p.delete()
    cursor = connection.cursor()
    print 'Bulk clearing out all map data'
    cursor.execute('DELETE from maps_mapdata')
    print 'All map data deleted'
    print 'Bulk clearing out all map history'
    cursor.execute('DELETE from maps_mapdata_hist')
    print 'All map history deleted'

    print 'Bulk clearing out all tag data'
    cursor.execute('DELETE from tags_pagetagset')
    cursor.execute('DELETE from tags_pagetagset_tags')
    cursor.execute('DELETE from tags_tag')
    print 'All tag data deleted'
    print 'Bulk clearing out all tag history'
    cursor.execute('DELETE from tags_pagetagset_hist')
    cursor.execute('DELETE from tags_pagetagset_hist_tags')
    cursor.execute('DELETE from tags_tag_hist')
    print 'All tag history deleted'

    print 'Bulk clearing out all file data'
    cursor.execute('DELETE from pages_pagefile')
    print 'All file data deleted'
    print 'Bulk clearing out all file history'
    cursor.execute('DELETE from pages_pagefile_hist')
    print 'All file history deleted'

    print 'Bulk clearing out all redirect data'
    cursor.execute('DELETE from redirects_redirect')
    print 'All redirect data deleted'
    print 'Bulk clearing out all redirect history'
    cursor.execute('DELETE from redirects_redirect_hist')
    print 'All redirect history deleted'

    print 'Bulk clearing out all page data'
    cursor.execute('DELETE from pages_page')
    print 'All page data deleted'
    print 'Bulk clearing out all page history'
    cursor.execute('DELETE from pages_page_hist')
    print 'All page history deleted'

    transaction.commit_unless_managed()
    print 'Done clearing out'


def process_redirects():
    # We create the Redirects here.  We don't try and port over the
    # version information for the formerly-page-based redirects, as that
    # is 1) not very important 2) preserved via the page content, in
    # this case.  For these old ported-over redirects, the old page
    # versions will note that the page used to be a redirect in the page
    # history.
    from django.contrib.auth.models import User
    global redirects

    try:
        u = User.objects.get(username="LocalWikiRobot")
    except User.DoesNotExist:
        u = User(name='LocalWiki Robot', username='LocalWikiRobot',
                 email='editrobot@localwiki.org')
        u.save()

    for from_pagename, to_pagename in redirects:
        try:
            to_page = Page.objects.get(name=to_pagename)
        except Page.DoesNotExist:
            print "Error creating redirect: %s --> %s" % (from_pagename, to_pagename)
            print "  (page %s does not exist)" % to_pagename
            continue

        if slugify(from_pagename) == to_page.slug:
            continue
        if not Redirect.objects.filter(source=slugify(from_pagename)):
          r = Redirect(source=slugify(from_pagename), destination=to_page)
          r.save(user=u, comment="Automated edit. Creating redirect.")


def fix_historical_ids():
    """
    Due to the way we process in parallel, it wasn't possible to get the
    correct id for a historical version when we pushed in the historical
    versions. So we fix that here.
    """
    print "Fixing historical ids"
    id_map = {}
    for ph in Page.versions.all().defer('content').iterator():
        if ph.slug in id_map:
            ph.id = id_map[ph.slug]
            ph.save()
            continue
        ps = Page.objects.filter(slug=ph.slug)
        if ps:
            id_map[ph.slug] = ps[0].id
            ph.id = ps[0].id
            ph.save()

    id_map = {}
    for ph in PageFile.versions.all().iterator():
        if (ph.name, ph.slug) in id_map:
            ph.id = id_map[(ph.name, ph.slug)]
            ph.save()
            continue
        ps = PageFile.objects.filter(name=ph.name, slug=ph.slug)
        if ps:
            id_map[(ph.name, ph.slug)] = ps[0].id
            ph.id = ps[0].id
            ph.save()


def turn_off_search():
    haystack_site.unregister(Page)


def run(*args, **kwargs):
    if not args:
        print "usage: python manage.py runscript syc_import --script-args=<export_file> <user_export_file>"
        print "or   : python manage.py runscript syc_import --script-args=<page_export_file> <user_export_file> <file_export_file> <map_export_file>"
        return
    filename = args[0]
    user_filename = args[1] 

    page_filename = filename
    file_filename = filename
    map_filename = filename
    if len(args) == 4:
        file_filename = args[2]
        map_filename = args[3]
         

    turn_off_search()
    clear_out_everything()
    f = open(user_filename, 'r')
    users_import_from_export_file(f)
    f.close()
    f = open(file_filename, 'r')
    import_from_export_file(f, exclude_pages=True)
    fix_historical_ids()
    f.close()
    f = open(page_filename, 'r')
    import_from_export_file(f, just_pages=True)
    f.close()
    fix_historical_ids()
    f = open(map_filename, 'r')
    import_from_export_file(f, just_maps=True)
    f.close()
    fix_historical_ids()
