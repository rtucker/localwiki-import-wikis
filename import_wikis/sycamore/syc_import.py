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

from multiprocessing import Process, JoinableQueue
from Queue import Empty, Full

import os
import sys
import site
import gc
import time
import logging

import re
import datetime
import dateutil
import urllib
import copy
from lxml import etree
from base64 import b64decode
from collections import defaultdict

from pages.models import Page, slugify, PageFile, clean_name
from maps.models import MapData
from redirects.models import Redirect
from haystack import site as haystack_site
from django.contrib.gis.geos import Point, MultiPoint
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.encoding import smart_str
from django.conf import settings

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

logger = logging.getLogger(__name__)

DEATH_SEMAPHORE = 0xDEAD


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
        self._is_isolating_comments = kwargs.pop('isolating_comments', False)

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

    def strike(self, on):
        return ['<strike>', '</strike>'][not on]

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
            from django.core.cache import cache
        except ImportError:
            return ''

        image_name, caption, is_thumbnail, size, alignment, has_border = \
            getArguments(args)

        url_image_name = urllib.quote(image_name.encode('utf-8'))
        photohandle = flickr.Photo(image_name)

        # We gotta do some caching here, due to the Flickr API limits.
        licensename = cache.get('flickr-license-%s' % photohandle.license)
        if not licensename:
            licensename = licenses_getInfo(photohandle.license)
            cache.set('flickr-license-%s' % photohandle.license, licensename)
        oklicenses = ['1','2','3','4','5','6','7','8']

        if (photohandle.license not in oklicenses) or (not photohandle.ispublic):
            return ("<!-- Don't have permissions for Flickr image here.\n"
                    "        Image_name %s\n"
                    "        Caption %s\n"
                    "        Is_Thumbnail %s\n"
                    "        Size %s\n"
                    "        Alignment %s\n"
                    "        Has_Border %s -->\n") % getArguments(args)

        ownername = cache.get('flickr-%s-owner' % url_image_name)
        if not ownername:
            ownername = photohandle.owner.username
            cache.set('flickr-%s-owner' % url_image_name, ownername)
        imageurl = cache.get('flickr-%s-imageurl' % url_image_name)
        if not imageurl:
            imageurl = photohandle.getURL(urlType='source', size=size)
            cache.set('flickr-%s-imageurl' % url_image_name, imageurl)
        linkurl = cache.get('flickr-%s-linkurl' % url_image_name)
        if not linkurl:
            linkurl = photohandle.getURL(urlType='url', size=size)
            cache.set('flickr-%s-linkurl' % url_image_name, linkurl)

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

        sizedata = cache.get('flickr-%s-sizedata' % url_image_name)
        if not sizedata:
            sizedata = photohandle.getSizes()
            cache.set('flickr-%s-sizedata' % url_image_name, sizedata)
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
        """We'll generally see something like:
            [[Comments]]
            ------
            ''2010-04-16 17:42:04'' [[nbsp]] Long time fan of DQ - the
            Blizzards are great, my favorites include the Butterfinger
            Blizzard and the Cappuccino-Heath Blizzard. Hoping an investor
            takes note (:>) --["Users/BradMandell"]
        (with zero or more comments, prefixed by ------.

        If we're aiming to extract the comments out, we'll put an ugly-ass
        flag here so we know what to look for.
        """
        title = (args and args.strip()) or "Comments"
        if self._is_isolating_comments:
            return '\nXXXCOMMENTSXXX: %s\n' % title
        else:
            return '<h2 class="plugin commentbox">%s</h2>' % title

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
        logger = logging.getLogger(__name__ + '.macro')
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
                logger.exception("macro processing failed, macro name: %s, args: %s, exception: %s", name, args, e)
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
    # This function previously removed standalone Comments tags.
    return s


def render_wikitext(text, strong=True, page_slug=None, isolating_comments=False):
    from Sycamore.request import RequestDummy
    from Sycamore.Page import Page
    from Sycamore.user import User
    from Sycamore import user
    logger = logging.getLogger(__name__ + '.render_wikitext')
    if not text:
        return ''

    user.unify_userpage = return_none

    request = RequestDummy(process_config=False)
    request.user = User(request)
    request.user.may = AllPermissions(request.user)
    request.theme.make_icon = return_empty_string
    formatter = Formatter(request, page_slug=page_slug, isolating_comments=isolating_comments)
    page = Page("PAGENAME", request)

    wiki_html = sycamore_wikifyString(text, request, page,
        formatter=formatter, strong=strong, doCache=False)

    if strong and hasattr(formatter, '_footnotes'):
        items = ["%s. %s" % (id, note) for (note, id) in formatter._footnotes]
        footnotes = "\n<h2>Footnotes</h2>\n<p>%s</p>" % ('<br/>'.join(items))
        wiki_html += footnotes

    return wiki_html


