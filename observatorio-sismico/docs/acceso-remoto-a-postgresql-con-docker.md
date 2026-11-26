# Acceso remoto a PostgreSQL con Docker

Guía para acceder de forma remota a PostgreSQL y trabajar con sus datos desde JupyterLab, sin publicar la base de datos en Internet.

## Arquitectura actual

La pila definida en [`compose.yaml`](../compose.yaml) contiene cinco servicios: Kafka, PostgreSQL, productor, consumidor y API. PostgreSQL no publica el puerto `5432` en el host; los demás servicios Docker acceden a él por la red interna de Compose usando `postgres:5432`. La API, en cambio, se publica únicamente en `127.0.0.1:8000`.

La configuración recomendada añade un sexto servicio opcional, JupyterLab. Jupyter se ejecuta en la misma red Docker y conecta directamente a PostgreSQL por `postgres:5432`. Para abrir Jupyter desde otro equipo se crea un túnel SSH al host Docker. Así no hace falta exponer ni PostgreSQL ni Jupyter a Internet.

> Los comandos de esta guía se ejecutan desde `observatorio-sismico/`, salvo que se indique lo contrario.

## Requisitos

- Docker Desktop con Docker Compose v2 en el equipo que aloja PostgreSQL.
- Acceso SSH al host Docker desde el equipo remoto. Es preferible usar una VPN privada, como Tailscale o WireGuard, y autenticación SSH mediante claves.
- La pila del proyecto configurada con un archivo `.env` local.

## 1. Añadir la imagen de Jupyter

Crea `jupyter/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /work

RUN pip install --no-cache-dir jupyterlab "psycopg[binary]" \
    && useradd --create-home --uid 10001 notebook \
    && chown -R notebook:notebook /work

USER notebook
EXPOSE 8888

CMD ["sh", "-c", "exec jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --ServerApp.root_dir=/work --IdentityProvider.token=\"$JUPYTER_TOKEN\""]
```

Jupyter escucha en todas las interfaces **dentro del contenedor** para que Docker pueda conectarse; la publicación al host se limitará a loopback en el siguiente paso.

## 2. Configurar el token y la conexión a la base de datos

El proyecto ya obtiene sus variables de configuración desde `.env`, que no se debe subir a Git. La plantilla está en [`.env.example`](../.env.example). La variable `DATABASE_URL` debe seguir apuntando al servicio Docker `postgres`, no a `localhost`. Su forma es:

```text
postgresql://observatorio:<contraseña>@postgres:5432/observatorio
```

Usa los mismos valores de base de datos, usuario y contraseña que ya utiliza el backend. Si la contraseña contiene caracteres reservados de URL, codifícalos correctamente en `DATABASE_URL`.

Genera un token de Jupyter aleatorio en PowerShell:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Añade el resultado al archivo `.env`:

```dotenv
JUPYTER_TOKEN=<token-aleatorio-generado>
```

No publiques ni compartas el token. No pongas secretos en los notebooks ni en archivos versionados.

## 3. Añadir Jupyter a Docker Compose

En `compose.yaml`, añade este servicio dentro de `services:`:

```yaml
  jupyter:
    build:
      context: .
      dockerfile: jupyter/Dockerfile
    restart: unless-stopped
    ports:
      - "127.0.0.1:8888:8888"
    environment:
      JUPYTER_TOKEN: ${JUPYTER_TOKEN:?define JUPYTER_TOKEN en .env}
      DATABASE_URL: ${DATABASE_URL:?define DATABASE_URL en .env}
    volumes:
      - ./notebooks:/work
    depends_on:
      postgres:
        condition: service_healthy
```

El enlace `127.0.0.1:8888:8888` permite que el host acceda al puerto, pero no lo publica en las interfaces de red externas. El túnel SSH conectará el navegador remoto a ese puerto local del host.

El montaje `./notebooks:/work` conserva los notebooks en el proyecto, fuera del ciclo de vida del contenedor. Al añadir este servicio, Compose tendrá seis servicios en vez de los cinco originales.

