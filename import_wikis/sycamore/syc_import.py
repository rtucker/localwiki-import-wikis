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
                logger.error("failed macro processing on %s: %s", smart_str(name), args)
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
    logger = logging.getLogger(__name__ + '.render_wikitext')
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
      logger.error("ERROR render_wikitext (page %s): %s", page_slug, e)
      return ''

    if strong and hasattr(formatter, '_footnotes'):
        items = ["%s. %s" % (id, note) for (note, id) in formatter._footnotes]
        footnotes = "\n<h2>Footnotes</h2>\n<p>%s</p>" % ('<br/>'.join(items))
        wiki_html += footnotes

    return wiki_html


def process_page_element(page_elem, redirect_queue=None):
    # We import a page in a few different phases.
    # We first pull in the raw wiki text, then we render it using the
    # Sycamore parser and a modified Sycamore formatter (which does the HTML
    # output).  Some fixes we need to make are easier to do after the
    # HTML is generated (like fixing empty paragraphs), while other
    # fixes are easier to do by modifying our custom Formatter.  So we
    # mix and match to get the best result.
    logger = logging.getLogger(__name__ + '.process_page_element')
    name = normalize_pagename(page_elem.attrib['propercased_name'])
    if Page.objects.filter(slug=slugify(name)).exists():
        logger.debug("page already exists: %s", name)
        return
    try:
        wikitext = page_elem.find('text').text
        wikitext = reformat_wikitext(wikitext)
        html = render_wikitext(wikitext, page_slug=slugify(name))
    except Exception, e:
        # render error
        logger.exception("ERROR rendering wikitext for %s", name)
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
        logger.debug("empty page (probably deleted): %s", smart_str(name))
        return
    p = Page(name=name, content=html)
    try:
        p.clean_fields()
    except Exception, e:
        logger.exception("ERROR importing HTML for %s", name)
        return
    p.content = tidy_html(p.content)
    p.save(track_changes=False)
    logger.debug("Imported page %s", smart_str(name))


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
        logger.info("version already exists: %s / %s / %s", name, history_comment, history_date)
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
        logger.exception("ERROR rendering wikitext for %s", smart_str(name))
        return

    if wikitext and wikitext.strip().startswith('#redirect'):
        # Page is a redirect
        line = wikitext.strip()
    	to_page = line[line.find('#redirect')+10:]
        html = '<p>This version of the page was a redirect.  See <a href="%s">%s</a>.</p>' % (to_page, to_page)
    if not html or not html.strip():
        logger.info("empty page version: %s (%s)", smart_str(name), history_date)

    # Create a dummy Page object to get the correct cleaning behavior
    p = Page(name=name, content=html)
    try:
        p.clean_fields()
    except Exception, e:
        logger.exception("ERROR importing HTML for %s", smart_str(name))
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
    logger.debug("Imported historical page %s at %s", smart_str(name), history_date)


def is_image(filename):
    import mimetypes
    try:
        file_type = mimetypes.guess_type('filename.gif')[0]
        return file_type.startswith('image/')
    except:
        return False