def parse_comment_list(elem_list):
    # We have a list of one or more <p> elements, corresponding to a comment.
    # The first will have an <em> child with a datetime.
    # The last will have a <a> child with user information.
    first_children = elem_list[0].getchildren()
    last_children = elem_list[-1].getchildren()
    first_child = first_children[0]
    last_child = last_children[-1]
    if first_child.tag != 'em' or last_child.tag != 'a':
        return None

    try:
        dttm = dateutil.parser.parse(first_child.text)
        user = last_child.attrib['href']
        elem_list[-1].remove(last_child)
        text = ''.join([etree.tostring(elem) for elem in elem_list])
        text = re.sub('<em>.+</em>( \&\#160\;)?', '', text)
        text = re.sub('\&\#8212\;</p>', '</p>', text)
        return (dttm, user, text)
    except:
        return None


def isolate_comments(text):
    """Returns a hunk of HTML without comments, the label to use for comment
       boxes, and a list of comments."""

    if (text is None) or (not 'XXXCOMMENTSXXX' in text):
        return (text, None, [])

    not_comments = []
    label = None
    comments = []
    in_comments = False
    in_a_comment = False
    comment_list = []

    element_list = etree.HTML(text).find('body').getchildren()
    for element in element_list:
        if element.tag is 'p' and element.text is not None and 'XXXCOMMENTSXXX' in element.text:
            # Jackpot
            in_comments = True
            contents = element.text.strip()
            label = contents.split(' ', 1)[1]
            continue

        if in_comments:
            if element.tag == 'hr' and in_a_comment:
                in_a_comment = False
            elif element.tag == 'hr':
                # May be the first one
                pass
            elif element.tag == 'p':
                in_a_comment = True
                comment_list.append(element)
            else:
                # utoh, I think we're done.
                in_comments = False
                in_a_comment = False

            if not in_a_comment and len(comment_list) > 0:
                result = parse_comment_list(comment_list)
                comment_list = []
                if result is None:
                    # Freak out
                    in_comments = False
                else:
                    comments.append(result)

        if not in_comments:
            not_comments.append(element)

    return ('\n'.join([etree.tostring(x) for x in not_comments]), label, comments)

def process_page_element(page_elem, redirect_queue=None, comment_queue=None):
    # We import a page in a few different phases.
    # We first pull in the raw wiki text, then we render it using the
    # Sycamore parser and a modified Sycamore formatter (which does the HTML
    # output).  Some fixes we need to make are easier to do after the
    # HTML is generated (like fixing empty paragraphs), while other
    # fixes are easier to do by modifying our custom Formatter.  So we
    # mix and match to get the best result.
    logger = logging.getLogger(__name__ + '.process_page_element')
    name = normalize_pagename(page_elem.attrib['propercased_name'])

    try:
        # If comments support is enabled, handle the comments.
        from comments.models import CommentConfiguration
        do_comments = True
    except ImportError:
        do_comments = False

    if Page.objects.filter(slug=slugify(name)).exists():
        logger.info("Page already exists: %s", name)
        return
    try:
        wikitext = page_elem.find('text').text
        wikitext = reformat_wikitext(wikitext)
        html = render_wikitext(wikitext, page_slug=slugify(name), isolating_comments=do_comments)
    except Exception, e:
        # render error
        logger.exception("ERROR rendering wikitext to HTML for page %s", name)
        logger.debug("Element dump for %s: %s", name, etree.tostring(page_elem))
        return
    if wikitext and wikitext.strip().lower().startswith('#redirect'):
        # Page is a redirect
        line = wikitext.split('\n')[0].strip()
    	from_page = name
    	to_page = line[line.find('#redirect')+10:]
        if redirect_queue is not None:
            redirect_queue.put((from_page, to_page))
            # skip page creation
            logger.debug("Queued page redirect %s -> %s", smart_str(from_page), smart_str(to_page))
            return
        raise RuntimeError("no redirect queue available")
    if not html or not html.strip():
        logger.debug("Empty page: %s (probably deleted)", name)
        return

    if do_comments:
        html, comment_label, comments = isolate_comments(html)
        if html is not None and html.strip() == '':
            html = '<!-- placeholder for empty page content -->'
    else:
        comment_label = None
        comments = []

    p = Page(name=name, content=html)
    try:
        p.clean_fields()
    except Exception, e:
        logger.exception("ERROR cleaning object for page %s", name)
        logger.debug("Element dump for %s: %s", name, etree.tostring(page_elem))
        return
    p.content = tidy_html(p.content)
    p.save(track_changes=False)
    logger.debug("Imported page %s", name)

    if comment_label is not None:
        # make it short enough to fit, if it's too long
        comment_label = comment_label[:230]
        qs = CommentConfiguration.objects.filter(page=p)
        if qs.exists():
            cc = qs.get()
        else:
            cc = CommentConfiguration(page=p)

        cc.enabled = True
        cc.heading = comment_label
        cc.save(track_changes=False)
        logger.debug("Updated CommentConfiguration for page %s (comment heading: %s)", name, comment_label)

    for comment_dttm, comment_username, comment_text in comments:
        if comment_queue is not None:
            comment_queue.put((p.id, comment_dttm, comment_username, comment_text))


