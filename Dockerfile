FROM alpine:3.14
LABEL maintainer="Thomas GUIRRIEC <thomas@guirriec.fr>"
ENV HUE_MOTION_SENSOR_EXPORTER_PORT=8123
ENV HUE_MOTION_SENSOR_EXPORTER_LOGLEVEL='INFO'
ENV HUE_MOTION_SENSOR_EXPORTER_NAME='hue-motion-sensor-exporter'
COPY requirements.txt /
COPY entrypoint.sh /
ENV VIRTUAL_ENV="/hue-motion-sensor-exporter"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN apk add --no-cache --update \
         python3 \
    && python3 -m venv ${VIRTUAL_ENV} \
    && pip install --no-cache-dir --no-dependencies --no-binary :all: -r requirements.txt \
    && pip uninstall -y setuptools pip \
    && rm -rf \
        /root/.cache \
        /tmp/* \
        /var/cache/* \
    && chmod +x /entrypoint.sh
COPY hue_motion_sensor_exporter.py ${VIRTUAL_ENV}
WORKDIR ${VIRTUAL_ENV}
HEALTHCHECK CMD nc -vz localhost ${HUE_MOTION_SENSOR_EXPORTER_PORT} || exit 1
ENTRYPOINT ["/entrypoint.sh"]
