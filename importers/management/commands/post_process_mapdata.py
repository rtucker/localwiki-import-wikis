from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = ('Finds coordinates in imported pages and turns them into mapdata.')

    def handle(self, *args, **options):
        from importers import mediawiki
        mediawiki.post_process_mapdata()