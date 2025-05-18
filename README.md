# HA iDRAC Controller Add-on

This Home Assistant add-on allows you to control Dell iDRAC fan speeds based on CPU temperature and monitor server health.

## Features

* Fan control based on CPU temperature.
* Web UI for configuration via Ingress.
* MQTT publishing for Home Assistant integration.
* (Planned) Disk health monitoring.

## Configuration

Configure the add-on via the Home Assistant UI after installation. You'll need your iDRAC IP address, username, and password.
Further settings like the fan curve can be configured in the add-on's web panel.