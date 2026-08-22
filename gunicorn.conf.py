import os

bind = "unix:/var/www/bookmark/bookmark.sock"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
chdir = "/var/www/bookmark"
accesslog = "app/logs/access.log"
errorlog = "app/logs/app.log"
access_log_format = '%(t)s %(h)s "%(r)s" %(s)s %(b)s %(L)ss'
loglevel = os.environ.get("LOG_LEVEL", "info")
