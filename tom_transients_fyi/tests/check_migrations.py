#!/usr/bin/env python
# django_shell.py

from boot_django import APP_NAME, boot_django  # noqa
from django.core.management import call_command

boot_django()
print(f"checking migrations for {APP_NAME}")
call_command("makemigrations", APP_NAME, "--check")
