"""Within RocWiki, there exists things I call "metapages".

These are pages that are simply lists of other pages.  The most common
example of these are related to cuisines, such as "Italian Food."

This is the sort of role one might expect tags to fill.  So, this script
takes a list of Metapages (in the METAPAGE list there) and makes a bunch
of nifty tags for all of 'em.
"""

import html5lib
from urllib import unquote

from pages.models import Page, slugify
from redirects.models import Redirect
from tags.models import Tag, PageTagSet

METAPAGES = [
    'Hole-in-the-wall Restaurants',
    'breakfast',
    'buffets',
    'casual gourmet restaurants',
    'chain restaurants',
    'cheap food',
    'diners',
    'take-out food',
    'upscale restaurants',
    'bbq',
    'breakfast',
    'caribbean food',
    'chinese food',
    'ethiopian food',
    'european food',
    'german food',
    'greek food',
    'indian food',
    'italian food',
    'japanese food',
    'korean food',
    'kosher food',
    'lebanese food',
    'Mediterranean food',
    'mexican food',
    'pizza',
    'puerto rican food',
    'rochester cuisine',
    'seafood',
    'steakhouses',
    'thai food',
    'vegetarian food',
    'vietnamese food',
    'bakeries',
    'bars',
    'cafes',
    'coffeehouses',
    'delis',
    "farmers' markets",
    'grocery stores',
    'street meat', 
    'eclectic foods',
    'ice cream',
    'alfresco dining',
    'water front food',
]

def parse_page(page):
    return html5lib.parse(page.content, treebuilder='lxml').getroot()

def iter_links(tree):
    for thing in tree.iter():
        if thing.tag.endswith('a') and 'href' in thing.keys():
            yield thing.get('href')

def run(*args, **kwargs):
    metatag, created = Tag.objects.get_or_create(name="Metapages")
    for metapage in METAPAGES:
        page = Page.objects.get(name__iexact=metapage)
        tag, created = Tag.objects.get_or_create(name=page.name)
        metapts, created = PageTagSet.objects.get_or_create(page=page)
        if metatag not in metapts.tags.all():
            metapts.tags.add(metatag)
            print("%s: tagged %s" % (metatag.name, page.name))
        pagetree = parse_page(page)
        for link in iter_links(pagetree):
            childpage_qs = Page.objects.filter(slug=slugify(unquote(link)))
            childredir_qs = Redirect.objects.filter(source=slugify(unquote(link)))

            if childpage_qs.exists():
                childpage = childpage_qs.get()
            elif childredir_qs.exists():
                childpage = childredir_qs.get().destination
            else:
                print("%s: no page: %s" % (tag.name, link))
                continue

            childpts, created = PageTagSet.objects.get_or_create(page=childpage)
            if tag not in childpts.tags.all():
                childpts.tags.add(tag)
                print("%s: tagged %s" % (tag.name, childpage.name))
