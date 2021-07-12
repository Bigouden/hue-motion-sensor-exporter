#!/usr/bin/env python3
#coding: utf-8

'''Hue Motion Sensor Exporter'''

import logging
import os
import sys
import time
from collections import defaultdict
import requests
from prometheus_client.core import REGISTRY, Metric
from prometheus_client import start_http_server, PROCESS_COLLECTOR, PLATFORM_COLLECTOR

HUE_DISCOVERY_URL =  "https://discovery.meethue.com"
HUE_APP_NAME = "Hue Motion Sensors Prometheus Exporter"
HUE_USERNAME = os.environ.get('HUE_USERNAME')
HUE_MOTION_SENSOR_EXPORTER_NAME = os.environ.get('HUE_MOTION_SENSOR_EXPORTER_NAME',
                                                 'hue-motion-sensor-exporter')
HUE_MOTION_SENSOR_EXPORTER_LOGLEVEL = os.environ.get('HUE_MOTION_SENSOR_LOGLEVEL',
                                                      'INFO').upper()

# Logging Configuration
try:
    logging.basicConfig(stream=sys.stdout,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        datefmt='%d/%m/%Y %H:%M:%S',
                        level=HUE_MOTION_SENSOR_EXPORTER_LOGLEVEL)
except ValueError:
    logging.basicConfig(stream=sys.stdout,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        datefmt='%d/%m/%Y %H:%M:%S',
                        level='INFO')
    logging.error("DOCKERHUB_LIMIT_EXPORTER_LOGLEVEL invalid !")
    sys.exit(1)

# Exporter Configuration
try:
    HUE_MOTION_SENSOR_EXPORTER_PORT = int(os.environ.get('HUE_MOTION_SENSOR_EXPORTER_PORT', '8123'))
except ValueError:
    logging.error("HUE_MOTION_SENSOR_EXPORTER_PORT must be int !")
    sys.exit(1)

HUE_MOTION_SENSORS = [
    {'uniqueid': '00:17:88:01:04:b6:e5:df-02-04', 'room': 'Salon'}
]

METRICS = [
        {'name': 'battery', 'description': 'Batterie restante en %', 'type': 'gauge'},
        {'name': 'lightlevel', 'description': 'Luminosité en lx', 'type': 'gauge'},
        {'name': 'presence', 'description': 'Présence (1: OUI, 0: NON)', 'type': 'gauge'},
        {'name': 'state', 'description': 'Etat (1: ON, 0: OFF)', 'type': 'gauge'},
        {'name': 'temperature', 'description': 'Température en °C', 'type': 'gauge'}
]

# REGISTRY Configuration
REGISTRY.unregister(PROCESS_COLLECTOR)
REGISTRY.unregister(PLATFORM_COLLECTOR)
REGISTRY.unregister(REGISTRY._names_to_collectors['python_gc_objects_collected_total'])

class HueMotionSensorCollector():
    '''Hue Motion Sensor Collector Class'''
    def __init__(self):
        self.session = requests.session()
        self.host = self.discover()
        self.api_endpoint = "http://%s/api" % self.host

        if not HUE_USERNAME:
            username = self.register()
            logging.info("Please set 'HUE_USERNAME=%s' environment variable. Exiting.", username)
            sys.exit(0)

    def discover(self):
        '''Discover Hue Bridge'''
        response = self.session.get(HUE_DISCOVERY_URL)
        return response.json()[0]['internalipaddress']

    def register(self):
        '''Register Exporter On Hue Bridge'''
        data = {'devicetype': '%s' % HUE_APP_NAME}
        response = self.session.post(url=self.api_endpoint, json=data)
        while ('error'in response.json()[0]
               and response.json()[0]['error']['description'] == 'link button not pressed'):
            logging.info("Please press link button to allow application.")
            time.sleep(5)
            response = self.session.post(url=self.api_endpoint, json=data)

        if 'success' in response.json()[0]:
            success = response.json()[0]['success']
            self.username = success['username']
            logging.info("Username: %s", self.username)
            return self.username

    def sensors(self):
        '''Get Sensors'''
        url = "%s/%s/sensors" % (self.api_endpoint, HUE_USERNAME)
        response = self.session.get(url=url)
        return response.json()

    def collect(self):
        '''Collect Prometheus Metrics'''
        sensors = self._parse_sensors(self.sensors())
        logging.info('Sensors : %s.', dict(sensors))
        labels = {'job': HUE_MOTION_SENSOR_EXPORTER_NAME}
        metrics = []
        for room, data in sensors.items():
            for key, value in data.items():
                if value is not None:
                    description = [i['description'] for i in METRICS if key == i['name']][0]
                    metric_type = [i['type'] for i in METRICS if key == i['name']][0]
                    metrics.append({'name': 'hue_motion_sensor_%s' % key.lower(),
                                    'value': int(value),
                                    'description': description,
                                    'type': metric_type,
                                    'room': room})

        for metric in metrics:
            labels['room'] = metric['room']
            prometheus_metric = Metric(metric['name'], metric['description'], metric['type'])
            prometheus_metric.add_sample(metric['name'], value=metric['value'], labels=labels)
            yield prometheus_metric

    @staticmethod
    def _parse_sensors(sensors):
        '''Parse Sensors'''
        res = defaultdict(dict)
        for key, value in sensors.items():
            if value['type'] in ['ZLLTemperature', 'ZLLPresence', 'ZLLLightLevel']:
                room = [
                        i['room'] for i in HUE_MOTION_SENSORS
                        if i['uniqueid'] in value['uniqueid']
                       ][0]
                if value['type'] == 'ZLLTemperature':
                    temperature = value['state']['temperature']
                    res[room]['temperature'] = temperature
                if value['type'] == 'ZLLPresence':
                    if value['state']['presence']:
                        presence = 1
                    else:
                        presence = 0
                    res[room]['presence'] = presence
                if value['type'] == 'ZLLLightLevel':
                    lightlevel = value['state']['lightlevel']
                    res[room]['lightlevel'] = lightlevel
                battery = value['config']['battery']
                res[room]['battery'] = battery
                if value['config']['on']:
                    state = 1
                else:
                    state = 0
                res[room]['state'] = state
        return res

def main():
    '''Main Function'''
    logging.info("Starting Hue Motion Sensor Exporter on port %s.", HUE_MOTION_SENSOR_EXPORTER_PORT)
    logging.debug("HUE_MOTION_SENSOR_EXPORTER_PORT: %s.", HUE_MOTION_SENSOR_EXPORTER_PORT)
    logging.debug("HUE_MOTION_SENSOR_EXPORTER_NAME: %s.", HUE_MOTION_SENSOR_EXPORTER_NAME)
    # Start Prometheus HTTP Server
    start_http_server(HUE_MOTION_SENSOR_EXPORTER_PORT)
    # Init HueMotionSensorCollector
    REGISTRY.register(HueMotionSensorCollector())
    # Loop Infinity
    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()
