"""Constantes para la integración Omada IP Groups."""

DOMAIN = "omada_ipgroups"

CONF_SITE_NAME = "site_name"
CONF_VERIFY_SSL = "verify_ssl"

DEFAULT_PORT = 443
DEFAULT_SITE_NAME = "Default"
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 120  # segundos

# Tipo de grupo en la API de Omada. Solo IP (0) está soportado por ahora.
GROUP_TYPE_IP = 0

ATTR_GROUP_ID = "group_id"
ATTR_NAME = "name"
ATTR_IPS = "ips"
ATTR_IP = "ip"
ATTR_MASK = "mask"
ATTR_DESCRIPTION = "description"

SERVICE_CREATE_GROUP = "create_group"
SERVICE_DELETE_GROUP = "delete_group"
SERVICE_ADD_IP = "add_ip"
SERVICE_REMOVE_IP = "remove_ip"
SERVICE_UPDATE_GROUP = "update_group"
