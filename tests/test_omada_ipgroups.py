"""Pruebas de la integración Omada IP Groups. Se ejecutan sin pytest:

    /tmp/hav/bin/python tests/test_omada_ipgroups.py

Arrancan un Home Assistant real (el del venv) en un directorio temporal, con
la integración enlazada en `custom_components/`. El controlador Omada es un
doble en memoria: se sustituye solo la capa HTTP del cliente
(`_async_request`, login y calentamiento de sesión), así que la lógica de
`api.py` —leer el grupo, rehacer la lista, construir el PATCH— es la real.

Todas las IPs, nombres y descripciones son inventados: este repositorio es
público.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
BASE = RAIZ / "custom_components" / "omada_ipgroups"
DOMINIO = "omada_ipgroups"

fallos: list[str] = []


def comprobar(condicion: bool, etiqueta: str) -> None:
    if condicion:
        print(f"  OK    {etiqueta}")
    else:
        print(f"  FALLO {etiqueta}")
        fallos.append(etiqueta)


# ── Ficheros estáticos ───────────────────────────────────────────────


def test_manifest_y_traducciones() -> None:
    print("\nManifest y traducciones")

    manifest = json.loads((BASE / "manifest.json").read_text("utf-8"))
    comprobar(
        "github.com/MaxiBass/" in manifest.get("documentation", "")
        and "issue_tracker" in manifest,
        "manifest apunta al repo (documentation, issue_tracker)",
    )
    comprobar(
        "aiohttp" not in manifest.get("requirements", []),
        "manifest no pide aiohttp (ya viene con Home Assistant)",
    )

    es = json.loads((BASE / "translations" / "es.json").read_text("utf-8"))
    en = json.loads((BASE / "translations" / "en.json").read_text("utf-8"))
    cadenas = json.loads((BASE / "strings.json").read_text("utf-8"))

    def claves(d: dict, prefijo: str = "") -> set[str]:
        salida = set()
        for k, v in d.items():
            salida |= claves(v, f"{prefijo}{k}.") if isinstance(v, dict) else {f"{prefijo}{k}"}
        return salida

    comprobar(claves(es) == claves(en), "es.json y en.json tienen las mismas claves")
    comprobar(es == cadenas, "strings.json coincide con es.json")
    comprobar(es != en, "en.json no es una copia de es.json")


# ── Controlador Omada falso ──────────────────────────────────────────


class ControladorFalso:
    """Lo que el cliente ve del controlador: sites, grupos y fallos a demanda."""

    def __init__(self) -> None:
        self.caido = False
        self.clave_mala = False
        self.sites = [{"id": "site1", "name": "Casa"}]
        self.grupos: dict[str, dict] = {
            "g1": {
                "groupId": "g1",
                "name": "Invitados",
                "type": 0,
                "description": "Red de invitados",
                "ipList": [{"ip": "10.0.0.20", "mask": 32, "description": "Tablet", "key": 1}],
            },
            "g2": {"groupId": "g2", "name": "Bloqueados", "type": 0, "description": None, "ipList": []},
            # Un grupo de MACs: la integración solo gestiona los de IP.
            "m1": {"groupId": "m1", "name": "Por MAC", "type": 2, "macAddressList": []},
        }
        self.clientes: list = []
        self._siguiente = 1

    def responder(self, method: str, path: str, cuerpo: dict | None):
        sites = "/c1/api/v2/sites"
        grupos = f"{sites}/site1/setting/profiles/groups"
        if method == "GET" and path == sites:
            return {"data": copy.deepcopy(self.sites)}
        if path == grupos and method == "GET":
            return {"data": copy.deepcopy(list(self.grupos.values()))}
        if path == grupos and method == "POST":
            gid = f"n{self._siguiente}"
            self._siguiente += 1
            self.grupos[gid] = {"groupId": gid, **copy.deepcopy(cuerpo)}
            return None
        if path.startswith(f"{grupos}/0/"):
            gid = path.rsplit("/", 1)[1]
            if method == "DELETE":
                self.grupos.pop(gid)
                return None
            if method == "PATCH":
                self.grupos[gid].update(
                    {k: copy.deepcopy(cuerpo[k]) for k in ("name", "ipList", "description")}
                )
                return None
        raise AssertionError(f"petición inesperada {method} {path}")


def instalar_doble(controlador: ControladorFalso) -> None:
    """Sustituye OmadaLocalClient por una subclase que habla con el doble."""
    import custom_components.omada_ipgroups as integracion
    from custom_components.omada_ipgroups import api, config_flow

    class ClienteFalso(api.OmadaLocalClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            controlador.clientes.append(self)

        async def _async_warm_up_session(self) -> None:
            if controlador.caido:
                raise api.OmadaConnectionError("el controlador no responde")

        async def _async_login(self) -> None:
            if controlador.clave_mala:
                raise api.OmadaAuthError("Invalid username or password")
            self._token, self._omadac_id = "tok", "c1"

        async def _async_request(self, method, path, json_body=None, params=None, _retry=True):
            if controlador.caido:
                raise api.OmadaConnectionError("el controlador no responde")
            return controlador.responder(method, path, json_body)

    integracion.OmadaLocalClient = ClienteFalso
    config_flow.OmadaLocalClient = ClienteFalso


# ── Home Assistant real ──────────────────────────────────────────────


class _Registros(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.mensajes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.mensajes.append(record.getMessage())

    def con(self, *trozos: str) -> list[str]:
        return [m for m in self.mensajes if all(t in m for t in trozos)]


async def _arrancar_hass(directorio: Path):
    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.core_config import async_process_ha_core_config
    from homeassistant.setup import async_setup_component

    hass = core.HomeAssistant(str(directorio))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    assert await bootstrap.async_load_base_functionality(hass)
    for dominio in bootstrap.CORE_INTEGRATIONS:
        assert await async_setup_component(hass, dominio, {}), dominio
    await async_process_ha_core_config(hass, {"time_zone": "Europe/Madrid"})
    hass.set_state(core.CoreState.running)
    return hass


def _entrada_antigua():
    """Una entrada como la de casa: dada de alta con el site por defecto."""
    from types import MappingProxyType

    from homeassistant.config_entries import ConfigEntry

    return ConfigEntry(
        data={
            "host": "10.0.0.1",
            "port": 443,
            "username": "usuario",
            "password": "clave",
            "site_name": "Default",
            "verify_ssl": False,
        },
        discovery_keys=MappingProxyType({}),
        domain=DOMINIO,
        minor_version=1,
        options={},
        source="user",
        subentries_data=None,
        title="Omada IP Groups (10.0.0.1)",
        unique_id="10.0.0.1:443:Default",
        version=1,
    )


def _entidad(hass, plataforma: str, unique_id: str) -> str:
    from homeassistant.helpers import entity_registry as er

    entity_id = er.async_get(hass).async_get_entity_id(plataforma, DOMINIO, unique_id)
    assert entity_id, f"no existe {plataforma} {unique_id}"
    return entity_id


def _sesion_cerrada(cliente) -> bool:
    return cliente._session is None or cliente._session.closed


async def _recorrido(directorio: Path) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr

    registros = _Registros()
    logging.getLogger().addHandler(registros)
    hass = await _arrancar_hass(directorio)
    controlador = ControladorFalso()
    instalar_doble(controlador)
    import custom_components.omada_ipgroups as integracion

    try:
        # ── Alta y avisos de HA ──
        print("\n  · alta de una entrada existente")
        entrada = _entrada_antigua()
        await hass.config_entries.async_add(entrada)
        await hass.async_block_till_done()
        comprobar(entrada.state is ConfigEntryState.LOADED, f"la entrada carga ({entrada.state})")

        via = registros.con("omada_ipgroups", "via_device")
        comprobar(not via, f"sin aviso de `via_device` obsoleto ({len(via)} avisos)")
        obsoletos = registros.con("omada_ipgroups", "deprecated")
        comprobar(not obsoletos, f"ningún otro aviso de obsoleto {obsoletos or ''}")

        registro = dr.async_get(hass)
        dispositivos = dr.async_entries_for_config_entry(registro, entrada.entry_id)
        hub = registro.async_get_device_by_identifier((DOMINIO, entrada.entry_id), entrada.entry_id)
        grupos = [d for d in dispositivos if d.model == "Grupo IP"]
        comprobar(hub is not None and len(dispositivos) == 3,
                  f"controlador + 2 grupos IP (el de MACs no) → {len(dispositivos)} dispositivos")
        comprobar(bool(grupos) and all(d.via_device_id == hub.id for d in grupos),
                  "cada grupo cuelga del controlador (via_device_id)")
        comprobar(hub is not None and hub.configuration_url == "https://10.0.0.1",
                  f"enlace al controlador ({hub and hub.configuration_url})")

        sensor = hass.states.get(_entidad(hass, "sensor", f"{entrada.entry_id}_g1"))
        comprobar(sensor.attributes.get("friendly_name") == "Invitados",
                  f"el sensor no repite el nombre del grupo ({sensor.attributes.get('friendly_name')!r})")
        comprobar(sensor.state == "1" and sensor.attributes["ips"][0]["ip"] == "10.0.0.20",
                  "el sensor cuenta las IPs y las lista")

        sitio = registros.con("no encontrado")
        comprobar(entrada.data["site_name"] == "Casa",
                  f"se guarda el site real en la entrada ({entrada.data['site_name']!r})")

        # ── Añadir una IP desde las entidades, como en el panel ──
        print("\n  · añadir y quitar IPs desde las entidades")
        ip = _entidad(hass, "text", f"{entrada.entry_id}_g1_new_ip")
        desc = _entidad(hass, "text", f"{entrada.entry_id}_g1_new_ip_desc")
        await hass.services.async_call("text", "set_value", {"entity_id": ip, "value": "10.0.0.21"}, blocking=True)
        await hass.services.async_call("text", "set_value", {"entity_id": desc, "value": "Portátil"}, blocking=True)
        await hass.services.async_call(
            "button", "press",
            {"entity_id": _entidad(hass, "button", f"{entrada.entry_id}_g1_add_ip_button")},
            blocking=True,
        )
        await hass.async_block_till_done()
        g1 = controlador.grupos["g1"]
        comprobar([e["ip"] for e in g1["ipList"]] == ["10.0.0.20", "10.0.0.21"], "la IP se añade al grupo")
        comprobar(g1["ipList"][1]["description"] == "Portátil", "con su descripción")
        comprobar(g1["description"] == "Red de invitados",
                  f"añadir una IP no borra la descripción del grupo ({g1['description']!r})")
        comprobar(hass.states.get(ip).state == "" and hass.states.get(desc).state == "",
                  "los campos se vacían tras añadir")
        comprobar(hass.states.get(sensor.entity_id).state == "2", "el sensor se refresca")

        seleccion = _entidad(hass, "select", f"{entrada.entry_id}_g1_remove_ip_select")
        await hass.services.async_call(
            "select", "select_option", {"entity_id": seleccion, "option": "10.0.0.20 (Tablet)"}, blocking=True
        )
        await hass.services.async_call(
            "button", "press",
            {"entity_id": _entidad(hass, "button", f"{entrada.entry_id}_g1_remove_ip_button")},
            blocking=True,
        )
        await hass.async_block_till_done()
        comprobar([e["ip"] for e in g1["ipList"]] == ["10.0.0.21"], "quita la IP seleccionada, no otra")
        comprobar(g1["description"] == "Red de invitados", "quitar una IP tampoco borra la descripción")

        # ── Servicios ──
        print("\n  · servicios")
        await hass.services.async_call(
            DOMINIO, "create_group",
            {"name": "Nuevo", "ips": [{"ip": "10.0.0.30"}, {"ip": "10.0.0.31"}, {"ip": "10.0.0.32"}]},
            blocking=True,
        )
        await hass.async_block_till_done()
        # async_request_refresh agrupa las peticiones que llegan en menos de
        # 10 s (el Debouncer del coordinator): tras los dos botones de arriba,
        # esta queda en espera. En casa el grupo aparece a los pocos segundos;
        # aquí se fuerza el sondeo para no esperar.
        await hass.data[DOMINIO][entrada.entry_id].async_refresh()
        await hass.async_block_till_done()
        nuevo = next(g for g in controlador.grupos.values() if g["name"] == "Nuevo")
        claves = [e["key"] for e in nuevo["ipList"]]
        comprobar(len(set(claves)) == 3, f"cada IP de un grupo nuevo lleva su propio `key` {claves}")
        comprobar(registro.async_get_device_by_identifier((DOMINIO, f"{entrada.entry_id}_{nuevo['groupId']}"), entrada.entry_id) is not None,
                  "el grupo nuevo aparece como dispositivo sin reiniciar")

        await hass.services.async_call(
            DOMINIO, "update_group", {"group_id": "g1", "name": "Invitados", "ips": [{"ip": "10.0.0.22"}]},
            blocking=True,
        )
        comprobar(g1["description"] == "Red de invitados",
                  "update_group sin descripción conserva la que había")
        await hass.services.async_call(
            DOMINIO, "update_group",
            {"group_id": "g1", "name": "Invitados", "ips": [{"ip": "10.0.0.22"}], "description": "Otra"},
            blocking=True,
        )
        comprobar(g1["description"] == "Otra", "update_group con descripción la cambia")

        # ── Recarga: nada duplicado, sin repetir el aviso del site ──
        print("\n  · recarga")
        antes = {d.id for d in dr.async_entries_for_config_entry(registro, entrada.entry_id)}
        await hass.config_entries.async_reload(entrada.entry_id)
        await hass.async_block_till_done()
        despues = {d.id for d in dr.async_entries_for_config_entry(registro, entrada.entry_id)}
        comprobar(entrada.state is ConfigEntryState.LOADED and antes == despues,
                  "tras recargar, los mismos dispositivos")
        sitio_despues = registros.con("no encontrado")
        comprobar(len(sitio_despues) == len(sitio) <= 1,
                  f"el aviso del site no se repite en cada arranque ({len(sitio)} → {len(sitio_despues)})")
        comprobar(_sesion_cerrada(controlador.clientes[-2]), "la sesión anterior se cierra al descargar")

        # ── Grupo borrado: su dispositivo se puede eliminar desde HA ──
        print("\n  · grupo borrado")
        await hass.services.async_call(
            "button", "press",
            {"entity_id": _entidad(hass, "button", f"{entrada.entry_id}_g2_delete_group_button")},
            blocking=True,
        )
        await hass.async_block_till_done()
        comprobar("g2" not in controlador.grupos, "el botón borra el grupo en el controlador")
        quitar = getattr(integracion, "async_remove_config_entry_device", None)
        dev_g2 = registro.async_get_device_by_identifier((DOMINIO, f"{entrada.entry_id}_g2"), entrada.entry_id)
        dev_g1 = registro.async_get_device_by_identifier((DOMINIO, f"{entrada.entry_id}_g1"), entrada.entry_id)
        comprobar(quitar is not None and await quitar(hass, entrada, dev_g2),
                  "el dispositivo de un grupo que ya no existe se puede eliminar")
        comprobar(quitar is not None and not await quitar(hass, entrada, dev_g1)
                  and not await quitar(hass, entrada, hub),
                  "el de un grupo vivo o el del controlador, no")

        # ── Controlador caído al arrancar HA ──
        print("\n  · fallos al arrancar")
        controlador.caido = True
        await hass.config_entries.async_reload(entrada.entry_id)
        await hass.async_block_till_done()
        comprobar(entrada.state is ConfigEntryState.SETUP_RETRY,
                  f"controlador caído → HA reintenta solo ({entrada.state})")
        comprobar(_sesion_cerrada(controlador.clientes[-1]), "y no deja la sesión HTTP abierta")

        controlador.caido = False
        await hass.config_entries.async_reload(entrada.entry_id)
        await hass.async_block_till_done()
        comprobar(entrada.state is ConfigEntryState.LOADED, "cuando vuelve, carga")

        controlador.clave_mala = True
        await hass.config_entries.async_reload(entrada.entry_id)
        await hass.async_block_till_done()
        comprobar(entrada.state is ConfigEntryState.SETUP_ERROR,
                  f"contraseña mala → error, sin reintentos inútiles ({entrada.state})")
        comprobar(_sesion_cerrada(controlador.clientes[-1]), "y tampoco deja la sesión abierta")
        controlador.clave_mala = False

        # ── Alta nueva por el formulario ──
        print("\n  · alta por el formulario")
        flujo = await hass.config_entries.flow.async_init(DOMINIO, context={"source": "user"})
        resultado = await hass.config_entries.flow.async_configure(
            flujo["flow_id"],
            {"host": "10.0.0.9", "port": 443, "username": "u", "password": "p",
             "site_name": "Default", "verify_ssl": False},
        )
        await hass.async_block_till_done()
        comprobar(resultado.get("type") == "create_entry", f"el formulario crea la entrada ({resultado.get('type')})")
        comprobar(resultado.get("result") is not None and resultado["result"].data["site_name"] == "Casa",
                  "el formulario guarda el site que de verdad se usa")
        comprobar(_sesion_cerrada(controlador.clientes[-2]), "la sesión de prueba del formulario se cierra")
    finally:
        await hass.async_stop(force=True)
        logging.getLogger().removeHandler(registros)


def test_home_assistant() -> None:
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        print("\nHome Assistant no instalado: se saltan las pruebas de integración")
        return

    print("\nIntegración en un Home Assistant real")
    directorio = Path(tempfile.mkdtemp(prefix="omada_ipgroups_"))
    try:
        (directorio / "custom_components").mkdir()
        (directorio / "custom_components" / DOMINIO).symlink_to(BASE)
        asyncio.run(_recorrido(directorio))
    finally:
        shutil.rmtree(directorio, ignore_errors=True)


if __name__ == "__main__":
    test_manifest_y_traducciones()
    test_home_assistant()
    print()
    if fallos:
        print(f"{len(fallos)} FALLOS:")
        for f in fallos:
            print(f"  - {f}")
    else:
        print("Todo OK")
    # os._exit y no sys.exit: con HA 2026.9.2 y el Python 3.14.7 del venv, el
    # intérprete da un segfault al cerrarse si hay cualquier entrada de
    # configuración cargada (lo mismo pasa en Integracion_Matriculas).
    sys.stdout.flush()
    sys.stderr.flush()
    import os

    os._exit(1 if fallos else 0)
