from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Finds coordinates in imported pages and turns them into mapdata.')

    def handle(self, *args, **options):
        from import_wikis import mediawiki
        mediawiki.find_more_mapdata()
