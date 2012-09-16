from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Finds coordinates in imported pages and turns them into mapdata.')

    def handle(self, *args, **options):
        from importers import mediawiki
        mediawiki.post_process_mapdata()
