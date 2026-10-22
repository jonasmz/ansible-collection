# `jmz.koha.user`

Crea un usuario de Koha y establece sus permisos operativos, sin llegar a
`superlibrarian`. No crea instancias, bibliotecas ni categorías, y no administra
atributos, mensajes ni preferencias del usuario.

[Índice de módulos](../README.md) · [Guía general](../../README.md) ·
[Ejemplos](examples.md)

## Requisitos

- Debian/Ubuntu con Koha empaquetado y `koha-shell`.
- Una versión de Koha con `Koha::Patron->set_permissions` (26.05 lo incluye).
- Ejecutar con `become: true` y después de `jmz.koha.initialize`; la biblioteca
  y la categoría deben existir.
- `files/user.pl` es un helper Perl empaquetado en la colección. El action
  plugin lo copia temporalmente a `/tmp`, lo ejecuta en `koha-shell` con la
  petición JSON por stdin (la contraseña no pasa por argumentos) y elimina el
  directorio. Usa las APIs `Koha::Patron` y `Koha::Patrons`, sin SQL.

## Parámetros

| Parámetro | Tipo | Obligatorio | Semántica |
| --- | --- | --- | --- |
| `instance` | string | sí | Identificador 1–11 caracteres, minúsculas/números/guiones, comienza con letra. |
| `username` | string | sí | `userid` de Koha; identifica al usuario para la idempotencia. |
| `password` | secreto | sí | Debe cumplir la política de la categoría. Marcada `no_log`. |
| `surname` | string | sí | Apellido. |
| `library` | string | sí | Código de una biblioteca existente. |
| `category` | string | sí | Código de una categoría existente. |
| `firstname`, `cardnumber`, `email` | string | no | Si se omiten, no se modifican en un usuario existente. |
| `permissions` | mapa | no | Ver abajo; predeterminado `{}` (cuenta sin permisos). |
| `timeout` | entero | no | Timeout de `koha-shell`, predeterminado 120 s. |

### `permissions`

Mapa de módulo de Koha (`catalogue`, `circulate`, `tools`, `reserveforothers`…)
a `true` (todo el módulo) o a una lista de subpermisos
(`circulate: [circulate_remaining_permissions, force_checkout]`). `false`
equivale a no listar el módulo. Los nombres se validan contra Koha: Koha
ignoraría en silencio un nombre mal escrito, así que aquí es un error.

## Comportamiento

- Los permisos son **exactos**: los que no se listan se revocan.
- `superlibrarian` no se puede conceder. Si el usuario existente ya es
  superlibrarian (por ejemplo el administrador de `initialize`), el módulo
  falla sin modificarlo en lugar de degradarlo.
- La contraseña se compara con el hash guardado; solo se cambia si difiere.
- Tras escribir, relee el estado desde Koha y verifica permisos, que no sea
  superlibrarian y que la contraseña sirva.

## Idempotencia, check mode y diff

Repetir con los mismos valores devuelve `changed: false`. Check mode no escribe.
El diff y el retorno nunca incluyen la contraseña: `password` es un booleano o,
si esta ejecución la cambió, `modificada`. Retorna `created`, `updated`
(perfil), `permissions_changed`, `password_changed`, `borrowernumber`, `before`
y `after`. Los cambios van en una transacción bajo un lock por instancia.

## Pruebas

`extensions/molecule/user_permissions` ejecuta el módulo contra Koha real.
