#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re


def find_non_googlemaps_coordinates(html, pagename):
    """
    Sometimes geolocation coordinates are embedded in a page in strange ways.
    Here are two examples:
        Wiki text: {{Coordinates|lat=42.961393|lon=85.657278}}
        HTML: Geographic coordinates are <span class="smwttinline">42.961393°N, 85.657278°W<span class="smwttcontent">Latitude: 42°57′41.015″N<br />Longitude: 85°39′26.201″W</span></span>.
              
        Wiki text: [[Coordinates:=42.960922° N, 85.66835° W]]
        HTML: [[address:=101 South <a href="/Division_Avenue" title="Division Avenue">Division</a>]] is located in the <a href="/Heartside-Downtown" title="Heartside-Downtown">Heartside-Downtown</a> neighborhood. Geographic coordinates are <span class="smwttinline">42.960922° N, 85.66835° W<span class="smwttcontent">Latitude: 42°57′39.319″N<br />Longitude: 85°40′6.06″W</span></span>.
    We process those here.
    """

    pattern = r'Geographic coordinates are <span class="smwttinline">([1-9]\d*(\.\d+)?)°[ ]?N, ([1-9]\d*(\.\d+)?)°[ ]?W<span class="smwttcontent">'
    match = re.search(pattern, html)
    if match:
        lat = match.group(1)
        lon = '-'+match.group(3)
        return {'pagename': pagename, 'lat': lat, 'lon': lon}


if __name__ == '__main__':
    mapdata_objects_to_create = []

    html1 = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en" dir="ltr">
  <head>
         <!-- More changes by paul 5/26/07 to get category tree to not throw "wgServer is not defined" error. We may need to look further at basic structure of g-wiki skin. Beagle was over a year old when we started redesigning it.-->
<!-- It's enough to just define wgServer & wgScriptPath to ''.  Hardcoding any other value can break depending on which URL someone uses to get to the wiki. ie http://www.viget.org vs http://viget.org  A more robust solution might be to look into the function provided by the MediaWiki Skin class, makeGlobalVariablesScript(), which should generate the javascript definitions based on what the wiki software is using for the current request.  Trannie 03/13/08 -->
<script type="text/javascript"> var wgServer = '';</script>
<script type="text/javascript"> var wgScriptPath = "";</script>
<script type="text/javascript"> var wgBreakFrames = "True";</script>
<script type="text/javascript"> var wgContentLanguage = "en";</script>



    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <meta http-equiv="Content-Style-Type" content="text/css" />
        <meta name="generator" content="MediaWiki 1.14.0" />
        <meta name="keywords" content="101 South Division,Division Avenue,Grand Rapids,Heartside-Downtown,Heartside Mainstreet Program,City directory,Meigs, Arthur and Company Wholesale and Retail Grocers,Glen Haven Hotel,Chaffee Brothers Furniture Company,Furniture Industry,Heather Ibrahim" />
        <link rel="alternate" type="application/atom+xml" title="Recently changed articles (ATOM 1.0)" href="http://viget.org/Special:WikiFeeds/atom/recentarticlechanges" />
        <link rel="alternate" type="application/atom+xml" title="Newest articles (ATOM 1.0)" href="http://viget.org/Special:WikiFeeds/atom/newestarticles" />
        <link rel="alternate" type="application/rss+xml" title="Recently changed articles (RSS 2.0)" href="http://viget.org/Special:WikiFeeds/rss/recentarticlechanges" />
        <link rel="alternate" type="application/rss+xml" title="Newest articles (RSS 2.0)" href="http://viget.org/Special:WikiFeeds/rss/newestarticles" />
        <link rel="stylesheet" type="text/css" href="/extensions/searchsuggest/style.css" />
        <link rel="shortcut icon" href="/favicon.ico" />
        <link rel="search" type="application/opensearchdescription+xml" href="/opensearch_desc.php" title="Viget, a Grand Rapids wiki (en)" />
        <link rel="copyright" href="/Viget:Copyrights" />
        <link rel="alternate" type="application/rss+xml" title="Viget, a Grand Rapids wiki RSS Feed" href="http://viget.org/index.php?title=Special:RecentChanges&amp;feed=rss" />
        <link rel="alternate" type="application/atom+xml" title="Viget, a Grand Rapids wiki Atom Feed" href="http://viget.org/index.php?title=Special:RecentChanges&amp;feed=atom" />
    <title>101 South Division (Viget, a Grand Rapids wiki)</title>
    <link rel="stylesheet" type="text/css" media="screen" href="/skins/gwiki/main.css" />
    <link rel="stylesheet" type="text/css" media="print" href="/skins/common/commonPrint.css" />
    <link rel="stylesheet" media="all" type="text/css" href="/skins/gwiki/final_drop.css" />
    <script type="text/javascript" src="/index.php?title=-&amp;action=raw&amp;gen=js&amp;useskin=gwiki"></script>    <script type="text/javascript" src="/skins/common/wikibits.js"></script>
    <script type="text/javascript" src="/skins/gwiki/prototype.js"></script>
    <script type="text/javascript" src="/skins/gwiki/mud_ToolTip.js"></script>
    <script type="text/javascript" src="/skins/gwiki/mud_Scripts.js"></script>

                     <!-- Head Scripts -Inserted by paul 5/26/07 to get category tree to work fully-->
        <script type="text/javascript" src="/extensions/searchsuggest/searchsuggest.js"></script>
        <script type="text/javascript">hookEvent("load", ss_ajax_onload);</script>
        <script type="text/javascript" src="/skins/common/ajax.js?195"></script>
        <link rel="stylesheet" type="text/css" href="/extensions/SemanticMediaWiki/skins/SMW_custom.css" />
        <script type="text/javascript" src="/extensions/SemanticMediaWiki/skins/SMW_tooltip.js"></script>
        <link rel="alternate" type="application/rdf+xml" title="101 South Division" href="/index.php?title=Special:ExportRDF/101_South_Division&amp;xmlmime=rdf" />

 </head>
  <body         >

<div id="tooltipbox" style="display: none;">
<div id="tooltipbox-pointer"></div>
<div id="tooltipbox-content" style="position: absolute; top: 4px; left: 0;"> </div>

</div>    

