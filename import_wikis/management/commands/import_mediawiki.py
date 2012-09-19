from django.core.management.base import BaseCommand
from optparse import make_option


class Command(BaseCommand):
    help = ('Imports pages from an existing MediaWiki site.  '
            'Clears out any existing data.')
    option_list = BaseCommand.option_list + (
        make_option('--users_email_csv', '-u', dest='users_email_csv',
            help='A CSV containing username,email,<optional real name>'),
    )

    def handle(self, *args, **options):
        from import_wikis import mediawiki
        mediawiki.run(**options)
