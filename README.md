# Integracion_Omada_IPGroups

Integración custom de Home Assistant para gestionar los **grupos IP** de un
controlador **TP-Link Omada local** (probado con un OC220, firmware 5.x): ver
qué IPs tiene cada grupo, y añadir, quitar, crear o borrar grupos desde HA.
Habla con la API web local del controlador; no usa la nube de TP-Link.

Sirve, por ejemplo, para cortar Internet a un dispositivo desde HA: si una
regla ACL de Omada bloquea un grupo IP, meter o sacar la IP del grupo es
activar o desactivar el bloqueo. Y para lo contrario, darle Internet un rato
(p. ej. para actualizar su firmware): se le saca del grupo temporalmente y
vuelve solo al cabo de los minutos que se elijan.

Historial de decisiones y de la revisión: [`docs/DECISIONES.md`](docs/DECISIONES.md).

## Qué crea

- Un **dispositivo por grupo IP** (colgando del dispositivo del controlador),
  con:
  - un sensor con el número de IPs y la lista como atributo (`ips`, `group_id`),
  - campos de texto «IP a añadir» y «Descripción de la IP a añadir», y el
    botón «Añadir IP»,
  - un desplegable «IP a quitar» y el botón «Quitar IP seleccionada»,
  - para quitarla solo un rato: el botón «Quitar temporalmente», el campo
    «Minutos fuera del grupo» (60 por defecto; 0 = no vuelve sola), el botón
    «Volver a añadir» y el sensor «Quitadas temporalmente», con cuándo
    vuelve cada IP,
  - el botón «Borrar este grupo».
- En el dispositivo del controlador: el campo «Nombre del nuevo grupo» y el
  botón «Crear grupo».
- Servicios `omada_ipgroups.create_group`, `update_group`, `delete_group`,
  `add_ip`, `remove_ip`, `remove_ip_temporarily` y `restore_ips`, para
  automatizaciones.

Solo gestiona grupos de tipo IP; los de MAC, puertos o países se ignoran.

## Instalación vía HACS

1. HACS → menú ⋮ → **Repositorios personalizados**.
2. URL: `https://github.com/MaxiBass/Integracion_Omada_IPGroups`, categoría
   **Integración**.
3. Instalar **Omada IP Groups** desde HACS.
4. Reiniciar Home Assistant.
5. Ajustes → Dispositivos y servicios → Añadir integración → **Omada IP
   Groups**, con la IP, el puerto (443) y un usuario local del controlador.

## Instalación manual (sin HACS)

Copia `custom_components/omada_ipgroups` a
`/config/custom_components/omada_ipgroups` en tu HA y reinicia.

## Pruebas

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.9.4
/tmp/hav/bin/python tests/test_omada_ipgroups.py
```

Arrancan un Home Assistant real con un controlador Omada simulado en memoria.