<div id="topbar">
        <div id="topbar_nav">
            <div id="topbar_nav_treeline"><a class="tooltip" title="Home" href="/Main_Page"><img src="/skins/gwiki/gfx/treeline.gif" border="0" /></a></div>

        <div id="topbar_nav_menu">
            <div class="menu">
                <ul>
                    <li style="border-left:1px solid #D6BF90;left:0px;"><a href="/Viget:Browse Category Tree"><strong>1.</strong> Browse<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                                <li><a href="/Category:People" title="Browse articles by people.">People</a></li> <!-- This isn't the right way to do this, but I haven't figured out the MediaWiki code for it yet like with mainpage -->
                                <li><a href="/Category:Places" title="Browse articles by place.">Places</a></li>
                                <li><a href="/Category:Spacing" title="Browse articles by space.">Spacing</a></li>
                                <li><a href="/Category:Political" title="Browse political.">Political</a></li>
                                <li><a href="/Category:Things" title="Browse articles by thing.">Things</a></li>
                                <li><a href="/Category:Ideas" title="Browse ideas.">Ideas</a></li>
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
    
                    </li>
                    <li><a href="/Special:Recentchanges"><strong>2.</strong> Recent<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul style="display:none;">
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                    <li><a href="/Viget:Mapping_system"><strong>3.</strong> Maps<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                               <li><a href="/Viget:Timeline">Timelines</a></li>                              
                               <li><a href="/Viget:Image_Gallery_Thumbnails">Images</a></li>
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                    <li><a href="/Viget:Projects"><strong>4.</strong> Projects<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul style="display:none;">
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                    <li><a href="/Help:Contents"><strong>5.</strong> Help<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                                <li><a href="/Viget" title="About Viget">About</a></li>
                                <li><a href="/Help:Wiki Quick Start" title="Help:Wiki Quick Start">Quick Start</a></li>
                                <li><a href="/Help:Cheatsheet" title="Syntax Cheatsheet">Cheat sheet</a></li>
                                <li><a href="/Viget:Index" title="Viget Project">Viget:Project</a></li>
                                
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>     
                    <!-- <li><a href="/Special:Userlogin"><strong>6.</strong> Login<!--[if IE 7]><!--></a><!--<![endif]--> --> 
                                         <li id="userPages-login"><a href="/index.php?title=Special:UserLogin&amp;returnto=101_South_Division"><div style="height:15px;width:80px;display:block;overflow:hidden;"><strong>6. </strong>Log in</div><!--[if IE 7]><!--></a><!--<![endif]--> 
                                                <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                                 <li style="width: 162px; background: #c0d381;border: 1px dashed #ffffff; border-width:0px 1px 1px 1px; width:150px;">
                                    <a style="width: 0; border: 0; margin: 0; line-height:200%;padding-bottom:10px;width:100%;">
                                        <form name="userlogin" method="post" action="/index.php?title=Special:Userlogin&amp;action=submitlogin&amp;type=login&amp;returnto=101 South Division">
                                            Username: <input class="loginText" name="wpName" id="wpName1" tabindex="1" value="" size="20" type="text" style="height:12px;width:142px;border:none;font-size:9px;font:family:Tahoma, Helvetica, Arial, sans-serif;"/> 
                                             Password: <input class="loginPassword" name="wpPassword" id="wpPassword1" tabindex="2" value="" size="20" type="password" style="height:12px;width:142px;border:none;ont-size:9px;font:family:Tahoma, Helvetica, Arial, sans-serif;"/>
                                             <table style="position:relative;" cellpadding="0" cellspacing="0" border="0">
                                                  <tr style="float:none;"> 
                                                     <td>
                                                          <input name="wpLoginattempt" id="wpLoginattempt" tabindex="5" value="LOG IN" type="submit" style="background:#c0d381;color:#FFFFFF;border:1px dotted #FFFFFF;padding:0px;margin-top:10px;font-size:9px;cursor:pointer;font-family:Tahoma, Helvetica, Arial, sans-serif;"/>
                                                      </td>
                                                      <td> 
                                                         <input name="wpMailmypassword" id="wpMailmypassword" tabindex="6" value="GET PASSWORD" type="submit" style="background:#c0d381;color:#FFFFFF;border:1px dotted #FFFFFF;padding:0px;margin:10px 0 0 5px;font-size:9px;font-family:Tahoma, Helvetica, Arial, sans-serif;cursor:pointer;"/>
                                                     </td>
                                                 </tr>
                                             </table>
                                         </form>
                                    </a>
                                 </li> 
                            </ul>
                                                <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                </ul>
            </div>
        </div>
        <div id="topbar_nav_search">
            <form id="searchForm" class="searchForm" name="searchForm" action="/Special:Search">
                <input input id="searchInput" class="searchInput" name="search" type="text" accesskey="f" value="" type="text" style="color:#777777;height:12px;width:150px;border:none;font-family:Tahoma, Helvetica, Arial, sans-serif;font-size:9px;padding-left:3px;">&nbsp;&nbsp;<input id="searchGoButton" class="searchButton" type='image' src="/skins/gwiki/gfx/search.gif" name="go" value="Go" />
            </form>
            <div id="searchsuggest"></div>
        </div>
    </div>
</div>



