FROM alpine:3.16
LABEL maintainer="Thomas GUIRRIEC <thomas@guirriec.fr>"
ENV HUE_MOTION_SENSOR_EXPORTER_PORT=8123
ENV HUE_MOTION_SENSOR_EXPORTER_LOGLEVEL='INFO'
ENV HUE_MOTION_SENSOR_EXPORTER_NAME='hue-motion-sensor-exporter'
ENV SCRIPT='hue_motion_sensor_exporter.py'
ENV USERNAME="exporter"
ENV UID="1000"
ENV GID="1000"
COPY apk_packages /
COPY pip_packages /
ENV VIRTUAL_ENV="/hue-motion-sensor-exporter"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN xargs -a /apk_packages apk add --no-cache --update \
    && python3 -m venv ${VIRTUAL_ENV} \
    && pip install --no-cache-dir --no-dependencies --no-binary :all: -r pip_packages \
    && pip uninstall -y setuptools pip \
    && useradd -l -u "${UID}" -U -s /bin/sh -m "${USERNAME}" \
    && rm -rf \
        /root/.cache \
        /tmp/* \
        /var/cache/*
COPY --chown=${USERNAME}:${USERNAME} --chmod=500 ${SCRIPT} ${VIRTUAL_ENV}
COPY --chown=${USERNAME}:${USERNAME} --chmod=500 entrypoint.sh /
USER ${USERNAME}
WORKDIR ${VIRTUAL_ENV}
EXPOSE ${HUE_MOTION_SENSOR_EXPORTER_PORT}
HEALTHCHECK CMD nc -vz localhost ${HUE_MOTION_SENSOR_EXPORTER_PORT} || exit 1
ENTRYPOINT ["/entrypoint.sh"]
