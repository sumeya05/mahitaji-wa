"""
Gunicorn settings for a 2 vCPU / 4 GB server. Started by deploy/systemd/mahitaji.service.

gthread workers: while one thread waits on Safaricom, the mail server or the assistant's
model, the other threads keep serving pages. 2 workers x 4 threads is plenty for a
mid-sized shop and uses ~400 MB; raise threads before workers if you add RAM.
"""
import multiprocessing

bind = 'unix:/run/mahitaji/gunicorn.sock'
workers = min(2, multiprocessing.cpu_count())
threads = 4
worker_class = 'gthread'
timeout = 30               # a request stuck longer than this is killed (M-Pesa/SMTP calls have their own shorter timeouts)
graceful_timeout = 20
keepalive = 5
max_requests = 1000        # recycle workers now and then so a slow leak never grows
max_requests_jitter = 100
accesslog = '-'            # to the journal (journalctl -u mahitaji)
errorlog = '-'
loglevel = 'info'
# Nginx terminates TLS and sets X-Forwarded-Proto; trust it only from the local socket.
forwarded_allow_ips = '127.0.0.1'
proxy_allow_ips = '127.0.0.1'
