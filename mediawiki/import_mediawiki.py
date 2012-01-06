import hashlib
import html5lib
from lxml import etree
from xml.dom import minidom
from urlparse import urljoin, urlsplit
import urllib
import re
from copy import copy
from html5lib import sanitizer
from wikitools import *

MEDIAWIKI_URL = 'http://127.0.0.1/mediawiki-1.16.0/index.php'


def guess_api_endpoint(url):
    return urljoin(url, 'api.php')


def guess_script_path(url):
    mw_path = urlsplit(MEDIAWIKI_URL).path
    if mw_path.endswith('.php'):
        return mw_path
    return urljoin(mw_path, '.')

API_ENDPOINT = guess_api_endpoint(MEDIAWIKI_URL)

site = wiki.Wiki(API_ENDPOINT)
SCRIPT_PATH = guess_script_path(MEDIAWIKI_URL)
redirects = []
include_pages_to_create = []
mapdata_objects_to_create = []


def get_robot_user():
    from django.contrib.auth.models import User

    try:
        u = User.objects.get(username="LocalWikiRobot")
    except User.DoesNotExist:
        u = User(name='LocalWiki Robot', username='LocalWikiRobot',
                 email='editrobot@localwiki.org')
        u.save()
    return u


def import_users():
    from django.contrib.auth.models import User

    request = api.APIRequest(site, {
        'action': 'query',
        'list': 'allusers',
    })
    for item in request.query()['query']['allusers']:
        username = item['name'][:30]

        # TODO: how do we get their email address here? I don't think
        # it's available via the API. Maybe we'll have to fill in the
        # users' emails in a separate step.
        # We require users to have an email address, so we fill this in with a
        # dummy value for now.
        name_hash = hashlib.sha1(username).hexdigest()
        email = "%s@FIXME.localwiki.org" % name_hash

        if User.objects.filter(username=username):
            continue

        print "Importing user %s" % username
        u = User(username=username, email=email)
        u.save()


def add_redirect(page):
    global redirects

    request = api.APIRequest(site, {
        'action': 'parse',
        'title': page.title,
        'text': page.wikitext,
    })
    links = request.query()['parse']['links']
    if not links:
        return
    to_pagename = links[0]['*']

    redirects.append((page.title, to_pagename))


def process_redirects():
    # We create the Redirects here.  We don't try and port over the
    # version information for the formerly-page-text-based redirects.
    global redirects

    from pages.models import Page, slugify
    from redirects.models import Redirect

    u = get_robot_user()

    for from_pagename, to_pagename in redirects:
        try:
            to_page = Page.objects.get(slug=slugify(to_pagename))
        except Page.DoesNotExist:
            print "Error creating redirect: %s --> %s" % (
                from_pagename, to_pagename)
            print "  (page %s does not exist)" % to_pagename
            continue

        if slugify(from_pagename) == to_page.slug:
            continue
        if not Redirect.objects.filter(source=slugify(from_pagename)):
            r = Redirect(source=slugify(from_pagename), destination=to_page)
            r.save(user=u, comment="Automated edit. Creating redirect.")
            print "Redirect %s --> %s created" % (from_pagename, to_pagename)


def process_mapdata():
    # We create the MapData models here.  We can't create them until the
    # Page objects are created.
    global mapdata_objects_to_create

    from maps.models import MapData
    from pages.models import Page, slugify
    from django.contrib.gis.geos import Point, MultiPoint

    for item in mapdata_objects_to_create:
        print "Adding mapdata for", item['pagename']
        p = Page.objects.get(slug=slugify(item['pagename']))

        mapdata = MapData.objects.filter(page=p)
        y = float(item['lat'])
        x = float(item['lon'])
        point = Point(x, y)
        if mapdata:
            m = mapdata[0]
            points = m.points
            points.append(point)
            m.points = points
        else:
            points = MultiPoint(point)
            m = MapData(page=p, points=points)
        m.save()


def render_wikitext(title, s):
    """
    Attrs:
        title: Page title.
        s: MediaWiki wikitext string.

    Returns:
        HTML string of the rendered wikitext.
    """
    request = api.APIRequest(site, {
        'action': 'parse',
        'title': title,
        'text': s,
    })
    result = request.query()['parse']
    # There's a lot more in result, like page links and category
    # information.  For now, let's just grab the html text.
    return result['text']['*']


