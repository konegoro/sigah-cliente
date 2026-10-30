# Prueba técnica: API de citas médicas (SIGAH)

## ⚠️ REGLA PRINCIPAL: SOLO LECTURA, SALVO LAS 3 CITAS DE PRUEBA

**El ambiente es PRODUCCIÓN del hospital. Las citas son de pacientes reales.**

- Por defecto, SOLO LECTURA: únicamente peticiones `GET` a endpoints de lectura.
- EXCEPCIÓN autorizada por el usuario: se puede confirmar y anular SOLO las 3 citas que Informática reservó para pruebas de integración ("El resto de la agenda no se debe modificar"):
  - `AGD-0000099013`, `AGD-0000099014` y `AGD-0000099015`: 15-12-2026, 14:00 / 14:30 / 15:00 hora local, centro 3, Medicina Interna.
  - Identificadas por desfase horario y por estructura (HALLAZGOS §1.3 y §3.2) y confirmadas por Jorge el 30-10. Estado actual: 099013 y 099014 canceladas; 099015 agendada (de reserva).
  - Escribir con el CLI y `SIGAH_IDS_ESCRIBIBLES` limitado a esos ids. Para probar transiciones que el cliente bloquea a propósito, se permite un POST directo, pero SOLO a esos mismos ids y con salida enmascarada.
  - Antes de cada escritura, releer la cita y verificar que fecha, hora, especialidad y centro coinciden con lo de arriba. Si no coinciden, NO escribir y avisar.
  - Anunciar al usuario cada escritura antes de ejecutarla (id, acción y para qué). Son solo 3 citas y una anulación no se puede revertir.
- PROHIBIDO escribir (`POST`, `PUT`, `PATCH`, `DELETE`, o un `GET` con efectos) sobre cualquier otro id, salvo una nueva autorización formal y explícita del usuario para esa acción puntual.
- Si hay dudas sobre si un endpoint escribe, NO se llama; se pregunta primero.

## Privacidad: datos de pacientes

- Las respuestas traen datos personales y de salud (RUT, nombre, teléfono, email, especialidad).
- Todo lo que se imprime en esta conversación llega a Anthropic: al consultar la API, NUNCA mostrar datos personales en claro. Solo estructura, nombres de campos, tipos, conteos y patrones enmascarados (ej. `+569XXXXXXXX` → `+9999999999`).
- Enmascarar por LISTA BLANCA (todo oculto salvo campos conocidos como seguros), nunca por lista negra: los nombres reales de los campos (`RUT_PAC`, `NOM_PAC`, `TEL_PAC`, `MEDICO`...) no son los del manual, y una lista negra con los nombres del manual dejó datos en claro.
- No guardar copias permanentes de respuestas reales. Tests y fixtures solo con datos inventados.

## API

- URL base: `https://sigah-entrevista-79007222944.southamerica-west1.run.app/api/v1`
- Autenticación: cabecera `X-Auth-Token` (no `X-API-Key` ni `Authorization: Bearer`).
- Errores vienen como `{"estado":"ERROR","codigo":"ERR-01","msg":"..."}`.

## API key: nunca exponerla

- Está cifrada con DPAPI (usuario de Windows) en `$HOME\.sigah_key` (PowerShell). No está en el proyecto.
- Nunca imprimir, mostrar, loguear ni escribir la key en archivos, comandos literales o respuestas. Usarla solo por variable:

```powershell
$sec = Get-Content "$HOME\.sigah_key" | ConvertTo-SecureString
$key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
curl.exe -s -H "X-Auth-Token: $key" "<URL base>/<endpoint>"
```
