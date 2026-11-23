# Unidades de systemd (VPS)

Copiadas tal cual desde `/etc/systemd/system/` en el servidor de producción (Hetzner, Falkenstein) — es documentación/respaldo, no se instalan solas.

Para instalar o actualizar en el servidor:

```bash
scp deploy/autotrading-*.service deploy/autotrading-*.timer root@<ip>:/etc/systemd/system/
ssh root@<ip> 'systemctl daemon-reload && systemctl enable --now autotrading-heartbeat.timer autotrading-telegram-bot.service'
```

- `autotrading-heartbeat.timer` + `.service`: corre `autotrading scheduled-run` cada 5 minutos (oneshot).
- `autotrading-telegram-bot.service`: proceso permanente (`Restart=always`) para el bot de Telegram.