def _convert_to_string(l):
    s = ''
    for e in l:
        if isinstance(e, basestring):
            s += e
        elif isinstance(e, list):
            s += _convert_to_string(e)
        else:
            s += etree.tostring(e, encoding='UTF-8')
    return s.decode('utf-8')


def _is_wiki_page_url(href):
    if href.startswith(SCRIPT_PATH):
        return True
    else:
        split_url = urlsplit(href)
        # If this is a relative url and has 'index.php' in it we'll say
        # it's a wiki link.
        if not split_url.scheme and split_url.path.endswith('index.php'):
            return True
    return False


def _get_wiki_link(link):
    """
    If the provided link is a wiki link then we return the name of the
    page to link to.  If it's not a wiki link then we return None.
    """
    pagename = None
    if 'href' in link.attrib:
        href = link.attrib['href']
        if _is_wiki_page_url(href):
            title = link.attrib.get('title')
            if 'new' in link.attrib.get('class', '').split():
                # It's a link to a non-existent page, so we parse the
                # page name from the title attribute in a really
                # hacky way.  Titles for non-existent links look
                # like <a ... title="Page name (page does not exist)">
                pagename = title[:title.rfind('(') - 1]
            else:
                pagename = title
    if type(pagename) == unicode:
        pagename = pagename.encode('utf-8')

    return pagename


def fix_internal_links(tree):
    def _process(item):
        pagename = _get_wiki_link(link)
        if pagename:
            # Set href to quoted pagename and clear out other attributes
            for k in link.attrib:
                del link.attrib[k]
            link.attrib['href'] = urllib.quote(pagename)

    for elem in tree:
        if elem.tag == 'a':
            _process(elem)
        for link in elem.findall('.//a'):
            _process(link)
    return tree


def fix_basic_tags(tree):
    for elem in tree:
        # Replace i, b with em, strong.
        if elem.tag == 'b':
            elem.tag = 'strong'
        for item in elem.findall('.//b'):
            item.tag = 'strong'

        if elem.tag == 'i':
            elem.tag = 'em'
        for item in elem.findall('.//i'):
            item.tag = 'em'
    return tree


def remove_edit_links(tree):
    for elem in tree:
        if (elem.tag == 'span' and
            ('editsection' in elem.attrib.get('class').split())):
            elem.tag = 'removeme'
        for item in elem.findall(".//span[@class='editsection']"):
            item.tag = 'removeme'  # hack to easily remove a bunch of elements
    return tree


def throw_out_tags(tree):
    throw_out = ['small']
    for elem in tree:
        for parent in elem.getiterator():
            for child in parent:
                if (child.tag in throw_out):
                    parent.text = parent.text or ''
                    parent.tail = parent.tail or ''
                    if child.text:
                        parent.text += (child.text + child.tail)
                    child.tag = 'removeme'
    return tree


def remove_headline_labels(tree):
    for elem in tree:
        for parent in elem.getiterator():
            for child in parent:
                if (child.tag == 'span' and
                    'mw-headline' in child.attrib.get('class', '').split()):
                    parent.text = parent.text or ''
                    parent.tail = parent.tail or ''
                    if child.text:
                        # We strip() here b/c mediawiki pads the text with a
                        # space for some reason.
                        tail = child.tail or ''
                        parent.text += (child.text.strip() + tail)
                    child.tag = 'removeme'
    return tree


def remove_elements_tagged_for_removal(tree):
    new_tree = []
    for elem in tree:
        if elem.tag == 'removeme':
            continue
        for parent in elem.getiterator():
            for child in parent:
                if child.tag == 'removeme':
                    parent.remove(child)
        new_tree.append(elem)
    return new_tree


def _get_templates_on_page(pagename):
    params = {
        'action': 'query',
        'prop': 'templates',
        'titles': pagename,
    }
    req = api.APIRequest(site, params)
    response = req.query()
    pages = response['query']['pages']

    if not pages:
        return []

    page_info = pages[pages.keys()[0]]
    if not 'templates' in page_info:
        return []

    # There are some templates in use.
    return [e['title'] for e in page_info['templates']]


def _render_template(template_name):
    name_part = template_name[len('Template:'):]
    wikitext = '{{%s}}' % name_part
    html = render_wikitext(template_name, wikitext)
    return html


