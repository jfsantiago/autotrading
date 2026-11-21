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
pytest tests/ -v
```

`decide` es un **dry-run**: combina la señal técnica más reciente con el sentimiento de noticias actual y dice qué haría el bot ahora mismo — no coloca ninguna orden.

El comando `news` requiere secrets en un archivo `.env` (copiar desde `.env.example`). Solo `OPENAI_API_KEY` es obligatoria; `NEWSDATA_API_KEY` y `COINMARKETCAL_API_KEY` son opcionales — si faltan, esas fuentes se desactivan solas sin romper la corrida.

## Estado

**Fase 1 completa**: motor de backtesting con datos históricos de Binance (público, sin API key), dos estrategias (`stable_trend` para cripto mayor, `volatile_breakout` para cripto volátil), riesgo configurable (tamaño de posición, stop-loss, take-profit, posiciones concurrentes) vía `configs/default.yaml`, y reporte de métricas (win rate, retorno, drawdown) en consola y CSV.

**Fase 2 completa**: módulo de noticias y eventos (`autotrading news`). Fuente primaria RSS (CoinDesk, CoinTelegraph, Decrypt, gratis) clasificada por LLM (OpenAI `gpt-5-mini`, Structured Outputs) en lotes con cache permanente por titular; fuente secundaria opcional NewsData.io (sentimiento nativo, free tier); calendario de eventos cripto vía CoinMarketCal (opcional, free tier) + calendario macro FOMC/CPI mantenido a mano en `configs/macro_events.yaml` (poblado con fechas reales de la Fed/BLS hasta fines de 2027). Todavía **no está conectado** al motor de backtest/decisión — es un módulo de análisis standalone.

**Fase 3 completa**: motor de decisión en vivo (`autotrading decide`). Combina la señal técnica de la vela más reciente (últimas 300 velas cerradas, sin cache en disco) con el sentimiento de noticias actual, vía un **filtro de veto**: la señal técnica manda, las noticias solo pueden bloquear un BUY cuando el sentimiento es muy negativo (umbral configurable, default -0.5); nunca generan un BUY por sí solas ni bloquean SELL/HOLD. Solo funciona en vivo (no hay backtest histórico de noticias posible, RSS no tiene archivo histórico) — es un dry-run, no coloca órdenes.

**Pendiente** (siguientes fases): ejecución en vivo real en Binance (con capital mínimo, solo tras observar `decide` funcionando por un tiempo), despliegue 24/7, bot de Telegram como panel de administración.
