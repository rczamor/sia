const { src, dest } = require('gulp');

// n8n loads node icons at runtime from the published dist/ tree, but tsc only
// emits .js — so copy the .svg assets alongside the compiled nodes.
function buildIcons() {
	return src('nodes/**/*.{svg,png}').pipe(dest('dist/nodes'));
}

exports['build:icons'] = buildIcons;
exports.default = buildIcons;
