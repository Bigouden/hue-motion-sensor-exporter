#!/usr/bin/env python3
# coding: utf-8
# pyright: reportMissingImports=false, reportUnboundVariable=false

"""Hue Motion Sensor Exporter"""

import logging
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Callable
from wsgiref.simple_server import make_server

import pytz
import requests
from prometheus_client import PLATFORM_COLLECTOR, PROCESS_COLLECTOR
from prometheus_client.core import REGISTRY, CollectorRegistry, Metric
from prometheus_client.exposition import _bake_output, parse_qs

HUE_DISCOVERY_URL = "https://discovery.meethue.com"
HUE_APP_NAME = "Hue Motion Sensors Prometheus Exporter"
HUE_USERNAME = os.environ.get("HUE_USERNAME")
HUE_MOTION_SENSOR_EXPORTER_NAME = os.environ.get(
    "HUE_MOTION_SENSOR_EXPORTER_NAME", "hue-motion-sensor-exporter"
)
HUE_MOTION_SENSOR_EXPORTER_LOGLEVEL = os.environ.get(
    "HUE_MOTION_SENSOR_LOGLEVEL", "INFO"
).upper()
HUE_MOTION_SENSOR_EXPORTER_TLS_VERIFY = os.environ.get(
    "HUE_MOTION_SENSOR_EXPORTER_TLS_VERIFY", False
)
HUE_MOTION_SENSOR_EXPORTER_TZ = os.environ.get("TZ", "Europe/Paris")


def make_wsgi_app(
    registry: CollectorRegistry = REGISTRY, disable_compression: bool = False
) -> Callable:
    """Create a WSGI app which serves the metrics from a registry."""

    def prometheus_app(environ, start_response):
        # Prepare parameters
        accept_header = environ.get("HTTP_ACCEPT")
        accept_encoding_header = environ.get("HTTP_ACCEPT_ENCODING")
        params = parse_qs(environ.get("QUERY_STRING", ""))
        headers = [
            ("Server", ""),
            ("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0"),
            ("Pragma", "no-cache"),
            ("Expires", "0"),
            ("X-Content-Type-Options", "nosniff"),
        ]
        if environ["PATH_INFO"] == "/":
            status = "301 Moved Permanently"
            headers.append(("Location", "/metrics"))
            output = b""
        elif environ["PATH_INFO"] == "/favicon.ico":
            status = "200 OK"
            output = b""
        elif environ["PATH_INFO"] == "/metrics":
            status, tmp_headers, output = _bake_output(
                registry,
                accept_header,
                accept_encoding_header,
                params,
                disable_compression,
            )
            headers += tmp_headers
        else:
            status = "404 Not Found"
            output = b""
        start_response(status, headers)
        return [output]

    return prometheus_app


def start_wsgi_server(
    port: int,
    addr: str = "0.0.0.0",  # nosec B104
    registry: CollectorRegistry = REGISTRY,
) -> None:
    """Starts a WSGI server for prometheus metrics as a daemon thread."""
    app = make_wsgi_app(registry)
    httpd = make_server(addr, port, app)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()


start_http_server = start_wsgi_server

# Logging Configuration
try:
    pytz.timezone(HUE_MOTION_SENSOR_EXPORTER_TZ)
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=pytz.timezone(HUE_MOTION_SENSOR_EXPORTER_TZ)
    ).timetuple()
    logging.basicConfig(
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
        level=HUE_MOTION_SENSOR_EXPORTER_LOGLEVEL,
    )
except pytz.exceptions.UnknownTimeZoneError:
    logging.Formatter.converter = lambda *args: datetime.now(
        tz=pytz.timezone("Europe/Paris")
    ).timetuple()
    logging.basicConfig(
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
        level="INFO",
    )
    logging.error("TZ invalid : %s !", HUE_MOTION_SENSOR_EXPORTER_TZ)
    os._exit(1)
except ValueError:
    logging.basicConfig(
        stream=sys.stdout,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
        level="INFO",
    )
    logging.error("DOCKERHUB_LIMIT_EXPORTER_LOGLEVEL invalid !")
    os._exit(1)

# Exporter Configuration
try:
    HUE_MOTION_SENSOR_EXPORTER_PORT = int(
        os.environ.get("HUE_MOTION_SENSOR_EXPORTER_PORT", "8123")
    )
except ValueError:
    logging.error("HUE_MOTION_SENSOR_EXPORTER_PORT must be int !")
    os._exit(1)

HUE_MOTION_SENSORS = [
    {"uniqueid": "00:17:88:01:04:b6:e5:df-02-04", "room": "Salon"},
    {"uniqueid": "00:17:88:01:06:f4:a5:9b-02", "room": "Véranda"},
]

METRICS = [
    {"name": "battery", "description": "Batterie restante en %", "type": "gauge"},
    {"name": "lightlevel", "description": "Luminosité en lx", "type": "gauge"},
    {"name": "presence", "description": "Présence (1: OUI, 0: NON)", "type": "gauge"},
    {"name": "state", "description": "Etat (1: ON, 0: OFF)", "type": "gauge"},
    {"name": "temperature", "description": "Température en °C", "type": "gauge"},
]

