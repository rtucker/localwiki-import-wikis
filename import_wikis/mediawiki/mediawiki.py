# coding=utf-8
import os
import sys

if "DJANGO_SETTINGS_MODULE" not in os.environ:
    print "This importer must be run from the manage.py script"
    sys.exit(1)

import time
from progress.bar import Bar
import hashlib
import html5lib
import csv
import threading
from collections import defaultdict
from lxml import etree

_treebuilder = html5lib.treebuilders.getTreeBuilder("lxml")

from xml.dom import minidom
from urlparse import urljoin, urlsplit, urlparse, parse_qs
import urllib
import urllib2
import re
from dateutil.parser import parse as date_parse
from mediawikitools import *

from django.db import transaction
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, DatabaseError, connection
from haystack import site as haystack_site
from pages.plugins import unquote_url


_maps_installed = False
try:
    import maps.models
    _maps_installed = True
except ImportError:
    pass


site = None
SCRIPT_PATH = None
include_pages_to_create = []
mapdata_objects_to_create = defaultdict(list)


def guess_api_endpoint(url):
    if url.endswith('api.php'):
        return url
    return urljoin(url, 'api.php')


def guess_script_path(url):
    mw_path = urlsplit(url).path
    if mw_path.endswith('.php'):
        return mw_path
    if not mw_path:
        return '/'
    return urljoin(mw_path, '.')


def set_script_path(path):
    global SCRIPT_PATH
    SCRIPT_PATH = path


# In general, we want only one thread at a time to write information
# about a particular page. Checking for page existence, etc is best done
# in isolation.
page_lookup_lock_db = defaultdict(threading.Lock)
page_lookup_lock = threading.Lock()


def process_concurrently(work_items, work_func, num_workers=4, name='items'):
    """
    Apply a function to all work items using a number of concurrent workers
    """
    def worker():
        from django.db import close_connection, connection
        close_connection()
        connection.connection = None
        while True:
            try:
                item = q.get()
                work_func(item)
            except:
                from django.db import close_connection, connection
                close_connection()
                connection.connection = None
                try:
                    # try again..
                    time.sleep(5)
                    work_func(item)
                except:
                    from django.db import close_connection, connection
                    close_connection()
                    connection.connection = None

                    traceback.print_exc()
                    print "Unable to process %s" % item
            q.task_done()
            progress_bar.next()
            print ""

    from Queue import Queue
    from threading import Thread
    import traceback

    q = Queue()
    for item in work_items:
        q.put(item)

    num_items = q.qsize()
    progress_bar = Bar('Progress', max=num_items)

    for i in range(num_workers):
        t = Thread(target=worker)
        t.daemon = True
        t.start()
    # wait for all workers to finish
    q.join()
    progress_bar.finish()


def get_robot_user():
    try:
        u = User.objects.get(username="LocalWikiRobot")
    except User.DoesNotExist:
        u = User(name='LocalWiki Robot', username='LocalWikiRobot',
                 email='editrobot@localwiki.org')
        try:
            u.save()
        except IntegrityError:
            pass  # another thread beat us
    return u


def normalize_username(username):
    """
    MediaWiki allows usernames with spaces in them, which is pretty weird.
    """
    max_length = 30
    return username[:max_length].replace(' ', '')


def import_users():
    request = api.APIRequest(site, {
        'action': 'query',
        'list': 'allusers',
        'aulimit': 500,
        'auprop': 'registration',
    })
    for item in request.query()['query']['allusers']:
        username = item['name']
        date_joined = item.get('registration', '').strip()
        if date_joined:
            date_joined = date_parse(date_joined)

        # We require users to have an email address, so we fill this in with a
        # dummy value for now.
        name_hash = hashlib.sha1(username.encode('utf-8')).hexdigest()
        email = "%s@FIXME.localwiki.org" % name_hash

        if User.objects.filter(username=normalize_username(username)).exists():
            continue

        print "Importing user %s as %s" % (
            username.encode('utf-8'),
            normalize_username(username).encode('utf-8'))

        user_args = {
            'username': normalize_username(username),
            'email': email,
            'name': username
        }

        if date_joined:
            user_args['date_joined'] = date_joined

        u = User(**user_args)
        u.save()


def set_user_emails_from_csv(csv_location):
    """
    Import users' email addresses and real names from provided CSV.
    """
    with open(csv_location) as csvfile:
        reader = csv.reader(csvfile)
        for item in reader:
            name = None
            username, email = item[0], item[1]
            if len(item) >= 3:
                name = item[2]
            if not username.strip() or not email.strip():
                continue
            user, created = User.objects.get_or_create(
                username=normalize_username(username))
            if name:
                user.name = name
            if created:
                if not user.name:
                    user.name = username
            if User.objects.filter(email=email):
                other = User.objects.get(email=email)
                if other.username != user.username:
                    print ('The user account "%s" is already using '
                           'the email address %s..skipping' %
                           (other.username, email))
                    continue
            user.email = email
            try:
                user.save()
            except:
                connection.close()
                continue


def fix_pagename(name):
    if name.startswith('Talk:'):
        return name[5:] + "/Talk"
    if name.startswith('User:'):
        return "Users/" + name[5:]
    if name.startswith('User talk:'):
        return "Users/" + name[10:] + "/Talk"
    if name.startswith('Category:'):
        # For now, let's just throw these into the main
        # namespace.
        return name[9:]
    if name.startswith('Category talk:'):
        # For now, let's just throw these into the main
        # namespace.
        return name[14:] + "/Talk"
    return name


