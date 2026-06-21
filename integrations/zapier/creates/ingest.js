const perform = async (z, bundle) => {
  const response = await z.request({
    url: `${bundle.authData.baseUrl}/api/ingest/webhook`,
    method: 'POST',
    body: {
      title: bundle.inputData.title,
      content: bundle.inputData.content,
      url: bundle.inputData.url,
      source: bundle.inputData.source || 'zapier',
      author: bundle.inputData.author,
    },
  });
  return response.data;
};

module.exports = {
  key: 'ingest',
  noun: 'Ingestion',
  display: {
    label: 'Ingest Content',
    description:
      'Push a document, message, or note into Sia for classification and consolidation.',
  },
  operation: {
    perform,
    inputFields: [
      { key: 'title', label: 'Title', type: 'string', required: true },
      {
        key: 'content',
        label: 'Content',
        type: 'text',
        helpText:
          'The text to ingest. Leave empty and set URL to have Sia fetch a public page instead.',
      },
      {
        key: 'url',
        label: 'URL',
        type: 'string',
        helpText: 'Source URL (provenance, or the page to fetch when Content is empty).',
      },
      {
        key: 'source',
        label: 'Source',
        type: 'string',
        helpText: 'Provenance label, e.g. zapier:gdrive. Defaults to "zapier".',
      },
      { key: 'author', label: 'Author', type: 'string' },
    ],
    sample: { status: 'queued', job_id: '5f2c1e8a', mode: 'content' },
    outputFields: [
      { key: 'status', label: 'Status' },
      { key: 'job_id', label: 'Job ID' },
      { key: 'mode', label: 'Mode' },
    ],
  },
};