# REGISTRY Configuration
REGISTRY.unregister(PROCESS_COLLECTOR)
REGISTRY.unregister(PLATFORM_COLLECTOR)
REGISTRY.unregister(REGISTRY._names_to_collectors["python_gc_objects_collected_total"])


class HueMotionSensorCollector:
    """Hue Motion Sensor Collector Class"""

    def __init__(self):
        self.session = requests.session()
        self.session.verify = HUE_MOTION_SENSOR_EXPORTER_TLS_VERIFY
        self.host, self.port = self.discover()
        if self.port == 443:
            method = "https"
        else:
            method = "http"
        self.api_endpoint = f"{method}://{self.host}/api"
        if not HUE_USERNAME:
            username = self.register()
            logging.info(
                "Please set 'HUE_USERNAME=%s' environment variable. Exiting.", username
            )
            os._exit(0)

    def discover(self):
        """Discover Hue Bridge"""
        response = self.session.get(HUE_DISCOVERY_URL)
        host = response.json()[0]["internalipaddress"]
        port = response.json()[0]["port"]
        return host, port

    def register(self):
        """Register Exporter On Hue Bridge"""
        data = {"devicetype": f"{HUE_APP_NAME}"}
        response = self.session.post(url=self.api_endpoint, json=data)
        while (
            "error" in response.json()[0]
            and response.json()[0]["error"]["description"] == "link button not pressed"
        ):
            logging.info("Please press link button to allow application.")
            time.sleep(5)
            response = self.session.post(url=self.api_endpoint, json=data)

        if "success" in response.json()[0]:
            success = response.json()[0]["success"]
            self.username = success["username"]
            logging.info("Username: %s", self.username)
            return self.username

        return False

    def sensors(self):
        """Get Sensors"""
        url = f"{self.api_endpoint}/{HUE_USERNAME}/sensors"
        response = self.session.get(url=url)
        return response.json()

    def collect(self):
        """Collect Prometheus Metrics"""
        sensors = self._parse_sensors(self.sensors())
        logging.info("Sensors : %s.", dict(sensors))
        labels = {"job": HUE_MOTION_SENSOR_EXPORTER_NAME}
        metrics = []
        for room, data in sensors.items():
            for key, value in data.items():
                if value is not None:
                    description = [
                        i["description"] for i in METRICS if key == i["name"]
                    ][0]
                    metric_type = [i["type"] for i in METRICS if key == i["name"]][0]
                    metrics.append(
                        {
                            "name": f"hue_motion_sensor_{key.lower()}",
                            "value": int(value),
                            "description": description,
                            "type": metric_type,
                            "room": room,
                        }
                    )

        for metric in metrics:
            labels["room"] = metric["room"]
            prometheus_metric = Metric(
                metric["name"], metric["description"], metric["type"]
            )
            prometheus_metric.add_sample(
                metric["name"], value=metric["value"], labels=labels
            )
            yield prometheus_metric

    @staticmethod
    def _parse_sensors(sensors):
        """Parse Sensors"""
        res = defaultdict(dict)
        unknown_sensors = set()
        for key, value in sensors.items():
            if value["type"] in ["ZLLTemperature", "ZLLPresence", "ZLLLightLevel"]:
                try:
                    room = [
                        i["room"]
                        for i in HUE_MOTION_SENSORS
                        if i["uniqueid"] in value["uniqueid"]
                    ][0]
                except IndexError:
                    unknown_sensors.add(value["uniqueid"][:-5])

                if value["type"] == "ZLLTemperature":
                    temperature = value["state"]["temperature"]
                    res[room]["temperature"] = temperature
                if value["type"] == "ZLLPresence":
                    if value["state"]["presence"]:
                        presence = 1
                    else:
                        presence = 0
                    res[room]["presence"] = presence
                if value["type"] == "ZLLLightLevel":
                    lightlevel = value["state"]["lightlevel"]
                    res[room]["lightlevel"] = lightlevel
                battery = value["config"]["battery"]
                res[room]["battery"] = battery
                if value["config"]["on"]:
                    state = 1
                else:
                    state = 0
                res[room]["state"] = state

        for unknown_sensor in unknown_sensors:
            logging.info("Unknown Sensor : %s (uniqueid)", unknown_sensor)
            logging.info("Please reference it in HUE_MOTION_SENSORS variable.")
            logging.info(
                "Syntax: {'uniqueid': '%s', 'room': 'Room Name'}", unknown_sensor
            )
        return res


def main():
    """Main Function"""
    logging.info(
        "Starting Hue Motion Sensor Exporter on port %s.",
        HUE_MOTION_SENSOR_EXPORTER_PORT,
    )
    logging.debug(
        "HUE_MOTION_SENSOR_EXPORTER_PORT: %s.", HUE_MOTION_SENSOR_EXPORTER_PORT
    )
    logging.debug(
        "HUE_MOTION_SENSOR_EXPORTER_NAME: %s.", HUE_MOTION_SENSOR_EXPORTER_NAME
    )
    # Start Prometheus HTTP Server
    start_http_server(HUE_MOTION_SENSOR_EXPORTER_PORT)
    # Init HueMotionSensorCollector
    REGISTRY.register(HueMotionSensorCollector())
    # Infinite Loop
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
