from setuptools import setup, find_packages
setup(
    name = "localwiki-importers",
    version = "0.1",
    author='Mike Ivanov',
    author_email='mivanov@gmail.com',
    url='http://localwiki.org',
    packages = find_packages(),
    install_requires=[
        'mediawikitools==1.2.0',
    ],
    dependency_links=[
        'https://github.com/mivanov/python-mediawikitools/tarball/master#egg=mediawikitools-1.2.0',
    ],
)