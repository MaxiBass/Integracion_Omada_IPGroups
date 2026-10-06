# Omada IP Groups — Registro de decisiones y problemas resueltos

Este documento no explica qué hace el código (para eso están los docstrings
de cada fichero). Recoge por qué se hizo así, qué se probó y qué queda
pendiente.

---

## 1. Cómo se habla con el controlador

La integración se escribió a principios de agosto de 2026 a partir de las
peticiones que hace el propio panel web del controlador (un OC220 con
firmware 5.x), capturadas con las DevTools del navegador. No usa la API
"Open API" de Omada ni la nube de TP-Link.

Lo que no es evidente y costó descubrir (detalle en el docstring de `api.py`):

- **El login es el único endpoint sin el prefijo `/{omadacId}/`.** La propia
  respuesta del login trae ese `omadacId` para el resto.
- **Sin un GET previo (a `/api/info`) el login devuelve 500.** El
  controlador necesita que exista la sesión Java antes del login, igual que
  cuando el navegador carga la página.
- **aiohttp tira la cookie de sesión si el host es una IP**, salvo con
  `CookieJar(unsafe=True)`.
- **El PATCH de un grupo reemplaza el grupo entero**: la lista de IPs y
  también la descripción. Por eso `add_ip` y `remove_ip` leen el grupo, lo
  modifican y lo reenvían completo. Ver §4.4.
- Cada entrada de `ipList` lleva un `key` (en las capturas, un epoch en ms).
- El id del grupo viene en `groupId`, no en `id`.
- El certificado es autofirmado: la verificación SSL va desactivada por
  defecto.

Si una petición falla (red, sesión caducada, controlador reiniciado), el
cliente rehace sesión y login y la repite una vez; si vuelve a fallar, da
error. Así se recupera solo sin recargar la integración.

## 2. Por qué entidades `text` / `select` / `button`

Para poder añadir y quitar IPs desde un panel sin depender de ayudantes
(`input_text`, scripts) creados a mano: cada grupo trae sus propios campos
y botones. Los campos de texto viven en memoria (se vacían al reiniciar).

El desplegable «IP a quitar» empieza sin ninguna IP elegida, y los botones
«Quitar IP seleccionada» y «Quitar temporalmente» no hacen nada (dan error)
hasta que se elige una. Hasta la v0.3.1 mostraba la primera IP del grupo por
defecto; ver §9.

## 3. Identificadores que no se deben cambiar

Las entidades de casa ya existen con estos `unique_id`, y los dispositivos
con estos identificadores. Cambiarlos crearía entidades nuevas y dejaría
las viejas huérfanas:

- Sensor de un grupo: `{entry_id}_{groupId}`
- Por grupo: `{entry_id}_{groupId}_new_ip`, `_new_ip_desc`,
  `_remove_ip_select`, `_add_ip_button`, `_remove_ip_button`,
  `_delete_group_button`; desde v0.3.0 también `_temp_remove_button`,
  `_restore_button`, `_temp_minutes` y `_temp_removed`
- Del controlador: `{entry_id}_new_group_name`, `{entry_id}_create_group_button`
- Dispositivos: `(omada_ipgroups, {entry_id})` el controlador y
  `(omada_ipgroups, {entry_id}_{groupId})` cada grupo.

## 4. Revisión de septiembre de 2026 (v0.2.0)

Al pasar la integración a este repositorio (27/09/2026) se revisó entera.
Cada fallo se reprodujo primero con el código original en
`tests/test_omada_ipgroups.py` (con el código original fallan 17
comprobaciones) y después se
arregló. Además se simuló la actualización en casa: HA con el código viejo,
parada, y el mismo directorio de configuración con el nuevo. Mismas
entidades, mismos dispositivos y mismos enlaces entre ellos.

### 4.1. Aviso de `via_device` obsoleto

El registro de HA mostraba, en cada arranque:

> Detected that custom integration 'omada_ipgroups' calls
> `device_registry.async_get_or_create` with a deprecated `via_device`
> parameter; use `via_device_id` instead … This will stop working in Home
> Assistant 2027.8.0

Desde HA 2026.9 el dispositivo padre ya no se indica con su identificador
(`via_device=(dominio, id)`), porque los identificadores dejaron de ser
únicos entre entradas. Se indica con el id del dispositivo en el registro
(`via_device_id`).

