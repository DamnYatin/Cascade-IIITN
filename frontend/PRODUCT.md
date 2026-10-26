# PRODUCT.md — The 72-Hour Warning

## Product Identity
- **Name**: The 72-Hour Warning
- **Tagline**: Urban Cascading-Crisis Prediction and Decision-Support Platform
- **Audience**: Emergency Operations Centers (EOCs), city resilience planners, infrastructure engineers, regional disaster management authorities (e.g. ASDMA / NDMA).
- **Core Mission**: Predict how localized environmental hazards (e.g. extreme rainfall and river flooding) propagate across interconnected urban systems (drainage, roads, power, comms, hospitals, emergency response) up to 72 hours ahead with calibrated probabilities, discovered dependencies, and verifiable evidence.

## Key Design Principles
1. **Backend Integrity**: 100% faithful to the FastAPI and Python forecast engine. Never invent or mock data; show honest "not exposed by the API" or unavailable states when an endpoint is absent.
2. **Data Honesty**: Explicitly distinguish real observations (IMD/Open-Meteo) vs. simulated synthetic nodes vs. disaggregated streams. Never disguise synthetic streams as real-world live events.
3. **Multi-Horizon Probabilistic Clarity**: Distinguish `p_by` (cumulative risk by horizon) from `p_at` (instantaneous risk at horizon). Always show time-to-critical as an uncertainty distribution (p10, p50, p90 quantiles), never a deterministic countdown.
4. **Resilience & High-Performance Streaming**: Graceful degradation under disconnects, auto-reconnect with capped exponential backoff, WebSocket batching to prevent main-thread lag, and zero skeleton loaders.
