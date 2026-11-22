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
pytest tests/ -v
```

`decide` es un **dry-run** sin estado: combina la señal técnica más reciente con el sentimiento de noticias actual y dice qué haría el bot ahora mismo — no coloca ninguna orden ni consulta posiciones.

`trade` sí es consciente de la posición real (consulta el exchange) y, con `--confirm`, coloca órdenes de verdad contra el **Binance Demo Trading** (dinero ficticio). Sin `--confirm` solo muestra el preview, igual que `decide` pero con la posición real incluida.

El comando `news`/`decide` requieren secrets en un archivo `.env` (copiar desde `.env.example`). Solo `OPENAI_API_KEY` es obligatoria; `NEWSDATA_API_KEY` y `COINMARKETCAL_API_KEY` son opcionales. `trade` además requiere `BINANCE_DEMO_API_KEY` / `BINANCE_DEMO_API_SECRET` (de Binance Demo Trading, demo.binance.com — reemplazó al viejo Futures Testnet).

`risk.position_size_pct` (tamaño de posición) y `futures.leverage` (apalancamiento) también se pueden sobrescribir con variables de entorno (`AUTOTRADING_POSITION_SIZE_PCT`, `AUTOTRADING_LEVERAGE`, vía `.env` o exportadas en la shell) sin tocar el YAML — es el primer paso hacia el control en caliente por Telegram. Ambas tienen un techo de seguridad hardcodeado en el código (25% y 10x respectivamente) que ninguna variable puede saltarse.

## Estado

**Fase 1 completa**: motor de backtesting con datos históricos de Binance (público, sin API key), dos estrategias (`stable_trend` para cripto mayor, `volatile_breakout` para cripto volátil), riesgo configurable (tamaño de posición, stop-loss, take-profit, posiciones concurrentes) vía `configs/default.yaml`, y reporte de métricas (win rate, retorno, drawdown) en consola y CSV.

**Fase 2 completa**: módulo de noticias y eventos (`autotrading news`). Fuente primaria RSS (CoinDesk, CoinTelegraph, Decrypt, gratis) clasificada por LLM (OpenAI `gpt-5-mini`, Structured Outputs) en lotes con cache permanente por titular; fuente secundaria opcional NewsData.io (sentimiento nativo, free tier); calendario de eventos cripto vía CoinMarketCal (opcional, free tier) + calendario macro FOMC/CPI mantenido a mano en `configs/macro_events.yaml` (poblado con fechas reales de la Fed/BLS hasta fines de 2027). Todavía **no está conectado** al motor de backtest/decisión — es un módulo de análisis standalone.

**Fase 3 completa**: motor de decisión en vivo (`autotrading decide`). Combina la señal técnica de la vela más reciente (últimas 300 velas cerradas, sin cache en disco) con el sentimiento de noticias actual, vía un **filtro de veto**: la señal técnica manda, las noticias solo pueden bloquear un BUY cuando el sentimiento es muy negativo (umbral configurable, default -0.5); nunca generan un BUY por sí solas ni bloquean SELL/HOLD. Solo funciona en vivo (no hay backtest histórico de noticias posible, RSS no tiene archivo histórico) — es un dry-run, no coloca órdenes.

**Fase 4 completa**: ejecución en Binance USD-M Futures (Demo Trading) (`autotrading trade`). Cambio de spot a futuros para poder ir short (apostar a la baja), apalancamiento configurable (default 4x, techo duro de 10x en código), margen siempre aislado (hardcoded, nunca cross) y stop-loss real colocado en el exchange (no solo en memoria) inmediatamente después de abrir cualquier posición — así una posición queda protegida aunque el proceso se caiga. La señal técnica sigue viniendo de datos spot (sin cambios); solo posiciones y órdenes pasan por el cliente de futuros. El veto de noticias ahora es simétrico: bajista bloquea abrir long, alcista bloquea abrir short. Sigue siendo **demo trading** (dinero ficticio) — nada de esto toca dinero real todavía.

**Pendiente** (siguientes fases): validar `trade --confirm` con keys reales de Binance Demo Trading, luego ejecución con capital real mínimo (solo tras observar el demo funcionando correctamente), despliegue 24/7, bot de Telegram como panel de administración.
