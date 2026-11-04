# HECTOR Backend

FastAPI de coordinación; para contratos HTTP, instalación, ejemplos y límites operativos consulta el [README principal](../README.md). API docs en `/docs` y `/openapi.json`.

## Configuración

Variables en `.env.example`. `HECTOR_STORAGE=sqlite` selecciona almacenamiento local; `HECTOR_STORAGE=dynamodb` requiere `AWS_REGION`, `MISSIONS_TABLE`, `TELEMETRY_TABLE` y credenciales AWS suministradas por el entorno/IAM role. No guardar claves AWS en `.env` o el repositorio.

## Ejecutar

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload
```

Entrenar/evaluar ML: `python -m app.ml.train` y `python -m app.ml.evaluate`. Los artefactos `joblib` solo deben cargarse desde almacenamiento confiable.
