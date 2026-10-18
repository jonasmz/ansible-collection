# Despliegue de una instancia Koha

El escenario [playbooks/single-instance.yml](../playbooks/single-instance.yml)
despliega una sola instancia, `codexlib26`, en la instalación activa del host
`10.27.49.248`. Reutiliza el inventario SSH
[inventory/integration.ini](../inventory/integration.ini).

El playbook utiliza `instance` para crear la base y los vhosts; `initialize`
para cargar la biblioteca, categorías, tipo de material, reglas básicas de
circulación y el usuario `superlibrarian`; `plack` para habilitar y arrancar la
aplicación web; `zebra` y `zebra_rebuild` para iniciar el motor de búsqueda y
cargar los índices iniciales; y `zebra_indexer` para mantenerlos actualizados.
Omite `worker`, que no es necesario para acceder al sitio y autenticar al
superlibrarian.

El password de Koha se solicita de forma privada y confirmada. El password
sudo de SSH se solicita a Ansible con `--ask-become-pass`; ninguno se guarda en
el inventario ni en el playbook. Para ejecutar:

```console
ANSIBLE_CONFIG=/tmp/koha-ansible.cfg \
  /tmp/koha-ansible-venv/bin/ansible-playbook \
  -i inventory/integration.ini playbooks/single-instance.yml \
  --ask-become-pass
```

La URL de personal es
<http://codexlib26-staff.10.27.49.248.sslip.io/> y la del OPAC es
<http://codexlib26-opac.10.27.49.248.sslip.io/>. El usuario de acceso al sitio
de personal es `superlibrarian`; la contraseña es la ingresada en el prompt.

## Resultado de la ejecución

La colección `jmz.koha:1.0.0` se instaló en el entorno local con Ansible Core
2.21.5. El playbook pasó `--syntax-check` y se ejecutó directamente contra
`10.27.49.248` en Ubuntu 24.04.5 con Koha `26.05.04.000`.

La ejecución terminó con `ok=9 changed=4 failed=0 unreachable=0`. Creó
`codexlib26`, inicializó la biblioteca `CENTRAL` y el superlibrarian,
habilitó/arrancó Plack y generó los índices iniciales. Zebra y el indexador
quedaron activos. El playbook comprobó las dos rutas virtuales y ambas
respondieron HTTP 200. Desde la VM, los nombres de OPAC y personal resolvieron
a `10.27.49.248`. Los estados de Plack y Zebra se confirmaron también con las
utilidades de Koha ejecutadas como root.

Los módulos Apache `headers` y `proxy_http` estaban habilitados en la VM. El
playbook no usó `worker`, porque no es necesario para el acceso web y el inicio
de sesión incluidos en este escenario.

Al probar el acceso desde el host controlador, UFW estaba activo y solo
permitía conexiones entrantes por SSH (`22/tcp`). Apache escuchaba en `80/tcp`
y los dos vhosts respondían `200` localmente. Sin embargo, esa respuesta era
la página predeterminada de Apache: los vhosts se habían generado como
`*:None`, por lo que Apache los ignoraba. Se corrigió el archivo de instancia
a `*:80` con los nombres DNS completos, se validó (`Syntax OK`) y se recargó
Apache. Se añadió una regla UFW de
`80/tcp` restringida al host controlador (`10.27.49.1`), que era la IP de
origen observada en la sesión SSH. Tras el cambio, ambos nombres resolvieron y
respondieron `HTTP 200` desde el controlador con contenido de Koha, no la
página predeterminada.

Se ajustó el módulo `instance` para usar el puerto 80 en OPAC y personal cuando
se define `vhosts` sin puertos explícitos. El playbook ahora valida y recarga
Apache cuando crea o cambia los vhosts.
