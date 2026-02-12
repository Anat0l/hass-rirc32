"""Constants for the RIRC integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

# Integration domain
DOMAIN: Final = "rirc32"

# Base URL for the RIRC personal cabinet
BASE_URL: Final = "https://lk.rirc.ru"

# Endpoints
ENDPOINT_LOGIN: Final = "/actionUserAuth.do"
ENDPOINT_SUBMIT_READING: Final = "/actionPassSchVal.do"
ENDPOINT_PAYMENT_HISTORY: Final = "/actionPaymentHistory.do"
ENDPOINT_KVIT_LIST: Final = "/kvitList.do"
ENDPOINT_LS_LIST: Final = "/cabinet/ls-list/"
ENDPOINT_METERS: Final = "/cabinet/control-meter-list/{ls}/"

# Form field names
FIELD_LOGIN: Final = "u_log"
FIELD_PASSWORD: Final = "u_psw"
FIELD_METHOD: Final = "_method"
FIELD_LS: Final = "ls"
FIELD_SCH_SER: Final = "sch_ser"
FIELD_SCH: Final = "sch"
FIELD_SCH_VAL: Final = "sch_val"

# Config entry keys
CONF_LOGIN: Final = "login"
CONF_PASSWORD: Final = "password"

# Cookie names
COOKIE_SID: Final = "sid"
COOKIE_UL: Final = "ul"
COOKIE_UN: Final = "un"

# Data keys for coordinator
DATA_ACCOUNTS: Final = "accounts"
DATA_METERS: Final = "meters"
DATA_PAYMENTS: Final = "payments"
DATA_KVIT: Final = "kvit"

# Account data keys
ATTR_ACCOUNT_ID: Final = "account_id"
ATTR_ADDRESS: Final = "address"
ATTR_LS_TYPE: Final = "ls_type"

# Meter data keys
ATTR_METER_ID: Final = "meter_id"
ATTR_METER_SERIAL: Final = "meter_serial"
ATTR_METER_NAME: Final = "meter_name"
ATTR_METER_TARIFF: Final = "meter_tariff"
ATTR_LAST_READING: Final = "last_reading"

# Kvit (receipt) data keys
ATTR_KVIT_NAME: Final = "kvit_name"
ATTR_KVIT_PERIOD: Final = "kvit_period"
ATTR_KVIT_TO_PAY: Final = "kvit_to_pay"
ATTR_KVIT_PAID: Final = "kvit_paid"
ATTR_KVIT_DEBT: Final = "kvit_debt"

# Events
EVENT_REFRESH_COMPLETED: Final = f"{DOMAIN}_refresh_completed"
EVENT_REFRESH_FAILED: Final = f"{DOMAIN}_refresh_failed"
EVENT_SEND_READINGS_COMPLETED: Final = f"{DOMAIN}_send_readings_completed"
EVENT_SEND_READINGS_FAILED: Final = f"{DOMAIN}_send_readings_failed"

# Platforms
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR, Platform.BUTTON]
