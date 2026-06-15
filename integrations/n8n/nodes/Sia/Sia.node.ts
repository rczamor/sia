import {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeConnectionType,
} from 'n8n-workflow';

export class Sia implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Sia',
		name: 'sia',
		icon: 'file:sia.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{ "Ingest: " + $parameter["title"] }}',
		description: 'Push content into Sia, a Context Engine',
		defaults: { name: 'Sia' },
		inputs: ['main'] as NodeConnectionType[],
		outputs: ['main'] as NodeConnectionType[],
		credentials: [{ name: 'siaApi', required: true }],
		properties: [
			{
				displayName: 'Title',
				name: 'title',
				type: 'string',
				default: '',
				required: true,
				description: 'Human-readable title for the ingested item',
			},
			{
				displayName: 'Content',
				name: 'content',
				type: 'string',
				typeOptions: { rows: 6 },
				default: '',
				description:
					'The text to ingest. Leave empty and set URL to have Sia fetch a public page instead.',
			},
			{
				displayName: 'URL',
				name: 'url',
				type: 'string',
				default: '',
				description: 'Source URL (provenance, or the page to fetch when Content is empty)',
			},
			{
				displayName: 'Source',
				name: 'source',
				type: 'string',
				default: '',
				placeholder: 'n8n:gdrive',
				description: 'Provenance label recorded with the item',
			},
			{
				displayName: 'Author',
				name: 'author',
				type: 'string',
				default: '',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const credentials = await this.getCredentials('siaApi');
		const baseUrl = (credentials.baseUrl as string).replace(/\/$/, '');
		const returnData: INodeExecutionData[] = [];

		for (let i = 0; i < items.length; i++) {
			const body: Record<string, string> = {
				title: this.getNodeParameter('title', i) as string,
			};
			const content = this.getNodeParameter('content', i, '') as string;
			const url = this.getNodeParameter('url', i, '') as string;
			const source = this.getNodeParameter('source', i, '') as string;
			const author = this.getNodeParameter('author', i, '') as string;
			if (content) body.content = content;
			if (url) body.url = url;
			if (source) body.source = source;
			if (author) body.author = author;

			const response = await this.helpers.httpRequestWithAuthentication.call(
				this,
				'siaApi',
				{
					method: 'POST',
					url: `${baseUrl}/api/ingest/webhook`,
					body,
					json: true,
				},
			);
			returnData.push({ json: response, pairedItem: { item: i } });
		}

		return [returnData];
	}
}