def import_redirect(from_pagename):
    """
    We create the Redirects here.  We don't try and port over the
    version information for the formerly-page-text-based redirects.
    """
    to_pagename = parse_redirect(from_pagename)
    if to_pagename is None:
        print "Error creating redirect: %s has no link" % from_pagename
        return
    to_pagename = fix_pagename(to_pagename)

    from pages.models import Page, slugify
    from redirects.models import Redirect

    u = get_robot_user()

    try:
        to_page = Page.objects.get(slug=slugify(to_pagename))
    except Page.DoesNotExist:
        print "Error creating redirect: %s --> %s" % (
            from_pagename.encode('utf-8'), to_pagename.encode('utf-8'))
        print "  (page %s does not exist)" % to_pagename.encode('utf-8')
        return

    if slugify(from_pagename) == to_page.slug:
        return
    if not Redirect.objects.filter(source=slugify(from_pagename)):
        r = Redirect(source=slugify(from_pagename), destination=to_page)
        try:
            r.save(user=u, comment="Automated edit. Creating redirect.")
        except IntegrityError:
            connection.close()
        print "Redirect %s --> %s created" % (from_pagename.encode('utf-8'),
                                              to_pagename.encode('utf-8'))


def import_redirects():
    redirects = [mw_p.title for mw_p in get_redirects()]
    process_concurrently(redirects, import_redirect,
                         num_workers=4, name='redirects')


def process_mapdata():
    """
    We create the MapData models here.  We can't create them until the
    Page objects are created.
    """
    global mapdata_objects_to_create

    from maps.models import MapData
    from pages.models import Page, slugify
    from django.contrib.gis.geos import Point, MultiPoint

    for page_name, coords in mapdata_objects_to_create.iteritems():
        print "Adding mapdata for", page_name.encode('utf-8')
        try:
            p = Page.objects.get(slug=slugify(page_name))
        except Page.DoesNotExist:
            print "*** Warning *** Skipping mapdata for page", page_name
            print ("    Found mapdata for the page on mediawiki site, but "
                   "the page does not exist in localwiki.")
            continue

        mapdata = MapData.objects.filter(page=p)
        if mapdata:
            m = mapdata[0]
        else:
            m = MapData(page=p)

        for lat, lon in coords:
            y = float(lat)
            x = float(lon)
            point = Point(x, y)

            if m.points:
                m.points.append(point)
            else:
                m.points = MultiPoint(point)

        try:
            m.save()
        except IntegrityError:
            connection.close()
        except ValueError:
            print "Bad value in mapdata"

        # Edit MapData history and set the current version to the time the page
        # was most recently edited to avoid spamming Recent Changes.
        m_h = m.versions.most_recent()
        m_h.history_date = p.versions.most_recent().version_info.date
        m_h.save()


def parse_page(page_name):
    """
    Attrs:
        page_name: Name of page to render.

    Returns:
        Dictionary containing:
         "html" - HTML string of the rendered wikitext
         "links" - List of links in the page
         "templates" - List of templates used in the page
         "categories" - List of categories
    """
    request = api.APIRequest(site, {
        'action': 'parse',
        'page': page_name
    })
    return parse_result(request)


def parse_revision(rev_id):
    """
    Attrs:
        rev_id: Revision to render.

    Returns:
        Dictionary containing:
         "html" - HTML string of the rendered wikitext
         "links" - List of links in the page
         "templates" - List of templates used in the page
         "categories" - List of categories
    """
    request = api.APIRequest(site, {
        'action': 'parse',
        'oldid': rev_id
    })
    return parse_result(request)


def parse_redirect(page_name):
    """
    Attrs:
        page_name: Name of redirect page to parse

    Returns:
        Redirect destination link or None
    """
    request = api.APIRequest(site, {
        'action': 'parse',
        'page': page_name,
        'prop': 'links'
    })
    result = parse_result(request)
    if result["links"]:
        return result["links"][0]
    return None


def parse_result(request):
    result = request.query()['parse']

    parsed = {}
    html = result.get('text', None)
    if html:
        parsed["html"] = result['text']['*']
    links = result.get('links', [])
    parsed["links"] = [l['*'] for l in links]
    templates = result.get('templates', [])
    parsed["templates"] = [t['*'] for t in templates]
    categories = result.get('categories', [])
    parsed["categories"] = [c['*'] for c in categories]
    return parsed


def parse_wikitext(wikitext, title):
    """
    Attrs:
        wikitext: Wikitext to parse.
        title: Title with which to render the page.

    Returns:
        HTML string of the parsed wikitext
    """
    request = api.APIRequest(site, {
        'action': 'parse',
        'text': wikitext,
        'title': title
    })
    result = request.query()['parse']
    return result['text']['*']


def _convert_to_string(l):
    s = ''
    for e in l:
        # ignore broken elements and HTML comments
        if e is None or isinstance(e, etree._Comment):
            continue
        if type(e) == str:
            s += e
        elif type(e) == unicode:
            s += e.encode('utf-8')
        elif isinstance(e, list):
            s += _convert_to_string(e)
        else:
            s += etree.tostring(e, method='html', encoding='UTF-8')
    return s.decode('utf-8')


