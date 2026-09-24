# Captura desde otra máquina de la LAN

El servidor anuncia la dirección de publicación usando `PUBLIC_RTMP_HOST`. En
el `.env` del servidor debe ser su IP o DNS visible en la red del evento, no
`localhost`:

```dotenv
PUBLIC_RTMP_HOST=192.168.10.20
PUBLIC_RTMP_PORT=1935
RTMP_BIND_ADDRESS=0.0.0.0
API_BIND_ADDRESS=0.0.0.0
```

Levantar el servidor y comprobarlo desde la máquina de captura:

```bash
docker compose up -d
curl http://192.168.10.20:8080/healthz
```

Abrir TCP `1935` (RTMP) y `8080` (registro/heartbeat) en el firewall del
servidor sólo para la subred del evento. RTSP, HLS y la API interna de MediaMTX
siguen ligados a loopback por defecto.

## Un comando

Con Python, FFmpeg y las dependencias del repo instaladas en la laptop:

```bash
python -m app.capture_node --stage 1 --server rtmp://192.168.10.20:1935 --api-url http://192.168.10.20:8080 --input-format pulse --source default
```

El comando se registra y mantiene un heartbeat con RTT, estado de FFmpeg y
bytes enviados. Si se omite `--server` usa la URL RTMP anunciada por el
servidor. Para Linux/ALSA usar
`--input-format alsa --source hw:0`; para macOS, `avfoundation`; para Windows,
`dshow`. `--demo` genera una señal sin depender de hardware.

En una laptop que también tenga este repo y Docker, el equivalente es:

```bash
docker compose --profile capture run --rm capture-node --stage 1 --server rtmp://192.168.10.20:1935 --api-url http://192.168.10.20:8080 --input-format pulse --source default
```

## OBS

- Server: `rtmp://192.168.10.20:1935/live`
- Stream Key: `stage-1`

Cada sala cambia sólo la clave (`stage-2`, `stage-auditorio`, etc.). Verificar
la llegada en `http://192.168.10.20:8080/api/metrics/stages/1`.

## Diagnóstico rápido

```bash
ffmpeg -re -stream_loop -1 -i evaluation/corpus/audio/stage-es.wav -vn -c:a aac -f flv rtmp://192.168.10.20:1935/live/stage-1
```

Si la API responde pero RTMP no conecta, revisar el firewall de `1935/tcp`. Si
ni la API responde, confirmar IP, VLAN y `API_BIND_ADDRESS=0.0.0.0`.