## 4. Crear la carpeta y arrancar Jupyter

En PowerShell, desde `observatorio-sismico/`:

```powershell
New-Item -ItemType Directory -Force .\notebooks
docker compose up -d --build jupyter
docker compose ps
docker compose logs --tail 50 jupyter
```

Compose iniciará PostgreSQL si todavía no está en marcha. Comprueba la conexión a la base de datos desde el contenedor:

```powershell
docker compose exec jupyter python -c "import os, psycopg; c=psycopg.connect(os.environ['DATABASE_URL']); print(c.execute('select current_database()').fetchone()); c.close()"
```

La salida debe incluir el nombre de la base de datos, normalmente `observatorio`.

## 5. Conectar desde otro equipo mediante SSH

Desde el equipo remoto, abre una terminal y ejecuta:

```powershell
ssh -N -L 8888:127.0.0.1:8888 usuario@<host-o-IP>
```

Sustituye `usuario` y `<host-o-IP>` por los datos de acceso SSH al equipo que aloja Docker. Mantén abierta la terminal del túnel y visita en el navegador del equipo remoto:

```text
http://127.0.0.1:8888
```

Introduce el valor de `JUPYTER_TOKEN` cuando Jupyter lo solicite. Si el puerto `8888` ya está ocupado en el equipo remoto, elige otro puerto local:

```powershell
ssh -N -L 8889:127.0.0.1:8888 usuario@<host-o-IP>
```

En ese caso, abre `http://127.0.0.1:8889`. Los notebooks se ejecutan en el contenedor del host y acceden a PostgreSQL internamente como `postgres:5432`; no necesitan un segundo túnel a la base de datos.

## Acceso directo opcional desde un cliente SQL

Si necesitas conectar desde el equipo remoto con una aplicación como DBeaver, puedes crear un túnel SSH directamente hacia PostgreSQL. Este paso es opcional y no es necesario para Jupyter.

1. Añade al servicio `postgres` de `compose.yaml` esta publicación, limitada a loopback:

   ```yaml
   ports:
     - "127.0.0.1:5432:5432"
   ```

2. Aplica el cambio desde `observatorio-sismico/`:

   ```powershell
   docker compose up -d postgres
   ```

3. En el equipo remoto, crea un túnel usando, por ejemplo, el puerto local `15432`:

   ```powershell
   ssh -N -L 15432:127.0.0.1:5432 usuario@<host-o-IP>
   ```

4. Configura el cliente SQL así:
   - Host: `127.0.0.1`
   - Puerto: `15432`
   - Base de datos, usuario y contraseña: los valores configurados en `.env`.

El puerto remoto `5432` sigue escuchando solo en el loopback del host. **No uses** `5432:5432` sin `127.0.0.1`: eso puede publicar PostgreSQL en interfaces accesibles desde la red.

## Seguridad y resolución de problemas

- No abras los puertos `8888` ni `5432` en el router o firewall para hacerlos accesibles directamente desde Internet. Usa SSH sobre una conexión confiable o una VPN privada.
- Protege el acceso SSH con claves, restringe quién puede iniciar sesión y mantén actualizado el host.
- Si Jupyter no arranca, comprueba que `JUPYTER_TOKEN` y `DATABASE_URL` están definidos en `.env` y revisa `docker compose logs jupyter`.
- Si falla la conexión a PostgreSQL desde Jupyter, confirma que `DATABASE_URL` usa `postgres` como host y que PostgreSQL aparece saludable en `docker compose ps`.
- Si no se puede abrir Jupyter desde el equipo remoto, verifica que el túnel SSH sigue activo, que el usuario y host SSH son correctos y que Jupyter está escuchando en el host en `127.0.0.1:8888`.
- `docker compose down` detiene los servicios sin borrar el volumen de PostgreSQL. Evita `docker compose down -v` salvo que quieras eliminar los datos persistidos.