def _is_wiki_page_url(href):
    if SCRIPT_PATH and href.startswith(SCRIPT_PATH):
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
            if has_class('new', link):
                # It's a link to a non-existent page, so we parse the
                # page name from the title attribute in a really
                # hacky way.  Titles for non-existent links look
                # like <a ... title="Page name (page does not exist)">
                pagename = title[:title.rfind('(') - 1]
            else:
                pagename = title
    if type(pagename) == unicode:
        pagename = pagename.encode('utf-8')

    if pagename:
        pagename = fix_pagename(pagename)

    return pagename


def fix_internal_links(tree):
    def _process(item):
        pagename = _get_wiki_link(item)
        if pagename:
            # Set href to quoted pagename and clear out other attributes
            for k in item.attrib:
                del item.attrib[k]
            item.attrib['href'] = urllib.quote(pagename)

    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'a':
            _process(elem)
        for link in elem.findall('.//a'):
            _process(link)
    return tree


def fix_basic_tags(tree):
    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        # Replace i, b with em, strong.
        if elem.tag == 'b':
            elem.tag = 'strong'
        for item in elem.findall('.//b'):
            item.tag = 'strong'

        if elem.tag == 'i':
            elem.tag = 'em'
        for item in elem.findall('.//i'):
            item.tag = 'em'

        # Replace <big> with <strong>
        if elem.tag == 'big':
            elem.tag = 'strong'
        for item in elem.findall('.//big'):
            item.tag = 'strong'

        # Replace <font> with <strong>
        if elem.tag == 'font':
            elem.tag = 'strong'
        for item in elem.findall('.//font'):
            item.tag = 'strong'

        # Replace <code> with <tt>
        if elem.tag == 'code':
            elem.tag = 'tt'
        for item in elem.findall('.//code'):
            item.tag = 'tt'

    return tree


def has_class(css_class, elem):
    attrib = elem.get('class')
    if attrib:
        return css_class in attrib.split()
    return False


def remove_edit_links(tree):
    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'span' and has_class('editsection', elem):
            elem.tag = 'removeme'
        for item in elem.findall(".//span[@class='editsection']"):
            item.tag = 'removeme'  # hack to easily remove a bunch of elements
    return tree


def strip_tags(tree):
    """
    There's some tags, like <small>, that we don't want to support.  We
    merge their content into the tree and remove the tag.
    """
    def _should_strip(elem):
        if elem.tag == 'small':
            return True
        if elem.tag == 'span':
            _special_classes = ['smwttinline', 'smwttcontent']
            # We want to keep certain spans that we process later on.
            if any([has_class(c, elem) for c in _special_classes]):
                return False
            return True
        return False

    # First, replace all tag names that ought to be stripped with
    # <stripme>
    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        for elem in elem.getiterator():
            if _should_strip(elem):
                elem.tag = 'stripme'

    # Merge the <stripme> tags into the tree.
    for subtree in tree:
        if subtree is None or isinstance(subtree, basestring):
            continue
        etree.strip_tags(subtree, 'stripme')

    return tree


def remove_headline_labels(tree):
    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        for parent in elem.getiterator():
            for child in parent:
                if child.tag == 'span' and has_class('mw-headline', child):
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
        if elem is None or isinstance(elem, basestring):
            continue
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


def _render_template(template_name, page_title=None):
    if page_title is None:
        page_title = template_name
    name_part = template_name[len('Template:'):]
    wikitext = '{{%s}}' % name_part
    html = parse_wikitext(wikitext, page_title)
    return html


def create_mw_template_as_page(template_name, template_html):
    """
    Create a page to hold the rendered template.

    Returns:
        String representing the pagename of the new include-able page.
    """
    from pages.models import Page, slugify

    robot = get_robot_user()

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
        # check if it exists again, processing takes time
        if not Page.objects.filter(slug=slugify(include_name)):
            try:
              p.save(user=robot,
                     comment="Automated edit. Creating included page.")
            except:
              pass  # another thread beat us
              

    return include_name


def replace_mw_templates_with_includes(tree, templates, page_title):
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
        p = html5lib.HTMLParser(tokenizer=html5lib.tokenizer.HTMLTokenizer,
                                tree=_treebuilder,
                                namespaceHTMLElements=False)
        tree = p.parseFragment(s, encoding='UTF-8')
        return _convert_to_string(tree)

    # Finding and replacing is easiest if we convert the tree to
    # HTML and then back again.  Maybe there's a better way?

    html = _convert_to_string(tree)
    for template in templates:
        normalized = _normalize_html(_render_template(template, page_title))
        template_html = normalized.strip()
        if template_html and template_html in html:
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

    p = html5lib.HTMLParser(tokenizer=html5lib.tokenizer.HTMLTokenizer,
                            tree=_treebuilder,
                            namespaceHTMLElements=False)
    tree = p.parseFragment(html, encoding='UTF-8')
    return tree


