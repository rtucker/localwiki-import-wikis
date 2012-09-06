#!/usr/bin/env python
# -*- coding: utf-8 -*-

import codecs
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
    with codecs.open(pagename+".txt", "w", "utf-8-sig") as f:
        f.write(html)
    pattern = r'Geographic coordinates are <span class="smwttinline">([1-9]\d*(\.\d+)?).[ ]?N, ([1-9]\d*(\.\d+)?).[ ]?W<span class="smwttcontent">'
    match = re.search(pattern, html)
    if match:
        lat = match.group(1)
        lon = '-'+match.group(3)
        return {'pagename': pagename, 'lat': lat, 'lon': lon}


if __name__ == '__main__':
    mapdata_objects_to_create = []

    def add_test_page(html_file, page_name):
        with codecs.open(html_file, "r", "utf-8-sig") as f:
            html = f.read()
            print html
            
        coord = find_non_googlemaps_coordinates(html, page_name)
        if coord:
            mapdata_objects_to_create.append(coord)
    
    add_test_page("example_files/101-south-division.html", "101-south-divison")
    add_test_page("example_files/103-college-avenue-se.html", "103-college-ave-se")
    
    print mapdata_objects_to_create
    