def import_comment(page_id, dttm, username, text):
    from django.contrib.auth.models import User
    from pages.models import Page
    from comments.models import Comment

    if username.lower().startswith('users/'):
        username = username[len('users/'):]
    comment_user = User.objects.filter(username__iexact=username)
    if comment_user.exists():
        comment_user = comment_user.get()
    else:
        comment_user = None
        text += ' <em>This comment was written by %s.</em>' % username

    p = Page.objects.get(id=page_id)

    if Comment.versions.filter(page=p, history_date=dttm, history_user=comment_user).exists():
        # We already have a version of this comment
        logger.debug("Not importing duplicate comment on page %s: date=%s, user=%s / %s", p.slug, dttm, username, comment_user)
    else:
        with transaction.commit_on_success():
            c = Comment(page=p, content=text)
            c.save(date=dttm, comment="Comment added", user=comment_user)
            logger.debug("Imported comment on page %s: date=%s, user=%s / %s", p.slug, dttm, username, comment_user)


def process_comments(comment_queue, recirculate_queue=None, midflight=False):
    from pages.models import Page
    from django.db import close_connection, connection

    close_connection()
    connection.connection = None
    logger = logging.getLogger(__name__ + '.process_comments')

    logger.debug("process_comments: %d to process", comment_queue.qsize())
    remain = comment_queue.qsize()
    while True:
        if remain < 0 and midflight:
            logger.debug("process_comments: stopping due to tail-biting (remain < 0)")
            break

        try:
            page_id, dttm, username, text = comment_queue.get(timeout=1)
            remain -= 1
        except Empty:
            logger.debug("process_comments: queue got empty")
            break

        if Page.versions.filter(id=page_id).exists():
            logger.debug("process_comments: processing page_id %d dttm %s by %s (remaining = %d)", page_id, dttm, username, comment_queue.qsize())
            import_comment(page_id, dttm, username, text)
            comment_queue.task_done()
        elif midflight and recirculate_queue is not None:
            logger.debug("process_comments: could not find versions for page_id %d, requeuing (remaining = %d)", page_id, comment_queue.qsize())
            recirculate_queue.put((page_id, dttm, username, text))
            comment_queue.task_done()
        else:
            logger.error("process_comments: could not find versions for page_id %d, dropping comment! dttm=%s username=%s content=%s", page_id, dttm, username, text)
            comment_queue.task_done()


    logger.debug("process_comments: done")


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


def process_version_element(version_elem):
    from django.contrib.auth.models import User
    logger = logging.getLogger(__name__ + '.process_version_element')

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
    if Page.versions.filter(name=name, history_comment=history_comment, history_date=history_date).exists():
        logger.info("Page version already exists: %s version %s (%s)", name, edit_time_epoch, history_comment)
        return

    # Set id to 0 because we create historical versions in
    # parallel.  We fix this in fix_historical_ids().
    id = 0

    wikitext = version_elem.find('text').text
    try:
        wikitext = reformat_wikitext(wikitext)
        html = render_wikitext(wikitext, page_slug=slugify(name))
    except Exception, e:
        # render error
        logger.exception("ERROR rendering wikitext to HTML for page %s version %s", name, edit_time_epoch)
        logger.debug("Element dump for %s v %s: %s", name, edit_time_epoch, etree.tostring(version_elem))
        return

    if wikitext and wikitext.strip().startswith('#redirect'):
        # Page is a redirect
        line = wikitext.strip()
    	to_page = line[line.find('#redirect')+10:]
        html = '<p>This version of the page was a redirect.  See <a href="%s">%s</a>.</p>' % (to_page, to_page)
    if not html or not html.strip():
        logger.error("Inserting placeholder text at empty page version: %s version %s", name, edit_time_epoch)
        logger.debug("Element dump for %s v %s: %s", name, edit_time_epoch, etree.tostring(version_elem))
        html = '<p>This version of the page was either intentionally left blank, or could not be parsed during import.</p>'

    # Create a dummy Page object to get the correct cleaning behavior
    p = Page(name=name, content=html)
    try:
        p.clean_fields()
    except Exception, e:
        logger.exception("ERROR cleaning object for page %s version %s", name, edit_time_epoch)
        logger.debug("Element dump for %s v %s: %s", name, edit_time_epoch, etree.tostring(version_elem))
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
    logger.debug("Imported page %s version %s", name, edit_time_epoch)


