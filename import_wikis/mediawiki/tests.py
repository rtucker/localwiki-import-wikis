import os
import site
import unittest
from lxml import etree
import html5lib

import sapling
site.addsitedir(os.path.abspath(os.path.split(sapling.__file__)[0]))
os.environ["DJANGO_SETTINGS_MODULE"] = "sapling.settings"

from import_wikis import mediawiki


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


def is_html_equal(h1, h2):
    p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
    h1_parsed = p.parseFragment(h1, encoding='UTF-8')
    h2_parsed = p.parseFragment(h2, encoding='UTF-8')
    return _convert_to_string(h1_parsed) == _convert_to_string(h2_parsed)


class TestHTMLNormalization(unittest.TestCase):
    def setUp(self):
        self.env = {'SCRIPT_PATH': 'http://www.arborwiki.org/index.php'}
        mediawiki.set_script_path(self.env['SCRIPT_PATH'])

    def test_internal_links(self):
        # Make sure we turn mediawiki internal links into our-style
        # internal wiki links.

        # A link to a page that doesn't exist.
        html = """<p>Some text here</p>
<p>And now a link: <a href="%(SCRIPT_PATH)s?title=Waverly_Road&amp;action=edit&amp;redlink=1" class="new" title="Waverly Road (page does not exist)">Waverly Road</a> woo!</p>""" % self.env
        expected_html = """<p>Some text here</p>
<p>And now a link: <a href="Waverly%20Road">Waverly Road</a> woo!</p>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

        # A link to a page that does exist.
        html = """<p>Some text here</p>
<p>And now a link: <a href="%(SCRIPT_PATH)s/Ann_Arbor" title="Ann Arbor">Ann Arbor</a> woo!</p>""" % self.env
        expected_html = """<p>Some text here</p>
