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
pytest tests/ -v
```

El comando `news` requiere secrets en un archivo `.env` (copiar desde `.env.example`). Solo `ANTHROPIC_API_KEY` es obligatoria; `NEWSDATA_API_KEY` y `COINMARKETCAL_API_KEY` son opcionales — si faltan, esas fuentes se desactivan solas sin romper la corrida.

## Estado

**Fase 1 completa**: motor de backtesting con datos históricos de Binance (público, sin API key), dos estrategias (`stable_trend` para cripto mayor, `volatile_breakout` para cripto volátil), riesgo configurable (tamaño de posición, stop-loss, take-profit, posiciones concurrentes) vía `configs/default.yaml`, y reporte de métricas (win rate, retorno, drawdown) en consola y CSV.

**Fase 2 completa**: módulo de noticias y eventos (`autotrading news`). Fuente primaria RSS (CoinDesk, CoinTelegraph, Decrypt, gratis) clasificada por LLM (Claude Haiku) en lotes con cache permanente por titular; fuente secundaria opcional NewsData.io (sentimiento nativo, free tier); calendario de eventos cripto vía CoinMarketCal (opcional, free tier) + calendario macro FOMC/CPI mantenido a mano en `configs/macro_events.yaml`. Todavía **no está conectado** al motor de backtest/decisión — es un módulo de análisis standalone.

**Pendiente** (siguientes fases): motor de decisión combinando señales técnicas + noticias, ejecución en vivo en Binance (con capital mínimo, solo tras validar resultados del backtest), despliegue 24/7, bot de Telegram como panel de administración.
