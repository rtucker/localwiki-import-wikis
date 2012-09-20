from setuptools import setup, find_packages
setup(
    name = "localwiki-import-wikis",
    version = "0.3",
    author='Philip Neustrom',
    author_email='philipn@gmail.com',
    url='http://github.com/philipn/localwiki-import-wikis',
    packages = find_packages(),
    install_requires=[
        'mediawikitools==1.2.0',
        'progress==1.0.2',
    ],
    dependency_links=[
        'https://github.com/mivanov/python-mediawikitools/tarball/master#egg=mediawikitools-1.2.0',
    ],
)