def is_image(filename):
    import mimetypes
    try:
        file_type = mimetypes.guess_type('filename.gif')[0]
        return file_type.startswith('image/')
    except:
        return False


def process_user_element(element):
    from django.contrib.auth.models import User, Group
    logger = logging.getLogger(__name__ + '.process_user_element')

    parent = element.getparent()
    if parent is None:
        return
    if parent.tag == 'users' and element.tag == 'user':
        username = element.attrib['name']
        email = element.attrib['email']
        enc_password = element.attrib.get('enc_password', '!')
        disabled = element.attrib['disabled']
        join_date = element.attrib.get('join_date')
        if disabled == '1':
            return
        if join_date == '':
            join_dttm = datetime.datetime.now()
        else:
            join_dttm = datetime.datetime.fromtimestamp(float(join_date))
        if User.objects.filter(email=email) or User.objects.filter(username=username):
            # skip import if user already exists
            return
        u = User.objects.create_user(username, email)
        u.date_joined = join_dttm
        if enc_password != '':
            u.password = enc_password
        u.save()
        g = Group.objects.get(name="Authenticated")
        u.groups.add(g)
        logger.debug("Created user: %s <%s>", smart_str(username), smart_str(email))


def process_file_element(element):
    from django.contrib.auth.models import User
    from pages.models import slugify, PageFile
    logger = logging.getLogger(__name__ + '.process_file_element')

    if element.tag != 'file':
        raise RuntimeError("element is not a file")

    filename = element.attrib.get('name')
    slug = slugify(normalize_pagename(element.attrib.get('attached_to_pagename')))

    if not element.text:
        logger.warning("slug '%s' filename '%s': element.text is blank",
                       slug, filename)
        return

    file_content = ContentFile(b64decode(element.text))

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

    if element.attrib.get('deleted', 'False') != 'True':
        # XXX TODO generic files
        if PageFile.objects.filter(name=filename, slug=slug).exists():
            logger.warning("slug '%s' filename '%s': already exists",
                           slug, filename)
            return

        pfile = PageFile(name=filename, slug=slug)
        pfile.file.save(filename, file_content, save=False)
        pfile.save()

        # Save historical version - with editor info, etc
        m_h = pfile.versions.most_recent()


        history_type = 0 # Will fix in historical version if needed
        history_date = datetime.datetime.fromtimestamp(edit_time_epoch)
        m_h.history_date = history_date
        m_h.history_type = history_type
        m_h.history_user_id = history_user_id
        m_h.history_user_ip = history_user_ip
        m_h.save()

        logger.debug("File imported to page %s: %s",
                     slug, filename)


    else:
        # Old version of a file for a page.
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
        logger.debug("Old file imported to page %s: %s",
                     slug, filename)


def process_point_element(element):
    from django.contrib.auth.models import User
    from django.contrib.gis.geos import Point, MultiPoint
    from pages.models import Page
    from maps.models import MapData
    logger = logging.getLogger(__name__ + '.process_point_element')

    try:
        p = Page.objects.get(slug=slugify(normalize_pagename(element.attrib['pagename'])))
    except Page.DoesNotExist:
        logger.info("map point attached to nonexistent page %s", smart_str(element.attrib['pagename']))
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

        logger.debug("Map point %g %g created on %s", x, y, smart_str(element.attrib['pagename']))

