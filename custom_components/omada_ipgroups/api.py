"""Cliente para la Web API local (no-cloud) del controlador Omada.

Basado en peticiones capturadas directamente contra un OC220 (firmware 5.x)
mediante las DevTools del navegador. Usa el mismo flujo que el panel web:

    GET  /api/info                                     -> (opcional, "calentamiento" de sesión)
    POST /api/v2/login                                  -> token + omadacId + cookie de sesión
    GET  /{omadacId}/api/v2/sites                        -> resolver siteId por nombre
    GET  /{omadacId}/api/v2/sites/{siteId}/setting/profiles/groups
    POST /{omadacId}/api/v2/sites/{siteId}/setting/profiles/groups
    PATCH  .../setting/profiles/groups/{type}/{groupId}
    DELETE .../setting/profiles/groups/{type}/{groupId}

Notas importantes:
- El login (POST /api/v2/login) es el único endpoint que NO lleva el prefijo
  /{omadacId}/ - es global al controlador. La propia respuesta trae el
  omadacId a usar en el resto de peticiones.
- Requiere un GET previo (a /api/info) antes del login para que el
  controlador cree correctamente la sesión Java; sin él, el login devuelve
  500 Internal Server Error.
- El host suele ser una IP local, y aiohttp descarta por defecto las cookies
  de hosts-IP salvo que se use CookieJar(unsafe=True) - imprescindible aquí.
- El PATCH de edición reemplaza la lista de IPs COMPLETA, no es incremental.
  Por eso add_ip/remove_ip primero leen el grupo actual y reenvían la lista entera.
- Cada entrada de ipList lleva un "key" propio (epoch en ms observado en las
  capturas). Se genera uno nuevo al añadir una IP.
- El identificador de cada grupo viene en el campo "groupId" (no "id").
- El certificado del controlador es autofirmado -> SSL verify desactivado por
  defecto (configurable).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import GROUP_TYPE_IP

_LOGGER = logging.getLogger(__name__)

# Sin límite propio, aiohttp espera hasta 5 minutos: con el controlador
# colgado, cada sondeo y cada botón se quedaban bloqueados ese tiempo.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Lo que puede fallar al hablar con el controlador: red, tiempo agotado o una
# respuesta que no es JSON (p. ej. la página de error HTML de un 500).
_NETWORK_ERRORS = (aiohttp.ClientError, TimeoutError, ValueError)


class OmadaApiError(Exception):
    """Error genérico devuelto por la API de Omada."""


class OmadaAuthError(OmadaApiError):
    """Error de autenticación (usuario/contraseña o sesión expirada)."""


class OmadaConnectionError(OmadaApiError):
    """Error de red/conexión con el controlador."""


class OmadaLocalClient:
    """Cliente async para gestionar Grupos IP en un controlador Omada local."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        site_name: str,
        verify_ssl: bool = False,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._site_name = site_name
        self._verify_ssl = verify_ssl

        self._base_url = f"https://{host}:{port}"
        self._omadac_id: str | None = None
        self._site_id: str | None = None
        self._resolved_site_name: str | None = None
        self._token: str | None = None

        self._external_session = session is not None
        self._session = session
        self._terminal_uuid = str(uuid.uuid4())

    @property
    def site_name(self) -> str | None:
        """Nombre del site que se está usando de verdad (tras async_setup)."""
        return self._resolved_site_name

    def _new_session(self) -> aiohttp.ClientSession:
        connector = aiohttp.TCPConnector(ssl=self._verify_ssl)
        # OJO: aiohttp descarta por defecto las cookies cuando el host es
        # una IP en vez de un dominio ("unsafe" host). El controlador es
        # local (192.168.x.x) y su cookie de sesión es imprescindible
        # para el login, así que forzamos el jar en modo unsafe.
        cookie_jar = aiohttp.CookieJar(unsafe=True)
        return aiohttp.ClientSession(
            connector=connector, cookie_jar=cookie_jar, timeout=REQUEST_TIMEOUT
        )

    async def async_setup(self) -> None:
        """Inicializa sesión HTTP, hace login y resuelve el site id."""
        if self._session is None:
            self._session = self._new_session()
        # Un GET previo (como hace el navegador al cargar la página antes de
        # loguearse) parece necesario para que el controlador cree la sesión
        # Java correctamente - sin esto el login devuelve 500.
        await self._async_warm_up_session()
        await self._async_login()
        await self._async_resolve_site_id()

    async def _async_warm_up_session(self) -> None:
        try:
            async with self._session.get(f"{self._base_url}/api/info", ssl=self._verify_ssl) as resp:
                await resp.read()
        except _NETWORK_ERRORS as err:
            raise OmadaConnectionError(f"No se pudo conectar a {self._base_url}: {err}") from err

    async def async_close(self) -> None:
        """Cierra la sesión HTTP si la creó este cliente."""
        if self._session is not None and not self._external_session:
            await self._session.close()

    async def _async_reconnect(self) -> None:
        """Reconecta desde cero: nueva sesión + login + resolución de site.

        Se usa para recuperarse solo de cualquier fallo (caída de red,
        sesión invalidada por el controlador, reinicio del controlador...)
        sin que haga falta recargar la integración a mano. Solo se llama una
        vez por petición fallida (ver _async_request) para no entrar en
        bucle si el controlador sigue inalcanzable.
        """
        if self._session is not None and not self._external_session:
            await self._session.close()
        self._session = self._new_session()
        self._external_session = False
        await self._async_warm_up_session()
        await self._async_login()
        await self._async_resolve_site_id()

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------

    async def _async_login(self) -> None:
        # OJO: a diferencia de los endpoints de sites/grupos, el login NO lleva
        # el prefijo /{omadacId}/ - es un endpoint global del controlador.
        # La propia respuesta del login trae el omadacId, así que no hace
        # falta consultar /api/info por separado.
        url = f"{self._base_url}/api/v2/login"
        payload = {
            "username": self._username,
            "password": self._password,
            "terminalUUID": self._terminal_uuid,
        }
        try:
            async with self._session.post(
                url,
                json=payload,
                ssl=self._verify_ssl,
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json;charset=UTF-8",
                },
            ) as resp:
                data = await resp.json(content_type=None)
        except _NETWORK_ERRORS as err:
            raise OmadaConnectionError(f"No se pudo conectar a {url}: {err}") from err

        if data.get("errorCode") != 0:
            raise OmadaAuthError(data.get("msg", "Login fallido"))
        self._token = data["result"]["token"]
        self._omadac_id = data["result"]["omadacId"]

    async def _async_resolve_site_id(self, _retry: bool = False) -> None:
        result = await self._async_request(
            "GET",
            f"/{self._omadac_id}/api/v2/sites",
            params={"currentPage": 1, "currentPageSize": 1000},
            _retry=_retry,
        )
        sites = result.get("data", []) if isinstance(result, dict) else result
        if not sites:
            raise OmadaApiError("El controlador no devolvió ningún site")

        match = next((s for s in sites if s.get("name") == self._site_name), None)
        if match is None:
            _LOGGER.warning(
                "Site '%s' no encontrado, usando el primero disponible ('%s')",
                self._site_name,
                sites[0].get("name"),
            )
            match = sites[0]
        self._site_id = match["id"]
        self._resolved_site_name = match.get("name")

    # ------------------------------------------------------------------
    # Núcleo de peticiones
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Csrf-Token": self._token or "",
            "Content-Type": "application/json;charset=UTF-8",
        }

    async def _async_request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        _retry: bool = True,
    ) -> Any:
        url = f"{self._base_url}{path}"
        req_params = dict(params or {})
        req_params["token"] = self._token

        try:
            async with self._session.request(
                method,
                url,
                params=req_params,
                json=json_body,
                headers=self._headers(),
                ssl=self._verify_ssl,
            ) as resp:
                data = await resp.json(content_type=None)
        except _NETWORK_ERRORS as err:
            if _retry:
                _LOGGER.warning(
                    "Fallo de red hablando con el controlador Omada (%s), reconectando...", err
                )
                await self._async_reconnect()
                return await self._async_request(
                    method, path, json_body=json_body, params=params, _retry=False
                )
            raise OmadaConnectionError(f"Error de red en {method} {url}: {err}") from err

        error_code = data.get("errorCode")
        if error_code != 0:
            if _retry:
                _LOGGER.debug(
                    "Petición rechazada (errorCode=%s), reconectando y reintentando", error_code
                )
                await self._async_reconnect()
                return await self._async_request(
                    method, path, json_body=json_body, params=params, _retry=False
                )
            raise OmadaApiError(f"[{error_code}] {data.get('msg')}")

        return data.get("result")

    def _groups_path(self, suffix: str = "") -> str:
        return f"/{self._omadac_id}/api/v2/sites/{self._site_id}/setting/profiles/groups{suffix}"

    # ------------------------------------------------------------------
    # Grupos IP
    # ------------------------------------------------------------------

    async def async_get_ip_groups(self) -> list[dict[str, Any]]:
        """Devuelve todos los grupos de tipo IP del site configurado."""
        result = await self._async_request("GET", self._groups_path())
        groups = result.get("data", result) if isinstance(result, dict) else result
        return [g for g in groups if g.get("type") == GROUP_TYPE_IP]

    async def async_get_ip_group(self, group_id: str) -> dict[str, Any]:
        groups = await self.async_get_ip_groups()
        for group in groups:
            if group.get("groupId") == group_id:
                return group
        raise OmadaApiError(f"Grupo IP con id '{group_id}' no encontrado")

    async def async_create_ip_group(
        self,
        name: str,
        ip_list: list[dict[str, Any]],
        description: str = "",
    ) -> Any:
        """Crea un grupo IP nuevo.

        ip_list: lista de dicts con al menos "ip", opcionalmente "mask" (32
        por defecto) y "description".
        """
        payload = self._build_group_payload(name, ip_list, description)
        return await self._async_request("POST", self._groups_path(), json_body=payload)

    async def async_update_ip_group(
        self,
        group_id: str,
        name: str,
        ip_list: list[dict[str, Any]],
        description: str | None = None,
    ) -> Any:
        """Reemplaza el contenido completo de un grupo IP existente.

        Sin `description` se conserva la que tenga el grupo: el PATCH
        reemplaza el grupo entero, y mandarla vacía la borraría.
        """
        if description is None:
            group = await self.async_get_ip_group(group_id)
            description = group.get("description") or ""
        payload = self._build_group_payload(name, ip_list, description)
        payload["resource"] = 0
        return await self._async_request(
            "PATCH",
            self._groups_path(f"/{GROUP_TYPE_IP}/{group_id}"),
            json_body=payload,
        )

    async def async_delete_ip_group(self, group_id: str) -> Any:
        return await self._async_request(
            "DELETE", self._groups_path(f"/{GROUP_TYPE_IP}/{group_id}")
        )

    async def async_add_ip(
        self, group_id: str, ip: str, mask: int = 32, description: str = ""
    ) -> Any:
        """Añade una IP a un grupo existente (lee + reenvía la lista completa)."""
        group = await self.async_get_ip_group(group_id)
        ip_list = list(group.get("ipList") or [])

        if any(entry.get("ip") == ip for entry in ip_list):
            _LOGGER.debug("La IP %s ya está en el grupo %s, no se duplica", ip, group_id)
            return group

        ip_list.append(
            {
                "ip": ip,
                "mask": mask,
                "description": description,
                "key": int(time.time() * 1000),
            }
        )
        return await self.async_update_ip_group(
            group_id, group["name"], ip_list, group.get("description") or ""
        )

    async def async_remove_ip(self, group_id: str, ip: str) -> Any:
        """Quita una IP de un grupo existente (lee + reenvía la lista completa)."""
        group = await self.async_get_ip_group(group_id)
        ip_list = [entry for entry in (group.get("ipList") or []) if entry.get("ip") != ip]
        return await self.async_update_ip_group(
            group_id, group["name"], ip_list, group.get("description") or ""
        )

    @staticmethod
    def _build_group_payload(
        name: str, ip_list: list[dict[str, Any]], description: str
    ) -> dict[str, Any]:
        # Las entradas nuevas necesitan cada una su propio "key": con el mismo
        # milisegundo para todas, las de un grupo creado de una vez salían
        # repetidas.
        new_key = int(time.time() * 1000)
        normalized = []
        for entry in ip_list:
            item = {
                "ip": entry["ip"],
                "mask": entry.get("mask", 32),
                "description": entry.get("description", ""),
            }
            if "key" in entry:
                item["key"] = entry["key"]
            else:
                item["key"] = new_key
                new_key += 1
            normalized.append(item)

        return {
            "name": name,
            "type": GROUP_TYPE_IP,
            "ipList": normalized,
            "ipv6List": None,
            "macAddressList": None,
            "portList": None,
            "countryList": None,
            "description": description,
            "portType": None,
            "portMaskList": None,
            "domainNamePort": None,
            "ouiList": None,
            "count": len(normalized),
        }
