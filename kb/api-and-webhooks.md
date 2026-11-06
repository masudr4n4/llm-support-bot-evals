---
id: api-and-webhooks
title: API and webhooks
updated: 2026-08-28
---
The Tidewell REST API is available on the Growth and Scale plans. Create API keys in Settings > Developers.

Rate limits: 120 requests per minute on Growth, 600 requests per minute on Scale. Requests over the limit get an HTTP 429 response.

Webhooks can notify your system about label created, tracking updated and delivered events. If your endpoint does not return a 2xx response, Tidewell retries up to 5 times over 24 hours.

A sandbox environment for testing is available to all API users; sandbox labels are free and not valid for shipping.