def import_process(items_queue, redirect_queue=None, comment_queue=None):
    """Subprocess to handle importing of content."""
    # Break old database connections, because we're probably not running
    # in the same process any more.
    from django.db import close_connection, connection
    close_connection()
    connection.connection = None

    # Self-destroy after some time, to avoid memory leaks
    life = 10000
    while life > 0:
        try:
            # Pull an item from the queue if there's one available.
            item = items_queue.get(timeout=10)

            if item == DEATH_SEMAPHORE:
                # oh no!
                logger.info("Death semaphore received, dying.")
                items_queue.task_done()
                return

            # Parse the XML so we have something to work with
            element = etree.XML(item)

            # Handle the element, ensuring that we commit ASAP
            with transaction.commit_on_success():
                if element.tag == 'page':
                    process_page_element(element, redirect_queue, comment_queue)
                    life -= 5
                elif element.tag == 'version':
                    process_version_element(element)
                    life -= 5
                elif element.tag == 'file':
                    process_file_element(element)
                    life -= 25
                else:
                    logger.error("unknown element tag %s", element.tag)
            items_queue.task_done()
        except Empty:
            # We're done, time to go home
            logger.info("my queue got Empty, goodbye")
            return
        except:
            # Utoh
            logger.exception("Unknown exception, dying")
            items_queue.task_done()
            return

def import_from_export_file(import_queue, file_items, page_items, version_items, redirect_queue):
    from django.db import close_connection, connection
    close_connection()
    connection.connection = None

    try:
        fn = import_queue.get(timeout=10)
        f = open(fn, 'r')
        logger.info("Beginning parsing on file %s (remaining: %d)", fn, import_queue.qsize())
    except Empty:
        logger.info("Import file queue is empty.")
        return

    parsing = True
    n = 0
    parser = etree.iterparse(f, events=("start", "end",), encoding='utf-8', huge_tree=True)
    while parsing:
        try:
            event, element = parser.next()
        except StopIteration:
            parsing = False
        except Exception, s:
            logger.exception("Error on parser.next() at %d", n)

        if event != 'end':
            continue

        if n % 1000 == 0:
            logger.debug("Ingestion checkpoint: file %s, element %d", fn, n)

        n += 1

        PAGE_QUEUE_MAX = 500
        VERSION_QUEUE_MAX = 20000
        FILE_QUEUE_MAX = 200

        if element.tag == 'page':
            # We have found a page.  We want to isolate this to just the
            # page itself, not the historic versions.  We also want to
            # immediately import the latest version of this page.
            flowpause = page_items.qsize() > PAGE_QUEUE_MAX
            while flowpause:
                logger.debug("Pausing to let page queue catch up... (count: %d)", page_items.qsize())
                time.sleep(2)
                flowpause = page_items.qsize() > (PAGE_QUEUE_MAX*0.90)
            leanpage = copy.copy(element)
            first_child = None
            child_count = 0
            for child in leanpage.iterchildren():
                if child.tag == 'version':
                    child_count += 1
                    if child_count == 1:
                        first_child = copy.copy(child)
                    leanpage.remove(child)
            page_items.put(etree.tostring(leanpage))
            if first_child is not None:
                page_items.put(etree.tostring(first_child))

        elif element.tag == 'version' and element.getparent().tag == 'page':
            # We have found a version of a page.
            flowpause = version_items.qsize() > VERSION_QUEUE_MAX
            while flowpause:
                logger.debug("Pausing to let version queue catch up... (count: %d)", version_items.qsize())
                time.sleep(2)
                flowpause = version_items.qsize() > (VERSION_QUEUE_MAX*0.90)
            parent_page = element.getparent()
            child_count = 0
            our_position = 0
            for child in parent_page.iterchildren():
                if child.tag == 'version':
                    child_count += 1
                if sorted(child.values()) == sorted(element.values()):
                    our_position = child_count
            if our_position > 1:
                version_items.put(etree.tostring(element))

        elif element.tag == 'point':
            # A point on a map.  Simple.  Just do it, since we can have
            # problems if multiple workers are going at once.

            # Skip import of historical map point data - not really
            # interesting and it'd be weird because the points are
            # kept separately in the XML dump.  People weren't
            # thinking about map data being independently versioned
            # at the time.
            parent_group = element.getparent()
            if parent_group is not None and parent_group.tag == 'current':
                process_point_element(element)

        elif element.tag == 'file':
            # A file.
            flowpause = file_items.qsize() > FILE_QUEUE_MAX
            while flowpause:
                logger.debug("Pausing to let file queue catch up... (count: %d)", file_items.qsize())
                time.sleep(2)
                flowpause = file_items.qsize() > (FILE_QUEUE_MAX*0.90)
            file_items.put(etree.tostring(element))

        elif element.tag == 'user':
            # It's a user.  Simple.  Do it.
            process_user_element(element)

        if element.tag in ['page', 'point', 'file']:
            # Remove all previous siblings to keep the in-memory tree small.
            element.clear()
            parent = element.getparent()
            previous_sibling = element.getprevious()
            while previous_sibling is not None:
                parent.remove(previous_sibling)
                previous_sibling = element.getprevious()
            gc.collect()

    f.close()
    import_queue.task_done()

