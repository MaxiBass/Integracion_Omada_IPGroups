# Integracion_Omada_IPGroups

Repositorio de la integración custom de Home Assistant "Omada IP Groups" de
Maxi: gestión de los grupos IP del controlador Omada local. Es la **fuente
de verdad** del código y la fuente desde la que HACS la instala.

Es **público** a propósito, porque HACS no lee repos privados (ver
`Integracion_Riego/CLAUDE.md`). Por eso:

- **Nunca** subir datos reales de la red de casa: ni las IPs de los grupos,
  ni las descripciones de los dispositivos, ni el usuario del controlador.
  Las pruebas y la documentación usan datos inventados (`10.0.0.x`).
- Las comprobaciones con datos reales se hacen en el scratchpad de la sesión.

## Entorno

- Repo local: `~/Downloads/GitHub/Integracion_Omada_IPGroups`
- HA real por Samba: `/Volumes/config` (si no está montado:
  `osascript -e 'mount volume "smb://192.168.1.9/config"'`).
- Esta sesión **no tiene credenciales de GitHub**: `git add` y `git commit`
  sí, `git push` no. El push, y crear el repo en GitHub, lo hace el usuario
  desde GitHub Desktop.

## Estructura

```
custom_components/omada_ipgroups/
  api.py          cliente de la API web local del controlador (sin HA)
  coordinator.py  sondeo de los grupos cada 120 s
  __init__.py     alta de la entrada, dispositivo del controlador, servicios
  temporal.py     IPs quitadas temporalmente: registro en disco y vuelta sola
  entity.py       DeviceInfo del controlador y de cada grupo
  sensor.py, text.py, select.py, number.py, button.py
  config_flow.py  alta, reconfigurar y volver a pedir la contraseña
  diagnostics.py  diagnóstico descargable, sin credenciales
  services.yaml, strings.json, translations/
  brand/          icono propio (HA 2026.9 lo lee de aquí)
docs/DECISIONES.md  por qué es así; NO va en custom_components
docs/icono/generar.py  dibuja brand/icon.png e icon@2x.png
tests/test_omada_ipgroups.py
```

## Antes de tocar nada, lee `docs/DECISIONES.md`

En particular:

- El PATCH de un grupo **reemplaza el grupo entero** (IPs y descripción).
  Cualquier cambio parcial tiene que leer el grupo y reenviarlo completo (§1).
- No cambiar ningún `unique_id` ni los identificadores de los dispositivos:
  son los que enlazan con las entidades que ya existen en casa (§3).

## Flujo para editar

1. Editar en el repo, dentro de `custom_components/omada_ipgroups/`.
2. Pasar las pruebas (abajo).
3. Commit (yo puedo). Push lo hace el usuario.
4. Subir la `version` de `manifest.json` cuando esté listo para probar: HACS
   detecta la actualización por ese número.
5. El usuario actualiza desde HACS y reinicia HA.

No copiar directamente en `/Volumes/config/custom_components/omada_ipgroups`
sin editar antes en el repo.

## Pruebas

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.9.4
/tmp/hav/bin/python tests/test_omada_ipgroups.py
```

El venv de `/tmp` lo borra a medias la limpieza de macOS; si `import
homeassistant` falla, recrearlo con `python3 -m venv --clear /tmp/hav`.

## Credenciales

La integración no guarda credenciales en el código: el usuario y la
contraseña del controlador se introducen en el formulario de alta y HA los
guarda en su propio almacenamiento (`.storage/core.config_entries`), fuera
de este repositorio.
