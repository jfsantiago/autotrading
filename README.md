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

**Pendiente**: observar las primeras corridas reales una vez se prenda `bot_state.bot_enabled`; más adelante, bot de Telegram como panel de administración, y — como decisión aparte, no automática — el camino hacia capital real.