def clear_out_everything():
    from django.db import connection
    from django.contrib.auth.models import User
    from users.models import UserProfile
    from pages.models import PageFile

    cursor = connection.cursor()

    n = 0
    for pf in PageFile.objects.filter(file__isnull=False):
        target = os.path.join(settings.MEDIA_ROOT, str(pf.file))
        try:
            os.unlink(target)
            n += 1
        except Exception, e:
            pass

    logger.info("Deleted %d underlying PageFile objects", n)

    try:
        # If comment support is enabled, nuke the comments
        from comments.models import Comment
        for table in ['comments_comment', 'comments_comment_hist', 'comments_commentconfiguration', 'comments_commentconfiguration_hist']:
            cursor.execute("DELETE FROM %s" % table)
            logger.info("Deleted all rows from table %s", table)
    except ImportError:
        logger.info("Comment support not enabled, not deleting comments.")

    for table in ['maps_mapdata', 'maps_mapdata_hist', 'tags_pagetagset',
                  'tags_pagetagset_tags', 'tags_tag',
                  'tags_pagetagset_hist', 'tags_pagetagset_hist_tags',
                  'pages_pagefile', 'pages_pagefile_hist',
                  'redirects_redirect', 'redirects_redirect_hist',
                  'pages_page', 'pages_page_hist']:
        cursor.execute("DELETE FROM %s" % table)
        logger.info("Deleted all rows from table %s", table)

    logger.info("Committing...")
    transaction.commit_unless_managed()

    logger.info("Deleting user profiles and users...")
    UserProfile.objects.filter(user__is_superuser=False).delete()
    User.objects.filter(is_superuser=False).delete()

    logger.info("Done clearing out old data.")

def process_redirects(redirect_queue, redirect_recirc_queue=None, midflight=False):
    # We create the Redirects here.  We don't try and port over the
    # version information for the formerly-page-based redirects, as that
    # is 1) not very important 2) preserved via the page content, in
    # this case.  For these old ported-over redirects, the old page
    # versions will note that the page used to be a redirect in the page
    # history.
    from django.contrib.auth.models import User
    from pages.models import Page, slugify
    from redirects.models import Redirect
    from django.db import close_connection, connection, transaction

    # The database connection from this process may be stale
    close_connection()
    connection.connection = None

    logger = logging.getLogger(__name__ + '.process_redirects')

    try:
        u = User.objects.get(username="LocalWikiRobot")
    except User.DoesNotExist:
        u = User(name='LocalWiki Robot', username='LocalWikiRobot',
                 email='editrobot@localwiki.org')
        u.save()

    remain = redirect_queue.qsize()
    while True:
        if midflight and remain < 1:
            # In this mode, we put stuff we couldn't handle back onto the
            # queue.  This keeps us from looping infinitely.
            return

        # Pull an item from the queue, if possible.
        try:
            from_pagename, to_pagename = redirect_queue.get(timeout=10)
            logger.debug("Begin processing redirect: %s -> %s", from_pagename, to_pagename)
            remain -= 1
        except Empty:
            return

        # We are either going to point at a page or a redirect.
        to_page_qs = Page.objects.filter(slug=slugify(to_pagename))
        to_redir_qs = Redirect.objects.filter(source=slugify(to_pagename))

        if to_page_qs.exists():
            # We have our target, run with it.
            to_page = to_page_qs.get()
        elif to_redir_qs.exists():
            # We are redirecting to a redirect, awesome.
            to_page = to_redir_qs.get().destination
            logger.debug("Double-redirect resolved: %s -> %s -> %s", from_pagename, to_pagename, to_page.name)
        else:
            # No idea where we're going yet.
            if midflight and redirect_recirc_queue is not None:
                logger.debug("Deferring redirect to page which does not exist yet: %s -> %s", from_pagename, to_pagename)
                redirect_recirc_queue.put((from_pagename, to_pagename))
                redirect_queue.task_done()
                continue
            else:
                logger.error("Error creating redirect to nonexistent page: %s -> %s", from_pagename, to_pagename)
                redirect_queue.task_done()
                continue

        # Get a date for the redirect, so we don't pollute Recent Changes
        redir_date = to_page.versions.latest('history_date').history_date
        if midflight and redirect_recirc_queue is not None:
            # If we're running before the page has met fix_historical_ids,
            # bad things happen.  Catch those bad things.
            if (redir_date is None) or (0 in to_page.versions.values_list('id', flat=True)):
                logger.debug("Deferring redirect to page without history: %s -> %s", from_pagename, to_pagename)
                redirect_recirc_queue.put((from_pagename, to_pagename))
                redirect_queue.task_done()
                continue
        elif redir_date is None:
            redir_date = datetime.datetime.now()

        # We can't redirect to ourselves, duh
        if slugify(from_pagename) == to_page.slug:
            logger.error("Redirect of %s -> %s illogical (equal slugs)", from_pagename, to_page)
            redirect_queue.task_done()
            continue

        # Create the redirect.  Note that we aren't using get_or_create here
        # so that we can explicitly define our history.
        if not Redirect.objects.filter(source=slugify(from_pagename)).exists():
            with transaction.commit_on_success():
                r = Redirect(source=slugify(from_pagename), destination=to_page)
                r.save(user=u, comment="Automated edit: Creating redirect.",
                       date=redir_date)
                logger.debug("Redirected: %s -> %s", from_pagename, to_pagename)
        redirect_queue.task_done()


