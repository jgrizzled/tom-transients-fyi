#!/usr/bin/env python
# django_shell.py

from boot_django import boot_django
from django.core.management import call_command

boot_django()
call_command("shell_plus")
