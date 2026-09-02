import os

bind = "unix:/var/www/bookmark/bookmark.sock"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
chdir = "/var/www/bookmark"
accesslog = "app/logs/access.log"
errorlog = "app/logs/app.log"
# The app logs via logging.basicConfig -> stderr; without this, those lines
# (incl. the per-call "LLM ..." timing) land in journald instead of app.log.
capture_output = True
access_log_format = '%(t)s %(h)s "%(r)s" %(s)s %(b)s %(L)ss'
loglevel = os.environ.get("LOG_LEVEL", "info")