def fix_googlemaps(tree, pagename, save_data=True):
    """
    If the googlemaps extension is installed, then we process googlemaps here.

    If the googlemaps extension isn't installed but its markup is in the wiki
    then the maps get processed in process_non_html_elements.
    """
    def _parse_mapdata(elem):
        if not save_data:
            return
        img = elem.find('.//img')
        if img is None:
            return
        src = img.attrib.get('src')
        qs = parse_qs(urlparse(src).query)
        if qs.get('markers'):
            markers = qs['markers'][0].split('|')
            for marker in markers:
                if not marker.strip():
                        continue
                vals = marker.split(',')
                if len(vals) == 2:
                    lat, lon = vals
                elif len(vals) == 3:
                    lat, lon, color = vals
                else:
                    continue
                mapdata_objects_to_create[pagename].append((lat, lon))
        else:
            # Use the map center as the point
            center = qs['center'][0]
            lat, lon = center.split(',')
            mapdata_objects_to_create[pagename].append((lat, lon))

    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'div' and elem.attrib.get('id', '').startswith('map'):
            _parse_mapdata(elem)
            elem.tag = 'removeme'
            continue
        for item in elem.findall(".//div"):
            if item.attrib.get('id', '').startswith('map'):
                _parse_mapdata(item)
                item.tag = 'removeme'

    return tree


def fix_embeds(tree):
    """
    Replace <object>-style embeds with <iframe> for stuff we know how to work
    with.
    """
    def _parse_flow_player(s):
        query = parse_qs(urlparse(s).query)
        config = query.get('config', None)
        if not config:
            return ''
        config = config[0]
        if 'url:' not in config:
            return ''
        video_id = config.split("url:'")[1].split('/')[0]
        return 'http://www.archive.org/embed/%s' % video_id

    def _fix_embed(elem):
        iframe = etree.Element('iframe')
        if 'width' in elem.attrib:
            iframe.attrib['width'] = elem.attrib['width']
        if 'height' in elem.attrib:
            iframe.attrib['height'] = elem.attrib['height']
        movie = elem.find('.//param[@name="movie"]')
        if movie is None:
            return
        moviestr = movie.attrib['value']
        if moviestr.startswith('http://www.archive.org/flow/'):
            iframe.attrib['src'] = _parse_flow_player(moviestr)

        elem.clear()
        elem.tag = 'span'
        elem.attrib['class'] = "plugin embed"
        elem.text = _convert_to_string([iframe])

    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'object':
            _fix_embed(elem)
            continue
        for item in elem.findall(".//object"):
            _fix_embed(item)
    return tree


def fix_references(tree):
    """
    Replace <li id="cite_blah"> with <li><a name="cite_blah"></a>
    """

    def _fix_reference(elem):
        if 'id' not in elem.attrib:
            return
        text = elem.text or ''
        elem.text = ''
        # remove arrow up thing
        if len(text) and text[0] == u"\u2191":
            text = text[1:]
        # remove back-links to citations
        for item in elem.findall(".//a[@href]"):
            if item.attrib['href'].startswith('#'):
                parent = item.getparent()
                if parent.tag == 'sup':
                    text += parent.tail or ''
                    parent.getparent().remove(parent)
                else:
                    text += item.tail or ''
                    parent.remove(item)
        # create anchor
        anchor = etree.Element('a')
        anchor.attrib['name'] = elem.attrib['id']
        elem.insert(0, anchor)
        anchor.tail = text.lstrip()

    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'li':
            _fix_reference(elem)
            continue
        for item in elem.findall(".//li"):
            _fix_reference(item)
    return tree


def process_non_html_elements(html, pagename):
    """
    Some MediaWiki extensions (e.g. google maps) output custom tags like
    &lt;googlemap&gt;.  We process those here.
    """
    def _repl_googlemap(match):
        global mapdata_objects_to_create
        xml = '<googlemap %s></googlemap>' % match.group('attribs')
        try:
            dom = minidom.parseString(xml)
        except:
            return ''
        elem = dom.getElementsByTagName('googlemap')[0]
        lon = elem.getAttribute('lon')
        lat = elem.getAttribute('lat')

        mapdata_objects_to_create[pagename].append((lat, lon))

        return ''  # Clear out the googlemap tag nonsense.

    html = re.sub(
        '(?P<map>&lt;googlemap (?P<attribs>.+?)&gt;'
        '((.|\n)+?)'
        '&lt;/googlemap&gt;)',
        _repl_googlemap, html)
    return html


def fix_image_html(mw_img_title, quoted_mw_img_title, filename, tree,
                   border=True):
    """
    Take the mediawiki image HTML and turn it into our type of image
    reference.
    """
    # Images start with something like this:
    # <a href="/mediawiki-1.16.0/index.php/File:1009-Packard.jpg"><img
    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        for img_a in elem.findall(".//a[@href]"):
            if img_a.find(".//img") is None:
                continue
            href = unquote_url(img_a.attrib.get('href', 'no href'))
            if href.endswith(quoted_mw_img_title):
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
                is_thumb = has_class('thumbimage', img_elem)
                caption = None
                if is_thumb:
                    img_wrapper = img_a.getparent().getparent()
                else:
                    # Is this a floated, non-thumbnailed image
                    if (img_a.getparent() is not None and has_class('float',
                                                                    img_a)):
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
                    if has_class('tright', img_wrapper):
                        extra_classes += ' image_right'
                    elif has_class('tleft', img_wrapper):
                        extra_classes += ' image_left'
                    # Does the image have a caption?
                    caption = img_wrapper.find(".//div[@class='thumbcaption']")
                    if caption is not None:
                        magnify = caption.find(".//div[@class='magnify']")
                        tail = ''
                        if magnify is not None:
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
                    if has_class('floatright', img_wrapper):
                        extra_classes += ' image_right'
                    elif has_class('floatright', img_wrapper):
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


