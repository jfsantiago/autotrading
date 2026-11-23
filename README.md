# AutoTrading

Proyecto de trading automatizado en cripto (Binance/Bybit vía ccxt).

Stack: Python 3.13.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -e .
```

## Uso

```bash
autotrading backtest --config configs/default.yaml --start 2024-01-01 --end 2024-04-01 --output results/run1
autotrading news --config configs/default.yaml
autotrading decide --config configs/default.yaml
autotrading trade --config configs/default.yaml              # preview, no coloca órdenes
autotrading trade --config configs/default.yaml --confirm     # coloca órdenes reales en Demo Trading
autotrading scheduled-run --config configs/default.yaml       # wrapper para cron/CI, respeta kill switch e intervalo
autotrading telegram-bot --config configs/default.yaml        # bot de Telegram de solo lectura, corre para siempre
pytest tests/ -v
```

`decide` es un **dry-run** sin estado: combina la señal técnica más reciente con el sentimiento de noticias actual y dice qué haría el bot ahora mismo — no coloca ninguna orden ni consulta posiciones.

`trade` sí es consciente de la posición real (consulta el exchange) y, con `--confirm`, coloca órdenes de verdad contra el **Binance Demo Trading** (dinero ficticio). Sin `--confirm` solo muestra el preview, igual que `decide` pero con la posición real incluida.

El comando `news`/`decide` requieren secrets en un archivo `.env` (copiar desde `.env.example`). `OPENAI_API_KEY` y `SUPABASE_DB_URL` son obligatorias (la segunda guarda el cache permanente de clasificaciones LLM en Postgres, necesario para que sobreviva entre corridas programadas); `NEWSDATA_API_KEY` y `COINMARKETCAL_API_KEY` son opcionales. `trade` además requiere `BINANCE_DEMO_API_KEY` / `BINANCE_DEMO_API_SECRET` (de Binance Demo Trading, demo.binance.com — reemplazó al viejo Futures Testnet). Antes del primer uso, correr `supabase/schema.sql` una vez en el SQL editor de Supabase.

`risk.position_size_pct` (tamaño de posición) y `futures.leverage` (apalancamiento) también se pueden sobrescribir con variables de entorno (`AUTOTRADING_POSITION_SIZE_PCT`, `AUTOTRADING_LEVERAGE`, vía `.env` o exportadas en la shell) sin tocar el YAML — es el primer paso hacia el control en caliente por Telegram. Ambas tienen un techo de seguridad hardcodeado en el código (25% y 10x respectivamente) que ninguna variable puede saltarse.

## Estado

**Fase 1 completa**: motor de backtesting con datos históricos de Binance (público, sin API key), dos estrategias (`stable_trend` para cripto mayor, `volatile_breakout` para cripto volátil), riesgo configurable (tamaño de posición, stop-loss, take-profit, posiciones concurrentes) vía `configs/default.yaml`, y reporte de métricas (win rate, retorno, drawdown) en consola y CSV.

**Fase 2 completa**: módulo de noticias y eventos (`autotrading news`). Fuente primaria RSS (CoinDesk, CoinTelegraph, Decrypt, gratis) clasificada por LLM (OpenAI `gpt-5-mini`, Structured Outputs) en lotes con cache permanente por titular; fuente secundaria opcional NewsData.io (sentimiento nativo, free tier); calendario de eventos cripto vía CoinMarketCal (opcional, free tier) + calendario macro FOMC/CPI mantenido a mano en `configs/macro_events.yaml` (poblado con fechas reales de la Fed/BLS hasta fines de 2027). Todavía **no está conectado** al motor de backtest/decisión — es un módulo de análisis standalone.

**Fase 3 completa**: motor de decisión en vivo (`autotrading decide`). Combina la señal técnica de la vela más reciente (últimas 300 velas cerradas, sin cache en disco) con el sentimiento de noticias actual, vía un **filtro de veto**: la señal técnica manda, las noticias solo pueden bloquear un BUY cuando el sentimiento es muy negativo (umbral configurable, default -0.5); nunca generan un BUY por sí solas ni bloquean SELL/HOLD. Solo funciona en vivo (no hay backtest histórico de noticias posible, RSS no tiene archivo histórico) — es un dry-run, no coloca órdenes.

**Fase 4 completa**: ejecución en Binance USD-M Futures (Demo Trading) (`autotrading trade`). Cambio de spot a futuros para poder ir short (apostar a la baja), apalancamiento configurable (default 4x, techo duro de 10x en código), margen siempre aislado (hardcoded, nunca cross) y stop-loss real colocado en el exchange (no solo en memoria) inmediatamente después de abrir cualquier posición — así una posición queda protegida aunque el proceso se caiga. La señal técnica sigue viniendo de datos spot (sin cambios); solo posiciones y órdenes pasan por el cliente de futuros. El veto de noticias ahora es simétrico: bajista bloquea abrir long, alcista bloquea abrir short. Sigue siendo **demo trading** (dinero ficticio) — nada de esto toca dinero real todavía.

**Fase 5 completa**: despliegue 24/7 (`autotrading scheduled-run`) vía un **VPS de Hetzner** (Falkenstein, Alemania) + Supabase (Postgres gratis). Se intentó primero con GitHub Actions, pero sus runners gratuitos corren en datacenters de EE.UU. y **Binance bloquea esas IPs por regulación** (HTTP 451, "restricted location") — confirmado en vivo, no es un bug de este proyecto. Los runners gratuitos de GitHub no permiten elegir región, y la alternativa paga (Larger Runners + red privada de Azure) sale más cara y más compleja que un VPS propio. Alemania sí funciona con Binance — confirmado en vivo desde el servidor.

El cache de clasificación LLM vive en una tabla Postgres (`llm_classification_cache`) — imprescindible para que sobreviva entre corridas y no se reclasifique todo cada vez. El intervalo real de trading (empieza en 60 min) y un interruptor de apagado (`bot_state.bot_enabled`, arranca en `false`) viven en otra tabla (`bot_state`) — ajustables sin tocar código ni el servidor, pensado como base para el control futuro por Telegram.

**Despliegue**: un timer de `systemd` (`autotrading-heartbeat.timer`) corre `autotrading scheduled-run` cada 5 minutos en el servidor; la mayoría de esas corridas se saltan gratis (dos consultas chicas a Supabase) y solo cuando toca de verdad se llama a Binance/OpenAI/RSS. Código en `/opt/autotrading` en el servidor, actualizado vía `git pull` + reinstalar.

**Fase 6 completa**: captura de PnL al cerrar + bot de Telegram de solo lectura (`autotrading telegram-bot`). `execution/orders.py::close_position()` ahora consulta el historial de ingresos de Binance (`REALIZED_PNL`) justo después de cada cierre y guarda el resultado en una tabla nueva de Supabase (`closed_trades`) — validado en vivo cerrando posiciones reales y comparando contra el cálculo manual. El bot de Telegram (`python-telegram-bot`, solo lectura) expone `/positions` (abiertas, con PnL no realizado y columna "Valor" = cantidad × entrada, el tamaño apalancado real en USD), `/history` (últimos cierres, en tabla monoespaciada) y `/status` (encendido/apagado, intervalo) — con doble capa de control de acceso (solo responde a un chat_id autorizado, en silencio para cualquier otro). Después de cada revisión real del heartbeat (haya abierto/cerrado algo o no) llega una notificación a Telegram con el resumen — configurado así a propósito, para confirmar que el bot sigue vivo y revisando. Usa el menú nativo de comandos de Telegram (botón único que despliega la lista) en vez de un teclado de varios botones.

**Detección de cierres por stop-loss**: un stop-loss se ejecuta directamente en Binance, sin pasar por el código del bot — sin esta pieza, esos cierres nunca llegaban a `closed_trades` ni a Telegram. Cada corrida con `--confirm` ahora mantiene una tabla propia (`open_position_tracking`) con lo que el bot sabe que abrió; si en una corrida posterior Binance muestra esa posición plana sin que el bot la haya cerrado, se confirma contra el historial de ingresos de Binance (`REALIZED_PNL`) — para no inventar un cierre falso ante un simple glitch de la API — y, si hay una entrada real, se reconstruye el precio de salida algebraicamente (`entrada ± pnl/cantidad`), se guarda en `closed_trades` con `closed_via='stop_loss'`, y llega una notificación distinta a Telegram ("cerrado por STOP-LOSS"). `/history` ahora tiene una columna "Vía" (`bot` / `SL`) para distinguir un cierre decidido por el bot de uno disparado por el stop-loss. Una posición abierta antes de este cambio (o si el tracking se desincroniza por cualquier motivo) se detecta y se empieza a rastrear sola, en vez de fallar o quedar invisible.

**Fase 7 completa**: el bot de Telegram deja de ser solo lectura y gana control real. `/balance` muestra el saldo total/disponible/en uso. `/close` cierra una posición manualmente — sin argumento lista las posiciones abiertas como botones (nada que escribir, imposible confundirse de símbolo si hay varias abiertas), y cualquiera de los dos caminos pasa por un segundo paso de confirmación explícito antes de ejecutar la orden, porque un cierre no se puede deshacer. `/settings` muestra el apalancamiento y el tamaño de posición efectivos (si hay un override activo o si se está usando el valor del YAML); `/set_leverage` y `/set_risk` cambian esos dos valores en caliente (guardados en `bot_state`, releídos en cada corrida — `set_leverage default`/`set_risk default` limpia el override y vuelve al YAML), validados contra los mismos techos de seguridad ya hardcodeados en el código (10x de apalancamiento, 25% de tamaño de posición) antes de guardarse, no solo al ejecutar una orden. Un cambio de apalancamiento/riesgo solo afecta la próxima posición que se abra, nunca una ya abierta.

**Pendiente**: pausar/reanudar el bot y cambiar el intervalo de revisión desde Telegram (hoy solo `bot_enabled`/`run_interval_minutes` se tocan directo en Supabase); y — como decisión aparte, no automática — el camino hacia capital real.
