FROM edoburu/pgbouncer:latest

COPY pgbouncer.ini.template /etc/pgbouncer/pgbouncer.ini.template
COPY docker-entrypoint.sh /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