<p>And now a link: <a href="Ann%20Arbor">Ann Arbor</a> woo!</p>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

        # A link to a redirect in MW.
        html = """<a href="%(SCRIPT_PATH)s/Ypsilanti" title="Ypsilanti" class="mw-redirect">Ypsilanti</a>""" % self.env
        expected_html = """<a href="Ypsilanti">Ypsilanti</a>"""

    def test_external_links(self):
        # Make sure we preserve external links.

        html = """<p>Some text here</p>
<p>And now a link: <a href="http://example.org/testing/?hi=1&what=there">Waverly Road</a> woo!</p>""" % self.env
        expected_html = """<p>Some text here</p>
<p>And now a link: <a href="http://example.org/testing/?hi=1&what=there">Waverly Road</a> woo!</p>""" % self.env
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

        html = """<p><a href="http://news.google.com/newspapers?id=eCVbAAAAIBAJ&amp;sjid=ZU8NAAAAIBAJ&amp;pg=3926%2C4841530" class="external text">Ann Arbor Argus</a>, Feb. 27, 1891.</p>"""
        expected_html = """<p><a href="http://news.google.com/newspapers?id=eCVbAAAAIBAJ&amp;sjid=ZU8NAAAAIBAJ&amp;pg=3926%2C4841530" class="external text">Ann Arbor Argus</a>, Feb. 27, 1891.</p>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

    def test_fix_i_b_tags(self):
        html = """<p>Some <i>text <b>here</b></i></p><p>and <i>then</i> <b>some</b> more</p>"""
        expected_html = """<p>Some <em>text <strong>here</strong></em></p><p>and <em>then</em> <strong>some</strong> more</p>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

    def test_remove_headline_labels(self):
        html = """<h2><span class="mw-headline" id="Water"> Water </span></h2>"""
        expected_html = """<h2>Water</h2>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

    def test_remove_edit_labels(self):
        html = """<h2><span class="editsection">[<a href="%(SCRIPT_PATH)s?title=After-hours_emergency&amp;action=edit&amp;section=2" title="Edit section: Water">edit</a>]</span> <span class="mw-headline" id="Water"> Water </span></h2>""" % self.env
        expected_html = """<h2>Water</h2>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

    def test_skip_small_tag(self):
        html = """<p>this is some <small>small text</small> here.</p>"""
        expected_html = """<p>this is some small text here.</p>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html), expected_html))

    def test_google_maps(self):
        html = """<p>stuff</p>&lt;googlemap lat="42.243338" lon="-83.616152" zoom="19" scale="yes" overview="yes"&gt; &lt;/googlemap&gt;"""
        expected_html = """<p>stuff</p>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html, "Test pagename"), expected_html))

    def test_image_html_fixing(self):
        mw_img_title = 'File:1873-Walling-map-excerpt.png'
        quoted_mw_img_title = 'File:1873-Walling-map-excerpt.png'
        filename = '1873-Walling-map-excerpt.png'
        html = """<div class="thumb tright"><div class="thumbinner" style="width:302px;"><a href="%(SCRIPT_PATH)s/File:1873-Walling-map-excerpt.png" class="image"><img alt="" src="/mediawiki-1.16.0/images/thumb/b/b1/1873-Walling-map-excerpt.png/300px-1873-Walling-map-excerpt.png" width="300" height="296" class="thumbimage" /></a>  <div class="thumbcaption"><div class="magnify"><a href="%(SCRIPT_PATH)s/File:1873-Walling-map-excerpt.png" class="internal" title="Enlarge"><img src="/mediawiki-1.16.0/skins/common/images/magnify-clip.png" width="15" height="11" alt="" /></a></div>Ann Arbor <b>Township</b> portion of 1873 Walling map via David Rumsey <a href="%(SCRIPT_PATH)s?title=Historical_Map_Collection&amp;action=edit&amp;redlink=1" class="new" title="Historical Map Collection (page does not exist)">Historical Map Collection</a></div></div></div>
<p>Map of Washtenaw County, Michigan. Drawn, compiled, and edited by <a href="%(SCRIPT_PATH)s/H.F._Walling" title="H.F. Walling" class="mw-redirect">H.F. Walling</a>, C.E. ... Published by R.M. &amp; S.T. Tackabury, Detroit, Mich. Entered ... 1873, by H.F. Walling ... Washington. The Claremont Manufacturing Company, Claremont, N.H., Book Manufacturers
</p>""" % self.env
        p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
        tree = p.parseFragment(html, encoding='UTF-8')
        fixed_tree = mediawiki.fix_image_html(mw_img_title, quoted_mw_img_title, filename, tree)
        fixed_html = _convert_to_string(fixed_tree)
        expected_html = """<span class="image_frame image_frame_border image_right"><img src="_files/1873-Walling-map-excerpt.png" style="width: 300px; height: 296px;"/><span class="image_caption" style="width: 300px;">Ann Arbor <b>Township</b> portion of 1873 Walling map via David Rumsey <a href="%(SCRIPT_PATH)s?title=Historical_Map_Collection&amp;action=edit&amp;redlink=1" class="new" title="Historical Map Collection (page does not exist)">Historical Map Collection</a></span></span><p>Map of Washtenaw County, Michigan. Drawn, compiled, and edited by <a href="%(SCRIPT_PATH)s/H.F._Walling" class="mw-redirect" title="H.F. Walling">H.F. Walling</a>, C.E. ... Published by R.M. &amp; S.T. Tackabury, Detroit, Mich. Entered ... 1873, by H.F. Walling ... Washington. The Claremont Manufacturing Company, Claremont, N.H., Book Manufacturers
</p>""" % self.env
        self.assertTrue(is_html_equal(fixed_html, expected_html))

        mw_img_title = 'File:Ritz Camera.jpg'
        quoted_mw_img_title = 'File:Ritz_Camera.jpg'
        filename = 'Ritz Camera.jpg'
        html = """<div class="thumb tright"><div class="thumbinner" style="width:252px;"><a href="/mediawiki-1.16.0/index.php/File:Ritz_Camera.jpg" class="image"><img alt="" src="/mediawiki-1.16.0/images/thumb/e/ec/Ritz_Camera.jpg/250px-Ritz_Camera.jpg" width="250" height="279" class="thumbimage" /></a>  <div class="thumbcaption"><div class="magnify"><a href="/mediawiki-1.16.0/index.php/File:Ritz_Camera.jpg" class="internal" title="Enlarge"><img src="/mediawiki-1.16.0/skins/common/images/magnify-clip.png" width="15" height="11" alt="" /></a></div>The front of 318 S. State St.</div></div></div>
<p>318 S. State St. is the current home of <a href="/mediawiki-1.16.0/index.php/7-Eleven" title="7-Eleven">7-Eleven</a>; it was previously occupied by <a href="/mediawiki-1.16.0/index.php/Ritz_Camera" title="Ritz Camera">Ritz Camera</a>.
</p>
<h2><span class="editsection">[<a href="/mediawiki-1.16.0/index.php?title=318_S._State_St.&amp;action=edit&amp;section=1" title="Edit section: In the news">edit</a>]</span> <span class="mw-headline" id="In_the_news"> In the news </span></h2>
<ul><li> <a href="http://www.annarbor.com/business-review/ann-arbors-ex-ritz-camera-building-on-south-state-sold-in-1305m-deal/" class="external free" rel="nofollow">http://www.annarbor.com/business-review/ann-arbors-ex-ritz-camera-building-on-south-state-sold-in-1305m-deal/</a>
</li></ul>"""
        expected_html = """<span class="image_frame image_frame_border image_right"><img src="_files/Ritz Camera.jpg" style="width: 250px; height: 279px;"/><span class="image_caption" style="width: 250px;">The front of 318 S. State St.</span></span><p>318 S. State St. is the current home of <a href="/mediawiki-1.16.0/index.php/7-Eleven" title="7-Eleven">7-Eleven</a>; it was previously occupied by <a href="/mediawiki-1.16.0/index.php/Ritz_Camera" title="Ritz Camera">Ritz Camera</a>.
</p>
<h2><span class="editsection">[<a href="/mediawiki-1.16.0/index.php?title=318_S._State_St.&amp;action=edit&amp;section=1" title="Edit section: In the news">edit</a>]</span> <span class="mw-headline" id="In_the_news"> In the news </span></h2>
<ul><li> <a href="http://www.annarbor.com/business-review/ann-arbors-ex-ritz-camera-building-on-south-state-sold-in-1305m-deal/" class="external free" rel="nofollow">http://www.annarbor.com/business-review/ann-arbors-ex-ritz-camera-building-on-south-state-sold-in-1305m-deal/</a>
</li></ul>"""
        p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
        tree = p.parseFragment(html, encoding='UTF-8')
        fixed_tree = mediawiki.fix_image_html(mw_img_title, quoted_mw_img_title, filename, tree)
        fixed_html = _convert_to_string(fixed_tree)
        self.assertTrue(is_html_equal(fixed_html, expected_html))

        mw_img_title = 'File:Archy lee ad.jpg'
        quoted_mw_img_title = 'File:Archy_lee_ad.jpg'
        filename = 'Archy lee ad.jpg'
        html = """<p><a href="/index.php?title=File:Archy_lee_ad.jpg" class="image" title="Image:Archy lee ad.jpg"><img src="/images/f/fa/Archy_lee_ad.jpg" alt="Image:Archy lee ad.jpg" height="481" border="0" width="567"/></a>
</p>"""
        expected_html = """<p><span class="image_frame image_frame_border"><img src="_files/Archy lee ad.jpg" style="width: 567px; height: 481px"></span>"""
        p = html5lib.HTMLParser(tokenizer=html5lib.sanitizer.HTMLSanitizer,
            tree=html5lib.treebuilders.getTreeBuilder("lxml"),
            namespaceHTMLElements=False)
        tree = p.parseFragment(html, encoding='UTF-8')
        fixed_tree = mediawiki.fix_image_html(mw_img_title, quoted_mw_img_title, filename, tree)
        fixed_html = _convert_to_string(fixed_tree)
        self.assertTrue(is_html_equal(fixed_html, expected_html))

    def test_convert_div(self):
        html = """<div>Blah</div>"""
        expected_html = """<table><tr><td>Blah</td></tr></table>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html, "Test convert div"), expected_html))
        html = """<div class="adr">123 Main Street</div>"""
        expected_html = """<span class="adr">123 Main Street</span>"""
        self.assertTrue(is_html_equal(mediawiki.process_html(html, "Test convert special div"), expected_html))

    def test_fix_embed(self):
        html = """<p><object width="320" height="245"><param name="movie" value="http://www.archive.org/flow/FlowPlayerLight.swf?config=%7Bembedded%3Atrue%2CshowFullScreenButton%3Atrue%2CshowMuteVolumeButton%3Atrue%2CshowMenu%3Atrue%2CautoBuffering%3Atrue%2CautoPlay%3Afalse%2CinitialScale%3A%27fit%27%2CmenuItems%3A%5Bfalse%2Cfalse%2Cfalse%2Cfalse%2Ctrue%2Ctrue%2Cfalse%5D%2CusePlayOverlay%3Afalse%2CshowPlayListButtons%3Atrue%2CplayList%3A%5B%7Burl%3A%27ssfGNSTRIK1%2FssfGNSTRIK1%5F512kb%2Emp4%27%7D%5D%2CcontrolBarGloss%3A%27high%27%2CshowVolumeSlider%3Atrue%2CbaseURL%3A%27http%3A%2F%2Fwww%2Earchive%2Eorg%2Fdownload%2F%27%2Cloop%3Afalse%2CcontrolBarBackgroundColor%3A%270x000000%27%7D"/><param name="wmode" value="transparent"/><embed height="245" width="320" wmode="transparent" type="application/x-shockwave-flash" src="http://www.archive.org/flow/FlowPlayerLight.swf?config=%7Bembedded%3Atrue%2CshowFullScreenButton%3Atrue%2CshowMuteVolumeButton%3Atrue%2CshowMenu%3Atrue%2CautoBuffering%3Atrue%2CautoPlay%3Afalse%2CinitialScale%3A%27fit%27%2CmenuItems%3A%5Bfalse%2Cfalse%2Cfalse%2Cfalse%2Ctrue%2Ctrue%2Cfalse%5D%2CusePlayOverlay%3Afalse%2CshowPlayListButtons%3Atrue%2CplayList%3A%5B%7Burl%3A%27ssfGNSTRIK1%2FssfGNSTRIK1%5F512kb%2Emp4%27%7D%5D%2CcontrolBarGloss%3A%27high%27%2CshowVolumeSlider%3Atrue%2CbaseURL%3A%27http%3A%2F%2Fwww%2Earchive%2Eorg%2Fdownload%2F%27%2Cloop%3Afalse%2CcontrolBarBackgroundColor%3A%270x000000%27%7D"/></object></p>"""
        expected_html = '<p><span class="plugin embed">&lt;iframe width="320" height="245" src="http://www.archive.org/embed/ssfGNSTRIK1"/&gt;</span></p>'
        self.assertEqual(mediawiki.process_html(html, "Test fix embeds"), expected_html)

def run():
    unittest.main()

if __name__ == '__main__':
    run()