def create_mw_template_as_page(template_name, template_html):
    """
    Create a page to hold the rendered template.

    Returns:
        String representing the pagename of the new include-able page.
    """
    from pages.models import Page, slugify

    name_part = template_name[len('Template:'):]
    # Keeping it simple for now.  We can namespace later if people want that.
    include_name = name_part

    if not Page.objects.filter(slug=slugify(include_name)):
        mw_page = page.Page(site, title=template_name)
        p = Page(name=include_name)
        p.content = process_html(template_html, pagename=template_name,
                                 mw_page_id=mw_page.pageid,
                                 attach_img_to_pagename=include_name,
                                 show_img_borders=False)
        p.clean_fields()
        p.save()

    return include_name


def replace_mw_templates_with_includes(tree, pagename):
    """
    Replace {{templatethings}} inside of pages with our page include plugin.

    We can safely do this when the template doesn't have any arguments.
    When it does have arguments we just import it as raw HTML for now.
    """
    # We use the API to figure out what templates are being used on a given
    # page, and then translate them to page includes.  This can be done for
    # templates without arguments.
    #
    # The API doesn't tell us whether or not a template has arguments,
    # but we can figure this out by rendering the template and comparing the
    # resulting HTML to the HTML inside the rendered page.  If it's identical,
    # then we know we can replace it with an include.

    def _normalize_html(s):
        p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
        tree = p.parseFragment(s, encoding='UTF-8')
        return _convert_to_string(tree)

    # Finding and replacing is easiest if we convert the tree to
    # HTML and then back again.  Maybe there's a better way?

    html = _convert_to_string(tree)
    templates = _get_templates_on_page(pagename)
    for template in templates:
        template_html = _normalize_html(_render_template(template))
        if template_html in html and template_html.strip():
            # It's an include-style template.
            include_pagename = create_mw_template_as_page(template,
                template_html)
            include_classes = ''
            include_html = (
                '<a href="%(quoted_pagename)s" '
                 'class="plugin includepage%(include_classes)s">'
                 'Include page %(pagename)s'
                '</a>' % {
                    'quoted_pagename': urllib.quote(include_pagename),
                    'pagename': include_pagename,
                    'include_classes': include_classes,
                    }
            )
            html = html.replace(template_html, include_html)
            p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
                    tree=html5lib.treebuilders.getTreeBuilder("lxml"),
                    namespaceHTMLElements=False)
            tree = p.parseFragment(html, encoding='UTF-8')

    return tree


def process_non_html_elements(html, pagename):
    """
    Some MediaWiki extensions (e.g. google maps) output custom tags like
    &lt;googlemap&gt;.  We process those here.
    """
    def _repl_googlemap(match):
        global mapdata_objects_to_create
        xml = '<googlemap %s></googlemap>' % match.group('attribs')
        dom = minidom.parseString(xml)
        elem = dom.getElementsByTagName('googlemap')[0]
        lon = elem.getAttribute('lon')
        lat = elem.getAttribute('lat')

        d = {'pagename': pagename, 'lat': lat, 'lon': lon}
        mapdata_objects_to_create.append(d)

        return ''  # Clear out the googlemap tag nonsense.

    html = re.sub(
        '(?P<map>&lt;googlemap (?P<attribs>.+?)&gt;'
            '((.|\n)+?)'
        '&lt;/googlemap&gt;)',
        _repl_googlemap, html)
    return html