def page_url_to_name(page_url):
    """
    Some wikis use pretty urls and soem use ?title=.
    Try to fix that here.
    """
    if '?title=' in page_url:
        return page_url.split('?title=')[1]
    return urlsplit(page_url).path.split('/')[-1]


def get_image_info(image_title):
    params = {'action': 'query',
              'prop': 'imageinfo',
              'iilimit': 500,
              'titles': image_title,
              'iiprop': 'timestamp|user|url|dimensions|comment',
              }
    req = api.APIRequest(site, params)
    response = req.query()
    info_by_pageid = response['query']['pages']
    # Doesn't matter what page it's on, we just want the info.
    info = info_by_pageid[info_by_pageid.keys()[0]]
    return info['imageinfo']


def grab_images(tree, page_id, pagename, attach_to_pagename=None,
                show_image_borders=True):
    """
    Imports the images on a page as PageFile objects and fixes the page's
    HTML to be what we want for images.
    """
    def _get_image_binary(image_url):
            # Get the full-size image binary and store it in a string.
            img_f = urllib2.urlopen(image_url, None, 10)
            file_content = ContentFile(img_f.read())
            img_f.close()
            return file_content

    def _create_image_revisions(pfile, image_info, filename, attach_to_pagename):
        rev_num = 0
        total_revs = len(image_info)
        for revision in image_info:
            image_url = revision['url']

            rev_num += 1
            if rev_num == total_revs:
                history_type = 0  # Added
            else:
                history_type = 1  # Updated

            history_comment = revision.get('comment', None)
            if history_comment:
                history_comment = history_comment[:200]

            username = normalize_username(revision.get('user', None))
            user = User.objects.filter(username=username)
            if user:
                user = user[0]
                history_user_id = user.id
            else:
                history_user_id = None
            history_user_ip = None  # MW offers no way to get this via API

            timestamp = revision.get('timestamp', None)
            history_date = date_parse(timestamp)

            print "Creating historical image %s on page %s" % (
                filename.encode('utf-8'), attach_to_pagename.encode('utf-8'))

            # Create the historical PageFile and associate it with the current page.
            pfile_h = PageFile.versions.model(
                id=pfile.id,
                name=filename,
                slug=slugify(attach_to_pagename),
                history_comment=history_comment,
                history_date=history_date,
                history_type=history_type,
                history_user_id=history_user_id,
                history_user_ip=history_user_ip
            )

            file_content = _get_image_binary(image_url)
            # Attach the image binary
            pfile_h.file.save(filename, file_content, save=False)
            pfile_h.save()

    from django.core.files.base import ContentFile
    from pages.models import slugify, PageFile

    robot = get_robot_user()

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
        try:
            image_info = get_image_info(image_title)
        except KeyError:
            # For some reason we can't get the image info.
            # TODO: Investigate this.
            continue

        image_url = image_info[0]['url']
        image_description_url = image_info[0]['descriptionurl']

        quoted_image_title = page_url_to_name(image_description_url)
        attach_to_pagename = attach_to_pagename or pagename

        # For each image, find the image's supporting HTML in the tree
        # and transform it to comply with our HTML.
        html_before_fix = _convert_to_string(tree)
        tree = fix_image_html(image_title, quoted_image_title, filename, tree,
                              border=show_image_borders)

        if _convert_to_string(tree) == html_before_fix:
            # Image isn't actually on the page, so let's not create or attach
            # the PageFile.
            continue

        if PageFile.objects.filter(name=filename,
                                   slug=slugify(attach_to_pagename)):
            continue  # Image already exists.

        # Create the PageFile and associate it with the current page.
        print "Creating image %s on page %s" % (filename.encode('utf-8'), pagename.encode('utf-8'))
        try:
            file_content = _get_image_binary(image_url)
            pfile = PageFile(name=filename, slug=slugify(attach_to_pagename))
            pfile.file.save(filename, file_content, save=False)
            pfile.save(track_changes=False)
            _create_image_revisions(pfile, image_info, filename, attach_to_pagename)
        except IntegrityError:
            connection.close()
        except IOError:
            connection.close()

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
        if elem is None or isinstance(elem, basestring):
            continue
        in_dd = False
        depth = 0
        for item in elem.iter():
            if item is None:
                continue
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
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'table' and elem.attrib.get('id') == 'toc':
            elem.tag = 'removeme'
        toc = elem.find(".//table[@id='toc']")
        if toc is not None:
            toc.tag = 'removeme'
    return tree


def remove_script_tags(html):
    """
    Remove script tags.
    """
    return re.sub('<script(.|\n)*?>(.|\n)*?<\/script>', '', html)


