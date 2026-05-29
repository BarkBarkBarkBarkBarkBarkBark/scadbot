#!/usr/bin/env python
"""Entry point. `python manage.py runserver` etc."""
import os
import sys


def run() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "forge.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    run()
