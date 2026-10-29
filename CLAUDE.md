# Prueba técnica: API de citas médicas (SIGAH)

## ⚠️ REGLA PRINCIPAL: SOLO LECTURA

**El ambiente es PRODUCCIÓN del hospital. Las citas son de pacientes reales.**

- SOLO se hacen consultas de LECTURA a la BD, usando ÚNICAMENTE endpoints de lectura (peticiones `GET`).
- PROHIBIDO usar `POST`, `PUT`, `PATCH`, `DELETE` o cualquier endpoint que confirme, anule, cree o modifique citas (aunque sea un `GET` con efectos, como `/confirmar` o `/anular`).
- La escritura SOLO se permite con AUTORIZACIÓN FORMAL Y EXPLÍCITA del usuario, en ese momento y para esa acción puntual. Una autorización anterior no vale para acciones nuevas.
- Motivo: aún no está resuelto un ambiente de prueba para escritura (pendiente con Jorge).
- Informática reservó 3 citas de prueba el 15-12-2026 (14:00, 14:30 y 15:00 hora local; centro 3; ids `AGD-0000099013` a `AGD-0000099015`, identificados por desfase horario y por estructura, falta la confirmación de Jorge). Aunque se autorice escribir, SOLO sobre esos ids y una vez que Jorge los confirme. "El resto de la agenda no se debe modificar."
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