Arreglo, siguiendo el patrón de las integraciones oficiales (p. ej.
`bsblan`): `async_setup_entry` registra el dispositivo del controlador
**antes** de crear las entidades, y cada grupo obtiene su id con
`dr.async_get_device_id_by_identifier`. Los dispositivos de casa ya
estaban enlazados al controlador, así que no cambia nada visible.

### 4.2. El sensor repetía el nombre del grupo

El sensor de cada grupo se llamaba igual que su dispositivo, y con
`has_entity_name` HA los concatena: se veía «X X». Ahora el sensor no tiene
nombre propio (es la entidad principal del dispositivo) y se ve «X». El
`entity_id` no cambia: lo guarda el registro.

Efecto secundario aceptado: si se renombra un grupo en Omada, el nombre
nuevo aparece al reiniciar o recargar, no en el siguiente sondeo.

### 4.3. Controlador caído al arrancar HA → integración muerta

Si el controlador no respondía cuando arrancaba HA (p. ej. tras un corte de
luz, si HA arranca antes), `async_setup_entry` lanzaba `HomeAssistantError`
y la entrada se quedaba en error hasta recargarla a mano. Ahora:

- controlador inalcanzable → `ConfigEntryNotReady`: HA reintenta solo;
- usuario o contraseña mal → `ConfigEntryError`: error claro y sin
  reintentos (reintentar con una contraseña mala solo acumula intentos de
  login fallidos en el controlador). Desde v0.3.1 es `ConfigEntryAuthFailed`,
  que tampoco reintenta pero además pide los datos nuevos (§8).

En los dos casos, y si falla el primer sondeo, se cierra la sesión HTTP; antes
se quedaba abierta.

También se puso un límite de 30 s a cada petición: sin él, aiohttp espera
hasta 5 minutos, y con el controlador colgado cada sondeo y cada botón se
quedaban bloqueados ese tiempo. Una respuesta que no es JSON (la página de
error de un 500) cuenta ahora como fallo de conexión, en vez de un error
inesperado con traza.

### 4.4. Añadir o quitar una IP borraba la descripción del grupo

`add_ip` y `remove_ip` reenviaban el grupo con `description=""`, y como el
PATCH reemplaza el grupo entero, la descripción se perdía. Ahora conservan
la que tenía. El servicio `update_group` sin `description` también la
conserva (antes la borraba); con `description`, la cambia.

En casa ningún grupo tenía descripción, así que no se había perdido nada.

### 4.5. `key` repetidos al crear un grupo con varias IPs

Todas las entradas nuevas recibían el mismo `key` (el milisegundo actual).
Ahora cada una lleva uno distinto. No se llegó a ver un fallo en el panel de
Omada por esto, pero en las capturas del navegador cada fila tiene el suyo.

### 4.6. Aviso del site en cada arranque

La entrada de casa se dio de alta con el site por defecto, «Default», pero
el site del controlador se llama de otra forma. En cada arranque salía «Site
'Default' no encontrado, usando el primero disponible». Aparte del ruido, si
algún día se crea otro site en Omada, «el primero» podría pasar a ser otro y
la integración cambiaría de site sin avisar.

Ahora, la primera vez que se da el caso, se guarda en la entrada el site
real. El formulario de alta hace lo mismo. El `unique_id` de la entrada no
se toca. Para no dar de alta dos veces el mismo controlador, el formulario
también compara host, puerto y site.

### 4.7. Grupos borrados: dispositivos imposibles de quitar

Al borrar un grupo (también con el propio botón «Borrar este grupo»), su
dispositivo y sus 7 entidades se quedaban como «no disponible» para siempre:
HA no ofrecía eliminarlos. Ahora `async_remove_config_entry_device` permite
eliminar desde la ficha del dispositivo los grupos que ya no existen (no los
vivos ni el controlador).

No se borran automáticamente a propósito: con un fallo puntual en el que la
API devolviera la lista vacía se perderían todas las entidades.

### 4.8. Menores

- `translations/en.json` era una copia del español (el mismo fallo que tenía
  Cointra). Traducido.
- `manifest.json`: la documentación apuntaba a `https://github.com/`, faltaba
  `issue_tracker` y pedía `aiohttp` como requisito (ya viene con HA).
- El enlace al controlador en la ficha del dispositivo ignoraba el puerto
  si no era 443.
- El coordinator recibe la entrada explícitamente, y el formulario usa
  `ConfigFlowResult` en lugar del antiguo `FlowResult`.