<div id="container" class="text">
    <div class="content">        
        <a name="top" id="contentTop"></a>
        
                <div class="tright" style="padding:0;margin:0;margin:0px -90px 0px 0px;">
                        <ul class="actionlist" style="height:15px;text-align:right;">
                 <li id="ca-nstab-main" class="selected" style="width:15px;"><a href="/101_South_Division">Page</a></li>
                 <li id="ca-talk" class="new" style="width:15px;"><a href="/index.php?title=Talk:101_South_Division&amp;action=edit&amp;redlink=1">Discussion</a></li>
                 <li id="ca-form_edit" style="width:15px;"><a href="/index.php?title=101_South_Division&amp;action=formedit">View form</a></li>
                 <li id="ca-viewsource" style="width:15px;"><a href="/index.php?title=101_South_Division&amp;action=edit">View source</a></li>
                 <li id="ca-history" style="width:15px;"><a href="/index.php?title=101_South_Division&amp;action=history">History</a></li>
                        </ul>
                </div>
        <script type="text/javascript">
                updateLink("ca-nstab-main", "/skins/gwiki/gfx/icon/ico_article.gif", "Article"); 
                updateLink("ca-talk", "/skins/gwiki/gfx/icon/ico_discuss.gif", "Discussion" );
                updateLink("ca-edit", "/skins/gwiki/gfx/icon/ico_edit.gif", "Edit");
                updateLink("ca-addsection","/skins/gwiki/gfx/icon/ico_plus.gif","Add Section");
                updateLink("ca-history", "/skins/gwiki/gfx/icon/ico_history.gif", "History");
                updateLink("ca-protect", "/skins/gwiki/gfx/icon/ico_protect.gif", "Protect");
                updateLink("ca-viewsource", "/skins/gwiki/gfx/icon/ico_viewsource.gif", "View Source");
                updateLink("ca-unprotect", "/skins/gwiki/gfx/icon/ico_unprotect.gif", "Unprotect");
                updateLink("ca-delete", "/skins/gwiki/gfx/icon/ico_delete.gif", "Delete");
                updateLink("ca-nstab-special", "/skins/gwiki/gfx/icon/ico_list.gif", "Special Page");
                updateLink("ca-nstab-category", "/skins/gwiki/gfx/icon/ico_list.gif", "Category");
                updateLink("ca-nstab-user", "/skins/gwiki/gfx/icon/ico_User.gif", "User Page");
                updateLink("ca-emailuser", "/skins/gwiki/gfx/icon/ico_email_user.gif", "Email this User");
                updateLink("ca-move", "/skins/gwiki/gfx/icon/ico_move.gif", "Move");
                updateLink("ca-watch", "/skins/gwiki/gfx/icon/ico_watch.gif", "Watch");
                updateLink("ca-unwatch", "/skins/gwiki/gfx/icon/ico_unwatch.gif", "Unwatch");
                updateLink("ca-nstab-project", "/skins/gwiki/gfx/icon/ico_article.gif", "Project Page");
                updateLink("ca-nstab-attribute", "/skins/gwiki/gfx/icon/ico_article.gif", "Attribute");
                updateLink("ca-nstab-image", "/skins/gwiki/gfx/icon/ico_article.gif", "Image");
                updateLink("ca-nstab-help", "/skins/gwiki/gfx/icon/ico_article.gif", "Help Page");
                updateLink("ca-nstab-projects", "/skins/gwiki/gfx/icon/ico_article.gif", "Projects"); 
                updateLink("ca-nstab-template", "/skins/gwiki/gfx/icon/ico_article.gif", "Template"); 
                updateLink("ca-purge", "/skins/gwiki/gfx/icon/ico_refresh.gif", "Refresh");
                
                
                
                
        </script>
                <div id="sidebar">
                                        <div class="tright"  style="background:#FCFCFC; border:1px solid #CCCCCC; padding: 9px 14px 0px 14px;margin-bottom:5px; width:182px;">
                        <div id="catlinks">
                            <div id='catlinks' class='catlinks'><div id="mw-normal-catlinks"><a href="/Special:Categories" title="Special:Categories">Categories</a>:&#32;<span dir='ltr'><a href="/Category:Buildings" title="Category:Buildings">Buildings</a></span> | <span dir='ltr'><a href="/Category:Architecture" title="Category:Architecture">Architecture</a></span></div></div>                        </div>
                    </div>
                </div>

                    <h1 class="firstHeading">101 South Division</h1>


                
            <!--[if IE]>
            <style type="text/css">
            v\:* {
                behavior:url(#default#VML);
            }
            </style>
            <![endif]-->
            <script src="http://maps.google.com/maps?file=api&amp;v=2.108&amp;key=ABQIAAAAVMNdXxc6yJs-Oq7wlDiWmBSqM7bzeu4ncRORHcdv6nHKo0a_sxSEhmv1eVKYSBz0kTdcH-gOfjiIdA&amp;hl=en" type="text/javascript"></script>
            <script type="text/javascript">
//<![CDATA[

        var mapIcons = {};function addLoadEvent(func) {var oldonload = window.onload;if (typeof oldonload == 'function') {window.onload= function() {oldonload();func();};} else {window.onload = func;}}
//]]>
</script>
<p>The address <strong class="selflink">101 South Division</strong> appears for the first time in the <a href="/index.php?title=City_directory&amp;action=edit&amp;redlink=1" class="new" title="City directory (page does not exist)">city directory</a> as the <a href="/index.php?title=Meigs,_Arthur_and_Company_Wholesale_and_Retail_Grocers&amp;action=edit&amp;redlink=1" class="new" title="Meigs, Arthur and Company Wholesale and Retail Grocers (page does not exist)">Meigs, Arthur and Company Wholesale and Retail Grocers</a>. By 1887 the <a href="/index.php?title=Glen_Haven_Hotel&amp;action=edit&amp;redlink=1" class="new" title="Glen Haven Hotel (page does not exist)">Glen Haven Hotel</a> began operating on the upper floors. The <a href="/index.php?title=Chaffee_Brothers_Furniture_Company&amp;action=edit&amp;redlink=1" class="new" title="Chaffee Brothers Furniture Company (page does not exist)">Chaffee Brothers Furniture Company</a>, a long time <a href="/Grand_Rapids" title="Grand Rapids">Grand Rapids</a> business, purchased the building in 1924. Chaffee’s was one of a number of <a href="/index.php?title=Furniture_Industry&amp;action=edit&amp;redlink=1" class="new" title="Furniture Industry (page does not exist)">furniture</a> stores located on South <a href="/Division_Avenue" title="Division Avenue">Division Avenue</a> from the 1920s to the 1950s. When the Furniture Company closed in the mid 1950s a variety of retail businesses were housed her and the upper floors became a rooming house.
</p>
<a name="Location" id="Location"></a><h2> <span class="mw-headline">Location</span></h2>
<p>[[address:=101 South <a href="/Division_Avenue" title="Division Avenue">Division</a>]] is located in the <a href="/Heartside-Downtown" title="Heartside-Downtown">Heartside-Downtown</a> neighborhood. Geographic coordinates are <span class="smwttinline">42.960922° N, 85.66835° W<span class="smwttcontent">Latitude: 42°57′39.319″N<br />Longitude: 85°40′6.06″W</span></span>.
</p>
<div id="map1" style="width: 600px; height: 400px; direction: ltr; "><noscript><img height="400" width="512" src="http://maps.google.com/staticmap?center=42.961495%2C-85.668254&amp;zoom=16&amp;size=512x400&amp;key=ABQIAAAAVMNdXxc6yJs-Oq7wlDiWmBSqM7bzeu4ncRORHcdv6nHKo0a_sxSEhmv1eVKYSBz0kTdcH-gOfjiIdA&amp;hl=en&amp;markers=42.960922%2C-85.66835%2Cred%7C" /></noscript><div id="map1_fallback" style="display: none;"><img height="400" width="512" src="http://maps.google.com/staticmap?center=42.961495%2C-85.668254&amp;zoom=16&amp;size=512x400&amp;key=ABQIAAAAVMNdXxc6yJs-Oq7wlDiWmBSqM7bzeu4ncRORHcdv6nHKo0a_sxSEhmv1eVKYSBz0kTdcH-gOfjiIdA&amp;hl=en&amp;markers=42.960922%2C-85.66835%2Cred%7C" /></div></div><script type="text/javascript">
//<![CDATA[
      function makeMap1() {       if (!GBrowserIsCompatible()) {           document.getElementById("map1_fallback").style.display = '';           return;       }       var map = new GMap2(document.getElementById("map1"), { 'mapTypes': [G_NORMAL_MAP, G_HYBRID_MAP, G_PHYSICAL_MAP, G_SATELLITE_MAP] });       GME_DEFAULT_ICON = G_DEFAULT_ICON;       map.setCenter(new GLatLng(42.961495, -85.668254), 16, G_HYBRID_MAP);       GEvent.addListener(map, 'click', function(overlay, point) {           if (overlay) {             if (overlay.tabs) {               overlay.openInfoWindowTabsHtml(overlay.tabs);             } else if (overlay.title_link || overlay.caption || overlay.maxContent) {                 overlay.openInfoWindowHtml('<div class="gmapinfowindow">'+                     (overlay.title?('<b>'+overlay.title_link+'</b><br />'):'')+overlay.caption+'</div>',                      { 'maxTitle': overlay.maxContent?overlay.title:undefined, 'maxContent': overlay.maxContent });                 if (overlay.maxContent) {                     map.getInfoWindow().enableMaximize();                 } else {                     map.getInfoWindow().disableMaximize();                 }             }            }       }); map.addControl(new GHierarchicalMapTypeControl());  map.addControl(new GSmallMapControl());  marker = new GMarker(new GLatLng(42.960922, -85.66835), {  'icon': GME_DEFAULT_ICON,  'clickable': true }); marker.caption = ''; marker.caption += '101 S Division Ave <!--  NewPP limit report Preprocessor node count: 1/1000000 Post-expand include size: 0/2097152 bytes Template argument size: 0/2097152 bytes Expensive parser function count: 0/100 #ifexist count: 0/100 --> '; map.addOverlay(marker); GME_DEFAULT_ICON = G_DEFAULT_ICON;} addLoadEvent(makeMap1);
//]]>
</script>

<a name="References" id="References"></a><h2> <span class="mw-headline">References</span></h2>
<p>Portions of this post were originally written by <a href="/index.php?title=Heather_Ibrahim&amp;action=edit&amp;redlink=1" class="new" title="Heather Ibrahim (page does not exist)">Heather Ibrahim</a> for the <a href="/Heartside_Mainstreet_Program" title="Heartside Mainstreet Program">Heartside Mainstreet Program</a>, reproduced with permission.
</p>
<!-- 
NewPP limit report
Preprocessor node count: 6/1000000
Post-expand include size: 0/2097152 bytes
Template argument size: 0/2097152 bytes
Expensive parser function count: 0/100
#ifexist count: 0/100
-->

<!-- Saved in parser cache with key wikidb:pcache:idhash:657-0!1!0!!en!2!edit=0 and timestamp 20120830174935 -->
<div class="printfooter">
Retrieved from "<a href="http://viget.org/101_South_Division">http://viget.org/101_South_Division</a>"</div>
    

            <script type="text/javascript">
                var toc = document.getElementById('toc');
                var sidebar = document.getElementById('sidebar');
                var catlinks = document.getElementById('catlinks');
                if(toc && sidebar && catlinks){
                    toc.parentNode.removeChild(toc);
                    catlinks.parentNode.insertBefore(toc, catlinks)
                   }
            </script>
            <div class="clear"></div>

        </div> <!-- content close -->

<div id="footer">
<div id="footer_box">
<ul class="footer">
<li><h3 style="color:#60751c">All about <strong>you</strong>!</h3></li>
<li>Pages that effect you and the experience you have with Viget (aka the preferences)</li>
<li>&nbsp;</li>    
            <li id="userPages-login"><a class="topbar" href="/index.php?title=Special:UserLogin&amp;returnto=101_South_Division">Log in / create account</a></li>
    </ul>

<ul class="footer">
<li><h3 style="color:#60751c;">Stuff about <strong>this page</strong></h3></li>
<li>The pages behind the page! You can learn about this page (and do a few things while you are at it) with the links below</li> 
<li>&nbsp;</li>
            <li id="articleInfo-whatlinkshere"><a class="topbar" href="/Special:WhatLinksHere/101_South_Division">What links here</a></li>
            <li id="articleInfo-recentchangeslinked"><a class="topbar" href="/Special:RecentChangesLinked/101_South_Division">Related changes</a></li>
            <li id="articleInfo-upload"><a class="topbar" href="">Upload file</a></li>
            <li id="articleInfo-specialpages"><a class="topbar" href="/Special:SpecialPages">Special pages</a></li>
    </ul>

<ul class="footer">
<li><h3 style="color:#60751c;"><strong>Viget</strong> MADNESS!?</h3></li>
<li>Some stuff you may find useful when using Viget</li>
<li>&nbsp;</li>
<li><a href="http://viget.org/Viget" class="topbar">About Viget</a></li>
<li><a href="http://viget.org/Help:Contents" class="topbar">Help Using Viget</a></li>
<li><a href="http://viget.org/Special:Recentchanges" class="topbar">Recent Changes</a></li>
<li><a href="http://viget.org/Special:Wantedpages" class="topbar">Wanted Pages</a></li>
<li><a href="http://viget.org/Special:Allpages" class="topbar">All Pages</a></li>
<li><a href="http://viget.org/Special:Categories" class="topbar">Categories</a></li>
<li><a href="http://viget.org/Special:Imagelist" class="topbar">Uploaded Images</a></li>
<li><a href="http://viget.org/Special:AddPage/Building" class="topbar">Add a Building</a></li>
<li><a href="http://viget.org/Viget:Copyrights" class="topbar">Copyrights</a></li>
</ul>

<ul class="footer" style="width:200px">
<li><h3 style="color:#60751c;"><strong>Find what you are looking for</strong></h3></li>
<li><form id="searchForm" class="searchForm" name="searchForm" action="/Special:Search">
                <input input id="searchInput" class="searchInput" name="search" type="text" accesskey="f" value="" type="text" style="height:16px;width:180px;border:1px solid #c0d381;font-family:arial;font-size:10pt;padding-left:4px;font-weigh:bold;">&nbsp;<input id="searchGoButton" class="searchButton" type='image' src="/skins/gwiki/gfx/search.gif" name="go" value="Go" style="margin-top:6px;" />
            </form>
            </li>
            <li><h3 style="color:#60751c;"><strong>Can't find it? Add it!</strong></h3></li>
            <li>Type in the name of the article you would like to add and go at it!</li>
            <li>&nbsp;</li>
            <li><form name="createbox" action="/index.php" method="get" class="createbox">
    <input type='hidden' name="action" value="edit" />
    <input type="hidden" name="preload" value="" />
    <input type="hidden" name="editintro" value="" />
    <input class="createboxInput" name="title" type="text"
    value="" style="height:16px;width:180px;border:1px solid #c0d381;font-family:arial;font-size:10pt;padding-left:4px;font-weigh:bold;" />&nbsp;<input type='image' name="create" class="createboxButton"
    value="Create page" src="/skins/gwiki/gfx/add.gif" style="margin-top:6px;" />
</form><br />
            </li>
            </ul>
            
            
<!-- <ul class="nav-bottom">
            <li id="articleActions=nstab-main"><a href="selected"<a href="/101_South_Division">Page</a></li>
            <li id="articleActions=talk"><a href="new"<a href="/index.php?title=Talk:101_South_Division&amp;action=edit&amp;redlink=1">Discussion</a></li>
            <li id="articleActions=form_edit"><a href=""<a href="/index.php?title=101_South_Division&amp;action=formedit">View form</a></li>
            <li id="articleActions=viewsource"><a href=""<a href="/index.php?title=101_South_Division&amp;action=edit">View source</a></li>
            <li id="articleActions=history"><a href=""<a href="/index.php?title=101_South_Division&amp;action=history">History</a></li>
    </ul> -->

<!-- <div class="searchForm">
    <form id="searchForm" class="searchForm" name="searchForm" action="/Special:Search">
        <input id="searchInput" class="searchInput" name="search" type="text" accesskey="f" value="" />&nbsp;<input id="searchGoButton" class="searchButton" type='submit' name="go" value="Go" />&nbsp;<input id="searchButton" class="searchButton" type='submit' name="fulltext" value="Search" />
    </form>
</div> -->

<div class="clear"></div>
</div>
 
<!-- <div class="poweredby">
            <span id="footer-poweredbyico"><a href="http://www.mediawiki.org/"><img src="/skins/common/images/poweredby_mediawiki_88x31.png" alt="Powered by MediaWiki" /></a></span>
    </div> -->
</div>
<div class="clear_footer"></div>
</div> <!-- container close -->
<!-- END CUSTOMIZED STUFF -->

    <!-- Served in 0.773 secs. --><script src="http://www.google-analytics.com/urchin.js" type="text/javascript">
</script>
<script type="text/javascript">
_uacct = "UA-1316290-2";
urchinTracker();
</script>
  </body>
</html>"""

    html2 = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en" dir="ltr">
  <head>
         <!-- More changes by paul 5/26/07 to get category tree to not throw "wgServer is not defined" error. We may need to look further at basic structure of g-wiki skin. Beagle was over a year old when we started redesigning it.-->
<!-- It's enough to just define wgServer & wgScriptPath to ''.  Hardcoding any other value can break depending on which URL someone uses to get to the wiki. ie http://www.viget.org vs http://viget.org  A more robust solution might be to look into the function provided by the MediaWiki Skin class, makeGlobalVariablesScript(), which should generate the javascript definitions based on what the wiki software is using for the current request.  Trannie 03/13/08 -->
<script type="text/javascript"> var wgServer = '';</script>
<script type="text/javascript"> var wgScriptPath = "";</script>
<script type="text/javascript"> var wgBreakFrames = "True";</script>
<script type="text/javascript"> var wgContentLanguage = "en";</script>



    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <meta http-equiv="Content-Style-Type" content="text/css" />
        <meta name="generator" content="MediaWiki 1.14.0" />
        <meta name="keywords" content="103 College Avenue SE,Architectural Significance,Heritage Hill,1895,Lowe, Edward" />
        <link rel="alternate" type="application/atom+xml" title="Recently changed articles (ATOM 1.0)" href="http://viget.org/Special:WikiFeeds/atom/recentarticlechanges" />
        <link rel="alternate" type="application/atom+xml" title="Newest articles (ATOM 1.0)" href="http://viget.org/Special:WikiFeeds/atom/newestarticles" />
        <link rel="alternate" type="application/rss+xml" title="Recently changed articles (RSS 2.0)" href="http://viget.org/Special:WikiFeeds/rss/recentarticlechanges" />
        <link rel="alternate" type="application/rss+xml" title="Newest articles (RSS 2.0)" href="http://viget.org/Special:WikiFeeds/rss/newestarticles" />
        <link rel="stylesheet" type="text/css" href="/extensions/searchsuggest/style.css" />
        <link rel="shortcut icon" href="/favicon.ico" />
        <link rel="search" type="application/opensearchdescription+xml" href="/opensearch_desc.php" title="Viget, a Grand Rapids wiki (en)" />
        <link rel="copyright" href="/Viget:Copyrights" />
        <link rel="alternate" type="application/rss+xml" title="Viget, a Grand Rapids wiki RSS Feed" href="http://viget.org/index.php?title=Special:RecentChanges&amp;feed=rss" />
        <link rel="alternate" type="application/atom+xml" title="Viget, a Grand Rapids wiki Atom Feed" href="http://viget.org/index.php?title=Special:RecentChanges&amp;feed=atom" />
    <title>103 College Avenue SE (Viget, a Grand Rapids wiki)</title>
    <link rel="stylesheet" type="text/css" media="screen" href="/skins/gwiki/main.css" />
    <link rel="stylesheet" type="text/css" media="print" href="/skins/common/commonPrint.css" />
    <link rel="stylesheet" media="all" type="text/css" href="/skins/gwiki/final_drop.css" />
    <script type="text/javascript" src="/index.php?title=-&amp;action=raw&amp;gen=js&amp;useskin=gwiki"></script>    <script type="text/javascript" src="/skins/common/wikibits.js"></script>
    <script type="text/javascript" src="/skins/gwiki/prototype.js"></script>
    <script type="text/javascript" src="/skins/gwiki/mud_ToolTip.js"></script>
    <script type="text/javascript" src="/skins/gwiki/mud_Scripts.js"></script>

                     <!-- Head Scripts -Inserted by paul 5/26/07 to get category tree to work fully-->
        <script type="text/javascript" src="/extensions/searchsuggest/searchsuggest.js"></script>
        <script type="text/javascript">hookEvent("load", ss_ajax_onload);</script>
        <script type="text/javascript" src="/skins/common/ajax.js?195"></script>
        <link rel="stylesheet" type="text/css" href="/extensions/SemanticMediaWiki/skins/SMW_custom.css" />
        <script type="text/javascript" src="/extensions/SemanticMediaWiki/skins/SMW_tooltip.js"></script>
        <link rel="alternate" type="application/rdf+xml" title="103 College Avenue SE" href="/index.php?title=Special:ExportRDF/103_College_Avenue_SE&amp;xmlmime=rdf" />

 </head>
  <body         >

<div id="tooltipbox" style="display: none;">
<div id="tooltipbox-pointer"></div>
<div id="tooltipbox-content" style="position: absolute; top: 4px; left: 0;"> </div>

</div>    

<div id="topbar">
        <div id="topbar_nav">
            <div id="topbar_nav_treeline"><a class="tooltip" title="Home" href="/Main_Page"><img src="/skins/gwiki/gfx/treeline.gif" border="0" /></a></div>

        <div id="topbar_nav_menu">
            <div class="menu">
                <ul>
                    <li style="border-left:1px solid #D6BF90;left:0px;"><a href="/Viget:Browse Category Tree"><strong>1.</strong> Browse<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                                <li><a href="/Category:People" title="Browse articles by people.">People</a></li> <!-- This isn't the right way to do this, but I haven't figured out the MediaWiki code for it yet like with mainpage -->
                                <li><a href="/Category:Places" title="Browse articles by place.">Places</a></li>
                                <li><a href="/Category:Spacing" title="Browse articles by space.">Spacing</a></li>
                                <li><a href="/Category:Political" title="Browse political.">Political</a></li>
                                <li><a href="/Category:Things" title="Browse articles by thing.">Things</a></li>
                                <li><a href="/Category:Ideas" title="Browse ideas.">Ideas</a></li>
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
    
                    </li>
                    <li><a href="/Special:Recentchanges"><strong>2.</strong> Recent<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul style="display:none;">
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                    <li><a href="/Viget:Mapping_system"><strong>3.</strong> Maps<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                               <li><a href="/Viget:Timeline">Timelines</a></li>                              
                               <li><a href="/Viget:Image_Gallery_Thumbnails">Images</a></li>
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                    <li><a href="/Viget:Projects"><strong>4.</strong> Projects<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul style="display:none;">
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                    <li><a href="/Help:Contents"><strong>5.</strong> Help<!--[if IE 7]><!--></a><!--<![endif]-->
                        <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                                <li><a href="/Viget" title="About Viget">About</a></li>
                                <li><a href="/Help:Wiki Quick Start" title="Help:Wiki Quick Start">Quick Start</a></li>
                                <li><a href="/Help:Cheatsheet" title="Syntax Cheatsheet">Cheat sheet</a></li>
                                <li><a href="/Viget:Index" title="Viget Project">Viget:Project</a></li>
                                
                            </ul>
                        <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>     
                    <!-- <li><a href="/Special:Userlogin"><strong>6.</strong> Login<!--[if IE 7]><!--></a><!--<![endif]--> --> 
                                         <li id="userPages-login"><a href="/index.php?title=Special:UserLogin&amp;returnto=103_College_Avenue_SE"><div style="height:15px;width:80px;display:block;overflow:hidden;"><strong>6. </strong>Log in</div><!--[if IE 7]><!--></a><!--<![endif]--> 
                                                <!--[if lte IE 6]><table><tr><td><![endif]-->
                            <ul>
                                 <li style="width: 162px; background: #c0d381;border: 1px dashed #ffffff; border-width:0px 1px 1px 1px; width:150px;">
                                    <a style="width: 0; border: 0; margin: 0; line-height:200%;padding-bottom:10px;width:100%;">
                                        <form name="userlogin" method="post" action="/index.php?title=Special:Userlogin&amp;action=submitlogin&amp;type=login&amp;returnto=103 College Avenue SE">
                                            Username: <input class="loginText" name="wpName" id="wpName1" tabindex="1" value="" size="20" type="text" style="height:12px;width:142px;border:none;font-size:9px;font:family:Tahoma, Helvetica, Arial, sans-serif;"/> 
                                             Password: <input class="loginPassword" name="wpPassword" id="wpPassword1" tabindex="2" value="" size="20" type="password" style="height:12px;width:142px;border:none;ont-size:9px;font:family:Tahoma, Helvetica, Arial, sans-serif;"/>
                                             <table style="position:relative;" cellpadding="0" cellspacing="0" border="0">
                                                  <tr style="float:none;"> 
                                                     <td>
                                                          <input name="wpLoginattempt" id="wpLoginattempt" tabindex="5" value="LOG IN" type="submit" style="background:#c0d381;color:#FFFFFF;border:1px dotted #FFFFFF;padding:0px;margin-top:10px;font-size:9px;cursor:pointer;font-family:Tahoma, Helvetica, Arial, sans-serif;"/>
                                                      </td>
                                                      <td> 
                                                         <input name="wpMailmypassword" id="wpMailmypassword" tabindex="6" value="GET PASSWORD" type="submit" style="background:#c0d381;color:#FFFFFF;border:1px dotted #FFFFFF;padding:0px;margin:10px 0 0 5px;font-size:9px;font-family:Tahoma, Helvetica, Arial, sans-serif;cursor:pointer;"/>
                                                     </td>
                                                 </tr>
                                             </table>
                                         </form>
                                    </a>
                                 </li> 
                            </ul>
                                                <!--[if lte IE 6]></td></tr></table></a><![endif]-->
                    </li>
                </ul>
            </div>
        </div>
        <div id="topbar_nav_search">
            <form id="searchForm" class="searchForm" name="searchForm" action="/Special:Search">
                <input input id="searchInput" class="searchInput" name="search" type="text" accesskey="f" value="" type="text" style="color:#777777;height:12px;width:150px;border:none;font-family:Tahoma, Helvetica, Arial, sans-serif;font-size:9px;padding-left:3px;">&nbsp;&nbsp;<input id="searchGoButton" class="searchButton" type='image' src="/skins/gwiki/gfx/search.gif" name="go" value="Go" />
            </form>
            <div id="searchsuggest"></div>
        </div>
    </div>
</div>



<div id="container" class="text">
    <div class="content">        
        <a name="top" id="contentTop"></a>
        
                <div class="tright" style="padding:0;margin:0;margin:0px -90px 0px 0px;">
                        <ul class="actionlist" style="height:15px;text-align:right;">
                 <li id="ca-nstab-main" class="selected" style="width:15px;"><a href="/103_College_Avenue_SE">Page</a></li>
                 <li id="ca-talk" class="new" style="width:15px;"><a href="/index.php?title=Talk:103_College_Avenue_SE&amp;action=edit&amp;redlink=1">Discussion</a></li>
                 <li id="ca-form_edit" style="width:15px;"><a href="/index.php?title=103_College_Avenue_SE&amp;action=formedit">View form</a></li>
                 <li id="ca-viewsource" style="width:15px;"><a href="/index.php?title=103_College_Avenue_SE&amp;action=edit">View source</a></li>
                 <li id="ca-history" style="width:15px;"><a href="/index.php?title=103_College_Avenue_SE&amp;action=history">History</a></li>
                        </ul>
                </div>
        <script type="text/javascript">
                updateLink("ca-nstab-main", "/skins/gwiki/gfx/icon/ico_article.gif", "Article"); 
                updateLink("ca-talk", "/skins/gwiki/gfx/icon/ico_discuss.gif", "Discussion" );
                updateLink("ca-edit", "/skins/gwiki/gfx/icon/ico_edit.gif", "Edit");
                updateLink("ca-addsection","/skins/gwiki/gfx/icon/ico_plus.gif","Add Section");
                updateLink("ca-history", "/skins/gwiki/gfx/icon/ico_history.gif", "History");
                updateLink("ca-protect", "/skins/gwiki/gfx/icon/ico_protect.gif", "Protect");
                updateLink("ca-viewsource", "/skins/gwiki/gfx/icon/ico_viewsource.gif", "View Source");
                updateLink("ca-unprotect", "/skins/gwiki/gfx/icon/ico_unprotect.gif", "Unprotect");
                updateLink("ca-delete", "/skins/gwiki/gfx/icon/ico_delete.gif", "Delete");
                updateLink("ca-nstab-special", "/skins/gwiki/gfx/icon/ico_list.gif", "Special Page");
                updateLink("ca-nstab-category", "/skins/gwiki/gfx/icon/ico_list.gif", "Category");
                updateLink("ca-nstab-user", "/skins/gwiki/gfx/icon/ico_User.gif", "User Page");
                updateLink("ca-emailuser", "/skins/gwiki/gfx/icon/ico_email_user.gif", "Email this User");
                updateLink("ca-move", "/skins/gwiki/gfx/icon/ico_move.gif", "Move");
                updateLink("ca-watch", "/skins/gwiki/gfx/icon/ico_watch.gif", "Watch");
                updateLink("ca-unwatch", "/skins/gwiki/gfx/icon/ico_unwatch.gif", "Unwatch");
                updateLink("ca-nstab-project", "/skins/gwiki/gfx/icon/ico_article.gif", "Project Page");
                updateLink("ca-nstab-attribute", "/skins/gwiki/gfx/icon/ico_article.gif", "Attribute");
                updateLink("ca-nstab-image", "/skins/gwiki/gfx/icon/ico_article.gif", "Image");
                updateLink("ca-nstab-help", "/skins/gwiki/gfx/icon/ico_article.gif", "Help Page");
                updateLink("ca-nstab-projects", "/skins/gwiki/gfx/icon/ico_article.gif", "Projects"); 
                updateLink("ca-nstab-template", "/skins/gwiki/gfx/icon/ico_article.gif", "Template"); 
                updateLink("ca-purge", "/skins/gwiki/gfx/icon/ico_refresh.gif", "Refresh");
                
                
                
                
        </script>
                <div id="sidebar">
                                        <div class="tright"  style="background:#FCFCFC; border:1px solid #CCCCCC; padding: 9px 14px 0px 14px;margin-bottom:5px; width:182px;">
                        <div id="catlinks">
                            <div id='catlinks' class='catlinks'><div id="mw-normal-catlinks"><a href="/Special:Categories" title="Special:Categories">Categories</a>:&#32;<span dir='ltr'><a href="/Category:Buildings" title="Category:Buildings">Buildings</a></span> | <span dir='ltr'><a href="/Category:Heritage_Hill" title="Category:Heritage Hill">Heritage Hill</a></span></div></div>                        </div>
                    </div>
                </div>

                    <h1 class="firstHeading">103 College Avenue SE</h1>


                <div class="floatleft"><a href="/File:103_College_SE-2.jpg" class="image" title="1969 Photo"><img alt="1969 Photo" src="/images/thumb/d/d3/103_College_SE-2.jpg/525px-103_College_SE-2.jpg" width="525" height="418" border="0" /></a></div>
<div class="thumb tright"><div class="thumbinner" style="width:182px;"><a href="/File:103_College_SE-3.JPG" class="image" title="Photo from 2003-2004"><img alt="" src="/images/thumb/a/a6/103_College_SE-3.JPG/180px-103_College_SE-3.JPG" width="180" height="135" border="0" class="thumbimage" /></a>  <div class="thumbcaption"><div class="magnify"><a href="/File:103_College_SE-3.JPG" class="internal" title="Enlarge"><img src="/skins/common/images/magnify-clip.png" width="15" height="11" alt="" /></a></div>Photo from 2003-2004</div></div></div>
<div class="thumb tright"><div class="thumbinner" style="width:182px;"><a href="/File:103_College_SE-1.gif" class="image" title="Architectural Survey Cards, Histories, House Highlights"><img alt="" src="/images/thumb/2/22/103_College_SE-1.gif/180px-103_College_SE-1.gif" width="180" height="235" border="0" class="thumbimage" /></a>  <div class="thumbcaption"><div class="magnify"><a href="/File:103_College_SE-1.gif" class="internal" title="Enlarge"><img src="/skins/common/images/magnify-clip.png" width="15" height="11" alt="" /></a></div>Architectural Survey Cards, Histories, House Highlights</div></div></div>
<p><br style="clear:left" /><br /> <strong class="selflink">103 College Avenue SE</strong> is located in <a href="/Heritage_Hill" title="Heritage Hill">Heritage Hill</a>. It was built in
<a href="/index.php?title=1895&amp;action=edit&amp;redlink=1" class="new" title="1895 (page does not exist)">1895</a>.   It's architectural significance is
<a href="/Architectural_Significance" title="Architectural Significance">EXCELLENT</a>.
Past owners include
<a href="/index.php?title=Lowe,_Edward&amp;action=edit&amp;redlink=1" class="new" title="Lowe, Edward (page does not exist)">Lowe, Edward</a>.
</p>
<a name="Description" id="Description"></a><h3> <span class="mw-headline"> Description </span></h3>
<p>Lowe/Idema House - 1973  Tour, Walking Tour
</p>
<a name="Comments" id="Comments"></a><h3> <span class="mw-headline"> Comments </span></h3>
<p>Edward Lowe built this imposing Chateauesquehome in 1895. During the early 1890's Mr. &amp; Mrs. Lowe visited England on many occasions and it is believed the architecture combines many of the elements they found particularly attractive in the widows, a double hanging switchback staircase with a third floor gallery and 104 leaded beveled glass windows.  This house was the birthplace of Kent Country Club, the first gold club in Michigan. On February 1, 1896, Mr. Lowe who had become interested in the game of men at dinner party at which the club wasorganized.  In 1906 Henry Idema purchased the home and lived in it until 1951. A prominent member of the financial community, Mr. Idema became Vice President of the Kent Savings Company, now  the Old Kent Bank, in 1892. In 1929 he became Chairman of the Board of the Company, a position he held until 1949.(Henry Idema in1906, OKB; 1912 Chester, Edw. H. &amp; Walter D. boarders)
</p><p>Geographic coordinates are <span class="smwttinline">42.961393°N, 85.657278°W<span class="smwttcontent">Latitude: 42°57′41.015″N<br />Longitude: 85°39′26.201″W</span></span>.
</p>
<a name="External_Links" id="External_Links"></a><h3> <span class="mw-headline"> External Links </span></h3>
<p><a href="http://www.heritagehillweb.org/Search/building.asp?id=86" class="external text" title="http://www.heritagehillweb.org/Search/building.asp?id=86" rel="nofollow">Original data from Heritage Hill Associaton</a>
</p>
<!-- 
NewPP limit report
Preprocessor node count: 99/1000000
Post-expand include size: 3197/2097152 bytes
Template argument size: 2268/2097152 bytes
Expensive parser function count: 0/100
#ifexist count: 0/100
-->

<!-- Saved in parser cache with key wikidb:pcache:idhash:1312-0!1!0!!en!2!edit=0 and timestamp 20120830174349 -->
<div class="printfooter">
Retrieved from "<a href="http://viget.org/103_College_Avenue_SE">http://viget.org/103_College_Avenue_SE</a>"</div>
    

            <script type="text/javascript">
                var toc = document.getElementById('toc');
                var sidebar = document.getElementById('sidebar');
                var catlinks = document.getElementById('catlinks');
                if(toc && sidebar && catlinks){
                    toc.parentNode.removeChild(toc);
                    catlinks.parentNode.insertBefore(toc, catlinks)
                   }
            </script>
            <div class="clear"></div>

        </div> <!-- content close -->

<div id="footer">
<div id="footer_box">
<ul class="footer">
<li><h3 style="color:#60751c">All about <strong>you</strong>!</h3></li>
<li>Pages that effect you and the experience you have with Viget (aka the preferences)</li>
<li>&nbsp;</li>    
            <li id="userPages-login"><a class="topbar" href="/index.php?title=Special:UserLogin&amp;returnto=103_College_Avenue_SE">Log in / create account</a></li>
    </ul>

<ul class="footer">
<li><h3 style="color:#60751c;">Stuff about <strong>this page</strong></h3></li>
<li>The pages behind the page! You can learn about this page (and do a few things while you are at it) with the links below</li> 
<li>&nbsp;</li>
            <li id="articleInfo-whatlinkshere"><a class="topbar" href="/Special:WhatLinksHere/103_College_Avenue_SE">What links here</a></li>
            <li id="articleInfo-recentchangeslinked"><a class="topbar" href="/Special:RecentChangesLinked/103_College_Avenue_SE">Related changes</a></li>
            <li id="articleInfo-upload"><a class="topbar" href="">Upload file</a></li>
            <li id="articleInfo-specialpages"><a class="topbar" href="/Special:SpecialPages">Special pages</a></li>
    </ul>

<ul class="footer">
<li><h3 style="color:#60751c;"><strong>Viget</strong> MADNESS!?</h3></li>
<li>Some stuff you may find useful when using Viget</li>
<li>&nbsp;</li>
<li><a href="http://viget.org/Viget" class="topbar">About Viget</a></li>
<li><a href="http://viget.org/Help:Contents" class="topbar">Help Using Viget</a></li>
<li><a href="http://viget.org/Special:Recentchanges" class="topbar">Recent Changes</a></li>
<li><a href="http://viget.org/Special:Wantedpages" class="topbar">Wanted Pages</a></li>
<li><a href="http://viget.org/Special:Allpages" class="topbar">All Pages</a></li>
<li><a href="http://viget.org/Special:Categories" class="topbar">Categories</a></li>
<li><a href="http://viget.org/Special:Imagelist" class="topbar">Uploaded Images</a></li>
<li><a href="http://viget.org/Special:AddPage/Building" class="topbar">Add a Building</a></li>
<li><a href="http://viget.org/Viget:Copyrights" class="topbar">Copyrights</a></li>
</ul>

<ul class="footer" style="width:200px">
<li><h3 style="color:#60751c;"><strong>Find what you are looking for</strong></h3></li>
<li><form id="searchForm" class="searchForm" name="searchForm" action="/Special:Search">
                <input input id="searchInput" class="searchInput" name="search" type="text" accesskey="f" value="" type="text" style="height:16px;width:180px;border:1px solid #c0d381;font-family:arial;font-size:10pt;padding-left:4px;font-weigh:bold;">&nbsp;<input id="searchGoButton" class="searchButton" type='image' src="/skins/gwiki/gfx/search.gif" name="go" value="Go" style="margin-top:6px;" />
            </form>
            </li>
            <li><h3 style="color:#60751c;"><strong>Can't find it? Add it!</strong></h3></li>
            <li>Type in the name of the article you would like to add and go at it!</li>
            <li>&nbsp;</li>
            <li><form name="createbox" action="/index.php" method="get" class="createbox">
    <input type='hidden' name="action" value="edit" />
    <input type="hidden" name="preload" value="" />
    <input type="hidden" name="editintro" value="" />
    <input class="createboxInput" name="title" type="text"
    value="" style="height:16px;width:180px;border:1px solid #c0d381;font-family:arial;font-size:10pt;padding-left:4px;font-weigh:bold;" />&nbsp;<input type='image' name="create" class="createboxButton"
    value="Create page" src="/skins/gwiki/gfx/add.gif" style="margin-top:6px;" />
</form><br />
            </li>
            </ul>
            
            
<!-- <ul class="nav-bottom">
            <li id="articleActions=nstab-main"><a href="selected"<a href="/103_College_Avenue_SE">Page</a></li>
            <li id="articleActions=talk"><a href="new"<a href="/index.php?title=Talk:103_College_Avenue_SE&amp;action=edit&amp;redlink=1">Discussion</a></li>
            <li id="articleActions=form_edit"><a href=""<a href="/index.php?title=103_College_Avenue_SE&amp;action=formedit">View form</a></li>
            <li id="articleActions=viewsource"><a href=""<a href="/index.php?title=103_College_Avenue_SE&amp;action=edit">View source</a></li>
            <li id="articleActions=history"><a href=""<a href="/index.php?title=103_College_Avenue_SE&amp;action=history">History</a></li>
    </ul> -->

<!-- <div class="searchForm">
    <form id="searchForm" class="searchForm" name="searchForm" action="/Special:Search">
        <input id="searchInput" class="searchInput" name="search" type="text" accesskey="f" value="" />&nbsp;<input id="searchGoButton" class="searchButton" type='submit' name="go" value="Go" />&nbsp;<input id="searchButton" class="searchButton" type='submit' name="fulltext" value="Search" />
    </form>
</div> -->

<div class="clear"></div>
</div>
 
<!-- <div class="poweredby">
            <span id="footer-poweredbyico"><a href="http://www.mediawiki.org/"><img src="/skins/common/images/poweredby_mediawiki_88x31.png" alt="Powered by MediaWiki" /></a></span>
    </div> -->
</div>
<div class="clear_footer"></div>
</div> <!-- container close -->
<!-- END CUSTOMIZED STUFF -->

    <!-- Served in 0.820 secs. --><script src="http://www.google-analytics.com/urchin.js" type="text/javascript">
</script>
<script type="text/javascript">
_uacct = "UA-1316290-2";
urchinTracker();
</script>
  </body>
</html>"""

    
    coord = find_non_googlemaps_coordinates(html1, 'page1')
    if coord:
        mapdata_objects_to_create.append(coord)
        
    coord = find_non_googlemaps_coordinates(html2, 'page2')
    if coord:
        mapdata_objects_to_create.append(coord)
    
    print mapdata_objects_to_create
    