def fix_image_html(mw_img_title, quoted_mw_img_title, filename, tree,
        border=True):
    # Images start with something like this:
    # <a href="/mediawiki-1.16.0/index.php/File:1009-Packard.jpg"
    #    class="image">
    for elem in tree:
        for img_a in elem.findall(".//a[@class='image']"):
            if img_a.attrib.get('href', '').endswith(quoted_mw_img_title):
                # This is a link to the image with class image, so this is an
                # image reference.

                # Let's turn the image's <a> tag into the <span> tag with
                # an <img> inside it.  And set all the attributes to the
                # correct values.
                # Our images look like this:
                # <span class="image_frame image_frame_border">
                #    <img src="_files/narwals.jpg"
                #         style="width: 272px; height: 362px;">
                # </span>
                if border:
                    extra_classes = ' image_frame_border'
                else:
                    extra_classes = ''
                img_elem = img_a.find('img')
                width = img_elem.attrib.get('width')
                height = img_elem.attrib.get('height')
                is_thumb = 'thumbimage' in img_elem.attrib.get('class', '')
                caption = None
                if is_thumb:
                    img_wrapper = img_a.getparent().getparent()
                else:
                    # Is this a floated, non-thumbnailed image
                    if (img_a.getparent() and
                        'float' in img_a.getparent().attrib.get('class', '')):
                        img_wrapper = img_a.getparent()
                    else:
                        img_wrapper = img_a

                if is_thumb:
                    # We use the parent's class info to figure out whether to
                    # float the image left/right.
                    #
                    # The MediaWiki HTML looks like this:
                    #
                    # <div class="thumb tright">
                    #   <div class="thumbinner" style="width:302px;">
                    #     <a href="/index.php/File:Michigan-State-Telephone-Company.png" class="image">
                    #       <img alt="" src="/mediawiki-1.16.0/images/thumb/d/dd/Michigan-State-Telephone-Company.png/300px-Michigan-State-Telephone-Company.png" width="300" height="272" class="thumbimage" />
                    #     </a>
                    #     <div class="thumbcaption">
                    #        <div class="magnify"><a href="/mediawiki-1.16.0/index.php/File:Michigan-State-Telephone-Company.png" class="internal" title="Enlarge"><img src="/mediawiki-1.16.0/skins/common/images/magnify-clip.png" width="15" height="11" alt="" /></a>
                    #        </div>
                    #        <strong class="selflink">Michigan State Telephone Company</strong>
                    #     </div>
                    #   </div>
                    # </div>
                    if 'tright' in img_wrapper.attrib.get('class'):
                        extra_classes += ' image_right'
                    elif 'tleft' in img_wrapper.attrib.get('class'):
                        extra_classes += ' image_left'
                    # Does the image have a caption?
                    caption = img_wrapper.find(".//div[@class='thumbcaption']")
                    if caption is not None:
                        magnify = caption.find(".//div[@class='magnify']")
                        tail = ''
                        if magnify:
                            tail = magnify.tail
                            caption.remove(magnify)
                        if tail:
                            caption.text = caption.text or ''
                            caption.text += tail
                        # MediaWiki creates a caption div even if the
                        # image doesn't have a caption, so we have to
                        # test to see if the div is empty here.
                        if not (_convert_to_string(caption) or caption.text):
                            # No caption content, so let's set caption
                            # to None.
                            caption = None
                        # Caption is now clean.  Yay!
                else:
                    # Can still be floated
                    if 'floatright' in img_wrapper.attrib.get('class', ''):
                        extra_classes += ' image_right'
                    elif 'floatright' in img_wrapper.attrib.get('class', ''):
                        extra_classes += ' image_left'

                img_wrapper.clear()
                img_wrapper.tag = 'span'

                img_wrapper.attrib['class'] = (
                    'image_frame' + extra_classes)
                img = etree.Element("img")
                img.attrib['src'] = "_files/%s" % filename
                if width and height:
                    img.attrib['style'] = 'width: %spx; height: %spx;' % (
                        width, height
                    )
                img_wrapper.append(img)
                if caption is not None:
                    caption.tag = 'span'
                    caption.attrib['class'] = 'image_caption'
                    caption.attrib['style'] = 'width: %spx;' % width
                    img_wrapper.append(caption)

    return tree


def grab_images(tree, page_id, pagename, attach_to_pagename=None,
        show_image_borders=True):
    """
    Imports the images on a page as PageFile objects and fixes the page's
    HTML to be what we want for images.
    """
    from django.core.files.base import ContentFile
    from pages.models import slugify, PageFile

    # Get the list of images on this page
    params = {
        'action': 'query',
        'prop': 'images',
        'imlimit': 500,
        'pageids': page_id,
    }
    req = api.APIRequest(site, params)
    response = req.query()
    imagelist_by_pageid = response['query']['pages']
    # We're processing one page at a time, so just grab the first.
    imagelist = imagelist_by_pageid[imagelist_by_pageid.keys()[0]]
    if not 'images' in imagelist:
        # Page doesn't have images.
        return tree
    images = imagelist['images']

    for image_dict in images:
        image_title = image_dict['title']
        filename = image_title[len('File:'):]
        # Get the image info for this image title
        params = {
            'action': 'query',
            'prop': 'imageinfo',
            'imlimit': 500,
            'titles': image_title,
            'iiprop': 'timestamp|user|url|dimensions|comment',
        }
        req = api.APIRequest(site, params)
        response = req.query()
        info_by_pageid = response['query']['pages']
        # Doesn't matter what page it's on, we just want the info.
        info = info_by_pageid[info_by_pageid.keys()[0]]
        image_info = info['imageinfo'][0]
        image_url = image_info['url']
        image_description_url = image_info['descriptionurl']
        quoted_image_title = urlsplit(image_description_url).path.split('/')[-1]

        # Get the full-size image binary and store it in a string.
        img_ptr = urllib.URLopener()
        img_tmp_f = open(img_ptr.retrieve(image_url)[0], 'r')
        file_content = ContentFile(img_tmp_f.read())
        img_tmp_f.close()
        img_ptr.close()

        # For each image, find the image's supporting HTML in the tree
        # and transform it to comply with our HTML.
        html_before_fix = _convert_to_string(tree)
        tree = fix_image_html(image_title, quoted_image_title, filename, tree,
            border=show_image_borders
        )

        if _convert_to_string(tree) == html_before_fix:
            # Image isn't actually on the page, so let's not create or attach
            # the PageFile.
            continue

        # Create the PageFile and associate it with the current page.
        print "..Creating image %s on page %s" % (filename, pagename)
        attach_to_pagename = attach_to_pagename or pagename
        pfile = PageFile(name=filename, slug=slugify(attach_to_pagename))
        pfile.file.save(filename, file_content, save=False)
        pfile.save()

    return tree


