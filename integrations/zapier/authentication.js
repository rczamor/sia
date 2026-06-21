// Custom auth: the operator's Sia base URL + the shared ingestion webhook secret.
// The connection test hits the unauthenticated /api/health so a wrong base URL is
// caught at setup; the token itself is exercised on the first real ingest.
module.exports = {
  type: 'custom',
  fields: [
    {
      key: 'baseUrl',
      label: 'Sia Base URL',
      type: 'string',
      required: true,
      helpText: 'e.g. https://sia.example.com (no trailing slash)',
    },
    {
      key: 'webhookToken',
      label: 'Webhook Token',
      type: 'password',
      required: true,
      helpText: 'The INGEST_WEBHOOK_SECRET configured on your Sia instance',
    },
  ],
  test: {
    url: '{{bundle.authData.baseUrl}}/api/health',
  },
  connectionLabel: '{{bundle.authData.baseUrl}}',
};
