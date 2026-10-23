# Troubleshooting

## The dashboard does not load

Most loading problems come from browser extensions or a stale cache. Try a private window,
then clear the site data for app.northwind.example. If the dashboard still does not load,
check the status page; during an incident, engineering posts updates every 30 minutes.

## API errors

HTTP 429 means the workspace exceeded its rate limit of 600 requests per minute; retry with
back-off. HTTP 500 and 503 errors are logged automatically and investigated by the on-call
engineer. Include the request id from the X-Request-Id header when you contact support.

## Webhooks are not arriving

Webhook deliveries are retried for 24 hours with exponential back-off. The delivery log under
Settings, Integrations shows every attempt and the response your endpoint returned.

## Data sync delays

Syncs with CRM integrations run every 15 minutes. A sync that has not completed in two hours
is flagged on the integration page and can be restarted manually.