- El formulario ya no monta su propia sesión HTTP: usa la del cliente y la
  cierra al terminar.

## 5. Paso a repositorio y HACS

Hasta septiembre de 2026 el código solo existía en
`/config/custom_components/omada_ipgroups` (v0.1.0). El primer commit de este
repo es esa copia exacta, para que el historial muestre qué se cambió. Se
instala con HACS igual que las demás integraciones de Maxi (ver README):
HACS sobrescribe la carpeta, y la entrada, los dispositivos y las entidades
existentes se mantienen.

## 6. Pendiente y decisiones abiertas

- **`IPGroup_Any` se queda como está (decisión de Maxi, 27/09/2026).** El
  controlador tiene un grupo con ese nombre y una sola entrada, `0.0.0.0/0`
  (parece el que crea Omada para «cualquier IP»). La integración le crea, como
  a cualquier grupo, los botones de añadir, quitar y **borrar**. Se planteó
  excluirlo y Maxi prefirió mantenerlo. No se ha probado si Omada deja
  borrarlo: si lo usa alguna regla, cuidado con ese botón.
- `remove_ip` quita todas las entradas con esa IP, sea cual sea la máscara.
- Los servicios actúan siempre sobre la primera entrada configurada; con un
  solo controlador no importa.

## 7. Quitar una IP temporalmente (v0.3.0, octubre de 2026)

Lo pidió Maxi para el grupo que corta Internet en casa: poder darle Internet
un rato a un dispositivo, sobre todo para actualizar su firmware, y luego
volver a bloquearlo.

Cómo funciona (código en `temporal.py`):

- **«Quitar temporalmente»** saca del grupo la IP elegida en el desplegable
  «IP a quitar» (el mismo que usa «Quitar IP seleccionada») y guarda su
  máscara y su descripción.
- **«Volver a añadir»** devuelve al grupo todas las IPs quitadas
  temporalmente de él, tal como estaban.
- **«Minutos fuera del grupo»**: pasado ese tiempo la IP vuelve sola. Es una
  red de seguridad que no estaba en la petición original: si a uno se le
  olvida pulsar «Volver a añadir», el dispositivo no se queda con Internet
  para siempre. Por defecto 60 minutos; 0 = no vuelve sola. El valor se
  recuerda tras reiniciar.
- **«Quitadas temporalmente»**: cuántas IPs están fuera, y en los atributos
  cuáles y cuándo vuelve cada una (`restore_at`, `next_restore`).
- Servicios `remove_ip_temporarily` (sin `minutes`, o 0, no vuelve sola) y
  `restore_ips` (una IP o todas las del grupo), para scripts.

Decisiones:

- **Se guarda en disco** (`.storage/omada_ipgroups.<entry_id>.temporales`).
  Un reinicio de HA no hace perder qué hay que devolver, y si el plazo
  venció con HA apagado, la IP vuelve nada más arrancar.
- **Se apunta antes de quitarla.** Si HA se cayera justo después de la
  petición al controlador, la IP seguiría constando como pendiente. Si la
  petición falla, se borra el apunte.
- **Si el controlador no responde al cumplirse el plazo, se reintenta cada
  minuto** hasta que entra; el apunte no se pierde.
- Si alguien vuelve a añadir la IP a mano entretanto, al devolverla no se
  duplica (`add_ip` ya lo evitaba); solo se borra el apunte. El sensor la
  sigue contando como fuera hasta entonces.
- Si se borra el grupo mientras la IP está fuera, al intentar devolverla se
  olvida el apunte con un aviso en el registro.
- **Si se borra la integración con IPs fuera, sale una notificación** con
  cuáles son: una entrada nueva no hereda el registro, así que habría que
  volver a añadirlas a mano. (El 27/09 se borró y se volvió a dar de alta
  la entrada; de haber habido una IP fuera, se habría perdido sin aviso.)
- Si una IP está en el grupo dos veces con distinta máscara, se quitan las
  dos y solo se devuelve la primera (así funcionaba ya `remove_ip`).

## 8. Icono, diagnóstico y reconfigurar (v0.3.1, octubre de 2026)