def fix_historical_ids():
    """
    Due to the way we process in parallel, it wasn't possible to get the
    correct id for a historical version when we pushed in the historical
    versions. So we fix that here.
    """

    # The database connection from this process may be stale
    from django.db import close_connection, connection
    close_connection()
    connection.connection = None

    fixed = 0
    logger.info("Fixing historical ids")
    for ph in Page.versions.filter(id=0).defer('content').iterator():
        ps = Page.objects.filter(slug=ph.slug)
        if ps.exists():
            ph.id = ps.get().id
            ph.save()
            fixed += 1

    for ph in PageFile.versions.filter(id=0).iterator():
        ps = PageFile.objects.filter(name=ph.name, slug=ph.slug)
        if ps.exists():
            ph.id = ps.get().id
            ph.save()
            fixed += 1

    logger.info("Fixed historical IDs on %d versions", fixed)


def turn_off_search():
    haystack_site.unregister(Page)


def identify_file(fn):
    f = open(fn, 'r')
    parser = etree.iterparse(f, events=("start", "end",), encoding='utf-8', huge_tree=True)

    count = 0
    for event, element in parser:
        count += 1
        if element.tag in ['users', 'pages', 'map', 'files']:
            return element.tag
        if count > 20:
            raise RuntimeError("Can't figure out what this file is: %s" % fn)

