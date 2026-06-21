const authentication = require('./authentication');
const ingest = require('./creates/ingest');

// Attach the shared ingestion secret to every outbound request.
const addWebhookToken = (request, z, bundle) => {
  if (bundle.authData && bundle.authData.webhookToken) {
    request.headers = request.headers || {};
    request.headers['X-Sia-Webhook-Token'] = bundle.authData.webhookToken;
  }
  return request;
};

module.exports = {
  version: require('./package.json').version,
  platformVersion: require('zapier-platform-core').version,
  authentication,
  beforeRequest: [addWebhookToken],
  creates: {
    [ingest.key]: ingest,
  },
};
