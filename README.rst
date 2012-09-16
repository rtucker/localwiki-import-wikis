These are scripts to import legacy wiki engines (MediaWiki, Sycamore / WikiSpot.org) into LocalWiki.

Very rough right now. Please tell us about your experiences on #localwiki on Freenode.

Usage
-----

To import pages from an existing MediaWiki site into LocalWiki, do the following:

1. Activate the virtualenv used for LocalWiki (typical path shown)::

   $ source /usr/share/localwiki/env/bin/activate

2. Install the localwiki-importers package::

   (env)$ pip install localwiki-importers

3. Add 'localwiki_importers' to LOCAL_INSTALLED_APPS in /usr/share/localwiki/conf/localsettings.py::

   LOCAL_INSTALLED_APPS = ('localwiki_importers',)

4. Now you can run the import command like this::

   $ localwiki-manage import_mediawiki

Follow the prompts to complete the import!

------------

Copyright (c) 2012 Philip Neustrom <philipn@gmail.com>
Copyright (c) 2012 Mike Ivanov <mivanov@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
