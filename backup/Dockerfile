# The backup service (see backup.py and the README, "Automatic backups").
# Same Postgres major version as the db service, so pg_dump matches the server.
FROM postgres:16-alpine
RUN apk add --no-cache python3 rsync tzdata
COPY backup.py /backup.py
CMD ["python3", "-u", "/backup.py"]
