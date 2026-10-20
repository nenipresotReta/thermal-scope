FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 BIND=0.0.0.0 PORT=8080 DATA_DIR=/data
WORKDIR /app
RUN groupadd --gid 10001 scope && useradd --uid 10001 --gid scope --no-create-home scope && mkdir /data && chown scope:scope /data
COPY server.py thermal_model.py calibration.py learning.py devices.py roast.py ./
COPY static ./static
USER scope
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/status',timeout=2).read()"
CMD ["python", "server.py"]