def fix_indents(tree):
    def _change_to_p():
        # We replace the dl_parent with the dd_item
        dl_parent.clear()
        dl_parent.tag = 'p'
        dl_parent.attrib['class'] = 'indent%s' % depth
        for child in dd_item.iterchildren():
            dl_parent.append(child)
        dl_parent.text = dl_parent.text or ''
        dl_parent.text += (dd_item.text or '')
        dl_parent.tail = dl_parent.tail or ''
        dl_parent.tail += (dd_item.tail or '')
    for elem in tree:
        in_dd = False
        depth = 0
        for item in elem.iter():
            if item.tag == 'dl' and not in_dd:
                dl_parent = item
            if item.tag == 'dd':
                depth += 1
                in_dd = True
                dd_item = item
            if in_dd and item.tag not in ('dd', 'dl'):
                in_dd = False
                _change_to_p()
        if in_dd:
            # Ended in dd
            _change_to_p()
    return tree


def remove_toc(tree):
    """
    Remove the table of contents table.
    """
    for elem in tree:
        if elem.tag == 'table' and elem.attrib.get('id') == 'toc':
            elem.tag = 'removeme'
        toc = elem.find(".//table[@id='toc']")
        if toc:
            toc.tag = 'removeme'
    return tree


def remove_script_tags(tree):
    """
    Remove script tags.
    """
    for elem in tree:
        if elem.tag == 'script':
            elem.tag = 'removeme'
        for script in elem.findall(".//script"):
            script.tag = 'removeme'
    return tree


def replace_blockquote(tree):
    """
    Replace <blockquote> with <p class="indent1">
    """
    for elem in tree:
        if elem.tag == 'blockquote':
            elem.tag = 'p'
            elem.attrib['class'] = 'indent1'
        for item in elem.findall(".//blockquote"):
            item.tag = 'p'
            item.attrib['class'] = 'ident1'
    return tree


def fix_image_galleries(tree):
    """
    We remove the image gallery wrapper HTML / table and we move the
    gallery text caption into the image caption itself.

    At some point we may have our own 'gallery' mode for displaying a set
    of images at equal size, but for now we just run them all together - it
    should look pretty reasonable in most cases.
    """
    def _fix_gallery(item):
        # Grab all of the image spans inside of the item table.
        p = etree.Element("p")
        for image in item.findall(".//span"):
            if not 'image_frame' in image.attrib.get('class'):
                continue
            caption = image.getparent().getparent(
                ).getparent().find(".//div[@class='gallerytext']")
            # We have a gallery caption, so let's add it to our image
            # span.
            if caption:
                img_style = image.find('img').attrib['style']
                for css_prop in img_style.split(';'):
                    if css_prop.startswith('width:'):
                        width = css_prop
                our_caption = etree.Element("span")
                our_caption.attrib['class'] = 'image_caption'
                our_caption.attrib['style'] = '%s;' % width
                # Caption has an inner p, and we don't want that.
                caption = caption.find('p')
                for child in caption.iterchildren():
                    our_caption.append(child)
                text = caption.text or ''
                our_caption.text = text
                image.append(our_caption)
            p.append(image)

        item.tag = 'removeme'
        if len(list(p.iterchildren())):
            return p
        return None

    new_tree = []
    for elem in tree:
        if elem.tag == 'table' and elem.attrib.get('class') == 'gallery':
            gallery = _fix_gallery(elem)
            new_tree.append(gallery)
        else:
            for item in elem.findall(".//table[@class='gallery']"):
                gallery = _fix_gallery(item)
                pos = gallery.getparent().index()
                gallery.getparent().insert(pos, gallery)
                item.tag = 'removeme'
            new_tree.append(elem)

    return new_tree


