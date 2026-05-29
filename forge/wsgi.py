import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "forge.settings")

application = get_wsgi_application()

# On Vercel the filesystem is read-only except /tmp.
# Run migrations on cold-start so /tmp/forge.db is initialised before any request.
if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
    try:
        from django.core.management import call_command
        call_command("migrate", "--run-syncdb", verbosity=0)
    except Exception:
        pass  # already migrated or using Postgres — not fatal
