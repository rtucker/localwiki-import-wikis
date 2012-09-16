from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Imports pages from an existing MediaWiki site.  '
            'Clears out any existing data.')

    def handle(self, *args, **options):
        from importers import mediawiki
        mediawiki.run()