def replace_blockquote(tree):
    """
    Replace <blockquote> with <p class="indent1">
    """
    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
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
            if not has_class('image_frame', image):
                continue
            caption = image.getparent().getparent().getparent().find(".//div[@class='gallerytext']")
            # We have a gallery caption, so let's add it to our image
            # span.
            if caption is not None:
                img_style = image.find('img').attrib['style']
                for css_prop in img_style.split(';'):
                    if css_prop.startswith('width:'):
                        width = css_prop
                our_caption = etree.Element("span")
                our_caption.attrib['class'] = 'image_caption'
                our_caption.attrib['style'] = '%s;' % width
                # Caption has an inner p, and we don't want that.
                caption_p = caption.find('p')
                if caption_p is not None:
                    caption = caption_p
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
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'table' and has_class('gallery', elem):
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
    which we allow styling on, aside from some special cases like addresses.
    """
    # For now we just convert divs to tables and let our HTML sanitization take
    # care of the rest.  This obviously won't always give the correct results,
    # but it's good enough most of the time. We convert special divs to span
    _special_classes = ['adr']

    def _fix(item):
        if any([has_class(c, item) for c in _special_classes]):
            item.tag = 'span'
            return
        item.tag = 'table'
        tbody = etree.Element('tbody')
        tr = etree.Element('tr')
        td = etree.Element('td')
        tr.append(td)
        tbody.append(tr)

        for child in item.iterchildren():
            td.append(child)
        td.text = item.text
        style = item.attrib.get('style')
        if style:
            td.attrib['style'] = style

        item.clear()
        item.append(tbody)

    for elem in tree:
        if elem is None or isinstance(elem, basestring):
            continue
        if elem.tag == 'div':
            _fix(elem)
        for item in elem.findall(".//div"):
            _fix(item)
    return tree


def fix_double_tables(tree):
    """
    The conversion sometimes ends up with the ever-so-pointless
    <table><tr><td><table>..</table></td></tr></table>
    """
    # For easier XPath searching.
    main = etree.Element('div')
    for elem in tree:
        main.append(elem)

    # First, let's zero out any essentially-empty <p> tags that are
    # inside of <td>s.  We need to do this because some of the infoboxes
    # are set up to create <p><br></p> all over the place.
    for p in main.findall('.//table/tbody/tr/td/p'):
        text = p.text or ''
        tail = p.tail or ''
        if (not text.strip() and not tail.strip() and
            all([c.tag == 'br' for c in p.getchildren()])):
            p.tag = 'stripme'
    etree.strip_elements(main, 'stripme')

    # Find all tables-inside-tables.
    for table in main.findall('.//table/tbody/tr/td/table'):
        # If the containing tbody has no other rows
        # and the containing row has no other cells
        # then let's ditch the containing table.
       
        table.attrib['from_merge'] = '1'

        containing_table = table.getparent().getparent().getparent().getparent()
        containing_tbody = table.getparent().getparent().getparent()
        containing_tr = table.getparent().getparent()
        containing_td = table.getparent()
        if (len(containing_tbody.getchildren()) == 1 and
            len(containing_tr.getchildren()) == 1):
            containing_table.tag = 'merge1'
            containing_tbody.tag = 'merge2'
            containing_tr.tag = 'merge3'
            containing_td.tag = 'merge4'

    etree.strip_tags(main, 'merge4')
    etree.strip_tags(main, 'merge3')
    etree.strip_tags(main, 'merge2')
    etree.strip_tags(main, 'merge1')
    tables_from_merge = list(main.findall(".//table[@from_merge='1']"))

    # Merge adjacent tables that were created via our process.
    merged_into = {}
    for i, table in enumerate(tables_from_merge):
        del table.attrib['from_merge']
        # If we have the same parent as the previously-merged and we occur
        # right after the previously-merged, then append all the table
        # rows to the previously-merged table.
        prev = tables_from_merge[i - 1]
        parent_children = list(table.getparent())
        if (i > 0 and prev.getparent() == table.getparent() and
            parent_children.index(table) == (parent_children.index(prev) + 1)):
            merge_into = merged_into.get(prev)
            if not merge_into:
                merge_into = prev[0]  # previous tbody
                merged_into[table] = merge_into
            tbody = table[0]
            for tr in tbody:
                merge_into.append(tr)
            table.tag = 'removeme'

    tree = [elem for elem in main]
    return tree


def process_html(html, pagename=None, mw_page_id=None, templates=[],
                 attach_img_to_pagename=None, show_img_borders=True,
                 historic=False):
    """
    This is the real workhorse.  We take an html string which represents
    a rendered MediaWiki page and process bits and pieces of it, normalize
    elements / attributes and return cleaned up HTML.
    """
    html = process_non_html_elements(html, pagename)
    html = remove_script_tags(html)
    p = html5lib.HTMLParser(tokenizer=html5lib.tokenizer.HTMLTokenizer,
                            tree=_treebuilder,
                            namespaceHTMLElements=False)
    tree = p.parseFragment(html, encoding='UTF-8')

    tree = remove_edit_links(tree)
    tree = remove_headline_labels(tree)
    tree = strip_tags(tree)

    tree = replace_mw_templates_with_includes(tree, templates, pagename)
    tree = fix_references(tree)
    tree = fix_embeds(tree)
    tree = fix_googlemaps(tree, pagename, save_data=(not historic))
    tree = remove_elements_tagged_for_removal(tree)
    if pagename is not None and mw_page_id:
        tree = grab_images(tree, mw_page_id, pagename,
                           attach_img_to_pagename, show_img_borders)
    tree = fix_internal_links(tree)
    tree = fix_basic_tags(tree)
    tree = remove_toc(tree)
    tree = replace_blockquote(tree)
    tree = fix_image_galleries(tree)
    tree = fix_indents(tree)

    tree = convert_some_divs_to_tables(tree)

    tree = fix_double_tables(tree)

    tree = remove_elements_tagged_for_removal(tree)

    return _convert_to_string(tree).strip()


def create_page_revisions(p, mw_p, parsed_page):
    from django.contrib.auth.models import User
    from pages.models import Page, slugify

    request = api.APIRequest(site,
                             {'action': 'query',
                              'prop': 'revisions',
                              'rvprop': 'ids|timestamp|user|comment',
                              'rvlimit': '500',
                              'titles': mw_p.title,
                              })
    response_pages = request.query()['query']['pages']
    first_pageid = response_pages.keys()[0]
    rev_num = 0
    total_revs = len(response_pages[first_pageid]['revisions'])
    for revision in response_pages[first_pageid]['revisions']:
        rev_num += 1
        if rev_num == total_revs:
            history_type = 0  # Added
        else:
            history_type = 1  # Updated

        history_comment = revision.get('comment', None)
        if history_comment:
            history_comment = history_comment[:200]

        username = normalize_username(revision.get('user', None))
        user = User.objects.filter(username=username)
        if user:
            user = user[0]
            history_user_id = user.id
        else:
            history_user_id = None
        history_user_ip = None  # MW offers no way to get this via API

        timestamp = revision.get('timestamp', None)
        history_date = date_parse(timestamp)

        revid = revision.get('revid', None)
        if rev_num == 1:  # latest revision is same as page
            parsed = parsed_page
        else:
            parsed = parse_revision(revid)
        html = parsed['html']

        # Create a dummy Page object to get the correct cleaning behavior
        dummy_p = Page(name=p.name, content=html)
        dummy_p.content = process_html(dummy_p.content, pagename=p.name,
                                       templates=parsed['templates'], mw_page_id=mw_p.pageid,
                                       historic=True)
        if not (dummy_p.content.strip()):
            dummy_p.content = '<p></p>'  # Can't be blank
        dummy_p.clean_fields()
        html = dummy_p.content

        p_h = Page.versions.model(
            id=p.id,
            name=p.name,
            slug=slugify(p.name),
            content=html,
            history_comment=history_comment,
            history_date=history_date,
            history_type=history_type,
            history_user_id=history_user_id,
            history_user_ip=history_user_ip
        )
        try:
            p_h.save()
        except IntegrityError:
            connection.close()
        print "  Imported historical page %s" % p.name.encode('utf-8')


def get_page_list(apfilterredir='nonredirects'):
    """
    Returns a list of all pages in all namespaces. Exclude redirects by
    default.
    """
    pages = []
    for namespace in ['0', '1', '2', '3', '14', '15']:
        request = api.APIRequest(site, {
            'action': 'query',
            'list': 'allpages',
            'aplimit': 500,
            'apnamespace': namespace,
            'apfilterredir': apfilterredir,
        })
        response_list = request.query()['query']['allpages']
        pages.extend(pagelist.listFromQuery(site, response_list))
    return pages


def get_redirects():
    """
    Returns a list of all redirect pages.
    """
    return get_page_list(apfilterredir='redirects')


def page_lock(f):
    def new_f(mw_p):
        from pages.models import slugify
        global page_lookup_lock, page_lookup_lock_db
        page_lookup_lock.acquire()
        page_lock = page_lookup_lock_db[slugify(mw_p.title)]
        page_lookup_lock.release()
        page_lock.acquire()
        f(mw_p)
        page_lock.release()
    return new_f


@page_lock
def import_page(mw_p):
    from pages.models import Page, slugify
    print "  Importing %s" % mw_p.title.encode('utf-8')
    parsed = parse_page(mw_p.title)
    html = parsed['html']
    name = fix_pagename(mw_p.title)

    if Page.objects.filter(slug=slugify(name)).exists():
        print "  Page %s already exists" % name.encode('utf-8')
        # Page already exists with this slug.  This is probably because
        # MediaWiki has case-sensitive pagenames.
        other_page = Page.objects.get(slug=slugify(name))
        if len(html) > other_page.content:
            print "  Clearing out other page..", other_page.name.encode('utf-8')
            # *This* page has more content.  Let's use it instead.
            for other_page_version in other_page.versions.all():
                other_page_version.delete()
            other_page.delete(track_changes=False)
        else:
            # Other page has more content.
            return

    if mw_p.title.startswith('Category:'):
        # include list of tagged pages
        include_html = (
                '<a href="tags/%(quoted_tag)s" '
                 'class="plugin includetag includepage_showtitle">'
                 'List of pages tagged &quot;%(tag)s&quot;'
                '</a>' % {
                    'quoted_tag': urllib.quote(name),
                    'tag': name,
                    }
            )
        html += include_html
    p = Page(name=name, content=html)
    p.content = process_html(p.content, pagename=p.name,
                             templates=parsed['templates'],
                             mw_page_id=mw_p.pageid, historic=False)

    if not (p.content.strip()):
        p.content = '<p> </p>'  # page content can't be blank
    p.clean_fields()
    try:
        p.save(track_changes=False)
    except IntegrityError:
        connection.close()

    try:
        create_page_revisions(p, mw_p, parsed)
    except KeyError:
        # For some reason the response lacks a revisions key
        # TODO: figure out why
        pass
    process_page_categories(p, parsed['categories'])


def import_pages():
    print "Getting master page list ..."
    get_robot_user()  # so threads won't try to create one concurrently
    pages = get_page_list()
    process_concurrently(pages, import_page, num_workers=4, name='pages')


def process_page_categories(page, categories):
    from tags.models import Tag, PageTagSet, slugify
    keys = []
    for c in categories:
        # MW uses underscores for spaces in categories
        c = str(c).replace("_", " ")
        try:
            tag, created = Tag.objects.get_or_create(slug=slugify(c),
                                                 defaults={'name': c})
            keys.append(tag.pk)
        except IntegrityError as e:
            pass
    if keys:
        pagetagset = PageTagSet(page=page)
        pagetagset.save(user=get_robot_user())
        pagetagset.tags = keys

        # Edit PageTagSet history and the current version to the time the page
        # was most recently edited to avoid spamming Recent Changes.
        pts_h = pagetagset.versions.most_recent()
        pts_h.history_date = page.versions.most_recent().version_info.date
        pts_h.save()


def find_non_googlemaps_coordinates(html_frag):
    """
    Sometimes geolocation coordinates are embedded in a page in strange ways.
    Here are two examples:
        Wiki text: {{Coordinates|lat=42.961393|lon=85.657278}}
        HTML: Geographic coordinates are <span class="smwttinline">42.961393°N, 85.657278°W<span class="smwttcontent">Latitude: 42°57′41.015″N<br />Longitude: 85°39′26.201″W</span></span>.

        Wiki text: [[Coordinates:=42.960922° N, 85.66835° W]]
        HTML: [[address:=101 South <a href="/Division_Avenue" title="Division Avenue">Division</a>]] is located in the <a href="/Heartside-Downtown" title="Heartside-Downtown">Heartside-Downtown</a> neighborhood. Geographic coordinates are <span class="smwttinline">42.960922° N, 85.66835° W<span class="smwttcontent">Latitude: 42°57′39.319″N<br />Longitude: 85°40′6.06″W</span></span>.
    We process those here.
    """
    #with codecs.open(pagename+".txt", "w", "utf-8-sig") as f:
    #    f.write(html)
    pattern = r'Geographic coordinates are <span class="smwttinline">([1-9]\d*(\.\d+)?).[ ]?N, ([1-9]\d*(\.\d+)?).[ ]?W<span class="smwttcontent">'
    match = re.search(pattern, html_frag)
    if match:
        lat = match.group(1)
        lon = '-' + match.group(3)
        return {'lat': lat, 'lon': lon}


def find_more_mapdata():
    """
    A management command that looks at all the imported pages and finds
    coordinates to turn into real mapdata. This should be run after a
    successful mediawiki import.
    """
    from django.contrib.gis.geos import Point, MultiPoint
    from maps.models import MapData
    from pages.models import Page

    for p in Page.objects.all():
        print '  Looking for mapdata in', p.name
        coord = find_non_googlemaps_coordinates(p.content)
        if coord:
            print "  Adding mapdata for", p.name
            mapdata = MapData.objects.filter(page=p)
            y = float(coord['lat'])
            x = float(coord['lon'])
            point = Point(x, y)
            if mapdata:
                m = mapdata[0]
                points = m.points
                points.append(point)
                m.points = points
            else:
                points = MultiPoint(point)
                m = MapData(page=p, points=points)
            try:
                m.save()
            except IntegrityError:
                connection.close()
            except ValueError:
                print "  Bad value in mapdata"


def clear_out_existing_data():
    """
    A utility function that clears out existing pages, users, files,
    etc before running the import.
    """
    from django.db import connection
    cursor = connection.cursor()

    from django.contrib.auth.models import User
    from users.models import UserProfile
    print 'Clearing out all user data'
    for u in UserProfile.objects.all():
        u.delete()
    for u in User.objects.all():
        u.delete()
    print 'All user data deleted'

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


def turn_off_search():
    from haystack import site as haystack_site
    from pages.models import Page
    from tags.models import PageTagSet
    from django.db import models

    haystack_site.unregister(Page)
    models.signals.m2m_changed.disconnect(sender=PageTagSet.tags.through)


def run(**options):
    global site, SCRIPT_PATH

    if options.get('users_email_csv'):
        return set_user_emails_from_csv(options.get('users_email_csv'))

    url = raw_input("Enter the address of a MediaWiki site (ex: http://arborwiki.org/): ")
    site = wiki.Wiki(guess_api_endpoint(url))
    SCRIPT_PATH = guess_script_path(url)
    sitename = site.siteinfo.get('sitename', None)
    if not sitename:
        print "Unable to connect to API. Please check the address."
        sys.exit(1)
    print "Ready to import %s" % sitename

    yes_no = raw_input("This import will clear out any existing data in this "
                       "LocalWiki instance. Continue import? (yes/no) ")
    if yes_no.lower() != "yes":
        sys.exit()

    turn_off_search()
    print "Clearing out existing data..."
    with transaction.commit_on_success():
        clear_out_existing_data()
    start = time.time()
    print "Importing users..."
    with transaction.commit_on_success():
        import_users()
    print "Importing pages..."
    import_pages()
    print "Importing redirects..."
    import_redirects()
    if _maps_installed:
        print "Processing map data..."
        process_mapdata()
    # We need to run setup_all to get back the initial user data
    # ("Anonymous", etc)
    call_command('setup_all')
    print "Import completed in %.2f minutes" % ((time.time() - start) / 60.0)

if __name__ == '__main__':
    try:
        run()
    except KeyboardInterrupt:
        print  # just a newline