Ideas sacadas de revisar
[bullitt186/ha-omada-open-api](https://github.com/bullitt186/ha-omada-open-api),
otra integración de Omada (de monitorización, sin grupos IP).

- **Icono propio** en `custom_components/omada_ipgroups/brand/`
  (`icon.png` 256×256 e `icon@2x.png` 512×512). Desde HA 2026.9 el
  componente `brands` sirve las imágenes de una integración custom desde esa
  carpeta; antes no había icono. Es un diseño propio (un grupo con tres
  equipos conectados), no el logo de TP-Link: el repo es público. Se dibuja
  con `docs/icono/generar.py` (Pillow, que ya trae HA). En la raíz del repo no
  sirve: Cointra y Bomba de calor tienen ahí su `icon.png` y HA no lo ve.
- **Diagnóstico descargable** (`diagnostics.py`): la entrada (sin usuario ni
  contraseña), el site en uso, el estado del último sondeo, los grupos tal
  como los devuelve el controlador y las IPs quitadas temporalmente.
- **Reconfigurar** (`async_step_reconfigure`): cambia IP, puerto, usuario,
  contraseña (vacía = la actual) o site sin borrar la entrada. Se valida
  contra el controlador antes de guardar y la entrada se recarga sola. Si
  cambia el controlador o el site, se actualizan el `unique_id` y el título;
  se rechaza si ya hay otra entrada con esos datos. El formulario no tiene
  valores por defecto: lo que no se mande se conserva (con valores por
  defecto, un campo vacío volvía al site «Default»; lo cazó la prueba).
- **Volver a pedir la contraseña** (`async_step_reauth`): si al arrancar el
  controlador rechaza el usuario o la contraseña, HA lo avisa y los pide. El
  27/09 la entrada se borró y se dio de alta otra vez; con esto ya no
  hace falta.
- Durante el funcionamiento normal, un login rechazado sigue contando como
  fallo del sondeo y se reintenta (no se pide la contraseña): un rechazo
  puntual del controlador no debe dejar la integración parada.

Lo que se descartó de aquella integración:

- **Pasar a la Open API oficial** (OAuth con client ID y secret). Está
  documentada, no guarda la contraseña de administrador y el controlador de
  casa (6.3.0.45) la soporta; tiene lectura de grupos
  (`GET /openapi/v1/{omadacId}/sites/{siteId}/profiles/groups`), pero no se
  pudo confirmar que permita modificarlos. Es un cambio grande y la API web
  funciona con la 6.3: se queda como plan B si una actualización la rompe.
  Si pasa, lo primero que probar es la cabecera
  `Omada-Request-Source: web-local`, que esa integración manda en el login
  web.
- **Bloquear clientes** (`clients/{mac}/block`): los saca de toda la red, no
  solo de Internet. Para dispositivos que deben seguir en la red local, lo
  correcto es grupo IP + regla ACL.

## 9. El desplegable saltaba a la primera IP (v0.3.2, octubre de 2026)

El 05/10, al probar «Quitar temporalmente» en el grupo «Sin Internet», Maxi
vio que «siempre deshabilita la primera de la lista». El historial de HA
mostró otra cosa: la IP que salió del grupo fue la elegida, y la primera de
la lista no se movió. Lo que fallaba era lo que se veía y lo que podía pasar
después:

- **El desplegable saltaba a la primera IP.** Al quitar la elegida, ya no
  estaba entre las opciones y `current_option` devolvía la primera del
  grupo. Parecía que la afectada era esa.
- **Y era peligroso.** Con la primera IP «elegida» sin que nadie la eligiera,
  pulsar otra vez «Quitar temporalmente» o «Quitar IP seleccionada» la
  quitaba de verdad. Lo mismo nada más arrancar HA: el desplegable salía con
  la primera IP puesta.
- **Si la IP volvía**, quedaba elegida otra vez sola.

Arreglo: el desplegable no tiene opción mientras no se elija una; si la
elegida desaparece del grupo, se olvida; y los dos botones dan «Elige primero
una IP en «IP a quitar»» si no hay ninguna. Las 7 comprobaciones nuevas
fallaban con la v0.3.1 (una de ellas quitaba la primera IP) y pasan ahora.

De paso, tras cada botón o servicio se refresca al momento
(`async_refresh`) en vez de con `async_request_refresh`, que agrupa los
refrescos de 10 s en 10 s: con dos acciones seguidas, la segunda tardaba en
verse y el desplegable podía seguir mostrando una IP ya quitada.

## 10. Nota sobre las pruebas

Con HA 2026.9 y el Python 3.14.7 del venv, el intérprete da un segfault
al cerrarse si hay una entrada de configuración cargada (pasa igual en
`Integracion_Matriculas`). Por eso la prueba termina con `os._exit`.
