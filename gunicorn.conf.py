bind = "unix:/var/www/bookmark/bookmark.sock"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
chdir = "/var/www/bookmark"
accesslog = "-"
errorlog = "-"
