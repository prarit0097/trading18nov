import fs from "node:fs";
import { pathToFileURL } from "node:url";

const [input, engine] = process.argv.slice(2);
// Only run on the screened candidates produced by delta_pine_compatibility.
globalThis.fetch = () => { throw Error("External network access disabled"); };
const { Indicator } = await import(pathToFileURL(engine).href);

for (const item of JSON.parse(fs.readFileSync(input, "utf8"))) {
  try {
    const indicator = new Indicator(item.code);
    // Compile first so parser errors cannot be masked by the fallback prop schema.
    indicator.prepare();
    indicator.prop.default_qty_type = "cash";
  } catch (error) {
    process.stdout.write(JSON.stringify([item.id, String(error.message).slice(0, 450)]) + "\n");
  }
}
