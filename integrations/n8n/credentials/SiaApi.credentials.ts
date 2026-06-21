import {
	IAuthenticateGeneric,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class SiaApi implements ICredentialType {
	name = 'siaApi';
	displayName = 'Sia API';
	documentationUrl =
		'https://github.com/rczamor/sia/blob/main/docs/ingestion-webhook.md';

	properties: INodeProperties[] = [
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			default: 'https://your-sia-host',
			placeholder: 'https://sia.example.com',
			description: 'Base URL of your Sia instance (no trailing slash)',
		},
		{
			displayName: 'Webhook Token',
			name: 'webhookToken',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			description: 'The INGEST_WEBHOOK_SECRET configured on your Sia instance',
		},
	];

	// Sent on every request the node makes with this credential.
	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				'X-Sia-Webhook-Token': '={{$credentials.webhookToken}}',
			},
		},
	};
}
