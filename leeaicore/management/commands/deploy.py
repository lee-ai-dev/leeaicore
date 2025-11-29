import subprocess
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Deploy current branch: git pull, migrate, collectstatic, restart lee service"

    def handle(self, *args, **options):
        steps = [
            ["git", "pull", "origin", "main"],
            ["python", "manage.py", "makemigrations"],
            ["python", "manage.py", "migrate"],
            ["python", "manage.py", "collectstatic", "--noinput"],
            ["sudo", "systemctl", "daemon-reload"],
            ["sudo", "systemctl", "enable", "--now", "lee"],
            ["sudo", "systemctl", "restart", "lee"],
        ]

        for cmd in steps:
            self.stdout.write(self.style.WARNING(f"Running: {' '.join(cmd)}"))
            try:
                subprocess.check_call(cmd)
            except subprocess.CalledProcessError as exc:
                raise CommandError(f"Command failed: {' '.join(cmd)} (exit code {exc.returncode})")

        self.stdout.write(self.style.SUCCESS("Deployment completed successfully."))
