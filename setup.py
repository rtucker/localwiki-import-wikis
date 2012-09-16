from setuptools import setup, find_packages
setup(
    name = "localwiki-importers",
    version = "0.2",
    author='Philip Neustrom',
    author_email='philipn@gmail.com',
    url='http://github.com/philipn/localwiki-importers',
    packages = find_packages(),
    install_requires=[
        'mediawikitools==1.2.0',
    ],
    dependency_links=[
        'https://github.com/mivanov/python-mediawikitools/tarball/master#egg=mediawikitools-1.2.0',
    ],
)