def convert_some_divs_to_tables(tree):
    """
    We don't allow generic <div>s.  So we convert some divs to table tags,
    which we allow styling on.
    """
    # For now we just convert all divs to tables and let our HTML
    # sanitization take care of the rest.  This obviously won't always
    # give the correct results, but it's good enough most of the time.
    def _fix(item):
        item.tag = 'table'
        tr = etree.Element('tr')
        td = etree.Element('td')
        tr.append(td)

        for child in item.iterchildren():
            td.append(child)
        td.text = item.text
        style = item.attrib.get('style')
        if style:
            td.attrib['style'] = style

        item.clear()
        item.append(td)

    for elem in tree:
        if elem.tag == 'div':
            _fix(elem)
        for item in elem.findall(".//div"):
            _fix(item)
    return tree


def process_html(html, pagename=None, mw_page_id=None, attach_img_to_pagename=None,
        show_img_borders=True):
    """
    This is the real workhorse.  We take an html string which represents
    a rendered MediaWiki page and process bits and pieces of it, normalize
    elements / attributes and return cleaned up HTML.
    """
    html = process_non_html_elements(html, pagename)
    p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
    tree = p.parseFragment(html, encoding='UTF-8')
    tree = replace_mw_templates_with_includes(tree, pagename)
    tree = fix_internal_links(tree)
    tree = fix_basic_tags(tree)
    tree = remove_edit_links(tree)
    tree = remove_headline_labels(tree)
    tree = throw_out_tags(tree)
    tree = remove_toc(tree)
    tree = remove_script_tags(tree)
    tree = replace_blockquote(tree)
    if pagename is not None and mw_page_id:
        tree = grab_images(tree, mw_page_id, pagename,
            attach_img_to_pagename, show_img_borders)
    tree = fix_image_galleries(tree)
    tree = fix_indents(tree)

    tree = convert_some_divs_to_tables(tree)

    tree = remove_elements_tagged_for_removal(tree)
    return _convert_to_string(tree)


def import_pages():
    from pages.models import Page, slugify

    request = api.APIRequest(site, {
        'action': 'query',
        'list': 'allpages',
        'aplimit': '250',
    })
    print "Getting master page list (this may take a bit).."
    response_list = request.query(querycontinue=False)['query']['allpages']
    pages = pagelist.listFromQuery(site, response_list)
    print "Got master page list."
    for mw_p in pages[:250]:
        print "Importing %s" % mw_p.title
        wikitext = mw_p.getWikiText()
        if mw_p.isRedir():
            add_redirect(mw_p)
            continue
        html = render_wikitext(mw_p.title, wikitext)

        if Page.objects.filter(slug=slugify(mw_p.title)):
            # Page already exists with this slug.  This is probably because
            # MediaWiki has case-sensitive pagenames.
            other_page = Page.objects.get(slug=slugify(mw_p.title))
            if len(html) > other_page.content:
                # *This* page has more content.  Let's use it instead.
                for other_page_version in other_page.versions.all():
                    other_page_version.delete()
                other_page.delete(track_changes=False)

        p = Page(name=mw_p.title, content=html)
        p.content = process_html(p.content, pagename=p.name,
                                 mw_page_id=mw_p.pageid)
        p.clean_fields()
        p.save()


def clear_out_existing_data():
    """
    A utility function that clears out existing pages, users, files,
    etc before running the import.
    """
    from pages.models import Page, PageFile
    from redirects.models import Redirect

    for p in Page.objects.all():
        print 'Clearing out', p
        p.delete(track_changes=False)
        for p_h in p.versions.all():
            p_h.delete()

    for f in PageFile.objects.all():
        print 'Clearing out', f
        f.delete(track_changes=False)
        for f_h in f.versions.all():
            f_h.delete()

    for r in Redirect.objects.all():
        print 'Clearing out', r
        r.delete(track_changes=False)
        for r_h in r.versions.all():
            r_h.delete()


def run():
    clear_out_existing_data()
    import_users()
    import_pages()
    process_redirects()
    process_mapdata()
