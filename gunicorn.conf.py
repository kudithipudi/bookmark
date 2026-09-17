import os

# Cap BLAS/OpenMP thread pools before numpy/onnxruntime get imported in the
# worker process. Each worker embeds one query/bookmark at a time (personal-
# library scale, brute-force cosine over a few hundred rows) — there is no
# parallelism to gain, only idle threads and context-switch overhead on this
# box's 2 shared vCPUs. Set here (master, pre-fork) so workers inherit it.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

bind = "unix:/var/www/bookmark/bookmark.sock"
# gunicorn>=26 enables a control socket by default, which tries to create a
# file under a path blocked by this unit's ProtectSystem=strict sandboxing
# ("Read-only file system" on restart). Disable it; we don't use it.
control_socket_disable = True
# One worker: this is a self-hosted, single-user app (see README). A second
# worker only duplicates the ONNX embedding model + in-memory vector cache
# (~150-200MB each) for no real concurrency benefit at this traffic level.
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
chdir = "/var/www/bookmark"
accesslog = "app/logs/access.log"
errorlog = "app/logs/app.log"
# The app logs via logging.basicConfig -> stderr; without this, those lines
# (incl. the per-call "LLM ..." timing) land in journald instead of app.log.
capture_output = True
access_log_format = '%(t)s %(h)s "%(r)s" %(s)s %(b)s %(L)ss'
loglevel = os.environ.get("LOG_LEVEL", "info")