def run(*args, **kwargs):
    INGEST_ORDER = ['users', 'files', 'pages', 'map']
    max_importers = 3

    if not args:
        print "usage: localwiki-manage runscript syc_import --script-args=(keep|destroy) exportfiles..."
        return

    disposition = args[0]
    files = args[1:]
    filedict = defaultdict(list)

    for fn in files:
        filetype = identify_file(fn)
        logger.info("Will ingest file of type %s: %s", filetype, fn)
        filedict[filetype].append(fn)

    ingest_queue = JoinableQueue()
    page_items = JoinableQueue()
    version_items = JoinableQueue()
    file_items = JoinableQueue()
    redirect_queue = JoinableQueue()
    redirect_recirc_queue = JoinableQueue()
    comment_queue = JoinableQueue()
    comment_recirc_queue = JoinableQueue()

    ingesters = []
    importers = []
    cleaners = []
    queues = [('files', file_items,),
              ('pages', page_items,),
              ('versions', version_items,),
             ]
    jobmap = {}

    last_cleaner_fixids = time.time()
    last_cleaner_redirs = time.time()
    last_cleaner_comments = time.time()

    turn_off_search()
    if disposition.lower() in ['destroy']:
        clear_out_everything()
    else:
        logger.warning("Not deleting existing database contents (disposition flag was %s)", disposition)

    for group in INGEST_ORDER:
        for fn in filedict.get(group):
            ingest_queue.put(fn)

    # Run a few subprocesses to handle things.
    running = True
    while running:
        # Clean up dead processes
        for cleaner in cleaners:
            if not cleaner.is_alive():
                logger.debug("Reaping dead cleaner %s", cleaner)
                cleaners.remove(cleaner)
            else:
                logger.debug("Cleaner still alive: %s", cleaner)
        for ingester in ingesters:
            if not ingester.is_alive():
                logger.debug("Reaping dead ingester %s", ingester)
                ingesters.remove(ingester)
        counts = defaultdict(int)
        for importer in importers:
            if not importer.is_alive():
                logger.debug("Reaping dead importer %s", importer)
                importers.remove(importer)
                if importer in jobmap:
                    del jobmap[importer]
            if importer in jobmap:
                counts[jobmap[importer]] += 1

        if len(ingesters) == 0 and not ingest_queue.empty():
            if (file_items.qsize() + page_items.qsize() + version_items.qsize()) > 0:
                logger.debug("Ingester startup delayed until import queues die down...")
            else:
                # Start an importer
                p = Process(target=import_from_export_file, name="xml_ingester", args=(ingest_queue, file_items, page_items, version_items, redirect_queue))
                p.daemon = True
                p.start()
                ingesters.append(p)
                logger.debug("Started XML ingester process %s", p)

        # file_items must go before page_items
        # version_items shouldn't get too far ahead of page_items
        for name, queue in queues:
            logger.debug("Considering %s with %d current importers and %d things in queue", name, counts[name], queue.qsize())
            if queue.empty():
                continue

            assassination = False

            if counts[name] < 1:
                for cname, cqueue in queues:
                    if counts[cname] > 1:
                        cqueue.put(DEATH_SEMAPHORE)
                        logger.warning("%s has no processes, even though there are %d items in queue!  Assassinating %s", name, queue.qsize(), cname)
                        assassination = True
                        break

            if (len(importers) < max_importers and queue.qsize() > len(importers)) or assassination:
                p = Process(target=import_process, name="%s_importer" % name, args=(queue, redirect_queue, comment_queue,))
                p.daemon = True
                p.start()
                importers.append(p)
                jobmap[p] = name
                logger.debug("Starting %s data import process %s", name, p)

        if len(cleaners) == 0:
            if (time.time() - last_cleaner_fixids) > 300:
                p = Process(target=fix_historical_ids, name="fix_historical_ids")
                p.daemon = True
                p.start()
                cleaners.append(p)
                logger.debug("Started cleaner process fix_historical_ids %s", p)
                last_cleaner_fixids = time.time()

            elif (time.time() - last_cleaner_comments) > 90:
                p = Process(target=process_comments, args=(comment_queue, comment_recirc_queue, True), name="process_comments")
                p.daemon = True
                p.start()
                cleaners.append(p)
                logger.debug("Started cleaner process process_comments %s", p)
                last_cleaner_comments = time.time()

            elif (time.time() - last_cleaner_redirs) > 60:
                p = Process(target=process_redirects, args=(redirect_queue, redirect_recirc_queue, True,), name="process_redirects")
                p.daemon = True
                p.start()
                cleaners.append(p)
                logger.debug("Started cleaner process process_redirects %s", p)
                last_cleaner_redirs = time.time()

        # Handle our recirculating queues.
        # When we put something onto a queue in another process, that process
        # joins the queue before terminating.  This is a problem, which we can
        # hopefully avoid by putting stuff onto a second queue.
        while True:
            try:
                comment_queue.put(comment_recirc_queue.get(timeout=1))
                comment_recirc_queue.task_done()
            except Empty:
                break
        while True:
            try:
                redirect_queue.put(redirect_recirc_queue.get(timeout=1))
                redirect_recirc_queue.task_done()
            except Empty:
                break


        logger.info("STATUS: XML Ingestion: %d workers, %d files pending", len(ingesters), ingest_queue.qsize())
        logger.info("STATUS: Data Import: %d workers (%s), queue status: files %d, pages %d, historic pages %d, redirects %d, comments %d", len(importers), '/'.join(['%s %d' % (key, value) for key, value in counts.items()]), file_items.qsize(), page_items.qsize(), version_items.qsize(), redirect_queue.qsize(), comment_queue.qsize())
        logger.info("STATUS: Cleaners: %d workers, fix_historical_ids started %d seconds ago, process_redirects started %d seconds ago, process_comments started %d seconds ago", len(cleaners), time.time() - last_cleaner_fixids, time.time() - last_cleaner_redirs, time.time() - last_cleaner_comments)

        # Still running?
        still_to_do = len(ingesters) + len(cleaners) + len(importers)
        still_to_do += ingest_queue.qsize()
        for name, queue in queues:
            still_to_do += queue.qsize()

        running = still_to_do > 0
        gc.collect()
        time.sleep(10)

    logger.info("Final run of fix_historical_ids")
    fix_historical_ids()
    logger.info("Final run of process_redirects")
    process_redirects(redirect_queue)
    logger.info("Final run of process_comments")
    process_comments(comment_queue)