def process_user_element(element):
    from django.contrib.auth.models import User
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

        logger.debug("slug '%s' filename '%s': file imported",
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
        logger.debug("slug '%s' filename '%s': historic file imported",
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

def import_process(items_queue, redirect_queue=None):
    """Subprocess to handle importing of content."""
    # Break old database connections, because we're probably not running
    # in the same process any more.
    from django.db import close_connection, connection
    close_connection()
    connection.connection = None

    life = 1000
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
                    process_page_element(element, redirect_queue)
                elif element.tag == 'version':
                    process_version_element(element)
                elif element.tag == 'point':
                    process_point_element(element)
                elif element.tag == 'file':
                    process_file_element(element)
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
        life -= 1

def import_from_export_file(import_queue, file_items, page_items, version_items, map_items, redirect_queue):
    jobs = []
    to_start = []
    n = 0
    parsing = True

    max_jobs = 4

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
            logger.info("At element %d: file queue %d, page queue %d, " +
                        "version queue %d, map queue %d, redirect queue %d",
                        n, file_items.qsize(), page_items.qsize(),
                        version_items.qsize(), map_items.qsize(),
                        redirect_queue.qsize())

        n += 1

        if element.tag == 'page':
            # We have found a page.  We want to isolate this to just the
            # page itself, not the historic versions.  We also want to
            # immediately import the latest version of this page.
            while page_items.qsize() > 500:
                logger.debug("Pausing to let page queue catch up... (count: %d)", page_items.qsize())
                time.sleep(10)
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
            while version_items.qsize() > 50000:
                logger.debug("Pausing to let version queue catch up... (count: %d)", version_items.qsize())
                page_items.put(DEATH_SEMAPHORE)
                time.sleep(10)
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
            # A point on a map.  Simple.
            # Skip import of historical map point data - not really
            # interesting and it'd be weird because the points are
            # kept separately in the XML dump.  People weren't
            # thinking about map data being independently versioned
            # at the time.

            parent_group = element.getparent()
            if parent_group is not None and parent_group.tag == 'current':
                map_items.put(etree.tostring(element))

        elif element.tag == 'file':
            # A file.
            while file_items.qsize() > 100:
                logger.debug("Pausing to let file queue catch up... (count: %d)", file_items.qsize())
                time.sleep(10)
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

def process_redirects(redirect_queue, midflight=False):
    # We create the Redirects here.  We don't try and port over the
    # version information for the formerly-page-based redirects, as that
    # is 1) not very important 2) preserved via the page content, in
    # this case.  For these old ported-over redirects, the old page
    # versions will note that the page used to be a redirect in the page
    # history.
    from django.contrib.auth.models import User

    # The database connection from this process may be stale
    from django.db import close_connection, connection
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
    running = True
    while running:
        if midflight and remain < 1:
            running = False
        try:
            from_pagename, to_pagename = redirect_queue.get(timeout=10)
            logger.debug("begin processing redirect: %s -> %s", from_pagename, to_pagename)
            remain -= 1
        except Empty:
            return

        try:
            to_page = Page.objects.get(name=to_pagename)
            redir_date = to_page.versions.latest('history_date').history_date
        except Page.DoesNotExist:
            if midflight:
                logger.debug("Recirculating premature redirect: %s -> %s", from_pagename, to_pagename)
                redirect_queue.put((from_pagename, to_pagename))
                redirect_queue.task_done()
                continue
            else:
                logger.error("Error creating redirect to nonexistent page: %s -> %s", from_pagename, to_pagename)
                redirect_queue.task_done()
                continue

        if redir_date is None and midflight:
            logger.debug("Recirculating redirect to page without history: %s -> %s", from_pagename, to_pagename)
            redirect_queue.put((from_pagename, to_pagename))
            redirect_queue.task_done()
            continue
        elif redir_date is None:
            redir_date = datetime.datetime.now()

        if slugify(from_pagename) == to_page.slug:
            logger.error("Redirect of %s -> %s illogical (equal slugs)", from_pagename, to_page)
            redirect_queue.task_done()
            continue
        if not Redirect.objects.filter(source=slugify(from_pagename)).exists():
            with transaction.commit_on_success():
                r = Redirect(source=slugify(from_pagename), destination=to_page)
                # XXX: Keeps throwing: ValueError: Cannot assign None: "Redirect_hist.destination" does not allow null values.
                r.save(user=u, comment="Automated edit. Creating redirect.",
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
    id_map = {}
    for ph in Page.versions.all().defer('content').iterator():
        if ph.slug not in id_map:
            ps = Page.objects.filter(slug=ph.slug)
            if ps:
                id_map[ph.slug] = ps[0].id

        if ph.slug in id_map:
            if ph.id != id_map[ph.slug]:
                ph.id = id_map[ph.slug]
                ph.save()
                fixed += 1

    id_map = {}
    for ph in PageFile.versions.all().iterator():
        if (ph.name, ph.slug) not in id_map:
            ps = PageFile.objects.filter(name=ph.name, slug=ph.slug)
            if ps:
                id_map[(ph.name, ph.slug)] = ps[0].id

        if (ph.name, ph.slug) in id_map:
            if ph.id != id_map[(ph.name, ph.slug)]:
                ph.id = id_map[(ph.name, ph.slug)]
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
    IMPORT_ORDER = ['users', 'files', 'pages', 'map']
    max_jobs = 5

    if not args:
        print "usage: localwiki-manage runscript syc_import --script-args=(keep|destroy) exportfiles..."
        return
    disposition = args[0]

    files = args[1:]

    filedict = defaultdict(list)
    for fn in files:
        filetype = identify_file(fn)
        logger.info("Input file of type %s: %s", filetype, fn)
        filedict[filetype].append(fn)

    import_queue = JoinableQueue()
    page_items = JoinableQueue()
    version_items = JoinableQueue()
    map_items = JoinableQueue()
    file_items = JoinableQueue()
    redirect_queue = JoinableQueue()

    importers = []
    jobs = []
    cleaners = []
    queues = [('files', file_items,),
              ('pages', page_items,),
              ('map', map_items,),
              ('versions', version_items,),
             ]
    jobmap = {}

    last_cleaner_fixids = time.time()
    last_cleaner_redirs = time.time()

    turn_off_search()
    if disposition.lower() in ['destroy']:
        clear_out_everything()
    else:
        logger.info("Not clearing everything out due to disposition %s", disposition)

    for group in IMPORT_ORDER:
        for fn in filedict.get(group):
            import_queue.put(fn)

    # Run a few subprocesses to handle things.
    running = True
    while running:
        # Clean up dead processes
        for cleaner in cleaners:
            if not cleaner.is_alive():
                logger.info("Reaping dead cleaner %s", cleaner)
                cleaners.remove(cleaner)
        for importer in importers:
            if not importer.is_alive():
                logger.info("Reaping dead importer %s", importer)
                importers.remove(importer)
        counts = defaultdict(int)
        for job in jobs:
            if not job.is_alive():
                logger.info("Reaping dead handler %s", job)
                jobs.remove(job)
                if job in jobmap:
                    del jobmap[job]
            if job in jobmap:
                counts[jobmap[job]] += 1

        if len(importers) == 0 and not import_queue.empty():
            # Start an importer
            p = Process(target=import_from_export_file, args=(import_queue, file_items, page_items, version_items, map_items, redirect_queue))
            p.daemon = True
            p.start()
            importers.append(p)
            logger.info("Started importer process %s", p)

        # file_items must go before page_items
        # page_items must go before map_items
        # version_items shouldn't get too far ahead of page_items
        for name, queue in queues:
            if queue.empty():
                continue

            logger.debug("Considering %s with %d current jobs", name, counts[name])
            assassination = False

            if counts[name] < 1:
                for cname, cqueue in queues:
                    if counts[cname] > 1:
                        cqueue.put(DEATH_SEMAPHORE)
                        logger.warning("%s has no handlers, even though there are %d items in queue!  Assassinating %s", name, queue.qsize(), cname)
                        assassination = True
                        break

            if (len(jobs) < max_jobs and queue.qsize() > len(jobs)) or assassination:
                p = Process(target=import_process, args=(queue, redirect_queue,))
                p.daemon = True
                p.start()
                jobs.append(p)
                jobmap[p] = name
                logger.info("Starting %s job runner process %s", name, p)

        if len(cleaners) == 0:
            if (time.time() - last_cleaner_fixids) > 300 and last_cleaner_fixids < last_cleaner_redirs:
                p = Process(target=fix_historical_ids)
                p.daemon = True
                p.start()
                cleaners.append(p)
                logger.info("Started fix_historical_ids background process %s", p)
                last_cleaner_fixids = time.time()

            elif (time.time() - last_cleaner_redirs) > 60:
                p = Process(target=process_redirects, args=(redirect_queue, True,))
                p.daemon = True
                p.start()
                cleaners.append(p)
                logger.info("Started process_redirects background process %s", p)
                last_cleaner_redirs = time.time()


        logger.info("Importer processes: %d, Job runners: %d (%s), Cleaners: %d", len(importers), len(jobs), dict(counts), len(cleaners))
        logger.info("Import queue: %d, File queue: %d, Page queue: %d, Version queue: %d, Map queue: %d, Redirect queue: %d",
                    import_queue.qsize(), file_items.qsize(), page_items.qsize(), version_items.qsize(), map_items.qsize(), redirect_queue.qsize())
        logger.info("Last ran fix_historical_ids %d ago, process_redirects %d ago", time.time() - last_cleaner_fixids, time.time() - last_cleaner_redirs)

        # Still running?
        still_to_do = len(importers) + len(cleaners) + len(jobs)
        still_to_do += import_queue.qsize()
        for name, queue in queues:
            still_to_do += queue.qsize()

        running = still_to_do > 0
        gc.collect()
        time.sleep(10)

    logger.info("Final run of fix_historical_ids")
    fix_historical_ids()
    logger.info("Final run of process_redirects")
    process_redirects(redirect_queue)
