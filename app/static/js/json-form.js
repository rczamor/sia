// htmx extension: serialize form submissions as JSON.
// Fields listed in the form's data-json-arrays attribute (comma-separated) are
// always encoded as arrays, so multi-checkbox groups match list-typed API schemas.
htmx.defineExtension("json-form", {
    onEvent: function (name, evt) {
        if (name === "htmx:configRequest") {
            evt.detail.headers["Content-Type"] = "application/json";
        }
    },
    encodeParameters: function (xhr, parameters, elt) {
        xhr.overrideMimeType("text/json");
        const form = elt.closest("form") || elt;
        const arrayFields = (form.dataset.jsonArrays || "")
            .split(",")
            .map(function (s) { return s.trim(); })
            .filter(Boolean);
        const obj = {};
        parameters.forEach(function (value, key) {
            if (arrayFields.indexOf(key) !== -1) {
                (obj[key] = obj[key] || []).push(value);
            } else if (key in obj) {
                obj[key] = [].concat(obj[key], value);
            } else {
                obj[key] = value;
            }
        });
        Object.keys(obj).forEach(function (key) {
            if (obj[key] === "") delete obj[key];
        });
        return JSON.stringify(obj);
    },
});
